"""
server.py — Layer 6: Backend API Server
=========================================
Single-file HTTP + SSE server that bridges the frontend and all Python engines.

No subprocesses — engines run directly in threads.
No external dependencies — stdlib only (http.server, json, threading).

Start: python3 server.py [--data-dir ./nba_data] [--port 8080]

Endpoints:
  GET  /api/status                    → server + engine state
  GET  /api/data/info                 → loaded dataset info

  POST /api/explore/start             → start exploration
  POST /api/explore/stop              → stop exploration
  GET  /api/explore/stream            → SSE live stats
  GET  /api/explore/summary           → latest generated_formulas/summary.json
  GET  /api/explore/batch/:name       → formulas in a batch (paginated)
  GET  /api/explore/batches           → list all batches

  POST /api/evolve/start              → start evolution run
  POST /api/evolve/stop               → stop evolution
  GET  /api/evolve/stream             → SSE live stats
  GET  /api/evolve/:fid/runs          → list runs for a formula
  GET  /api/evolve/:fid/:rid/best     → best formula of a run
  GET  /api/evolve/:fid/:rid/history  → accepted mutation history

  GET  /api/formulas                  → list saved formulas
  GET  /api/formulas/:id              → one formula detail

  GET  /                              → serve index.html from ./dist
  GET  /assets/*                      → serve static assets from ./dist
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

# ── Engine imports ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_loader import DataLoader
from stats_meta import get_variable_list, CATEGORIES
from exploration_engine import (
    ExplorationEngine, ExplorationConfig, ExplorationStats,
    load_summary, load_batch, list_batches, get_formula,
)
from formula_dashboard import evaluate_formula_dashboard
from brute_force_engine import BruteForceEngine, BruteForceConfig, BruteForceStats
from evolution_engine import (
    EvolutionEngine, EvolutionConfig, EvolutionStats,
    load_best, load_history, list_runs, next_run_id,
)

# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL STATE
# ─────────────────────────────────────────────────────────────────────────────

class AppState:
    """Shared mutable state — thread-safe via lock."""

    def __init__(self, data_dir: str,
                 explore_dir: str = "./generated_formulas",
                 evolve_dir:  str = "./saved_formulas"):
        self.data_dir    = data_dir
        self.explore_dir = explore_dir
        self.evolve_dir  = evolve_dir
        self._lock       = threading.Lock()

        # Lazy-loaded
        self._loader:   Optional[DataLoader]       = None
        self._bruteforce: Optional[BruteForceEngine] = None
        self._explorer: Optional[ExplorationEngine] = None
        self._evolver:  Optional[EvolutionEngine]   = None

        # SSE subscriber queues  { subscriber_id → queue }
        self._explore_subs: Dict[str, queue.Queue] = {}
        self._bf_subs:      Dict[str, queue.Queue] = {}
        self._evolve_subs:  Dict[str, queue.Queue] = {}

        # Latest stats snapshots (for new subscribers joining mid-run)
        self._explore_stats: Optional[dict] = None
        self._bf_stats:     Optional[dict] = None
        self._evolve_stats:  Optional[dict] = None

        # Active thread references
        self._explore_thread: Optional[threading.Thread] = None
        self._evolve_thread:  Optional[threading.Thread] = None

    # ── Lazy singletons ────────────────────────────────────────────────────

    def loader(self) -> DataLoader:
        with self._lock:
            if self._loader is None:
                self._loader = DataLoader(self.data_dir, verbose=True)
        return self._loader

    def explorer(self) -> ExplorationEngine:
        # Load first (acquires lock, then releases)
        loader = self.loader()
        with self._lock:
            if self._explorer is None:
                self._explorer = ExplorationEngine(
                    loader, output_dir=self.explore_dir)
        return self._explorer

    def evolver(self) -> EvolutionEngine:
        loader = self.loader()
        with self._lock:
            if self._evolver is None:
                self._evolver = EvolutionEngine(
                    loader, output_dir=self.evolve_dir)
        return self._evolver

    def bruteforcer(self) -> BruteForceEngine:
        loader = self.loader()
        with self._lock:
            if self._bruteforce is None:
                self._bruteforce = BruteForceEngine(
                    loader, output_dir=self.explore_dir)
        return self._bruteforce

    def subscribe_bf(self, sub_id: str) -> queue.Queue:
        q = queue.Queue(maxsize=50)
        with self._lock:
            self._bf_subs[sub_id] = q
            if self._bf_stats:
                try: q.put_nowait(self._bf_stats)
                except queue.Full: pass
        return q

    def unsubscribe_bf(self, sub_id: str):
        with self._lock:
            self._bf_subs.pop(sub_id, None)

    def push_bf(self, stats):
        d = stats.to_dict()
        d['type'] = 'brute_force'
        with self._lock:
            self._bf_stats = d
            self._broadcast(self._bf_subs, d)

    # ── SSE pub/sub ────────────────────────────────────────────────────────

    def subscribe_explore(self, sub_id: str) -> queue.Queue:
        q = queue.Queue(maxsize=50)
        with self._lock:
            self._explore_subs[sub_id] = q
            # Send latest stats immediately if available
            if self._explore_stats:
                try: q.put_nowait(self._explore_stats)
                except queue.Full: pass
        return q

    def unsubscribe_explore(self, sub_id: str):
        with self._lock:
            self._explore_subs.pop(sub_id, None)

    def subscribe_evolve(self, sub_id: str) -> queue.Queue:
        q = queue.Queue(maxsize=50)
        with self._lock:
            self._evolve_subs[sub_id] = q
            if self._evolve_stats:
                try: q.put_nowait(self._evolve_stats)
                except queue.Full: pass
        return q

    def unsubscribe_evolve(self, sub_id: str):
        with self._lock:
            self._evolve_subs.pop(sub_id, None)

    def _broadcast(self, subs: dict, data: dict):
        dead = []
        for sid, q in list(subs.items()):
            try: q.put_nowait(data)
            except queue.Full: dead.append(sid)
        for sid in dead:
            subs.pop(sid, None)

    def push_explore(self, stats: ExplorationStats):
        d = stats.to_dict()
        with self._lock:
            self._explore_stats = d
            self._broadcast(self._explore_subs, d)

    def push_evolve(self, stats: EvolutionStats):
        d = stats.to_dict()
        with self._lock:
            self._evolve_stats = d
            self._broadcast(self._evolve_subs, d)

    # ── Status ─────────────────────────────────────────────────────────────

    def status(self) -> dict:
        with self._lock:
            explore_running = (self._explorer is not None and
                                self._explorer.is_running())
            evolve_running  = (self._evolver is not None and
                                self._evolver.is_running())
        return {
            "server":          "ok",
            "explore_running": explore_running,
            "evolve_running":  evolve_running,
            "bf_running":      (self._bruteforce is not None and self._bruteforce.is_running()),
            "explore_stats":   self._explore_stats,
            "evolve_stats":    self._evolve_stats,
            "data_dir":        self.data_dir,
        }


# ─────────────────────────────────────────────────────────────────────────────
# HTTP HANDLER
# ─────────────────────────────────────────────────────────────────────────────

CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control":                "no-cache",
}

_sub_counter = 0
_sub_lock    = threading.Lock()

def _next_sub_id() -> str:
    global _sub_counter
    with _sub_lock:
        _sub_counter += 1
        return f"sub_{_sub_counter}"


class Handler(BaseHTTPRequestHandler):

    # Injected by server setup
    app: AppState = None

    def log_message(self, fmt, *args):
        pass  # suppress default access log

    # ── Routing ────────────────────────────────────────────────────────────

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        p = urlparse(self.path)
        path = p.path.rstrip("/")

        if path == "/api/status":
            self._send(200, self.app.status())

        elif path == "/api/data/info":
            self._handle_data_info()

        elif path == "/api/brute/stream":
            self._handle_sse_generic(
                subscribe   = self.app.subscribe_bf,
                unsubscribe = self.app.unsubscribe_bf,
            )

        elif path == "/api/brute/summary":
            self._send(200, self.app._bf_stats or {})

        elif path == "/api/data/variables":
            self._send(200, {
                "categories": CATEGORIES,
                "variables":  get_variable_list(),
            })

        elif path == "/api/explore/stream":
            self._handle_sse_explore()

        elif path == "/api/explore/summary":
            self._handle_explore_summary()

        elif path == "/api/explore/batches":
            self._handle_list_batches()

        elif path.startswith("/api/explore/batch/"):
            name = path[len("/api/explore/batch/"):]
            qs   = parse_qs(p.query)
            offset = int(qs.get("offset", ["0"])[0])
            limit  = int(qs.get("limit",  ["50"])[0])
            self._send(200, load_batch(
                self.app.explore_dir, name, offset, limit))

        elif path == "/api/evolve/stream":
            self._handle_sse_evolve()

        elif path == "/api/formulas":
            self._handle_list_formulas()

        elif path.startswith("/api/evolve/") and "/runs" in path:
            fid = path.split("/")[3]
            self._send(200, list_runs(self.app.evolve_dir, fid))

        elif path.startswith("/api/evolve/"):
            parts = path.split("/")
            # /api/evolve/:fid/:rid/best  or  /api/evolve/:fid/:rid/history
            if len(parts) >= 6:
                fid  = parts[3]
                rid  = parts[4]
                what = parts[5]
                if what == "best":
                    r = load_best(self.app.evolve_dir, fid, rid)
                    self._send(200 if r else 404, r or {"error": "not found"})
                elif what == "history":
                    r = load_history(self.app.evolve_dir, fid, rid)
                    self._send(200 if r else 404, r or {"error": "not found"})
                else:
                    self._send(404, {"error": "unknown endpoint"})
            else:
                self._send(404, {"error": "unknown endpoint"})

        elif path.startswith("/api/formulas/"):
            fid = path[len("/api/formulas/"):]
            self._handle_get_formula(fid)

        elif path == "" or path == "/":
            self._serve_static("index.html")

        elif path.startswith("/assets/"):
            self._serve_static(path.lstrip("/"))

        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        body = self._read_body()

        if path == "/api/explore/start":
            self._handle_explore_start(body)
        elif path == "/api/explore/stop":
            self._handle_explore_stop()
        elif path == "/api/evolve/start":
            self._handle_evolve_start(body)
        elif path == "/api/evolve/stop":
            self._handle_evolve_stop()
        elif path == "/api/brute/start":
            self._handle_bf_start(body)
        elif path == "/api/brute/stop":
            self._handle_bf_stop()
        elif path == "/api/dashboard/evaluate":
            self._handle_dashboard_evaluate(body)
        else:
            self._send(404, {"error": "not found"})

    # ── Handlers ───────────────────────────────────────────────────────────

    def _handle_data_info(self):
        try:
            info = self.app.loader().info()
            self._send(200, info)
        except Exception as e:
            self._send(500, {"error": str(e)})

    def _handle_explore_summary(self):
        s = load_summary(self.app.explore_dir)
        self._send(200, s or {})

    def _handle_list_batches(self):
        self._send(200, list_batches(self.app.explore_dir))

    def _handle_list_formulas(self):
        """List all saved formulas from the evolve dir."""
        out = []
        d   = self.app.evolve_dir
        if os.path.isdir(d):
            for fid in sorted(os.listdir(d)):
                runs = list_runs(d, fid)
                out.append({"formula_id": fid, "runs": runs})
        self._send(200, out)

    def _handle_get_formula(self, fid: str):
        """Get a formula + its runs."""
        runs = list_runs(self.app.evolve_dir, fid)
        if not runs:
            # Try explore dir
            from exploration_engine import get_formula as gf
            parts = fid.split("/")
            if len(parts) == 2:
                rec = gf(self.app.explore_dir, parts[0], parts[1])
                if rec:
                    self._send(200, rec); return
            self._send(404, {"error": "not found"}); return
        self._send(200, {"formula_id": fid, "runs": runs})

    def _handle_explore_start(self, body: dict):
        eng = self.app.explorer()
        if eng.is_running():
            self._send(409, {"error": "Exploration already running"}); return

        try:
            cfg = ExplorationConfig.from_dict(body) if body else ExplorationConfig()
        except Exception as e:
            self._send(400, {"error": f"Bad config: {e}"}); return

        def _run():
            eng.run(
                config      = cfg,
                on_progress = self.app.push_explore,
                on_save     = lambda rec: self.app.push_explore(eng.stats),
            )
            # Final push when done
            self.app.push_explore(eng.stats)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        self.app._explore_thread = t
        self._send(200, {"started": True, "batch_name": cfg.batch_name})

    def _handle_explore_stop(self):
        eng = self.app.explorer()
        if not eng.is_running():
            self._send(200, {"stopped": False, "reason": "not running"}); return
        eng.request_stop()
        self._send(200, {"stopped": True, "message": "Stop signal sent"})

    def _handle_evolve_start(self, body: dict):
        eng = self.app.evolver()
        if eng.is_running():
            self._send(409, {"error": "Evolution already running"}); return

        formula_id = body.get("formula_id")
        if not formula_id:
            self._send(400, {"error": "formula_id required"}); return

        # Load start node from body or from saved formula
        from formula_engine import node_from_dict
        tree = body.get("tree")
        if tree:
            try:
                start_node = node_from_dict(tree)
            except Exception as e:
                self._send(400, {"error": f"Bad tree: {e}"}); return
        else:
            # Try to load from generated or saved formulas
            batch = body.get("batch_name", "")
            rec   = get_formula(self.app.explore_dir, batch, formula_id) if batch else None
            if rec is None:
                best = load_best(self.app.evolve_dir, formula_id,
                                  body.get("run_id", "run_001"))
                if best:
                    rec = best
            if rec is None:
                self._send(404, {"error": "formula not found"}); return
            try:
                start_node = node_from_dict(rec["tree"])
            except Exception as e:
                self._send(400, {"error": f"Bad stored tree: {e}"}); return

        try:
            cfg = EvolutionConfig.from_dict(body.get("config", {}))
        except Exception as e:
            self._send(400, {"error": f"Bad config: {e}"}); return

        run_id = body.get("run_id") or next_run_id(
            self.app.evolve_dir, formula_id)

        # Check if continuing existing run
        continue_run = body.get("continue", False)

        def _run():
            try:
                if continue_run:
                    eng.continue_run(
                        formula_id  = formula_id,
                        run_id      = run_id,
                        config      = cfg,
                        on_progress = self.app.push_evolve,
                        on_accept   = lambda rec: self.app.push_evolve(eng.stats),
                    )
                else:
                    eng.run(
                        formula_id  = formula_id,
                        start_node  = start_node,
                        config      = cfg,
                        run_id      = run_id,
                        on_progress = self.app.push_evolve,
                        on_accept   = lambda rec: self.app.push_evolve(eng.stats),
                    )
            except Exception as ex:
                print(f"[Evolution] Error: {ex}")
            finally:
                self.app.push_evolve(eng.stats)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        self.app._evolve_thread = t
        self._send(200, {"started": True, "run_id": run_id,
                          "formula_id": formula_id})

    def _handle_evolve_stop(self):
        eng = self.app.evolver()
        if not eng.is_running():
            self._send(200, {"stopped": False, "reason": "not running"}); return
        eng.request_stop()
        self._send(200, {"stopped": True, "message": "Stop signal sent"})

    def _handle_bf_start(self, body: dict):
        eng = self.app.bruteforcer()
        if eng.is_running():
            self._send(409, {"error": "Brute force already running"}); return
        try:
            cfg = BruteForceConfig.from_dict(body) if body else BruteForceConfig()
        except Exception as e:
            self._send(400, {"error": f"Bad config: {e}"}); return

        def _run():
            eng.run(
                config      = cfg,
                on_progress = self.app.push_bf,
                on_save     = lambda rec: self.app.push_bf(eng.stats),
            )
            self.app.push_bf(eng.stats)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        self._send(200, {"started": True, "batch_name": cfg.batch_name})

    def _handle_bf_stop(self):
        eng = self.app.bruteforcer()
        if not eng.is_running():
            self._send(200, {"stopped": False}); return
        eng.request_stop()
        self._send(200, {"stopped": True})

    def _handle_dashboard_evaluate(self, body: dict):
        tree = body.get("tree")
        if not tree:
            self._send(400, {"error": "tree required"}); return
        try:
            result = evaluate_formula_dashboard(tree, self.app.loader())
            self._send(200, result)
        except Exception as e:
            self._send(500, {"error": str(e)})

    def _handle_bf_start(self, body: dict):
        eng = self.app.bruteforcer()
        if eng.is_running():
            self._send(409, {"error": "Brute force already running"}); return
        try:
            cfg = BruteForceConfig.from_dict(body) if body else BruteForceConfig()
        except Exception as e:
            self._send(400, {"error": f"Bad config: {e}"}); return

        def _run():
            eng.run(
                config      = cfg,
                on_progress = self.app.push_bf,
                on_save     = lambda rec: self.app.push_bf(eng.stats),
            )
            self.app.push_bf(eng.stats)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        self._send(200, {"started": True, "batch_name": cfg.batch_name})

    def _handle_bf_stop(self):
        eng = self.app.bruteforcer()
        if not eng.is_running():
            self._send(200, {"stopped": False}); return
        eng.request_stop()
        self._send(200, {"stopped": True})

    def _handle_dashboard_evaluate(self, body: dict):
        tree = body.get("tree")
        if not tree:
            self._send(400, {"error": "tree required"}); return
        try:
            result = evaluate_formula_dashboard(tree, self.app.loader())
            self._send(200, result)
        except Exception as e:
            self._send(500, {"error": str(e)})

    # ── SSE ────────────────────────────────────────────────────────────────

    def _handle_sse_explore(self):
        self._sse_loop(self.app.subscribe_explore, self.app.unsubscribe_explore)

    def _handle_sse_evolve(self):
        self._sse_loop(self.app.subscribe_evolve, self.app.unsubscribe_evolve)

    def _handle_sse_generic(self, subscribe, unsubscribe):
        self._sse_loop(subscribe, unsubscribe)

    def _sse_loop(self, subscribe, unsubscribe):
        sub_id = _next_sub_id()
        q      = subscribe(sub_id)

        self.send_response(200)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Type",  "text/event-stream")
        self.send_header("Connection",    "keep-alive")
        self.end_headers()

        try:
            # Send initial keepalive
            self._sse_write({"type": "connected", "sub_id": sub_id})

            while True:
                try:
                    data = q.get(timeout=15)  # 15s timeout → send keepalive
                    self._sse_write(data)
                except queue.Empty:
                    # Keepalive ping
                    self._sse_write({"type": "ping"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            unsubscribe(sub_id)

    def _sse_write(self, data: dict):
        msg = f"data: {json.dumps(data)}\n\n"
        self.wfile.write(msg.encode())
        self.wfile.flush()

    # ── Static files ───────────────────────────────────────────────────────

    def _serve_static(self, rel_path: str):
        dist = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "dist")
        path = os.path.normpath(os.path.join(dist, rel_path))

        # Security: prevent path traversal
        if not path.startswith(dist):
            self._send_raw(403, b"Forbidden", "text/plain"); return

        if not os.path.exists(path):
            # SPA fallback: serve index.html for unknown routes
            path = os.path.join(dist, "index.html")
            if not os.path.exists(path):
                self._send_raw(404, b"Not found", "text/plain"); return

        ext_map = {
            ".html": "text/html",
            ".js":   "application/javascript",
            ".css":  "text/css",
            ".json": "application/json",
            ".png":  "image/png",
            ".svg":  "image/svg+xml",
            ".ico":  "image/x-icon",
            ".woff2":"font/woff2",
        }
        ext  = os.path.splitext(path)[1].lower()
        mime = ext_map.get(ext, "application/octet-stream")

        with open(path, "rb") as f:
            content = f.read()

        self._send_raw(200, content, mime)

    # ── HTTP helpers ───────────────────────────────────────────────────────

    def _send(self, code: int, data: Any):
        body = json.dumps(data).encode()
        self.send_response(code)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_raw(self, code: int, body: bytes, mime: str):
        self.send_response(code)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Type",   mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length: return {}
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}


# ─────────────────────────────────────────────────────────────────────────────
# THREADED SERVER
# ─────────────────────────────────────────────────────────────────────────────

class ThreadedServer(HTTPServer):
    """One thread per request."""
    def process_request(self, request, client_address):
        t = threading.Thread(
            target=self._process_request_thread,
            args=(request, client_address),
            daemon=True,
        )
        t.start()

    def _process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def make_app(data_dir: str,
             explore_dir: str = "./generated_formulas",
             evolve_dir:  str = "./saved_formulas") -> AppState:
    """Create and return the AppState (useful for testing)."""
    os.makedirs(explore_dir, exist_ok=True)
    os.makedirs(evolve_dir,  exist_ok=True)
    return AppState(data_dir, explore_dir, evolve_dir)


def make_handler(app: AppState):
    """Create a Handler class with the app baked in."""
    class BoundHandler(Handler):
        pass
    BoundHandler.app = app
    return BoundHandler


def run_server(data_dir: str, port: int = 8080,
               explore_dir: str = "./generated_formulas",
               evolve_dir:  str = "./saved_formulas"):
    app     = make_app(data_dir, explore_dir, evolve_dir)
    handler = make_handler(app)
    server  = ThreadedServer(("", port), handler)

    print(f"╔══════════════════════════════════════════════════╗")
    print(f"║  NBA Formula Evolver — Backend Server            ║")
    print(f"║  http://localhost:{port:<5}                         ║")
    print(f"║  Data: {data_dir:<42}║")
    print(f"╚══════════════════════════════════════════════════╝")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Server] Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NBA Formula Evolver — Backend")
    parser.add_argument("--data-dir",    default="./nba_data",
                        help="Path to NBA data directory")
    parser.add_argument("--port",        type=int, default=8080)
    parser.add_argument("--explore-dir", default="./generated_formulas")
    parser.add_argument("--evolve-dir",  default="./saved_formulas")
    args = parser.parse_args()

    run_server(args.data_dir, args.port, args.explore_dir, args.evolve_dir)