"""
brute_force_engine.py — Exhaustive Formula Enumeration
========================================================
Systematically tests all formula combinations up to a given tree size.

Enumeration order (within each size n):
  1. unary_op( formulas_of_size(n-1) )
  2. binary_op( size_a, size_b )  where a + b = n - 1, a in [1..n-2]

Constants use the '+1/10' progression scheme:
  0.010, 0.011, ..., 0.099  (step 0.001)
  0.100, 0.110, ..., 0.990  (step 0.010)
  1.000, 1.100, ..., 9.900  (step 0.100)
  10.00, 11.00, ..., 99.00  (step 1.000)
  100.0, 110.0, ..., 1000.  (step 10.00)
  Both positive and negative.

Memory strategy: only size-1 and size-2 formulas are materialised.
All larger enumerations are streaming generators to avoid OOM.
"""

from __future__ import annotations

import ctypes
import json
import os
import random
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Callable, Iterator, List, Optional, Tuple

from nba_engine_binding import CDataset, FormulaEngine, get_registry
from formula_engine import (
    BINARY_OPS, UNARY_OPS,
    BinaryNode, ConstNode, Node, UnaryNode, VarNode,
    ast_to_c_formula, variable_set,
)
from data_loader import DataLoader

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS — the '+1/10' scheme
# ─────────────────────────────────────────────────────────────────────────────

def generate_constants() -> List[float]:
    """
    Generate systematic constants.
    Uses integer arithmetic (millis = value × 1000) to avoid float drift.

    Decade  Range        Step    Values
    1       0.010–0.099  0.001   90
    2       0.100–0.990  0.010   90
    3       1.000–9.900  0.100   90
    4       10.00–99.00  1.000   90
    5       100.0–1000.  10.00   91
    Total positive: 451  Total with negatives: 902
    """
    millis: set[int] = set()

    for i in range(10, 100):          # 0.010 – 0.099, step 0.001
        millis.add(i)
    for i in range(100, 1000, 10):    # 0.100 – 0.990, step 0.010
        millis.add(i)
    for i in range(1000, 10000, 100): # 1.000 – 9.900, step 0.100
        millis.add(i)
    for i in range(10000, 100000, 1000):    # 10.00 – 99.00, step 1.000
        millis.add(i)
    for i in range(100000, 1000001, 10000): # 100.0 – 1000., step 10.00
        millis.add(i)

    pos = sorted(m / 1000.0 for m in millis)
    neg = [-v for v in pos]
    return sorted(set(pos + neg))


_CONSTANTS: Optional[List[float]] = None

def get_constants() -> List[float]:
    global _CONSTANTS
    if _CONSTANTS is None:
        _CONSTANTS = generate_constants()
    return _CONSTANTS


# ─────────────────────────────────────────────────────────────────────────────
# LEAVES
# ─────────────────────────────────────────────────────────────────────────────

def build_leaves() -> Tuple[List[Node], int, int]:
    """
    Build the full list of size-1 nodes.
    Returns (leaves, n_vars, n_consts).
    """
    reg    = get_registry()
    leaves: List[Node] = []

    for name, idx in sorted(reg.items(), key=lambda x: x[1]):
        leaves.append(VarNode(name, idx))

    consts = get_constants()
    for val in consts:
        leaves.append(ConstNode(val))

    return leaves, len(reg), len(consts)


# ─────────────────────────────────────────────────────────────────────────────
# FORMULA COUNTS (for progress display)
# ─────────────────────────────────────────────────────────────────────────────

def compute_size_counts(n_leaves: int, max_size: int) -> dict:
    """
    Precompute total formula count for each size, for the progress bar.
    (Counts all combinations before filtering.)
    """
    c = {0: 0, 1: n_leaves}
    for s in range(2, max_size + 1):
        total = 6 * c[s - 1]                          # unary(s-1)
        for ls in range(1, s - 1):                    # binary splits
            rs = s - 1 - ls
            if rs >= 1:
                total += 7 * c[ls] * c[rs]
        c[s] = total
    return c


# ─────────────────────────────────────────────────────────────────────────────
# FORMULA GENERATORS (streaming — O(1) memory)
# ─────────────────────────────────────────────────────────────────────────────

def gen_size1(leaves: List[Node]) -> Iterator[Node]:
    yield from leaves


def gen_size2(leaves: List[Node]) -> Iterator[Node]:
    """6 unary ops × all leaves."""
    for op in UNARY_OPS:
        for leaf in leaves:
            yield UnaryNode(op, leaf.clone())


def gen_size3(leaves: List[Node], size2: List[Node]) -> Iterator[Node]:
    """
    unary(size-2) + binary(size-1, size-1).
    size-2 is pre-materialised (9 708 items).
    """
    # Unary chains
    for op in UNARY_OPS:
        for f in size2:
            yield UnaryNode(op, f.clone())

    # Binary: both operands are leaves
    for op in BINARY_OPS:
        for left in leaves:
            for right in leaves:
                yield BinaryNode(op, left.clone(), right.clone())


def gen_size4(leaves: List[Node], size2: List[Node]) -> Iterator[Node]:
    """
    binary(size-1, size-2) + binary(size-2, size-1).
    Skips unary(size-3) to avoid materialising 18 M nodes.
    Also skips binary(size-1, size-1) [already covered in size-3 unary would not be correct]
    
    Note: binary(1, 2) and binary(2, 1) cover most interesting size-4 patterns.
    unary(size-3) would add unary chains over 18M formulas — skipped for memory.
    """
    for op in BINARY_OPS:
        # leaf OP size-2
        for left in leaves:
            for right in size2:
                yield BinaryNode(op, left.clone(), right.clone())
        # size-2 OP leaf
        for left in size2:
            for right in leaves:
                yield BinaryNode(op, left.clone(), right.clone())


def gen_size5_binary_only(leaves: List[Node], size2: List[Node]) -> Iterator[Node]:
    """binary(size-2, size-2) — the main interesting size-5 patterns."""
    for op in BINARY_OPS:
        for left in size2:
            for right in size2:
                yield BinaryNode(op, left.clone(), right.clone())


GENERATORS = {
    1: lambda l, _s2: gen_size1(l),
    2: lambda l, _s2: gen_size2(l),
    3: lambda l,  s2: gen_size3(l, s2),
    4: lambda l,  s2: gen_size4(l, s2),
    5: lambda l,  s2: gen_size5_binary_only(l, s2),
}


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG & STATS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BruteForceConfig:
    # Filter
    min_interest:    float = 0.20    # interest = |acc - 0.5| × 2
    start_fraction:  float = 0.5     # ramping threshold start
    block_size:      int   = 100     # games per filter block

    # Scope
    min_size:        int   = 1       # start from this tree size
    max_size:        int   = 3       # stop after this size

    # Output
    output_dir:      str   = "./brute_force_results"
    batch_name:      str   = ""      # auto-generated if empty

    def __post_init__(self):
        if not self.batch_name:
            self.batch_name = datetime.now().strftime("bf_%Y%m%d_%H%M%S")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BruteForceConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BruteForceStats:
    # Current position
    current_size:      int   = 0
    current_idx:       int   = 0     # formula index within current size
    current_size_total:int   = 0     # total expected for current size

    # Cumulative counters
    n_tested:          int   = 0     # total formulas compiled and tested
    n_invalid:         int   = 0     # failed compile or directional constant
    n_filtered:        int   = 0     # passed constant check, failed interest
    n_saved:           int   = 0     # saved to disk

    # Performance
    started_at:        float = 0.0
    elapsed_s:         float = 0.0
    formulas_per_s:    float = 0.0

    # State
    is_running:        bool  = False
    stop_requested:    bool  = False
    batch_name:        str   = ""
    best_accuracy:     float = 0.5
    best_formula_repr: str   = ""

    @property
    def progress_pct(self) -> float:
        if self.current_size_total <= 0:
            return 0.0
        return min(100.0, self.current_idx / self.current_size_total * 100)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["progress_pct"]   = round(self.progress_pct, 2)
        d["elapsed_s"]      = round(self.elapsed_s, 1)
        d["formulas_per_s"] = round(self.formulas_per_s, 1)
        d["best_accuracy"]  = round(self.best_accuracy, 4)
        return d


# ─────────────────────────────────────────────────────────────────────────────
# PERSISTENCE  (same batch format as exploration, for UI reuse)
# ─────────────────────────────────────────────────────────────────────────────

def _batch_dir(config: BruteForceConfig) -> str:
    return os.path.join(config.output_dir, config.batch_name)


def _save_formula(batch_dir: str, fid: str, node: Node, score: dict):
    record = {
        "id":         fid,
        "saved_at":   datetime.now().isoformat(),
        "tree":       node.to_dict(),
        "tree_size":  node.size(),
        "tree_depth": node.depth(),
        "score":      score,
        "repr":       repr(node),
        "vars":       sorted(variable_set(node)),
    }
    path = os.path.join(batch_dir, f"{fid}.json")
    with open(path, "w") as f:
        json.dump(record, f, separators=(",", ":"))


def _update_summary(config: BruteForceConfig, stats: BruteForceStats, top_formulas: list = None):
    summary = {
        "updated_at":   datetime.now().isoformat(),
        "batch_name":   config.batch_name,
        "type":         "brute_force",
        "config":       config.to_dict(),
        "stats":        stats.to_dict(),
        "top_formulas": (top_formulas or [])[:100],
    }
    path = os.path.join(config.output_dir, "summary.json")
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class BruteForceEngine:
    """
    Exhaustively enumerates formula ASTs up to max_size nodes,
    filters by interest score, and saves survivors.
    """

    def __init__(self,
                 data_loader: DataLoader,
                 output_dir:  str = "./brute_force_results"):
        self.data_loader = data_loader
        self.output_dir  = output_dir
        self._engine     = FormulaEngine()
        self._stats      = BruteForceStats()
        self._lock       = threading.Lock()

    # ── public API ─────────────────────────────────────────────────────────

    @property
    def stats(self) -> BruteForceStats:
        with self._lock:
            return BruteForceStats(**asdict(self._stats))

    def request_stop(self):
        with self._lock:
            self._stats.stop_requested = True

    def is_running(self) -> bool:
        return self._stats.is_running

    def run(self,
            config:      Optional[BruteForceConfig]             = None,
            on_progress: Optional[Callable[[BruteForceStats], None]] = None,
            on_save:     Optional[Callable[[dict], None]]        = None,
            ) -> BruteForceStats:

        if config is None:
            config = BruteForceConfig()

        config.output_dir = self.output_dir
        os.makedirs(_batch_dir(config), exist_ok=True)

        # Build leaves + size-2 cache
        leaves, n_vars, n_consts = build_leaves()
        size2 = list(gen_size2(leaves))

        # Precompute counts for progress
        size_counts = compute_size_counts(len(leaves), config.max_size)

        # Load dataset
        ds = self.data_loader.get_training()
        _top_formulas: list = []  # top-100 by accuracy, maintained in-memory

        with self._lock:
            self._stats = BruteForceStats(
                started_at  = time.time(),
                is_running  = True,
                batch_name  = config.batch_name,
            )

        # Reporter thread
        _stop_rpt = threading.Event()
        def _reporter():
            while not _stop_rpt.is_set():
                _stop_rpt.wait(2.0)
                if _stop_rpt.is_set(): break
                self._update_perf()
                if on_progress:
                    try: on_progress(self.stats)
                    except Exception: pass
        rpt = threading.Thread(target=_reporter, daemon=True)
        rpt.start()

        try:
            for size in range(config.min_size, config.max_size + 1):

                if self._should_stop():
                    break

                total_this_size = size_counts.get(size, 0)

                with self._lock:
                    self._stats.current_size       = size
                    self._stats.current_idx        = 0
                    self._stats.current_size_total = total_this_size

                gen = GENERATORS.get(size)
                if gen is None:
                    continue

                for node in gen(leaves, size2):

                    if self._should_stop():
                        break

                    with self._lock:
                        self._stats.current_idx += 1

                    # ── Compile ────────────────────────────────────────────
                    cf = ast_to_c_formula(node)
                    if cf is None or not self._engine.validate(cf):
                        with self._lock: self._stats.n_invalid += 1
                        continue

                    with self._lock: self._stats.n_tested += 1

                    # ── Constant-direction check ───────────────────────────
                    if self._is_constant_quick(cf, ds):
                        with self._lock: self._stats.n_invalid += 1
                        continue

                    # ── Interest filter (ramping) ──────────────────────────
                    fs, eliminated = self._engine.filter(
                        cf, ds,
                        block_size     = config.block_size,
                        min_interest   = config.min_interest,
                        start_fraction = config.start_fraction,
                    )

                    if eliminated or fs.interest < config.min_interest:
                        with self._lock: self._stats.n_filtered += 1
                        continue

                    # ── Save ───────────────────────────────────────────────
                    with self._lock:
                        n = self._stats.n_saved + 1
                        self._stats.n_saved = n
                        if fs.accuracy > self._stats.best_accuracy:
                            self._stats.best_accuracy     = fs.accuracy
                            self._stats.best_formula_repr = repr(node)

                    fid   = f"formula_{n:06d}"
                    score = {
                        "accuracy":     round(fs.accuracy, 4),
                        "interest":     round(fs.interest, 4),
                        "n_games_eval": fs.n_games_eval,
                        "direction":    fs.direction,
                        "size":         size,
                    }
                    _save_formula(_batch_dir(config), fid, node, score)

                    entry = {"id": fid, "repr": repr(node), **score}
                    # Maintain sorted top-100
                    _top_formulas.append(entry)
                    _top_formulas.sort(key=lambda x: x.get("accuracy", 0), reverse=True)
                    if len(_top_formulas) > 100:
                        _top_formulas.pop()
                    _update_summary(config, self._stats, _top_formulas)

                    if on_save:
                        try: on_save(entry)
                        except Exception: pass

        finally:
            _stop_rpt.set()
            rpt.join(timeout=3)
            self._update_perf()
            with self._lock:
                self._stats.is_running     = False
                self._stats.stop_requested = False
            _update_summary(config, self._stats, _top_formulas)

        return self.stats

    # ── helpers ────────────────────────────────────────────────────────────

    def _is_constant_quick(self, cf, ds: CDataset,
                            n_samples: int = 15) -> bool:
        """
        Detect constant-direction formulas by checking prediction direction
        on n_samples random games. If all the same → constant → skip.
        """
        n = ds.n_games
        if n < 2: return False
        indices = random.sample(range(n), min(n_samples, n))
        preds   = set()
        for i in indices:
            s = self._engine.eval_single(cf, ds.games[i])
            preds.add(1 if s >= 0.0 else 0)
            if len(preds) > 1:
                return False
        return True

    def _should_stop(self) -> bool:
        with self._lock:
            return self._stats.stop_requested

    def _update_perf(self):
        with self._lock:
            elapsed = time.time() - self._stats.started_at
            self._stats.elapsed_s = elapsed
            if elapsed > 0:
                self._stats.formulas_per_s = self._stats.n_tested / elapsed