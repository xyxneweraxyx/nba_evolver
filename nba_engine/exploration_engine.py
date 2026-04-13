"""
exploration_engine.py — Layer 4: Exploration Engine
=====================================================
Massive random formula generation with interest filtering.
Designed to feed the frontend via clean JSON state + SSE-friendly callbacks.

Architecture:
  ExplorationEngine.run()
    ├── generates random formulas (Layer 2)
    ├── evaluates with interest filter (Layer 1 C engine)
    ├── saves survivors to generated_formulas/
    └── emits real-time stats via callback (for SSE streaming)

Output structure:
  generated_formulas/
    batch_YYYYMMDD_HHMMSS/
      formula_0001.json
      formula_0002.json
      ...
    summary.json          ← live-updated after each save
"""

from __future__ import annotations

import os
import json
import time
import random
import hashlib
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, List, Optional, Set

from nba_engine_binding import FormulaEngine, CDataset
from formula_engine import (
    Node, random_formula, ast_to_c_formula,
    variable_set,
)
from data_loader import DataLoader, subset_cdataset

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExplorationConfig:
    """All tunable parameters for one exploration run."""

    # ── Generation ────────────────────────────────────────────────────────
    max_depth:    int   = 4       # max AST depth
    max_size:     int   = 50      # max AST nodes

    # ── Interest filter ───────────────────────────────────────────────────
    block_size:   int   = 100     # games per evaluation block
    min_interest: float = 0.20    # minimum |acc-0.5|*2 to survive each block

    # Interest direction:
    #   "both"      → keep formulas good (>0.5) AND bad (<0.5)
    #   "good_only" → only keep high accuracy (>0.5)
    #   "bad_only"  → only keep low accuracy (<0.5)
    interest_mode: str  = "both"

    # ── Fast pre-filter ───────────────────────────────────────────────────
    # Evaluate on a small subset first for speed, then full dataset
    # Set to 0 to disable (evaluate on full dataset from the start)
    fast_prefilter_n: int   = 500   # games for initial fast filter
    fast_min_interest: float = 0.10  # min interest on fast subset to proceed

    # ── Save thresholds ───────────────────────────────────────────────────
    save_min_interest: float = 0.30  # min interest to save a formula
    max_saved:         int   = 1000  # max formulas to keep in this batch

    # ── Dedup ─────────────────────────────────────────────────────────────
    dedup_enabled:   bool  = True   # reject structurally identical formulas

    # ── Output ────────────────────────────────────────────────────────────
    output_dir:      str   = "./generated_formulas"
    batch_name:      str   = ""     # auto-generated if empty

    # ── Runtime ───────────────────────────────────────────────────────────
    # Max formulas to generate (0 = unlimited, stop via stop signal)
    max_generated:   int   = 0
    # Report callback interval (every N generated formulas)
    report_every:    int   = 50

    def __post_init__(self):
        if not self.batch_name:
            self.batch_name = datetime.now().strftime("batch_%Y%m%d_%H%M%S")
        assert self.interest_mode in ("both", "good_only", "bad_only")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ExplorationConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─────────────────────────────────────────────────────────────────────────────
# LIVE STATS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExplorationStats:
    """Live statistics — updated in real-time, serializable for SSE."""

    # Counters
    n_generated:    int   = 0
    n_invalid:      int   = 0      # failed RPN compilation / C validation
    n_prefiltered:  int   = 0      # eliminated at fast pre-filter
    n_filtered:     int   = 0      # eliminated at full filter
    n_saved:        int   = 0      # saved to disk
    n_duplicates:   int   = 0      # rejected as duplicates

    # Performance
    started_at:     float = 0.0
    elapsed_s:      float = 0.0
    formulas_per_s: float = 0.0

    # Best found
    best_accuracy:  float = 0.50
    best_interest:  float = 0.0
    best_direction: int   = 1     # +1 good, -1 bad
    best_formula_id: str  = ""

    # Running
    is_running:     bool  = False
    stop_requested: bool  = False
    batch_name:     str   = ""

    def survival_rate(self) -> float:
        n = self.n_generated - self.n_invalid - self.n_duplicates
        if n <= 0: return 0.0
        return self.n_saved / n

    def to_dict(self) -> dict:
        d = asdict(self)
        d["survival_rate"]    = round(self.survival_rate(), 4)
        d["elapsed_s"]        = round(self.elapsed_s, 1)
        d["formulas_per_s"]   = round(self.formulas_per_s, 1)
        d["best_accuracy"]    = round(self.best_accuracy, 4)
        d["best_interest"]    = round(self.best_interest, 4)
        return d


# ─────────────────────────────────────────────────────────────────────────────
# FORMULA HASH (dedup)
# ─────────────────────────────────────────────────────────────────────────────

def formula_hash(node: Node) -> str:
    """Stable MD5 hash of the serialized AST."""
    s = json.dumps(node.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.md5(s.encode()).hexdigest()


def load_existing_hashes(output_dir: str) -> Set[str]:
    """Load hashes of all previously saved formulas (for cross-batch dedup)."""
    seen = set()
    if not os.path.isdir(output_dir):
        return seen
    for root, _, files in os.walk(output_dir):
        for fname in files:
            if not fname.endswith(".json") or fname == "summary.json":
                continue
            try:
                with open(os.path.join(root, fname)) as f:
                    d = json.load(f)
                tree = d.get("tree")
                if tree:
                    s = json.dumps(tree, sort_keys=True, separators=(",", ":"))
                    seen.add(hashlib.md5(s.encode()).hexdigest())
            except Exception:
                pass
    return seen


# ─────────────────────────────────────────────────────────────────────────────
# PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def save_formula_record(batch_dir: str, formula_id: str,
                        node: Node, score: dict) -> str:
    """Save one formula record to disk. Returns file path."""
    record = {
        "id":        formula_id,
        "saved_at":  datetime.now().isoformat(),
        "tree":      node.to_dict(),
        "tree_size": node.size(),
        "tree_depth":node.depth(),
        "score":     score,
        "repr":      repr(node),
        "vars":      sorted(variable_set(node)),
    }
    path = os.path.join(batch_dir, f"{formula_id}.json")
    with open(path, "w") as f:
        json.dump(record, f, separators=(",", ":"))
    return path


def update_summary(output_dir: str, batch_name: str,
                   config: ExplorationConfig,
                   stats: ExplorationStats,
                   top_formulas: List[dict]):
    """Write/overwrite summary.json — called after each save."""
    summary = {
        "updated_at":    datetime.now().isoformat(),
        "batch_name":    batch_name,
        "config":        config.to_dict(),
        "stats":         stats.to_dict(),
        "top_formulas":  top_formulas[:20],  # top 20 by interest
    }
    path = os.path.join(output_dir, "summary.json")
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# EXPLORATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class ExplorationEngine:
    """
    Main exploration engine.

    Usage:
        engine = ExplorationEngine(
            data_loader=DataLoader("./nba_data"),
            output_dir="./generated_formulas",
        )
        engine.run(config, on_progress=my_callback)

    on_progress(stats: ExplorationStats) is called every config.report_every
    formulas — use it to stream stats to the frontend via SSE.
    """

    def __init__(self,
                 data_loader: DataLoader,
                 output_dir: str = "./generated_formulas"):
        self.data_loader = data_loader
        self.output_dir  = output_dir
        self._engine     = FormulaEngine()
        self._stop_file  = ".stop_exploration"
        self._stats      = ExplorationStats()
        self._lock       = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────

    @property
    def stats(self) -> ExplorationStats:
        with self._lock:
            return ExplorationStats(**asdict(self._stats))

    def request_stop(self):
        """Signal the engine to stop after the current formula."""
        with self._lock:
            self._stats.stop_requested = True
        # Also write stop file (for multi-process use)
        with open(self._stop_file, "w") as f:
            f.write("stop")

    def is_running(self) -> bool:
        return self._stats.is_running

    def run(self,
            config: Optional[ExplorationConfig] = None,
            on_progress: Optional[Callable[[ExplorationStats], None]] = None,
            on_save: Optional[Callable[[dict], None]] = None) -> ExplorationStats:
        """
        Run exploration loop.

        Args:
            config:      ExplorationConfig (uses defaults if None)
            on_progress: called every config.report_every formulas
                         with current ExplorationStats — use for SSE streaming
            on_save:     called every time a formula is saved
                         with the formula record dict

        Returns final ExplorationStats.
        """
        if config is None:
            config = ExplorationConfig()

        # Engine's output_dir always takes precedence over config default
        config.output_dir = self.output_dir
        if not config.batch_name:
            config.batch_name = datetime.now().strftime("batch_%Y%m%d_%H%M%S")

        # Clean up any leftover stop signal
        if os.path.exists(self._stop_file):
            os.remove(self._stop_file)

        # Mark running IMMEDIATELY — before any I/O
        # This prevents double-start race conditions
        with self._lock:
            self._stats = ExplorationStats(
                started_at = time.time(),
                is_running = True,
                batch_name = config.batch_name,
            )

        # Prepare output directories
        batch_dir = os.path.join(config.output_dir, config.batch_name)
        os.makedirs(batch_dir, exist_ok=True)

        # Load datasets (happens AFTER is_running=True)
        ds_full = self.data_loader.get_training()
        ds_fast = (subset_cdataset(ds_full, config.fast_prefilter_n)
                   if config.fast_prefilter_n > 0 else None)

        # Load existing hashes for dedup
        seen_hashes: Set[str] = set()
        if config.dedup_enabled:
            seen_hashes = load_existing_hashes(config.output_dir)

        # Top formulas list (kept sorted by interest for summary.json)
        top_formulas: List[dict] = []
        formula_counter = 0

        # ── Background progress reporter (every 2s, non-blocking) ────────
        _stop_reporter = threading.Event()
        def _reporter():
            while not _stop_reporter.is_set():
                _stop_reporter.wait(2.0)
                if _stop_reporter.is_set(): break
                self._update_perf()
                if on_progress:
                    try: on_progress(self.stats)
                    except Exception: pass
        _rep_thread = threading.Thread(target=_reporter, daemon=True)
        _rep_thread.start()

        try:
            while True:
                # ── Stop conditions ────────────────────────────────────────
                if self._check_stop(config):
                    break
                if config.max_saved > 0 and self._stats.n_saved >= config.max_saved:
                    break

                formula_counter += 1

                # ── Generate ───────────────────────────────────────────────
                node = random_formula(config.max_depth, config.max_size)
                with self._lock:
                    self._stats.n_generated += 1

                # ── Compile to C ───────────────────────────────────────────
                cf = ast_to_c_formula(node)
                if cf is None or not self._engine.validate(cf):
                    with self._lock:
                        self._stats.n_invalid += 1
                    continue

                # ── Dedup ──────────────────────────────────────────────────
                if config.dedup_enabled:
                    h = formula_hash(node)
                    if h in seen_hashes:
                        with self._lock:
                            self._stats.n_duplicates += 1
                        continue
                    seen_hashes.add(h)

                # ── Fast pre-filter ────────────────────────────────────────
                if ds_fast is not None:
                    elim = [0]
                    fs, eliminated = self._engine.filter(
                        cf, ds_fast,
                        block_size   = config.block_size,
                        min_interest = config.fast_min_interest,
                    )
                    if eliminated or not self._direction_ok(fs, config):
                        with self._lock:
                            self._stats.n_prefiltered += 1
                        continue

                # ── Full interest filter ───────────────────────────────────
                fs, eliminated = self._engine.filter(
                    cf, ds_full,
                    block_size   = config.block_size,
                    min_interest = config.min_interest,
                )

                if eliminated or not self._direction_ok(fs, config):
                    with self._lock:
                        self._stats.n_filtered += 1
                    continue

                # ── Save threshold ────────────────────────────────────────
                if fs.interest < config.save_min_interest:
                    with self._lock:
                        self._stats.n_filtered += 1
                    continue

                # ── Save ───────────────────────────────────────────────────
                fid    = f"formula_{self._stats.n_saved + 1:06d}"
                score  = {
                    "accuracy":     round(fs.accuracy, 4),
                    "interest":     round(fs.interest, 4),
                    "n_games_eval": fs.n_games_eval,
                    "direction":    fs.direction,
                }
                save_formula_record(batch_dir, fid, node, score)

                with self._lock:
                    self._stats.n_saved += 1
                    # Update best
                    if fs.interest > self._stats.best_interest:
                        self._stats.best_interest    = fs.interest
                        self._stats.best_accuracy    = fs.accuracy
                        self._stats.best_direction   = fs.direction
                        self._stats.best_formula_id  = fid

                # Update top list
                top_entry = {
                    "id":        fid,
                    "accuracy":  round(fs.accuracy, 4),
                    "interest":  round(fs.interest, 4),
                    "direction": fs.direction,
                    "size":      node.size(),
                    "repr":      repr(node),
                }
                top_formulas.append(top_entry)
                top_formulas.sort(key=lambda x: x["interest"], reverse=True)

                # Notify save callback
                if on_save:
                    try:
                        on_save(top_entry)
                    except Exception:
                        pass

                # Persist summary
                update_summary(config.output_dir, config.batch_name,
                                config, self._stats, top_formulas)

        finally:
            _stop_reporter.set()
            _rep_thread.join(timeout=3)
            # Final stats update
            self._update_perf()
            with self._lock:
                self._stats.is_running  = False
                self._stats.stop_requested = False

            update_summary(config.output_dir, config.batch_name,
                            config, self._stats, top_formulas)

            if os.path.exists(self._stop_file):
                os.remove(self._stop_file)

        return self.stats

    # ── Helpers ────────────────────────────────────────────────────────────

    def _is_constant_formula(self, cf, ds: CDataset,
                              sample: int = 50) -> bool:
        """
        Returns True if the formula produces the same prediction
        (always home OR always away) on the first `sample` games.
        Such formulas exploit home-court baseline and carry zero signal.
        """
        n_save    = ds.n_games
        ds.n_games = min(sample, n_save)
        preds     = [0] * ds.n_games

        import ctypes
        pred_arr = (ctypes.c_int * ds.n_games)()
        self._engine._lib.nba_eval_dataset(
            ctypes.byref(cf._c),
            ctypes.byref(ds),
            pred_arr,
        )
        ds.n_games = n_save

        predictions = list(pred_arr[:min(sample, n_save)])
        if not predictions:
            return True
        # If all predictions are the same value → constant
        return len(set(predictions)) == 1

    def _check_stop(self, config: ExplorationConfig) -> bool:
        with self._lock:
            if self._stats.stop_requested:
                return True
        if os.path.exists(self._stop_file):
            return True
        if config.max_generated > 0:
            with self._lock:
                if self._stats.n_generated >= config.max_generated:
                    return True
        return False

    def _direction_ok(self, fs, config: ExplorationConfig) -> bool:
        if config.interest_mode == "both":
            return True
        if config.interest_mode == "good_only":
            return fs.direction == 1
        if config.interest_mode == "bad_only":
            return fs.direction == -1
        return True

    def _update_perf(self):
        with self._lock:
            elapsed = time.time() - self._stats.started_at
            self._stats.elapsed_s = elapsed
            if elapsed > 0:
                self._stats.formulas_per_s = (
                    self._stats.n_generated / elapsed
                )


# ─────────────────────────────────────────────────────────────────────────────
# BATCH READER (for frontend)
# ─────────────────────────────────────────────────────────────────────────────

def load_summary(output_dir: str) -> Optional[dict]:
    """Load summary.json — returns None if not found."""
    path = os.path.join(output_dir, "summary.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def load_batch(output_dir: str, batch_name: str,
               offset: int = 0, limit: int = 50) -> List[dict]:
    """
    Load saved formulas from a batch (paginated).
    Returns list of formula records.
    """
    batch_dir = os.path.join(output_dir, batch_name)
    if not os.path.isdir(batch_dir):
        return []
    files = sorted(
        f for f in os.listdir(batch_dir)
        if f.endswith(".json") and f != "summary.json"
    )
    results = []
    for fname in files[offset: offset + limit]:
        try:
            with open(os.path.join(batch_dir, fname)) as f:
                results.append(json.load(f))
        except Exception:
            pass
    return results


def list_batches(output_dir: str) -> List[dict]:
    """List all batches with their formula counts."""
    if not os.path.isdir(output_dir):
        return []
    batches = []
    for name in sorted(os.listdir(output_dir)):
        path = os.path.join(output_dir, name)
        if not os.path.isdir(path):
            continue
        n = len([f for f in os.listdir(path)
                 if f.endswith(".json") and f != "summary.json"])
        batches.append({"name": name, "n_formulas": n, "path": path})
    return batches


def get_formula(output_dir: str, batch_name: str,
                formula_id: str) -> Optional[dict]:
    """Load one specific formula by ID."""
    path = os.path.join(output_dir, batch_name, f"{formula_id}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)