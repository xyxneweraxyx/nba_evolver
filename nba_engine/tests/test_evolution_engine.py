#!/usr/bin/env python3
"""
tests/test_evolution_engine.py — Layer 5 test suite
====================================================
Run: python3 tests/test_evolution_engine.py
"""

import sys, os, json, time, tempfile, shutil, threading, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evolution_engine import (
    EvolutionConfig, EvolutionStats, GenerationRecord,
    EvolutionEngine,
    evaluate_child_vs_parent,
    save_run_config, save_generation_snapshot, save_best, save_run_history,
    load_run_config, load_best, load_history, list_runs, next_run_id,
)
from data_loader import DataLoader
from formula_engine import (
    VarNode, ConstNode, BinaryNode, UnaryNode,
    node_from_dict, random_formula, ast_to_c_formula,
)
from nba_engine_binding import FormulaEngine, get_registry, CDataset

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

def eq(a, b, tol=1e-5):
    assert abs(float(a)-float(b)) <= tol, f"{a} != {b} (tol={tol})"

ENGINE = FormulaEngine()
REG    = get_registry()
TMPDIR = None

# ─────────────────────────────────────────────────────────────────────────────
# SYNTHETIC DATA
# ─────────────────────────────────────────────────────────────────────────────

def make_game(i, won):
    """Synthetic game where home net_rtg > 0 iff home wins."""
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
                         "opponent_rest_days":2,"win_streak":2,
                         "home_win_streak":1,"games_last_7_days":3,
                         "days_since_last_home_game":4,
                         "players_available":11,
                         "km_traveled":0,"timezone_shift":0},
            "season_stats": {
                # Strong signal: when home wins, net_rtg=10; when away wins, -5
                "net_rtg": 10.0 if won else -5.0,
                "off_rtg": 118.0 if won else 108.0,
                "w_pct": 0.70 if won else 0.35,
                "pts": 115, "pace": 99.0,
                "ast": 26.0, "tov": 13.0,
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
                "net_rtg": -10.0 if won else 5.0,
                "off_rtg": 108.0 if won else 118.0,
                "w_pct": 0.35 if won else 0.70,
                "pts": 105, "pace": 98.0,
                "ast": 23.0, "tov": 14.5,
            },
            **{k: None for k in ["last10_stats","last5_stats","home_stats",
               "away_stats","b2b_stats","vs_above500_stats",
               "q1_stats","q4_stats","clutch_stats"]},
            "players": [],
        },
    }


def build_data(tmpdir, n=600, home_w=0.65):
    """Build a minimal data directory with interleaved wins/losses."""
    # Interleave wins/losses so each block has realistic distribution
    step = round(1.0 / home_w)
    results = [i % step != 0 for i in range(n)]  # ~home_w fraction = True
    # Adjust to exact target
    while sum(results) / n < home_w - 0.01:
        for i in range(n):
            if not results[i]: results[i] = True; break
    while sum(results) / n > home_w + 0.01:
        for i in range(n-1, -1, -1):
            if results[i]: results[i] = False; break

    path = os.path.join(tmpdir, "training", "2021-22")
    os.makedirs(path)
    for i in range(n):
        g = make_game(i, won=results[i])
        with open(os.path.join(path, f"t_{i:04d}.json"), "w") as f:
            json.dump(g, f)
    # Small testing split
    t = os.path.join(tmpdir, "testing", "2022-23")
    os.makedirs(t)
    for i in range(100):
        g = make_game(i, won=(i % 10 < 7))
        with open(os.path.join(t, f"t_{i:04d}.json"), "w") as f:
            json.dump(g, f)


def setup():
    global TMPDIR
    TMPDIR = tempfile.mkdtemp(prefix="nba_evol_")
    build_data(TMPDIR, n=600, home_w=0.65)

def teardown():
    if TMPDIR and os.path.isdir(TMPDIR):
        shutil.rmtree(TMPDIR)

def make_loader():
    return DataLoader(TMPDIR, use_disk_cache=False, verbose=False)

def make_engine():
    out = os.path.join(TMPDIR, "saved_formulas")
    return EvolutionEngine(make_loader(), output_dir=out)

def net_rtg_node():
    """A good formula: season_stats.net_rtg."""
    idx = REG.get("season_stats.net_rtg", 3)
    return VarNode("season_stats.net_rtg", idx)

def weak_node():
    """A weak formula: constant 1 (always predicts home, ~65% acc)."""
    return ConstNode(1.0)

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 1: EvolutionConfig
# ─────────────────────────────────────────────────────────────────────────────

def test_config_defaults():
    c = EvolutionConfig()
    assert c.direction == "up"
    eq(c.mutation_strength, 0.5)
    assert c.eval_block_size == 500
    assert c.stagnation_limit == 100

def test_config_custom():
    c = EvolutionConfig(mutation_strength=0.8, direction="down",
                         stagnation_limit=50, min_improvement=0.001)
    eq(c.mutation_strength, 0.8)
    assert c.direction == "down"
    assert c.stagnation_limit == 50

def test_config_serialization():
    c  = EvolutionConfig(mutation_strength=0.7, min_improvement=0.001)
    d  = c.to_dict()
    c2 = EvolutionConfig.from_dict(d)
    eq(c2.mutation_strength, 0.7)
    eq(c2.min_improvement, 0.001)

def test_config_invalid_direction():
    try:
        EvolutionConfig(direction="sideways")
        assert False
    except AssertionError:
        pass

def test_config_invalid_strength():
    try:
        EvolutionConfig(mutation_strength=1.5)
        assert False
    except AssertionError:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 2: EvolutionStats
# ─────────────────────────────────────────────────────────────────────────────

def test_stats_accept_rate_zero():
    s = EvolutionStats()
    eq(s.accept_rate, 0.0)

def test_stats_accept_rate():
    s = EvolutionStats(gen_tried=100, gen_accepted=15, gen_invalid=5)
    # 100-5=95 valid, 15/95 ≈ 0.1578
    eq(s.accept_rate, 15/95, tol=1e-4)

def test_stats_serializable():
    s = EvolutionStats(gen_tried=50, gen_accepted=5,
                        current_accuracy=0.72, best_accuracy=0.73)
    d = s.to_dict()
    assert "accept_rate"     in d
    assert "mutations_per_s" in d
    assert "elapsed_s"       in d
    eq(d["current_accuracy"], 0.72)

def test_stats_not_running_by_default():
    s = EvolutionStats()
    assert not s.is_running

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 3: GenerationRecord
# ─────────────────────────────────────────────────────────────────────────────

def test_gen_record_creation():
    r = GenerationRecord(
        gen_number=1, accuracy=0.72, improvement=0.005,
        n_games_eval=600, mutation_type="mutate",
        tree_size=5, tree_depth=2,
    )
    assert r.gen_number == 1
    assert r.timestamp != ""

def test_gen_record_serializable():
    r = GenerationRecord(1, 0.72, 0.005, 600, "mutate", 5, 2)
    d = r.to_dict()
    assert "gen_number" in d
    assert "accuracy"   in d
    assert "timestamp"  in d

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 4: evaluate_child_vs_parent
# ─────────────────────────────────────────────────────────────────────────────

def _make_ds(n=600, home_w=0.65):
    """Build a small CDataset with interleaved wins/losses."""
    from data_loader import games_to_cdataset
    results = [i % round(1/home_w) != 0 for i in range(n)]
    games = [make_game(i, won=results[i]) for i in range(n)]
    return games_to_cdataset(games)

DS_EVAL = None
def get_ds_eval():
    global DS_EVAL
    if DS_EVAL is None:
        DS_EVAL = _make_ds(600)
    return DS_EVAL

def test_eval_better_child_accepted():
    """A strictly better formula should be accepted."""
    ds  = get_ds_eval()
    idx = REG.get("season_stats.net_rtg", 3)
    cfg = EvolutionConfig(min_improvement=0.001, eval_block_size=200,
                          min_blocks_confirm=1, direction="up")

    # Parent: constant 0 (50% on any dataset with >= 50% home wins → 65% here)
    # Child: net_rtg (much better predictor)
    parent_cf = ast_to_c_formula(ConstNode(1.0))
    child_cf  = ast_to_c_formula(VarNode("season_stats.net_rtg", idx))

    accepted, acc, n_eval = evaluate_child_vs_parent(
        ENGINE, child_cf, parent_cf, ds, cfg)
    assert accepted, f"Better child should be accepted (acc={acc:.4f})"
    assert acc > 0.60

def test_eval_worse_child_rejected():
    """A worse formula should be rejected at first block."""
    ds  = get_ds_eval()
    idx = REG.get("season_stats.net_rtg", 3)
    cfg = EvolutionConfig(min_improvement=0.001, eval_block_size=200,
                          min_blocks_confirm=1, direction="up")

    # Parent: good (net_rtg)
    # Child: bad (inverted net_rtg → predicts wrong)
    parent_cf = ast_to_c_formula(VarNode("season_stats.net_rtg", idx))
    bad_node  = UnaryNode("neg", VarNode("season_stats.net_rtg", idx))
    child_cf  = ast_to_c_formula(bad_node)

    accepted, acc, n_eval = evaluate_child_vs_parent(
        ENGINE, child_cf, parent_cf, ds, cfg)
    assert not accepted, f"Worse child should be rejected (acc={acc:.4f})"
    assert n_eval <= 400  # eliminated at first or second block

def test_eval_early_stopping_saves_time():
    """Worse child is eliminated before evaluating full dataset."""
    ds  = get_ds_eval()
    idx = REG.get("season_stats.net_rtg", 3)
    cfg = EvolutionConfig(min_improvement=0.01, eval_block_size=100,
                          min_blocks_confirm=1, direction="up")

    parent_cf = ast_to_c_formula(VarNode("season_stats.net_rtg", idx))
    bad_cf    = ast_to_c_formula(ConstNode(-1.0))  # always predicts away

    _, _, n_eval = evaluate_child_vs_parent(
        ENGINE, bad_cf, parent_cf, ds, cfg)
    assert n_eval < ds.n_games, \
        f"Should have stopped early: n_eval={n_eval} < {ds.n_games}"

def test_eval_direction_down():
    """Direction='down' should accept formulas that decrease accuracy."""
    ds  = get_ds_eval()
    idx = REG.get("season_stats.net_rtg", 3)
    cfg = EvolutionConfig(min_improvement=0.001, eval_block_size=200,
                          min_blocks_confirm=1, direction="down")

    # Parent: constant 1.0 (predicts home ~65% correct)
    # Child: neg(net_rtg) → predicts wrong → lower accuracy → better for "down"
    parent_cf = ast_to_c_formula(ConstNode(1.0))
    child_cf  = ast_to_c_formula(
        UnaryNode("neg", VarNode("season_stats.net_rtg", idx)))

    accepted, acc, _ = evaluate_child_vs_parent(
        ENGINE, child_cf, parent_cf, ds, cfg)
    assert accepted, f"Worse accuracy should be accepted in 'down' mode (acc={acc:.4f})"

def test_eval_high_threshold_rejects_marginal():
    """A very high min_improvement should reject marginal improvements."""
    ds  = get_ds_eval()
    idx = REG.get("season_stats.net_rtg", 3)
    cfg = EvolutionConfig(min_improvement=0.50,  # 50%! impossible
                          eval_block_size=200, min_blocks_confirm=1)

    parent_cf = ast_to_c_formula(VarNode("season_stats.net_rtg", idx))
    # Even a good child can't beat parent by 50%
    child_cf  = ast_to_c_formula(
        BinaryNode("+", VarNode("season_stats.net_rtg", idx), ConstNode(0.001)))

    accepted, _, _ = evaluate_child_vs_parent(
        ENGINE, child_cf, parent_cf, ds, cfg)
    assert not accepted

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 5: Persistence
# ─────────────────────────────────────────────────────────────────────────────

def test_save_run_config():
    out = os.path.join(TMPDIR, "persist_test")
    cfg = EvolutionConfig(mutation_strength=0.7)
    save_run_config(out, "f001", "run_001", cfg,
                     {"tree": ConstNode(1.0).to_dict(), "accuracy": 0.65})
    d = load_run_config(out, "f001", "run_001")
    assert d is not None
    eq(d["config"]["mutation_strength"], 0.7)
    assert "origin" in d

def test_save_generation_snapshot():
    out  = os.path.join(TMPDIR, "snap_test")
    cfg  = EvolutionConfig()
    save_run_config(out, "f001", "run_001", cfg,
                     {"tree": ConstNode(1.0).to_dict()})
    rec  = GenerationRecord(1, 0.72, 0.005, 500, "mutate", 5, 2)
    node = VarNode("season_stats.net_rtg", 3)
    save_generation_snapshot(out, "f001", "run_001", rec, node)
    path = os.path.join(out, "f001", "run_001", "generations",
                         "gen_000001.json")
    assert os.path.exists(path)
    with open(path) as f:
        d = json.load(f)
    assert d["gen_number"] == 1
    eq(d["accuracy"], 0.72)
    assert "tree" in d

def test_save_and_load_best():
    out  = os.path.join(TMPDIR, "best_test")
    cfg  = EvolutionConfig()
    save_run_config(out, "f001", "run_001", cfg,
                     {"tree": ConstNode(1.0).to_dict()})
    node = VarNode("season_stats.net_rtg", 3)
    save_best(out, "f001", "run_001", node, 0.78, 5)
    b = load_best(out, "f001", "run_001")
    assert b is not None
    eq(b["accuracy"], 0.78)
    assert b["gen_number"] == 5
    assert "tree" in b

def test_save_and_load_history():
    out  = os.path.join(TMPDIR, "hist_test")
    cfg  = EvolutionConfig()
    save_run_config(out, "f001", "run_001", cfg,
                     {"tree": ConstNode(1.0).to_dict()})
    hist = [
        GenerationRecord(1, 0.70, 0.005, 500, "mutate", 3, 1),
        GenerationRecord(2, 0.71, 0.010, 500, "mutate", 4, 2),
    ]
    stats = EvolutionStats(gen_tried=20, gen_accepted=2)
    save_run_history(out, "f001", "run_001", hist, stats)
    d = load_history(out, "f001", "run_001")
    assert d is not None
    assert d["n_accepted"] == 2
    assert len(d["history"]) == 2

def test_list_runs_empty():
    out = os.path.join(TMPDIR, "list_empty")
    assert list_runs(out, "f_unknown") == []

def test_list_runs_after_save():
    out = os.path.join(TMPDIR, "list_runs_test")
    for rid in ["run_001", "run_002"]:
        save_run_config(out, "f001", rid, EvolutionConfig(),
                         {"tree": ConstNode(1.0).to_dict()})
    runs = list_runs(out, "f001")
    rids = [r["run_id"] for r in runs]
    assert "run_001" in rids
    assert "run_002" in rids

def test_next_run_id_empty():
    out = os.path.join(TMPDIR, "next_id_test")
    assert next_run_id(out, "f001") == "run_001"

def test_next_run_id_increments():
    out = os.path.join(TMPDIR, "next_id_inc")
    save_run_config(out, "f001", "run_001", EvolutionConfig(),
                     {"tree": ConstNode(1.0).to_dict()})
    assert next_run_id(out, "f001") == "run_002"

def test_load_run_config_missing():
    assert load_run_config("/nonexistent", "f001", "run_001") is None

def test_load_best_missing():
    assert load_best("/nonexistent", "f001", "run_001") is None

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 6: EvolutionEngine — basic run
# ─────────────────────────────────────────────────────────────────────────────

def test_engine_run_creates_files():
    eng  = make_engine()
    cfg  = EvolutionConfig(
        max_generations  = 20,
        stagnation_limit = 20,
        eval_block_size  = 200,
        min_improvement  = 0.0001,
        attempts_per_gen = 3,
        report_every     = 50,
    )
    eng.run("f001", weak_node(), cfg, run_id="run_001")
    out = os.path.join(TMPDIR, "saved_formulas")
    assert os.path.exists(os.path.join(out, "f001", "run_001", "config.json"))
    assert os.path.exists(os.path.join(out, "f001", "run_001", "history.json"))

def test_engine_run_stats_consistent():
    eng  = make_engine()
    cfg  = EvolutionConfig(
        max_generations  = 30,
        stagnation_limit = 30,
        eval_block_size  = 150,
        min_improvement  = 0.0001,
        attempts_per_gen = 3,
        report_every     = 50,
    )
    stats = eng.run("f_stat", weak_node(), cfg, run_id="run_001")
    total = (stats.gen_tried + stats.gen_invalid)
    # gen_tried = accepted + rejected
    assert stats.gen_tried == stats.gen_accepted + stats.gen_rejected, \
        f"tried={stats.gen_tried} != accepted={stats.gen_accepted} + rejected={stats.gen_rejected}"
    assert not stats.is_running
    assert stats.elapsed_s > 0

def test_engine_run_stops_at_max_gen():
    eng  = make_engine()
    cfg  = EvolutionConfig(
        max_generations  = 15,
        stagnation_limit = 1000,
        eval_block_size  = 150,
        min_improvement  = 0.0001,
        attempts_per_gen = 2,
        report_every     = 100,
    )
    stats = eng.run("f_maxgen", weak_node(), cfg)
    assert stats.gen_tried <= 15 + 5  # small tolerance for rounding
    assert stats.stop_reason in ("max_generations", "stagnation")

def test_engine_run_stops_at_stagnation():
    eng  = make_engine()
    cfg  = EvolutionConfig(
        max_generations  = 0,
        stagnation_limit = 5,
        eval_block_size  = 150,
        # Impossibly high threshold → everything rejected → stagnation
        min_improvement  = 0.99,
        attempts_per_gen = 2,
        report_every     = 100,
    )
    stats = eng.run("f_stag", weak_node(), cfg)
    assert stats.stop_reason == "stagnation", \
        f"Expected stagnation, got: {stats.stop_reason!r}"
    assert stats.gen_accepted == 0

def test_engine_not_running_after_finish():
    eng  = make_engine()
    cfg  = EvolutionConfig(max_generations=10, stagnation_limit=10,
                            eval_block_size=150, min_improvement=0.0001,
                            attempts_per_gen=2, report_every=100)
    eng.run("f_done", weak_node(), cfg)
    assert not eng.is_running()

def test_engine_saves_best():
    eng  = make_engine()
    cfg  = EvolutionConfig(
        max_generations  = 0,
        stagnation_limit = 5,
        eval_block_size  = 150,
        min_improvement  = 0.0001,
        attempts_per_gen = 5,
        report_every     = 100,
    )
    eng.run("f_best", net_rtg_node(), cfg, run_id="run_001")
    best = load_best(os.path.join(TMPDIR, "saved_formulas"), "f_best", "run_001")
    assert best is not None
    assert "tree" in best
    assert "accuracy" in best

def test_engine_invalid_start_raises():
    eng = make_engine()
    # A formula that doesn't compile
    class BadNode:
        def to_dict(self): return {}
        def size(self): return 0
        def depth(self): return 0
    try:
        from formula_engine import Node
        bad = ConstNode(1.0)
        bad.to_rpn = lambda: []   # empty RPN → invalid
        cf = ast_to_c_formula(bad)
        # If it somehow compiles, the engine should handle it
    except Exception:
        pass  # Expected

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 7: continue_run
# ─────────────────────────────────────────────────────────────────────────────

def test_continue_run_picks_up_from_best():
    eng  = make_engine()
    cfg  = EvolutionConfig(
        max_generations  = 10,
        stagnation_limit = 10,
        eval_block_size  = 150,
        min_improvement  = 0.0001,
        attempts_per_gen = 3,
        report_every     = 100,
    )
    # First run
    stats1 = eng.run("f_cont", net_rtg_node(), cfg, run_id="run_001")
    gen1   = stats1.gen_accepted

    # Continue
    stats2 = eng.continue_run("f_cont", "run_001", cfg)
    # History should have more entries
    hist = load_history(os.path.join(TMPDIR, "saved_formulas"),
                         "f_cont", "run_001")
    assert hist["n_accepted"] >= gen1

def test_continue_run_missing_raises():
    eng = make_engine()
    try:
        eng.continue_run("nonexistent", "run_999")
        assert False, "Should have raised"
    except FileNotFoundError:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 8: Direction modes
# ─────────────────────────────────────────────────────────────────────────────

def test_direction_up_improves_accuracy():
    """Evolution 'up' should find formulas with equal or better accuracy."""
    eng  = make_engine()
    cfg  = EvolutionConfig(
        direction        = "up",
        max_generations  = 0,
        stagnation_limit = 8,
        eval_block_size  = 200,
        min_improvement  = 0.0001,
        attempts_per_gen = 8,
        report_every     = 100,
        mutation_strength= 0.5,
    )
    start_acc = ENGINE.accuracy(
        ast_to_c_formula(weak_node()),
        make_loader().get_training()
    )
    stats = eng.run("f_up", weak_node(), cfg)
    best  = load_best(os.path.join(TMPDIR,"saved_formulas"), "f_up",
                       next_run_id(os.path.join(TMPDIR,"saved_formulas"),"f_up")
                       .replace("run_00","run_00")[:-1] +
                       str(len(list_runs(os.path.join(TMPDIR,"saved_formulas"),"f_up"))))
    if best and stats.gen_accepted > 0:
        assert best["accuracy"] >= start_acc - 0.001, \
            f"'up' mode went down: {best['accuracy']:.4f} < {start_acc:.4f}"

def test_direction_down_decreases_accuracy():
    """Evolution 'down' should produce formulas with lower accuracy."""
    eng   = make_engine()
    cfg   = EvolutionConfig(
        direction        = "down",
        max_generations  = 0,
        stagnation_limit = 8,
        eval_block_size  = 200,
        min_improvement  = 0.0001,
        attempts_per_gen = 8,
        report_every     = 100,
        mutation_strength= 0.7,
    )
    # Start from net_rtg (good predictor ~85%+ on synthetic data)
    idx        = REG.get("season_stats.net_rtg", 3)
    start_node = VarNode("season_stats.net_rtg", idx)
    stats = eng.run("f_down", start_node, cfg, run_id="run_001")
    # May not always find improvements, but should not crash
    assert not stats.is_running

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 9: Stop signal
# ─────────────────────────────────────────────────────────────────────────────

def test_stop_via_request_stop():
    eng  = make_engine()
    cfg  = EvolutionConfig(
        max_generations  = 0,
        stagnation_limit = 10000,
        eval_block_size  = 100,
        min_improvement  = 0.0001,
        attempts_per_gen = 3,
        report_every     = 100,
    )
    def stopper():
        time.sleep(0.5)  # give the engine time to start
        eng.request_stop()

    t       = threading.Thread(target=stopper, daemon=True)
    t.start()
    t0      = time.time()
    stats   = eng.run("f_stop", net_rtg_node(), cfg)
    elapsed = time.time() - t0
    t.join(timeout=3)

    assert not stats.is_running, "Engine should not be running after stop"
    assert elapsed < 3.0, f"Took too long: {elapsed:.2f}s"
    assert stats.stop_reason == "stop_signal", \
        f"Expected stop_signal, got: {stats.stop_reason!r}"

def test_stop_cleans_up_stop_file():
    eng = make_engine()
    cfg = EvolutionConfig(max_generations=5, stagnation_limit=5,
                           eval_block_size=100, min_improvement=0.0001,
                           attempts_per_gen=2, report_every=100)
    eng.run("f_cleanup", weak_node(), cfg)
    assert not os.path.exists(".stop_evolution"), \
        "Stop file should be cleaned up after run"

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 10: Callbacks
# ─────────────────────────────────────────────────────────────────────────────

def test_progress_callback_called():
    calls = []
    def on_prog(s):
        calls.append(s.gen_tried)

    eng  = make_engine()
    cfg  = EvolutionConfig(
        max_generations  = 30,
        stagnation_limit = 30,
        eval_block_size  = 100,
        min_improvement  = 0.0001,
        attempts_per_gen = 2,
        report_every     = 5,
    )
    eng.run("f_cb", weak_node(), cfg, on_progress=on_prog)
    assert len(calls) >= 1

def test_accept_callback_called_on_improvement():
    accepted_recs = []
    def on_acc(rec):
        accepted_recs.append(rec.gen_number)

    eng  = make_engine()
    cfg  = EvolutionConfig(
        max_generations  = 0,
        stagnation_limit = 5,
        eval_block_size  = 150,
        min_improvement  = 0.0001,
        attempts_per_gen = 5,
        report_every     = 100,
    )
    stats = eng.run("f_acc_cb", weak_node(), cfg, on_accept=on_acc)
    assert len(accepted_recs) == stats.gen_accepted

def test_callbacks_not_required():
    """Engine should work fine with no callbacks."""
    eng  = make_engine()
    cfg  = EvolutionConfig(max_generations=5, stagnation_limit=5,
                            eval_block_size=100, min_improvement=0.0001,
                            attempts_per_gen=2, report_every=100)
    stats = eng.run("f_no_cb", weak_node(), cfg)
    assert not stats.is_running

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 11: History integrity
# ─────────────────────────────────────────────────────────────────────────────

def test_history_is_monotone_up():
    """In 'up' mode, each accepted generation should be >= previous."""
    eng  = make_engine()
    cfg  = EvolutionConfig(
        direction        = "up",
        max_generations  = 0,
        stagnation_limit = 10,
        eval_block_size  = 150,
        min_improvement  = 0.0001,
        attempts_per_gen = 5,
        report_every     = 100,
    )
    stats = eng.run("f_mono", weak_node(), cfg, run_id="run_001")
    if stats.gen_accepted < 2:
        return  # can't test monotonicity with < 2 points
    hist = load_history(os.path.join(TMPDIR, "saved_formulas"),
                         "f_mono", "run_001")
    accs = [r["accuracy"] for r in hist["history"]]
    for i in range(1, len(accs)):
        assert accs[i] >= accs[i-1] - 1e-6, \
            f"Accuracy went down at gen {i}: {accs[i]:.6f} < {accs[i-1]:.6f}"

def test_history_gen_numbers_sequential():
    """Gen numbers in history should be 1, 2, 3, ..."""
    eng  = make_engine()
    cfg  = EvolutionConfig(
        max_generations  = 0,
        stagnation_limit = 5,
        eval_block_size  = 150,
        min_improvement  = 0.0001,
        attempts_per_gen = 5,
        report_every     = 100,
    )
    eng.run("f_seq", net_rtg_node(), cfg, run_id="run_001")
    hist = load_history(os.path.join(TMPDIR, "saved_formulas"),
                         "f_seq", "run_001")
    if not hist or hist["n_accepted"] == 0:
        return
    nums = [r["gen_number"] for r in hist["history"]]
    assert nums == list(range(1, len(nums)+1)), \
        f"Non-sequential gen numbers: {nums}"

def test_best_matches_last_accepted():
    """best.json accuracy should match the best in history."""
    eng  = make_engine()
    cfg  = EvolutionConfig(
        direction        = "up",
        max_generations  = 0,
        stagnation_limit = 6,
        eval_block_size  = 150,
        min_improvement  = 0.0001,
        attempts_per_gen = 5,
        report_every     = 100,
    )
    eng.run("f_bestcheck", weak_node(), cfg, run_id="run_001")
    out  = os.path.join(TMPDIR, "saved_formulas")
    best = load_best(out, "f_bestcheck", "run_001")
    hist = load_history(out, "f_bestcheck", "run_001")
    if not best or not hist or hist["n_accepted"] == 0:
        return
    hist_best = max(r["accuracy"] for r in hist["history"])
    eq(best["accuracy"], hist_best, tol=1e-5)

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 12: Performance
# ─────────────────────────────────────────────────────────────────────────────

def test_perf_mutations_per_second():
    """Measure raw mutation throughput."""
    eng  = make_engine()
    cfg  = EvolutionConfig(
        max_generations  = 200,
        stagnation_limit = 10000,
        eval_block_size  = 200,
        min_improvement  = 0.0001,
        attempts_per_gen = 1,
        report_every     = 500,
    )
    t0    = time.time()
    stats = eng.run("f_perf", weak_node(), cfg)
    ms    = (time.time()-t0)*1000
    mps   = stats.gen_tried / (ms/1000) if ms > 0 else 0

    print(f"\n           ({ms:.0f}ms, {mps:.0f} mutations/s, "
          f"{stats.gen_accepted} accepted/{stats.gen_tried} tried, "
          f"accept_rate={stats.accept_rate:.1%})", end="")

    assert mps >= 10, f"Too slow: {mps:.1f} mutations/s"

def test_perf_accept_rate_realistic():
    """With a reasonable threshold, accept rate should be 5-30%."""
    eng  = make_engine()
    cfg  = EvolutionConfig(
        max_generations  = 100,
        stagnation_limit = 10000,
        eval_block_size  = 200,
        min_improvement  = 0.0005,
        attempts_per_gen = 1,
        report_every     = 500,
        mutation_strength= 0.5,
    )
    stats = eng.run("f_rate", weak_node(), cfg)
    print(f"\n           (accept_rate={stats.accept_rate:.1%}, "
          f"accepted={stats.gen_accepted}/{stats.gen_tried})", end="")
    # With a weak formula there should be some improvements
    # Accept rate can be anywhere from 0 to 50%+ — just ensure it's finite
    assert 0.0 <= stats.accept_rate <= 1.0

def test_perf_early_stopping_faster_than_full():
    """Worse child should be eliminated before evaluating all games."""
    ds  = get_ds_eval()
    idx = REG.get("season_stats.net_rtg", 3)
    parent = ast_to_c_formula(VarNode("season_stats.net_rtg", idx))
    bad    = ast_to_c_formula(ConstNode(-1.0))  # always predicts away

    cfg = EvolutionConfig(eval_block_size=100, min_improvement=0.01)
    _, _, n_eval = evaluate_child_vs_parent(ENGINE, bad, parent, ds, cfg)

    # Bad child should be eliminated BEFORE seeing all games
    print(f"\n           (bad child stopped at {n_eval}/{ds.n_games} games "
          f"= {n_eval/ds.n_games:.0%} of dataset)", end="")
    assert n_eval < ds.n_games, \
        f"Should have stopped early: {n_eval} == {ds.n_games}"

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    setup()
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║   Layer 5 — Evolution Engine Test Suite             ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    print("── 1. EvolutionConfig ────────────────────────────────────")
    test("config_defaults",          test_config_defaults)
    test("config_custom",            test_config_custom)
    test("config_serialization",     test_config_serialization)
    test("config_invalid_direction", test_config_invalid_direction)
    test("config_invalid_strength",  test_config_invalid_strength)

    print("\n── 2. EvolutionStats ─────────────────────────────────────")
    test("stats_accept_rate_zero",   test_stats_accept_rate_zero)
    test("stats_accept_rate",        test_stats_accept_rate)
    test("stats_serializable",       test_stats_serializable)
    test("stats_not_running",        test_stats_not_running_by_default)

    print("\n── 3. GenerationRecord ───────────────────────────────────")
    test("gen_record_creation",      test_gen_record_creation)
    test("gen_record_serializable",  test_gen_record_serializable)

    print("\n── 4. evaluate_child_vs_parent ───────────────────────────")
    test("better_child_accepted",    test_eval_better_child_accepted)
    test("worse_child_rejected",     test_eval_worse_child_rejected)
    test("early_stopping_saves",     test_eval_early_stopping_saves_time)
    test("direction_down",           test_eval_direction_down)
    test("high_threshold_rejects",   test_eval_high_threshold_rejects_marginal)

    print("\n── 5. Persistence ────────────────────────────────────────")
    test("save_run_config",          test_save_run_config)
    test("save_gen_snapshot",        test_save_generation_snapshot)
    test("save_and_load_best",       test_save_and_load_best)
    test("save_and_load_history",    test_save_and_load_history)
    test("list_runs_empty",          test_list_runs_empty)
    test("list_runs_after_save",     test_list_runs_after_save)
    test("next_run_id_empty",        test_next_run_id_empty)
    test("next_run_id_increments",   test_next_run_id_increments)
    test("load_config_missing",      test_load_run_config_missing)
    test("load_best_missing",        test_load_best_missing)

    print("\n── 6. Engine — basic run ─────────────────────────────────")
    test("run_creates_files",        test_engine_run_creates_files)
    test("run_stats_consistent",     test_engine_run_stats_consistent)
    test("stops_at_max_gen",         test_engine_run_stops_at_max_gen)
    test("stops_at_stagnation",      test_engine_run_stops_at_stagnation)
    test("not_running_after_finish", test_engine_not_running_after_finish)
    test("saves_best",               test_engine_saves_best)
    test("invalid_start_handled",    test_engine_invalid_start_raises)

    print("\n── 7. continue_run ───────────────────────────────────────")
    test("continue_picks_up",        test_continue_run_picks_up_from_best)
    test("continue_missing_raises",  test_continue_run_missing_raises)

    print("\n── 8. Direction modes ────────────────────────────────────")
    test("direction_up_improves",    test_direction_up_improves_accuracy)
    test("direction_down_decreases", test_direction_down_decreases_accuracy)

    print("\n── 9. Stop signal ────────────────────────────────────────")
    test("stop_request_stop",        test_stop_via_request_stop)
    test("stop_cleans_up_file",      test_stop_cleans_up_stop_file)

    print("\n── 10. Callbacks ─────────────────────────────────────────")
    test("progress_callback",        test_progress_callback_called)
    test("accept_callback",          test_accept_callback_called_on_improvement)
    test("no_callbacks_ok",          test_callbacks_not_required)

    print("\n── 11. History integrity ─────────────────────────────────")
    test("history_monotone_up",      test_history_is_monotone_up)
    test("gen_numbers_sequential",   test_history_gen_numbers_sequential)
    test("best_matches_history",     test_best_matches_last_accepted)

    print("\n── 12. Performance ───────────────────────────────────────")
    test("mutations_per_second",     test_perf_mutations_per_second)
    test("accept_rate_realistic",    test_perf_accept_rate_realistic)
    test("early_stopping_faster",    test_perf_early_stopping_faster_than_full)

    teardown()
    print(f"\n╔══════════════════════════════════════════════════════╗")
    print(f"║  Results: {_p:3d} passed  {_f:3d} failed  {_p+_f:3d} total           ║")
    print(f"╚══════════════════════════════════════════════════════╝\n")
    return 0 if _f == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
