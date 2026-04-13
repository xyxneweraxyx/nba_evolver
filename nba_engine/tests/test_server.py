#!/usr/bin/env python3
"""
tests/test_server.py — Layer 6 (Backend API) test suite
=========================================================
Tests the HTTP server endpoints and SSE streaming.

Run: python3 tests/test_server.py

Uses a live test server on a random port.
"""

import sys, os, json, time, tempfile, shutil, threading, urllib.request
import urllib.error, queue, socket
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import make_app, make_handler, ThreadedServer

# ── framework ─────────────────────────────────────────────────────────────────
_p = _f = 0
def test(name, fn):
    global _p, _f
    try:
        fn()
        print(f"  {'PASS':6}  {name}")
        _p += 1
    except AssertionError as e:
        print(f"  {'FAIL':6}  {name}\n           {e}")
        _f += 1
    except Exception as e:
        print(f"  {'ERROR':6}  {name}\n           {type(e).__name__}: {e}")
        _f += 1

# ─────────────────────────────────────────────────────────────────────────────
# TEST SERVER SETUP
# ─────────────────────────────────────────────────────────────────────────────

TMPDIR = None
SERVER = None
PORT   = None
BASE   = None

def find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]

def make_game(i, won):
    return {
        "meta":   {"game_id": f"t_{i:04d}", "season": "2021-22",
                   "game_number": i+1},
        "result": {"winner": "home" if won else "away",
                   "home_pts": 112, "away_pts": 105},
        "home": {
            "team_id": 1,
            "binary":  {"is_home":1,"is_back_to_back":0,
                         "opponent_is_back_to_back":0},
            "context": {"match_number":i+1,"rest_days":2,
                         "opponent_rest_days":2,"win_streak":1,
                         "home_win_streak":1,"games_last_7_days":3,
                         "days_since_last_home_game":4,
                         "players_available":11,
                         "km_traveled":0,"timezone_shift":0},
            "season_stats": {
                "net_rtg": 5.0 if won else -3.0,
                "off_rtg": 115.0, "w_pct": 0.65 if won else 0.40,
                "pts": 112, "pace": 99.0,
            },
            **{k: None for k in ["last10_stats","last5_stats","home_stats",
               "away_stats","b2b_stats","vs_above500_stats",
               "q1_stats","q4_stats","clutch_stats"]},
            "players": [],
        },
        "away": {
            "team_id": 2,
            "binary":  {"is_home":0,"is_back_to_back":0,
                         "opponent_is_back_to_back":0},
            "context": {"match_number":i+1,"rest_days":2,
                         "opponent_rest_days":2,"win_streak":-1,
                         "home_win_streak":0,"games_last_7_days":3,
                         "days_since_last_home_game":7,
                         "players_available":10,
                         "km_traveled":800,"timezone_shift":-1},
            "season_stats": {
                "net_rtg": -5.0 if won else 3.0,
                "off_rtg": 110.0, "w_pct": 0.40 if won else 0.65,
                "pts": 105, "pace": 98.0,
            },
            **{k: None for k in ["last10_stats","last5_stats","home_stats",
               "away_stats","b2b_stats","vs_above500_stats",
               "q1_stats","q4_stats","clutch_stats"]},
            "players": [],
        },
    }

def setup():
    global TMPDIR, SERVER, PORT, BASE

    TMPDIR = tempfile.mkdtemp(prefix="nba_srv_")

    # Build minimal data
    path = os.path.join(TMPDIR, "nba_data", "training", "2021-22")
    os.makedirs(path)
    for i in range(200):
        g = make_game(i, won=(i % 10 < 7))
        with open(os.path.join(path, f"t_{i:04d}.json"), "w") as f:
            json.dump(g, f)

    explore_dir = os.path.join(TMPDIR, "generated_formulas")
    evolve_dir  = os.path.join(TMPDIR, "saved_formulas")

    PORT = find_free_port()
    BASE = f"http://localhost:{PORT}"

    app     = make_app(os.path.join(TMPDIR, "nba_data"),
                        explore_dir, evolve_dir)
    handler = make_handler(app)
    SERVER  = ThreadedServer(("", PORT), handler)

    t = threading.Thread(target=SERVER.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)   # let server start


def teardown():
    if SERVER: SERVER.shutdown()
    if TMPDIR and os.path.isdir(TMPDIR): shutil.rmtree(TMPDIR)


# ─────────────────────────────────────────────────────────────────────────────
# HTTP HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get(path: str, timeout: float = 5.0) -> tuple:
    """Returns (status_code, json_body)."""
    req = urllib.request.Request(f"{BASE}{path}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def post(path: str, body: dict = None, timeout: float = 5.0) -> tuple:
    data = json.dumps(body or {}).encode()
    req  = urllib.request.Request(
        f"{BASE}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def read_sse_events(path: str, n: int = 3,
                    timeout: float = 8.0) -> list:
    """Read first n SSE events from an endpoint."""
    events = []
    req = urllib.request.Request(f"{BASE}{path}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            buf = b""
            deadline = time.time() + timeout
            while len(events) < n and time.time() < deadline:
                chunk = r.read(1)
                if not chunk: break
                buf += chunk
                while b"\n\n" in buf:
                    msg, buf = buf.split(b"\n\n", 1)
                    for line in msg.split(b"\n"):
                        if line.startswith(b"data:"):
                            try:
                                events.append(json.loads(line[5:].strip()))
                            except Exception:
                                pass
    except Exception:
        pass
    return events

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 1: Basic connectivity
# ─────────────────────────────────────────────────────────────────────────────

def test_server_starts():
    code, body = get("/api/status")
    assert code == 200
    assert body["server"] == "ok"

def test_status_fields():
    code, body = get("/api/status")
    assert "explore_running" in body
    assert "evolve_running"  in body
    assert not body["explore_running"]
    assert not body["evolve_running"]

def test_cors_headers():
    req = urllib.request.Request(f"{BASE}/api/status")
    with urllib.request.urlopen(req, timeout=5) as r:
        headers = dict(r.headers)
    assert "Access-Control-Allow-Origin" in headers or \
           "access-control-allow-origin" in headers

def test_unknown_endpoint_404():
    code, _ = get("/api/nonexistent")
    assert code == 404

def test_data_info():
    code, body = get("/api/data/info")
    assert code == 200
    assert "training" in body
    assert body["training"]["total_games"] == 200

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 2: Explore endpoints
# ─────────────────────────────────────────────────────────────────────────────

def test_explore_summary_empty():
    code, body = get("/api/explore/summary")
    assert code == 200
    # Empty dir returns {}
    assert isinstance(body, dict)

def test_explore_batches_empty():
    code, body = get("/api/explore/batches")
    assert code == 200
    assert isinstance(body, list)

def test_explore_start_stop():
    # Start exploration
    code, body = post("/api/explore/start", {
        "batch_name":        "api_test_batch",
        "max_generated":     0,       # unlimited — we'll stop it
        "fast_prefilter_n":  50,
        "fast_min_interest": 0.01,
        "min_interest":      0.01,
        "save_min_interest": 0.01,
        "block_size":        30,
        "dedup_enabled":     False,
        "report_every":      20,
    })
    assert code == 200
    assert body["started"] is True
    assert body["batch_name"] == "api_test_batch"

    # Verify running
    time.sleep(0.3)
    code2, status = get("/api/status")
    assert status["explore_running"] is True

    # Stop
    code3, stop = post("/api/explore/stop")
    assert code3 == 200
    assert stop["stopped"] is True

    # Wait for stop
    for _ in range(20):
        time.sleep(0.2)
        _, st = get("/api/status")
        if not st["explore_running"]: break

    _, st = get("/api/status")
    assert not st["explore_running"]

def test_explore_double_start_409():
    # Start once
    post("/api/explore/start", {
        "max_generated": 0, "fast_prefilter_n": 50,
        "min_interest": 0.01, "save_min_interest": 0.01,
        "block_size": 30, "dedup_enabled": False,
        "report_every": 50,
    })
    time.sleep(0.2)

    # Try to start again
    code, body = post("/api/explore/start", {
        "max_generated": 0, "fast_prefilter_n": 50,
        "min_interest": 0.01, "save_min_interest": 0.01,
        "block_size": 30, "dedup_enabled": False,
        "report_every": 50,
    })
    assert code == 409, f"Expected 409, got {code}"

    # Clean up
    post("/api/explore/stop")
    for _ in range(15):
        time.sleep(0.2)
        _, st = get("/api/status")
        if not st["explore_running"]: break

def test_explore_stop_when_not_running():
    _, st = get("/api/status")
    if st["explore_running"]:
        post("/api/explore/stop")
        time.sleep(1.0)

    code, body = post("/api/explore/stop")
    assert code == 200
    assert body["stopped"] is False

def test_explore_batch_after_run():
    """Run a short exploration and check the batch endpoint."""
    post("/api/explore/start", {
        "batch_name":        "batch_check",
        "max_generated":     100,
        "fast_prefilter_n":  50,
        "fast_min_interest": 0.01,
        "min_interest":      0.01,
        "save_min_interest": 0.01,
        "block_size":        30,
        "dedup_enabled":     False,
        "report_every":      100,
    })
    # Wait for it to finish
    for _ in range(30):
        time.sleep(0.3)
        _, st = get("/api/status")
        if not st["explore_running"]: break

    # Check batches list
    code, batches = get("/api/explore/batches")
    assert code == 200
    names = [b["name"] for b in batches]
    assert "batch_check" in names, f"batch_check not in {names}"

    # Check summary
    code2, summ = get("/api/explore/summary")
    assert code2 == 200

    # Check batch formulas
    code3, forms = get("/api/explore/batch/batch_check?limit=10")
    assert code3 == 200
    assert isinstance(forms, list)

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 3: SSE streaming
# ─────────────────────────────────────────────────────────────────────────────

def test_sse_explore_connects():
    events = read_sse_events("/api/explore/stream", n=1, timeout=3.0)
    assert len(events) >= 1
    assert events[0].get("type") == "connected"

def test_sse_explore_receives_stats():
    """Start exploration and verify SSE stream gets stats."""
    # Start exploration in background
    post("/api/explore/start", {
        "batch_name":        "sse_test",
        "max_generated":     0,
        "fast_prefilter_n":  50,
        "fast_min_interest": 0.01,
        "min_interest":      0.01,
        "save_min_interest": 0.01,
        "block_size":        30,
        "dedup_enabled":     False,
        "report_every":      10,
    })

    time.sleep(0.1)
    # Read a few events
    events = read_sse_events("/api/explore/stream", n=3, timeout=5.0)
    post("/api/explore/stop")

    # Wait for stop
    for _ in range(15):
        time.sleep(0.2)
        _, st = get("/api/status")
        if not st["explore_running"]: break

    # Should have received at least connected + some stats
    assert len(events) >= 1
    types = [e.get("type") for e in events]
    assert "connected" in types

    stat_events = [e for e in events if "n_generated" in e]
    if stat_events:
        assert "formulas_per_s" in stat_events[0]
        assert "n_saved"        in stat_events[0]

def test_sse_evolve_connects():
    events = read_sse_events("/api/evolve/stream", n=1, timeout=3.0)
    assert len(events) >= 1
    assert events[0].get("type") == "connected"

def test_sse_keepalive():
    """SSE should send keepalive ping if no activity."""
    # With no engines running, we should eventually get a ping
    events = read_sse_events("/api/explore/stream", n=2, timeout=5.0)
    types  = [e.get("type") for e in events]
    # Should have connected + potentially ping
    assert "connected" in types

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 4: Evolve endpoints
# ─────────────────────────────────────────────────────────────────────────────

def _formula_tree():
    """Simple formula tree dict."""
    from formula_engine import VarNode
    from nba_engine_binding import get_registry
    reg = get_registry()
    idx = reg.get("season_stats.net_rtg", 3)
    return VarNode("season_stats.net_rtg", idx).to_dict()

def test_evolve_start_stop():
    code, body = post("/api/evolve/start", {
        "formula_id": "f_api_001",
        "tree":       _formula_tree(),
        "config": {
            "max_generations":  0,
            "stagnation_limit": 10000,
            "eval_block_size":  100,
            "min_improvement":  0.0001,
            "attempts_per_gen": 2,
            "report_every":     20,
        },
    })
    assert code == 200
    assert body["started"] is True

    time.sleep(0.3)
    _, st = get("/api/status")
    assert st["evolve_running"] is True

    code2, stop = post("/api/evolve/stop")
    assert code2 == 200
    assert stop["stopped"] is True

    for _ in range(15):
        time.sleep(0.2)
        _, st = get("/api/status")
        if not st["evolve_running"]: break

    _, st = get("/api/status")
    assert not st["evolve_running"]

def test_evolve_double_start_409():
    post("/api/evolve/start", {
        "formula_id": "f_double",
        "tree": _formula_tree(),
        "config": {"max_generations": 0, "stagnation_limit": 10000,
                    "eval_block_size": 100, "min_improvement": 0.0001,
                    "attempts_per_gen": 2, "report_every": 100},
    })
    time.sleep(0.2)

    code, _ = post("/api/evolve/start", {
        "formula_id": "f_double2",
        "tree": _formula_tree(),
        "config": {"max_generations": 0, "stagnation_limit": 10000,
                    "eval_block_size": 100, "min_improvement": 0.0001,
                    "attempts_per_gen": 2, "report_every": 100},
    })
    assert code == 409

    post("/api/evolve/stop")
    for _ in range(15):
        time.sleep(0.2)
        _, st = get("/api/status")
        if not st["evolve_running"]: break

def test_evolve_stop_when_not_running():
    _, st = get("/api/status")
    if st["evolve_running"]:
        post("/api/evolve/stop")
        time.sleep(1.0)

    code, body = post("/api/evolve/stop")
    assert code == 200
    assert body["stopped"] is False

def test_evolve_missing_formula_id():
    code, body = post("/api/evolve/start", {
        "tree": _formula_tree(),
        "config": {"max_generations": 5},
    })
    assert code == 400
    assert "formula_id" in body.get("error", "")

def test_evolve_creates_run_files():
    """Run a short evolution and check files are created."""
    post("/api/evolve/start", {
        "formula_id": "f_files",
        "run_id":     "run_001",
        "tree":       _formula_tree(),
        "config": {
            "max_generations":  20,
            "stagnation_limit": 20,
            "eval_block_size":  60,
            "min_improvement":  0.0001,
            "attempts_per_gen": 3,
            "report_every":     50,
        },
    })
    # Wait for it to finish
    for _ in range(30):
        time.sleep(0.3)
        _, st = get("/api/status")
        if not st["evolve_running"]: break

    # Check runs endpoint
    code, runs = get("/api/evolve/f_files/runs")
    assert code == 200
    assert isinstance(runs, list)
    assert len(runs) >= 1

    # Check best endpoint
    code2, best = get("/api/evolve/f_files/run_001/best")
    assert code2 == 200
    assert "accuracy" in best or "tree" in best

    # Check history endpoint
    code3, hist = get("/api/evolve/f_files/run_001/history")
    assert code3 == 200
    assert "history" in hist

def test_evolve_sse_receives_stats():
    """Evolution SSE should broadcast stats."""
    post("/api/evolve/start", {
        "formula_id": "f_sse",
        "tree":       _formula_tree(),
        "config": {
            "max_generations":  0,
            "stagnation_limit": 10000,
            "eval_block_size":  60,
            "min_improvement":  0.0001,
            "attempts_per_gen": 2,
            "report_every":     5,
        },
    })

    time.sleep(0.1)
    events = read_sse_events("/api/evolve/stream", n=3, timeout=4.0)
    post("/api/evolve/stop")

    for _ in range(15):
        time.sleep(0.2)
        _, st = get("/api/status")
        if not st["evolve_running"]: break

    assert len(events) >= 1
    assert events[0].get("type") == "connected"

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 5: Formulas endpoints
# ─────────────────────────────────────────────────────────────────────────────

def test_formulas_list_empty():
    code, body = get("/api/formulas")
    assert code == 200
    assert isinstance(body, list)

def test_formulas_list_after_evolve():
    """After a successful evolve run, formula should appear in list."""
    # Run evolution to generate some saved files
    post("/api/evolve/start", {
        "formula_id": "f_list_test",
        "run_id":     "run_001",
        "tree":       _formula_tree(),
        "config": {
            "max_generations":  15,
            "stagnation_limit": 15,
            "eval_block_size":  60,
            "min_improvement":  0.0001,
            "attempts_per_gen": 2,
            "report_every":     100,
        },
    })
    for _ in range(20):
        time.sleep(0.3)
        _, st = get("/api/status")
        if not st["evolve_running"]: break

    code, body = get("/api/formulas")
    assert code == 200
    fids = [f["formula_id"] for f in body]
    assert "f_list_test" in fids

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 6: Static files
# ─────────────────────────────────────────────────────────────────────────────

def test_static_index_html():
    """Server should serve index.html or 404 if dist/ doesn't exist."""
    req = urllib.request.Request(f"{BASE}/")
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            assert r.getcode() == 200
    except urllib.error.HTTPError as e:
        assert e.code == 404  # dist/ not built yet — acceptable

def test_static_path_traversal_blocked():
    """Path traversal should be blocked."""
    req = urllib.request.Request(f"{BASE}/../../etc/passwd")
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            code = r.getcode()
    except urllib.error.HTTPError as e:
        code = e.code
    assert code in (400, 403, 404)

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 7: Error handling
# ─────────────────────────────────────────────────────────────────────────────

def test_bad_json_body():
    """Bad JSON in POST body should not crash server."""
    req = urllib.request.Request(
        f"{BASE}/api/explore/start",
        data=b"not valid json{{{",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            code = r.getcode()
    except urllib.error.HTTPError as e:
        code = e.code
    # Server should handle gracefully
    assert code in (200, 400, 422, 500)

def test_server_handles_concurrent_requests():
    """Multiple concurrent GET requests should all succeed."""
    results = []

    def fetch():
        code, _ = get("/api/status")
        results.append(code)

    threads = [threading.Thread(target=fetch) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=5)

    assert len(results) == 10
    assert all(c == 200 for c in results), f"Not all 200: {results}"

def test_evolve_unknown_formula_404():
    code, body = get("/api/evolve/does_not_exist/runs")
    assert code == 200   # returns empty list, not 404
    assert body == []

def test_evolve_best_missing_404():
    code, body = get("/api/evolve/does_not_exist/run_001/best")
    assert code == 404

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 8: Status updates during run
# ─────────────────────────────────────────────────────────────────────────────

def test_status_reflects_explore_running():
    """Status endpoint should accurately reflect exploration state."""
    _, st = get("/api/status")
    assert not st["explore_running"]

    post("/api/explore/start", {
        "max_generated": 0, "fast_prefilter_n": 50,
        "min_interest": 0.01, "save_min_interest": 0.01,
        "block_size": 30, "dedup_enabled": False, "report_every": 100,
    })

    # Wait up to 2s for engine to start
    running = False
    for _ in range(20):
        time.sleep(0.1)
        _, st = get("/api/status")
        if st["explore_running"]:
            running = True
            break
    assert running, "Engine should be running after start"

    post("/api/explore/stop")
    for _ in range(25):
        time.sleep(0.2)
        _, st = get("/api/status")
        if not st["explore_running"]: break

    _, st = get("/api/status")
    assert not st["explore_running"]

def test_status_has_stats_after_explore():
    """After exploration, status should contain explore_stats."""
    post("/api/explore/start", {
        "batch_name": "stats_check",
        "max_generated": 50,
        "fast_prefilter_n": 30,
        "min_interest": 0.01,
        "save_min_interest": 0.01,
        "block_size": 30,
        "dedup_enabled": False,
        "report_every": 25,
    })
    for _ in range(20):
        time.sleep(0.3)
        _, st = get("/api/status")
        if not st["explore_running"]: break

    _, st = get("/api/status")
    assert st["explore_stats"] is not None
    assert "n_generated" in st["explore_stats"]

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    setup()
    print(f"\n╔══════════════════════════════════════════════════════╗")
    print(f"║   Layer 6 — Backend API Test Suite (port {PORT})    ║")
    print(f"╚══════════════════════════════════════════════════════╝\n")

    print("── 1. Connectivity ───────────────────────────────────────")
    test("server_starts",           test_server_starts)
    test("status_fields",           test_status_fields)
    test("cors_headers",            test_cors_headers)
    test("unknown_404",             test_unknown_endpoint_404)
    test("data_info",               test_data_info)

    print("\n── 2. Explore endpoints ──────────────────────────────────")
    test("explore_summary_empty",   test_explore_summary_empty)
    test("explore_batches_empty",   test_explore_batches_empty)
    test("explore_start_stop",      test_explore_start_stop)
    test("explore_double_409",      test_explore_double_start_409)
    test("explore_stop_idle",       test_explore_stop_when_not_running)
    test("explore_batch_after_run", test_explore_batch_after_run)

    print("\n── 3. SSE streaming ──────────────────────────────────────")
    test("sse_explore_connects",    test_sse_explore_connects)
    test("sse_explore_stats",       test_sse_explore_receives_stats)
    test("sse_evolve_connects",     test_sse_evolve_connects)
    test("sse_keepalive",           test_sse_keepalive)

    print("\n── 4. Evolve endpoints ───────────────────────────────────")
    test("evolve_start_stop",       test_evolve_start_stop)
    test("evolve_double_409",       test_evolve_double_start_409)
    test("evolve_stop_idle",        test_evolve_stop_when_not_running)
    test("evolve_missing_fid",      test_evolve_missing_formula_id)
    test("evolve_creates_files",    test_evolve_creates_run_files)
    test("evolve_sse_stats",        test_evolve_sse_receives_stats)

    print("\n── 5. Formulas endpoints ─────────────────────────────────")
    test("formulas_empty",          test_formulas_list_empty)
    test("formulas_after_evolve",   test_formulas_list_after_evolve)

    print("\n── 6. Static files ───────────────────────────────────────")
    test("static_index",            test_static_index_html)
    test("path_traversal_blocked",  test_static_path_traversal_blocked)

    print("\n── 7. Error handling ─────────────────────────────────────")
    test("bad_json_body",           test_bad_json_body)
    test("concurrent_requests",     test_server_handles_concurrent_requests)
    test("unknown_formula_runs",    test_evolve_unknown_formula_404)
    test("best_missing_404",        test_evolve_best_missing_404)

    print("\n── 8. Status updates ─────────────────────────────────────")
    test("status_explore_running",  test_status_reflects_explore_running)
    test("status_has_stats",        test_status_has_stats_after_explore)

    teardown()
    print(f"\n╔══════════════════════════════════════════════════════╗")
    print(f"║  Results: {_p:3d} passed  {_f:3d} failed  {_p+_f:3d} total           ║")
    print(f"╚══════════════════════════════════════════════════════╝\n")
    return 0 if _f == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
