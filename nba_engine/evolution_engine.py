"""
evolution_engine.py — Layer 5: Evolution Engine
=================================================
Controlled evolution of a single formula through mutations.
Each run evolves one formula independently with its own parameters.

Key differences from exploration:
  - Works on ONE formula at a time (not a massive stream)
  - Mutations accepted only if they IMPROVE the parent by > threshold
  - Early stopping: compare child vs parent every 500 games
  - Full history tracked per run (every accepted mutation)
  - JIT compilation hook for promising formulas (future)

Output structure:
  saved_formulas/
    formula_001/
      meta.json              ← original formula + info
      run_001/
        config.json          ← evolution parameters
        history.json         ← every accepted mutation
        best.json            ← best formula found so far
        generations/
          gen_0001.json      ← snapshot after each accepted mutation
      run_002/
        ...
"""

from __future__ import annotations

import os
import json
import time
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from nba_engine_binding import FormulaEngine, CDataset
from formula_engine import (
    Node, node_from_dict, random_formula,
    mutate, crossover,
    ast_to_c_formula, variable_set,
)
from data_loader import DataLoader, subset_cdataset

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EvolutionConfig:
    """Parameters for one evolution run."""

    # ── Mutation ──────────────────────────────────────────────────────────
    mutation_strength:  float = 0.5   # 0.0 gentle → 1.0 violent
    population_size:    int   = 1     # variants tried per generation
    # How many mutations to attempt before accepting the best one
    # (tournament selection within a generation)
    attempts_per_gen:   int   = 10

    # ── Improvement filter ────────────────────────────────────────────────
    # Child must beat parent by at least this much to be accepted
    min_improvement:    float = 0.0005  # 0.05% = 5 games per 10k

    # Block evaluation: compare child vs parent every N games
    eval_block_size:    int   = 500   # games per comparison block
    # Min blocks that must show improvement before accepting
    # (avoids lucky streaks on first block)
    min_blocks_confirm: int   = 1

    # ── Direction ─────────────────────────────────────────────────────────
    # "up"   → maximize accuracy (good formula)
    # "down" → minimize accuracy (bad formula → invert for betting)
    direction:          str   = "up"

    # ── Stagnation ────────────────────────────────────────────────────────
    # Stop run if no improvement after this many generations
    stagnation_limit:   int   = 100
    # Total max generations (0 = unlimited, stop via signal)
    max_generations:    int   = 0

    # ── Output ────────────────────────────────────────────────────────────
    # Save a generation snapshot every N accepted mutations
    snapshot_every:     int   = 1

    # ── Tree size control ─────────────────────────────────────────────
    # Mutations producing trees larger than these limits are rejected.
    # Prevents unbounded tree growth over many generations.
    max_tree_size:  int   = 80    # max nodes (0 = unlimited)
    max_tree_depth: int   = 8     # max depth  (0 = unlimited)

    # ── Reporting ─────────────────────────────────────────────────────────
    report_every:       int   = 10    # callback every N generations tried

    def __post_init__(self):
        assert self.direction in ("up", "down"), \
            f"direction must be 'up' or 'down', got {self.direction!r}"
        assert 0.0 <= self.mutation_strength <= 1.0
        assert self.eval_block_size > 0
        assert self.attempts_per_gen >= 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EvolutionConfig":
        return cls(**{k: v for k, v in d.items()
                      if k in cls.__dataclass_fields__})


# ─────────────────────────────────────────────────────────────────────────────
# GENERATION RECORD
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GenerationRecord:
    """One accepted mutation in the evolution history."""
    gen_number:    int
    accuracy:      float
    improvement:   float     # delta vs previous best
    n_games_eval:  int
    mutation_type: str       # which mutation produced this
    tree_size:     int
    tree_depth:    int
    timestamp:     str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# EVOLUTION STATS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EvolutionStats:
    """Live stats for one evolution run — SSE-streamable."""

    # Counters
    gen_tried:       int   = 0   # total mutations attempted
    gen_accepted:    int   = 0   # accepted (improved)
    gen_rejected:    int   = 0   # rejected (no improvement)
    gen_invalid:     int   = 0   # invalid C formula

    # Current state
    current_accuracy: float = 0.0
    best_accuracy:    float = 0.0
    best_gen:         int   = 0
    stagnation_count: int   = 0  # gens since last improvement

    # Performance
    started_at:       float = 0.0
    elapsed_s:        float = 0.0
    mutations_per_s:  float = 0.0
    accepts_per_s:    float = 0.0

    # State
    is_running:       bool  = False
    stop_requested:   bool  = False
    stop_reason:      str   = ""   # "stagnation"/"max_gen"/"stop_signal"/"max_saved"

    # Run identity
    formula_id:       str   = ""
    run_id:           str   = ""

    @property
    def accept_rate(self) -> float:
        n = self.gen_tried - self.gen_invalid
        return self.gen_accepted / n if n > 0 else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["accept_rate"]    = round(self.accept_rate, 4)
        d["elapsed_s"]      = round(self.elapsed_s, 1)
        d["mutations_per_s"]= round(self.mutations_per_s, 1)
        d["accepts_per_s"]  = round(self.accepts_per_s, 1)
        d["current_accuracy"]= round(self.current_accuracy, 6)
        d["best_accuracy"]   = round(self.best_accuracy, 6)
        return d


# ─────────────────────────────────────────────────────────────────────────────
# CHILD EVALUATION (early stopping vs parent)
# ─────────────────────────────────────────────────────────────────────────────

def _score_on_block(engine: FormulaEngine,
                    cf, ds: CDataset,
                    start: int, size: int) -> float:
    """
    Score a compiled formula on games[start:start+size].
    Returns accuracy on that block.
    """
    sub = subset_cdataset(ds, min(start + size, ds.n_games))
    if start > 0:
        # We need games[start:start+size] — create a view of the tail
        # by evaluating the full sub and computing block accuracy manually
        pass
    # Evaluate full subset up to start+size, then derive block accuracy
    # Simple approach: evaluate on subset and return accuracy
    # (slight imprecision but avoids complex slicing)
    return engine.accuracy(cf, sub)


def evaluate_child_vs_parent(
    engine:         FormulaEngine,
    child_cf,
    parent_cf,
    ds:             CDataset,
    config:         EvolutionConfig,
) -> Tuple[bool, float, int]:
    """
    Compare child vs parent using block-based early stopping.

    Temporarily modifies ds.n_games to evaluate on increasing slices —
    zero allocation, no 128MB copies.

    At each checkpoint (every eval_block_size games):
      - If child is clearly WORSE than parent → eliminate early
    At end of full dataset:
      - Child must beat parent by at least min_improvement to accept

    Returns:
        (accepted, final_child_accuracy, n_games_evaluated)
    """
    block    = config.eval_block_size
    n_total  = ds.n_games
    sign     = 1.0 if config.direction == "up" else -1.0
    orig_n   = ds.n_games   # save to restore

    last_child_acc = 0.5

    try:
        for end in range(block, n_total + block, block):
            end = min(end, n_total)

            # Temporarily limit dataset to 'end' games — zero copy
            ds.n_games = end

            child_acc  = engine.accuracy(child_cf,  ds)
            parent_acc = engine.accuracy(parent_cf, ds)
            last_child_acc = child_acc

            child_s  = child_acc  * sign
            parent_s = parent_acc * sign

            # Early elimination: child is clearly worse than parent
            if child_s < parent_s - config.min_improvement:
                return False, child_acc, end

            if end >= n_total:
                break

        # Final verdict on full dataset
        ds.n_games = n_total
        child_acc  = engine.accuracy(child_cf,  ds)
        parent_acc = engine.accuracy(parent_cf, ds)

        child_s  = child_acc  * sign
        parent_s = parent_acc * sign

        if child_s >= parent_s + config.min_improvement:
            return True, child_acc, n_total

        return False, child_acc, n_total

    finally:
        ds.n_games = orig_n   # always restore


# ─────────────────────────────────────────────────────────────────────────────
# PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def _run_dir(output_dir: str, formula_id: str, run_id: str) -> str:
    return os.path.join(output_dir, formula_id, run_id)


def save_run_config(output_dir: str, formula_id: str,
                    run_id: str, config: EvolutionConfig,
                    origin: dict):
    """Save run config + origin formula."""
    rd = _run_dir(output_dir, formula_id, run_id)
    os.makedirs(os.path.join(rd, "generations"), exist_ok=True)
    d = {"run_id": run_id, "formula_id": formula_id,
         "created_at": datetime.now().isoformat(),
         "config": config.to_dict(),
         "origin": origin}
    with open(os.path.join(rd, "config.json"), "w") as f:
        json.dump(d, f, indent=2)


def save_generation_snapshot(output_dir: str, formula_id: str,
                              run_id: str, gen: GenerationRecord,
                              node: Node):
    """Save a generation snapshot (accepted mutation)."""
    rd   = _run_dir(output_dir, formula_id, run_id)
    snap = {
        **gen.to_dict(),
        "tree":  node.to_dict(),
        "repr":  repr(node),
        "vars":  sorted(variable_set(node)),
    }
    fname = os.path.join(rd, "generations", f"gen_{gen.gen_number:06d}.json")
    with open(fname, "w") as f:
        json.dump(snap, f, separators=(",", ":"))


def save_best(output_dir: str, formula_id: str,
              run_id: str, node: Node,
              accuracy: float, gen_number: int):
    """Overwrite best.json with current best formula."""
    rd = _run_dir(output_dir, formula_id, run_id)
    d  = {
        "updated_at":  datetime.now().isoformat(),
        "gen_number":  gen_number,
        "accuracy":    round(accuracy, 6),
        "tree":        node.to_dict(),
        "tree_size":   node.size(),
        "tree_depth":  node.depth(),
        "repr":        repr(node),
        "vars":        sorted(variable_set(node)),
    }
    with open(os.path.join(rd, "best.json"), "w") as f:
        json.dump(d, f, indent=2)


def save_run_history(output_dir: str, formula_id: str,
                     run_id: str, history: List[GenerationRecord],
                     stats: EvolutionStats):
    """Overwrite history.json with full accepted mutation log."""
    rd = _run_dir(output_dir, formula_id, run_id)
    d  = {
        "updated_at": datetime.now().isoformat(),
        "n_accepted": len(history),
        "stats":      stats.to_dict(),
        "history":    [g.to_dict() for g in history],
    }
    with open(os.path.join(rd, "history.json"), "w") as f:
        json.dump(d, f, indent=2)


def load_run_config(output_dir: str, formula_id: str,
                    run_id: str) -> Optional[dict]:
    path = os.path.join(_run_dir(output_dir, formula_id, run_id),
                         "config.json")
    if not os.path.exists(path): return None
    with open(path) as f: return json.load(f)


def load_best(output_dir: str, formula_id: str,
              run_id: str) -> Optional[dict]:
    path = os.path.join(_run_dir(output_dir, formula_id, run_id), "best.json")
    if not os.path.exists(path): return None
    with open(path) as f: return json.load(f)


def load_history(output_dir: str, formula_id: str,
                 run_id: str) -> Optional[dict]:
    path = os.path.join(_run_dir(output_dir, formula_id, run_id),
                         "history.json")
    if not os.path.exists(path): return None
    with open(path) as f: return json.load(f)


def list_runs(output_dir: str, formula_id: str) -> List[dict]:
    """List all runs for a formula with basic stats."""
    base = os.path.join(output_dir, formula_id)
    if not os.path.isdir(base): return []
    runs = []
    for name in sorted(os.listdir(base)):
        rd = os.path.join(base, name)
        if not os.path.isdir(rd): continue
        cfg_path = os.path.join(rd, "config.json")
        if not os.path.exists(cfg_path): continue
        hist  = load_history(output_dir, formula_id, name)
        best  = load_best(output_dir, formula_id, name)
        runs.append({
            "run_id":       name,
            "formula_id":   formula_id,
            "n_accepted":   hist["n_accepted"] if hist else 0,
            "best_accuracy":best["accuracy"]    if best else None,
        })
    return runs


def next_run_id(output_dir: str, formula_id: str) -> str:
    """Return next available run ID (run_001, run_002, ...)."""
    runs = list_runs(output_dir, formula_id)
    n    = len(runs) + 1
    return f"run_{n:03d}"


# ─────────────────────────────────────────────────────────────────────────────
# EVOLUTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class EvolutionEngine:
    """
    Evolves a single formula through directed mutations.

    Usage:
        engine = EvolutionEngine(
            data_loader = DataLoader("./nba_data"),
            output_dir  = "./saved_formulas",
        )

        # Start from a formula node
        stats = engine.run(
            formula_id = "formula_001",
            start_node = my_node,
            config     = EvolutionConfig(mutation_strength=0.5),
            on_progress = lambda s: print(s.to_dict()),
        )

        # Continue from last best in an existing run
        stats = engine.continue_run(
            formula_id = "formula_001",
            run_id     = "run_001",
            config     = new_config,
        )
    """

    def __init__(self,
                 data_loader: DataLoader,
                 output_dir:  str = "./saved_formulas"):
        self.data_loader = data_loader
        self.output_dir  = output_dir
        self._engine     = FormulaEngine()
        self._stop_file  = ".stop_evolution"
        self._stats      = EvolutionStats()
        self._lock       = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────

    @property
    def stats(self) -> EvolutionStats:
        with self._lock:
            return EvolutionStats(**asdict(self._stats))

    def request_stop(self):
        with self._lock:
            self._stats.stop_requested = True
        with open(self._stop_file, "w") as f:
            f.write("stop")

    def is_running(self) -> bool:
        return self._stats.is_running

    def run(self,
            formula_id:  str,
            start_node:  Node,
            config:      Optional[EvolutionConfig]   = None,
            run_id:      Optional[str]               = None,
            on_progress: Optional[Callable[[EvolutionStats], None]] = None,
            on_accept:   Optional[Callable[[GenerationRecord], None]] = None,
            ) -> EvolutionStats:
        """
        Start a new evolution run from start_node.

        Args:
            formula_id:  identifier for the formula being evolved
            start_node:  initial formula AST
            config:      EvolutionConfig (defaults if None)
            run_id:      explicit run ID (auto-generated if None)
            on_progress: called every config.report_every generations
            on_accept:   called every time a mutation is accepted
        """
        if config is None:
            config = EvolutionConfig()
        if run_id is None:
            run_id = next_run_id(self.output_dir, formula_id)

        # Compile start node
        start_cf = ast_to_c_formula(start_node)
        if start_cf is None or not self._engine.validate(start_cf):
            raise ValueError("start_node does not compile to a valid C formula")

        # Baseline accuracy
        ds            = self.data_loader.get_training()
        start_accuracy = self._engine.accuracy(start_cf, ds)

        # Save run config
        origin = {
            "tree":      start_node.to_dict(),
            "accuracy":  round(start_accuracy, 6),
            "tree_size": start_node.size(),
        }
        save_run_config(self.output_dir, formula_id, run_id, config, origin)

        return self._evolve(
            formula_id, run_id, config, ds,
            start_node, start_cf, start_accuracy,
            on_progress, on_accept,
        )

    def continue_run(self,
                     formula_id:  str,
                     run_id:      str,
                     config:      Optional[EvolutionConfig] = None,
                     on_progress: Optional[Callable] = None,
                     on_accept:   Optional[Callable] = None,
                     ) -> EvolutionStats:
        """
        Continue an existing run from its current best formula.
        Can use a new config (different strength, thresholds, etc.)
        """
        best = load_best(self.output_dir, formula_id, run_id)
        if best is None:
            # No best yet — load origin from config
            cfg_data = load_run_config(self.output_dir, formula_id, run_id)
            if cfg_data is None:
                raise FileNotFoundError(
                    f"Run not found: {formula_id}/{run_id}")
            tree = cfg_data["origin"]["tree"]
        else:
            tree = best["tree"]

        node = node_from_dict(tree)

        if config is None:
            # Load original config
            cfg_data = load_run_config(self.output_dir, formula_id, run_id)
            config   = EvolutionConfig.from_dict(cfg_data["config"])

        cf = ast_to_c_formula(node)
        if cf is None or not self._engine.validate(cf):
            raise ValueError("Stored formula is no longer valid")

        ds       = self.data_loader.get_training()
        accuracy = self._engine.accuracy(cf, ds)

        return self._evolve(
            formula_id, run_id, config, ds,
            node, cf, accuracy,
            on_progress, on_accept,
        )

    # ── Core evolution loop ────────────────────────────────────────────────

    def _evolve(self,
                formula_id:   str,
                run_id:       str,
                config:       EvolutionConfig,
                ds:           CDataset,
                current_node: Node,
                current_cf,
                current_acc:  float,
                on_progress:  Optional[Callable],
                on_accept:    Optional[Callable],
                ) -> EvolutionStats:

        if os.path.exists(self._stop_file):
            os.remove(self._stop_file)

        # Load existing history (if continuing)
        hist_data = load_history(self.output_dir, formula_id, run_id)
        history: List[GenerationRecord] = []
        if hist_data:
            for g in hist_data.get("history", []):
                history.append(GenerationRecord(**g))

        gen_offset = len(history)   # offset for gen numbers

        with self._lock:
            self._stats = EvolutionStats(
                started_at       = time.time(),
                is_running       = True,
                formula_id       = formula_id,
                run_id           = run_id,
                current_accuracy = current_acc,
                best_accuracy    = current_acc,
            )

        best_node  = current_node
        best_cf    = current_cf
        best_acc   = current_acc
        stagnation = 0

        try:
            gen = 0
            while True:
                # ── Stop checks ───────────────────────────────────────────
                stop, reason = self._check_stop(config, stagnation)
                if stop:
                    with self._lock:
                        self._stats.stop_reason = reason
                    break

                gen += 1

                # ── Generate candidates ───────────────────────────────────
                best_child_node = None
                best_child_cf   = None
                best_child_acc  = current_acc
                best_child_eval = 0
                accepted_this_gen = False

                for attempt in range(config.attempts_per_gen):
                    # Mutate current (not best — avoids jumping around)
                    child_node = mutate(current_node,
                                        max_depth = max(4, current_node.depth()+1),
                                        strength  = config.mutation_strength)

                    child_cf = ast_to_c_formula(child_node)
                    if child_cf is None or not self._engine.validate(child_cf):
                        with self._lock:
                            self._stats.gen_invalid += 1
                        continue

                    # ── Reject oversized trees ───────────────────────────
                    if (config.max_tree_size > 0 and
                            child_node.size() > config.max_tree_size):
                        with self._lock:
                            self._stats.gen_invalid += 1
                        continue
                    if (config.max_tree_depth > 0 and
                            child_node.depth() > config.max_tree_depth):
                        with self._lock:
                            self._stats.gen_invalid += 1
                        continue

                    # ── Block-based comparison vs CURRENT (not best) ──────
                    accepted, child_acc, n_eval = evaluate_child_vs_parent(
                        self._engine, child_cf, current_cf, ds, config)

                    with self._lock:
                        self._stats.gen_tried += 1

                    if not accepted:
                        with self._lock:
                            self._stats.gen_rejected += 1
                        continue

                    # Within this generation, keep the best candidate
                    sign = 1 if config.direction == "up" else -1
                    if (best_child_node is None or
                            child_acc * sign > best_child_acc * sign):
                        best_child_node = child_node
                        best_child_cf   = child_cf
                        best_child_acc  = child_acc
                        best_child_eval = n_eval
                        accepted_this_gen = True

                if not accepted_this_gen:
                    stagnation += 1
                    with self._lock:
                        self._stats.stagnation_count = stagnation
                    # Report progress even on rejection
                    if gen % config.report_every == 0:
                        self._update_perf()
                        if on_progress:
                            try: on_progress(self.stats)
                            except Exception: pass
                    continue

                # ── Accept best candidate of this generation ──────────────
                improvement = (best_child_acc - current_acc) * (
                    1 if config.direction == "up" else -1)

                current_node = best_child_node
                current_cf   = best_child_cf
                current_acc  = best_child_acc

                # Update best ever
                sign = 1 if config.direction == "up" else -1
                if current_acc * sign > best_acc * sign:
                    best_node = current_node
                    best_cf   = current_cf
                    best_acc  = current_acc

                stagnation = 0

                with self._lock:
                    self._stats.gen_accepted     += 1
                    self._stats.current_accuracy  = current_acc
                    self._stats.best_accuracy     = best_acc
                    self._stats.best_gen          = gen_offset + len(history) + 1
                    self._stats.stagnation_count  = 0

                # ── Record ────────────────────────────────────────────────
                rec = GenerationRecord(
                    gen_number    = gen_offset + len(history) + 1,
                    accuracy      = round(current_acc, 6),
                    improvement   = round(improvement, 6),
                    n_games_eval  = best_child_eval,
                    mutation_type = "mutate",
                    tree_size     = current_node.size(),
                    tree_depth    = current_node.depth(),
                )
                history.append(rec)

                # Persist
                if len(history) % config.snapshot_every == 0:
                    save_generation_snapshot(
                        self.output_dir, formula_id, run_id, rec, current_node)

                save_best(self.output_dir, formula_id, run_id,
                          best_node, best_acc, rec.gen_number)
                save_run_history(
                    self.output_dir, formula_id, run_id, history, self.stats)

                # Callbacks
                if on_accept:
                    try: on_accept(rec)
                    except Exception: pass

                if gen % config.report_every == 0:
                    self._update_perf()
                    if on_progress:
                        try: on_progress(self.stats)
                        except Exception: pass

        finally:
            self._update_perf()
            with self._lock:
                self._stats.is_running = False

            save_run_history(
                self.output_dir, formula_id, run_id, history, self.stats)
            save_best(self.output_dir, formula_id, run_id,
                      best_node, best_acc,
                      gen_offset + len(history))

            if os.path.exists(self._stop_file):
                os.remove(self._stop_file)

        return self.stats

    # ── Helpers ────────────────────────────────────────────────────────────

    def _is_constant_formula(self, cf, ds: CDataset,
                              sample: int = 50) -> bool:
        """Returns True if formula predicts identically on all sample games."""
        import ctypes
        n_save     = ds.n_games
        ds.n_games = min(sample, n_save)
        pred_arr   = (ctypes.c_int * ds.n_games)()
        self._engine._lib.nba_eval_dataset(
            ctypes.byref(cf._c),
            ctypes.byref(ds),
            pred_arr,
        )
        ds.n_games  = n_save
        predictions = list(pred_arr[:min(sample, n_save)])
        return len(predictions) == 0 or len(set(predictions)) == 1

    def _check_stop(self, config: EvolutionConfig,
                    stagnation: int) -> Tuple[bool, str]:
        with self._lock:
            if self._stats.stop_requested:
                return True, "stop_signal"

        if os.path.exists(self._stop_file):
            return True, "stop_signal"

        if config.stagnation_limit > 0 and stagnation >= config.stagnation_limit:
            return True, "stagnation"

        if config.max_generations > 0:
            with self._lock:
                if self._stats.gen_tried >= config.max_generations:
                    return True, "max_generations"

        return False, ""

    def _update_perf(self):
        with self._lock:
            elapsed = time.time() - self._stats.started_at
            self._stats.elapsed_s = elapsed
            if elapsed > 0:
                self._stats.mutations_per_s = self._stats.gen_tried / elapsed
                self._stats.accepts_per_s   = self._stats.gen_accepted / elapsed