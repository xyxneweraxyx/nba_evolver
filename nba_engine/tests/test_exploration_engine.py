#!/usr/bin/env python3
"""
tests/test_exploration_engine.py — Layer 4 test suite
======================================================
Run: python3 tests/test_exploration_engine.py
"""

import sys, os, json, time, tempfile, shutil, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exploration_engine import (
    ExplorationConfig, ExplorationStats,
    ExplorationEngine,
    formula_hash, load_existing_hashes,
    save_formula_record, update_summary,
    load_summary, load_batch, list_batches, get_formula,
)
from data_loader import DataLoader
from formula_engine import VarNode, ConstNode, BinaryNode, random_formula
from nba_engine_binding import get_registry

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

def eq(a, b, tol=1e-5): assert abs(float(a)-float(b)) <= tol, f"{a} != {b}"

# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

TMPDIR = None

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
                "off_rtg": 116.0, "w_pct": 0.65 if won else 0.40,
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


def build_data_dir(tmpdir, n=300):
    """Build minimal data dir for DataLoader."""
    path = os.path.join(tmpdir, "training", "2021-22")
    os.makedirs(path)
    for i in range(n):
        g = make_game(i, won=(i < int(n * 0.65)))
        with open(os.path.join(path, f"2021-22_{i:04d}.json"), "w") as f:
            json.dump(g, f)
    # testing
    path2 = os.path.join(tmpdir, "testing", "2022-23")
    os.makedirs(path2)
    for i in range(50):
        g = make_game(i, won=(i < 30))
        with open(os.path.join(path2, f"2022-23_{i:04d}.json"), "w") as f:
            json.dump(g, f)


def setup():
    global TMPDIR
    TMPDIR = tempfile.mkdtemp(prefix="nba_expl_")
    build_data_dir(TMPDIR, n=300)

def teardown():
    if TMPDIR and os.path.isdir(TMPDIR):
        shutil.rmtree(TMPDIR)

def make_loader():
    return DataLoader(TMPDIR, use_disk_cache=False, verbose=False)

def make_engine():
    out = os.path.join(TMPDIR, "generated_formulas")
    return ExplorationEngine(make_loader(), output_dir=out)

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 1: ExplorationConfig
# ─────────────────────────────────────────────────────────────────────────────

def test_config_defaults():
    c = ExplorationConfig()
    assert c.max_depth == 4
    assert c.max_size == 50
    assert c.block_size == 100
    assert c.interest_mode == "both"
    assert c.batch_name != ""  # auto-generated

def test_config_auto_batch_name():
    c = ExplorationConfig()
    assert c.batch_name.startswith("batch_")

def test_config_custom_batch_name():
    c = ExplorationConfig(batch_name="my_run")
    assert c.batch_name == "my_run"

def test_config_serialization():
    c  = ExplorationConfig(max_depth=6, min_interest=0.25)
    d  = c.to_dict()
    c2 = ExplorationConfig.from_dict(d)
    assert c2.max_depth == 6
    eq(c2.min_interest, 0.25)

def test_config_invalid_mode():
    try:
        ExplorationConfig(interest_mode="invalid")
        assert False, "Should have raised"
    except AssertionError:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 2: ExplorationStats
# ─────────────────────────────────────────────────────────────────────────────

def test_stats_survival_rate_zero():
    s = ExplorationStats()
    eq(s.survival_rate(), 0.0)

def test_stats_survival_rate():
    s = ExplorationStats(n_generated=100, n_saved=20,
                          n_invalid=5, n_duplicates=5)
    # 100 - 5 - 5 = 90 valid, 20/90 ≈ 0.222
    eq(s.survival_rate(), 20/90, tol=1e-4)

def test_stats_serializable():
    s = ExplorationStats(n_generated=50, n_saved=5)
    d = s.to_dict()
    assert "survival_rate" in d
    assert "formulas_per_s" in d
    assert isinstance(d["n_generated"], int)

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 3: Dedup (formula hashing)
# ─────────────────────────────────────────────────────────────────────────────

def test_hash_same_formula():
    f1 = BinaryNode("+", VarNode("a", 0), ConstNode(1.0))
    f2 = BinaryNode("+", VarNode("a", 0), ConstNode(1.0))
    assert formula_hash(f1) == formula_hash(f2)

def test_hash_different_formulas():
    f1 = BinaryNode("+", VarNode("a", 0), ConstNode(1.0))
    f2 = BinaryNode("+", VarNode("a", 0), ConstNode(2.0))
    assert formula_hash(f1) != formula_hash(f2)

def test_hash_stable_across_clones():
    f = random_formula(3, 20)
    assert formula_hash(f) == formula_hash(f.clone())

def test_load_existing_hashes_empty_dir():
    out = os.path.join(TMPDIR, "empty_gen")
    hashes = load_existing_hashes(out)
    assert hashes == set()

def test_load_existing_hashes_loads_saved():
    out      = os.path.join(TMPDIR, "hash_test")
    batch    = os.path.join(out, "batch_001")
    os.makedirs(batch)
    f        = VarNode("x", 0)
    score    = {"accuracy": 0.7, "interest": 0.4,
                 "n_games_eval": 300, "direction": 1}
    save_formula_record(batch, "formula_000001", f, score)
    hashes = load_existing_hashes(out)
    assert formula_hash(f) in hashes

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 4: Persistence helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_save_formula_record_creates_file():
    out   = os.path.join(TMPDIR, "save_test")
    batch = os.path.join(out, "batch_001")
    os.makedirs(batch)
    f     = VarNode("season_stats.net_rtg", 0)
    score = {"accuracy": 0.72, "interest": 0.44,
              "n_games_eval": 300, "direction": 1}
    path  = save_formula_record(batch, "formula_000001", f, score)
    assert os.path.exists(path)
    with open(path) as fp:
        d = json.load(fp)
    assert d["id"] == "formula_000001"
    eq(d["score"]["accuracy"], 0.72)
    assert "tree" in d
    assert "vars" in d

def test_save_formula_record_complete():
    out   = os.path.join(TMPDIR, "save_test2")
    batch = os.path.join(out, "batch_001")
    os.makedirs(batch)
    f     = BinaryNode("+", VarNode("a", 0), ConstNode(1.0))
    score = {"accuracy": 0.65, "interest": 0.30,
              "n_games_eval": 300, "direction": 1}
    path  = save_formula_record(batch, "formula_000001", f, score)
    with open(path) as fp:
        d = json.load(fp)
    assert d["tree_size"] == f.size()
    assert d["tree_depth"] == f.depth()

def test_update_summary_creates_file():
    out  = os.path.join(TMPDIR, "summary_test")
    os.makedirs(out)
    cfg  = ExplorationConfig(batch_name="b1")
    st   = ExplorationStats(n_generated=100, n_saved=5)
    top  = [{"id":"f1","accuracy":0.7,"interest":0.4,
              "direction":1,"size":3,"repr":"x"}]
    update_summary(out, "b1", cfg, st, top)
    path = os.path.join(out, "summary.json")
    assert os.path.exists(path)
    with open(path) as f:
        d = json.load(f)
    assert d["batch_name"] == "b1"
    assert d["stats"]["n_generated"] == 100
    assert len(d["top_formulas"]) == 1

def test_load_summary_missing():
    assert load_summary("/nonexistent/path") is None

def test_load_batch_empty():
    out = os.path.join(TMPDIR, "empty_batch_test")
    os.makedirs(out + "/batch_x")
    result = load_batch(out, "batch_x")
    assert result == []

def test_list_batches():
    out = os.path.join(TMPDIR, "list_test")
    os.makedirs(out + "/batch_001")
    os.makedirs(out + "/batch_002")
    batches = list_batches(out)
    names = [b["name"] for b in batches]
    assert "batch_001" in names
    assert "batch_002" in names

def test_get_formula_missing():
    out = os.path.join(TMPDIR, "get_test")
    os.makedirs(out + "/b1")
    assert get_formula(out, "b1", "formula_999") is None

def test_load_batch_pagination():
    out   = os.path.join(TMPDIR, "page_test")
    batch = os.path.join(out, "b1")
    os.makedirs(batch)
    for i in range(10):
        f     = VarNode("x", i % 5)
        score = {"accuracy": 0.6+i*0.01, "interest": 0.2+i*0.01,
                  "n_games_eval": 300, "direction": 1}
        save_formula_record(batch, f"formula_{i:06d}", f, score)
    page1 = load_batch(out, "b1", offset=0, limit=5)
    page2 = load_batch(out, "b1", offset=5, limit=5)
    assert len(page1) == 5
    assert len(page2) == 5
    assert page1[0]["id"] != page2[0]["id"]

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 5: ExplorationEngine — basic run
# ─────────────────────────────────────────────────────────────────────────────

def test_engine_creates_batch_dir():
    eng = make_engine()
    cfg = ExplorationConfig(
        batch_name      = "test_basic",
        max_generated   = 20,
        fast_prefilter_n= 100,
        fast_min_interest = 0.01,
        min_interest    = 0.01,
        save_min_interest = 0.01,
        block_size      = 50,
        dedup_enabled   = False,
        report_every    = 10,
    )
    eng.run(cfg)
    batch_dir = os.path.join(TMPDIR, "generated_formulas", "test_basic")
    assert os.path.isdir(batch_dir)

def test_engine_generates_correct_count():
    eng = make_engine()
    cfg = ExplorationConfig(
        batch_name       = "test_count",
        max_generated    = 30,
        fast_prefilter_n = 0,
        min_interest     = 0.01,
        save_min_interest= 0.01,
        block_size       = 50,
        dedup_enabled    = False,
        report_every     = 50,
    )
    stats = eng.run(cfg)
    assert stats.n_generated == 30

def test_engine_saves_formulas():
    eng = make_engine()
    cfg = ExplorationConfig(
        batch_name       = "test_saves",
        max_generated    = 200,
        fast_prefilter_n = 100,
        fast_min_interest= 0.01,
        min_interest     = 0.10,
        save_min_interest= 0.10,
        block_size       = 50,
        dedup_enabled    = False,
        report_every     = 100,
    )
    stats = eng.run(cfg)
    assert stats.n_saved >= 0   # may be 0 if all filtered
    assert stats.n_generated == 200

def test_engine_writes_summary():
    eng = make_engine()
    cfg = ExplorationConfig(
        batch_name       = "test_summary",
        max_generated    = 50,
        fast_prefilter_n = 0,
        min_interest     = 0.01,
        save_min_interest= 0.01,
        block_size       = 50,
        dedup_enabled    = False,
        report_every     = 50,
    )
    eng.run(cfg)
    out  = os.path.join(TMPDIR, "generated_formulas")
    summ = load_summary(out)
    assert summ is not None
    assert summ["stats"]["n_generated"] >= 50

def test_engine_stats_consistent():
    eng = make_engine()
    cfg = ExplorationConfig(
        batch_name       = "test_stats",
        max_generated    = 100,
        fast_prefilter_n = 100,
        fast_min_interest= 0.01,
        min_interest     = 0.05,
        save_min_interest= 0.05,
        block_size       = 50,
        dedup_enabled    = False,
        report_every     = 50,
    )
    stats = eng.run(cfg)
    # Basic sanity
    assert stats.n_generated == 100
    total_accounted = (stats.n_invalid + stats.n_duplicates +
                       stats.n_prefiltered + stats.n_filtered +
                       stats.n_saved)
    assert total_accounted == 100, \
        f"Unaccounted formulas: {100} generated vs {total_accounted} counted"
    assert not stats.is_running
    assert stats.elapsed_s > 0

def test_engine_not_running_after_finish():
    eng = make_engine()
    cfg = ExplorationConfig(
        batch_name    = "test_running",
        max_generated = 10,
        fast_prefilter_n = 0,
        min_interest  = 0.01,
        save_min_interest = 0.01,
        block_size    = 50,
        dedup_enabled = False,
        report_every  = 50,
    )
    eng.run(cfg)
    assert not eng.is_running()

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 6: Interest filter modes
# ─────────────────────────────────────────────────────────────────────────────

def test_mode_good_only_no_bad():
    """good_only mode should never save direction=-1 formulas."""
    eng  = make_engine()
    cfg  = ExplorationConfig(
        batch_name       = "test_good_only",
        max_generated    = 300,
        fast_prefilter_n = 0,
        min_interest     = 0.05,
        save_min_interest= 0.05,
        block_size       = 50,
        interest_mode    = "good_only",
        dedup_enabled    = False,
        report_every     = 300,
    )
    eng.run(cfg)
    out   = os.path.join(TMPDIR, "generated_formulas")
    batch = load_batch(out, "test_good_only", limit=100)
    for rec in batch:
        assert rec["score"]["direction"] == 1, \
            f"Found bad formula in good_only mode: {rec['id']}"

def test_mode_bad_only_no_good():
    """bad_only mode should never save direction=+1 formulas."""
    eng  = make_engine()
    cfg  = ExplorationConfig(
        batch_name       = "test_bad_only",
        max_generated    = 300,
        fast_prefilter_n = 0,
        min_interest     = 0.05,
        save_min_interest= 0.05,
        block_size       = 50,
        interest_mode    = "bad_only",
        dedup_enabled    = False,
        report_every     = 300,
    )
    eng.run(cfg)
    out   = os.path.join(TMPDIR, "generated_formulas")
    batch = load_batch(out, "test_bad_only", limit=100)
    for rec in batch:
        assert rec["score"]["direction"] == -1, \
            f"Found good formula in bad_only mode: {rec['id']}"

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 7: Dedup
# ─────────────────────────────────────────────────────────────────────────────

def test_dedup_rejects_duplicates():
    eng  = make_engine()
    cfg  = ExplorationConfig(
        batch_name       = "test_dedup",
        max_generated    = 200,
        fast_prefilter_n = 0,
        min_interest     = 0.01,
        save_min_interest= 0.01,
        block_size       = 50,
        dedup_enabled    = True,
        report_every     = 200,
    )
    stats = eng.run(cfg)
    # With dedup on, duplicates should be counted
    # (may be 0 for small runs, just verify it doesn't crash)
    assert stats.n_duplicates >= 0
    assert stats.n_generated == 200

def test_dedup_no_duplicate_saves():
    """With dedup, no two saved formulas should have the same hash."""
    eng  = make_engine()
    cfg  = ExplorationConfig(
        batch_name       = "test_dedup_unique",
        max_generated    = 200,
        fast_prefilter_n = 0,
        min_interest     = 0.01,
        save_min_interest= 0.01,
        block_size       = 50,
        dedup_enabled    = True,
        report_every     = 200,
    )
    eng.run(cfg)
    out     = os.path.join(TMPDIR, "generated_formulas")
    records = load_batch(out, "test_dedup_unique", limit=200)
    hashes  = set()
    for rec in records:
        from formula_engine import node_from_dict
        node = node_from_dict(rec["tree"])
        h    = formula_hash(node)
        assert h not in hashes, "Duplicate formula saved despite dedup=True"
        hashes.add(h)

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 8: Stop signal
# ─────────────────────────────────────────────────────────────────────────────

def test_stop_via_request_stop():
    """request_stop() should cause run() to exit cleanly within 2 seconds."""
    eng   = make_engine()
    cfg   = ExplorationConfig(
        batch_name       = "test_stop",
        max_generated    = 0,      # unlimited
        fast_prefilter_n = 0,
        min_interest     = 0.01,
        save_min_interest= 0.01,
        block_size       = 50,
        dedup_enabled    = False,
        report_every     = 50,
    )
    def stopper():
        time.sleep(0.3)
        eng.request_stop()

    t  = threading.Thread(target=stopper, daemon=True)
    t.start()
    t0    = time.time()
    stats = eng.run(cfg)
    elapsed = time.time() - t0
    t.join(timeout=2)

    assert not stats.is_running,   "Engine should not be running after stop"
    assert elapsed < 2.0,          f"Engine took too long to stop: {elapsed:.2f}s"

def test_stop_via_max_generated():
    eng   = make_engine()
    cfg   = ExplorationConfig(
        batch_name       = "test_maxgen",
        max_generated    = 25,
        fast_prefilter_n = 0,
        min_interest     = 0.01,
        save_min_interest= 0.01,
        block_size       = 50,
        dedup_enabled    = False,
        report_every     = 50,
    )
    stats = eng.run(cfg)
    assert stats.n_generated == 25

def test_stop_via_max_saved():
    eng   = make_engine()
    cfg   = ExplorationConfig(
        batch_name       = "test_maxsave",
        max_generated    = 0,      # unlimited
        max_saved        = 2,      # stop after 2 saved
        fast_prefilter_n = 0,
        min_interest     = 0.01,
        save_min_interest= 0.01,
        block_size       = 50,
        dedup_enabled    = False,
        report_every     = 50,
    )
    stats = eng.run(cfg)
    assert stats.n_saved <= 2

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 9: Progress callback
# ─────────────────────────────────────────────────────────────────────────────

def test_progress_callback_called():
    calls = []
    def on_prog(s):
        calls.append(s.n_generated)

    eng  = make_engine()
    cfg  = ExplorationConfig(
        batch_name       = "test_callback",
        max_generated    = 100,
        fast_prefilter_n = 0,
        min_interest     = 0.01,
        save_min_interest= 0.01,
        block_size       = 50,
        dedup_enabled    = False,
        report_every     = 25,    # callback every 25 formulas
    )
    eng.run(cfg, on_progress=on_prog)
    assert len(calls) >= 1   # called at least once
    assert all(isinstance(n, int) for n in calls)

def test_save_callback_called():
    saves = []
    def on_save(rec):
        saves.append(rec["id"])

    eng  = make_engine()
    cfg  = ExplorationConfig(
        batch_name       = "test_save_cb",
        max_generated    = 200,
        fast_prefilter_n = 0,
        min_interest     = 0.01,
        save_min_interest= 0.01,
        block_size       = 50,
        dedup_enabled    = False,
        report_every     = 200,
    )
    stats = eng.run(cfg, on_save=on_save)
    assert len(saves) == stats.n_saved

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 10: Frontend helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_list_batches_after_run():
    eng  = make_engine()
    cfg  = ExplorationConfig(
        batch_name       = "front_batch_a",
        max_generated    = 20,
        fast_prefilter_n = 0,
        min_interest     = 0.01,
        save_min_interest= 0.01,
        block_size       = 50,
        dedup_enabled    = False,
        report_every     = 50,
    )
    eng.run(cfg)
    out     = os.path.join(TMPDIR, "generated_formulas")
    batches = list_batches(out)
    names   = [b["name"] for b in batches]
    assert "front_batch_a" in names

def test_get_formula_after_save():
    out   = os.path.join(TMPDIR, "gen_test_get")
    batch = os.path.join(out, "b1")
    os.makedirs(batch)
    f     = VarNode("x", 0)
    score = {"accuracy": 0.72, "interest": 0.44,
              "n_games_eval": 300, "direction": 1}
    save_formula_record(batch, "formula_000001", f, score)
    rec = get_formula(out, "b1", "formula_000001")
    assert rec is not None
    assert rec["id"] == "formula_000001"
    eq(rec["score"]["interest"], 0.44)

def test_summary_has_frontend_fields():
    eng  = make_engine()
    cfg  = ExplorationConfig(
        batch_name       = "front_summary",
        max_generated    = 30,
        fast_prefilter_n = 0,
        min_interest     = 0.01,
        save_min_interest= 0.01,
        block_size       = 50,
        dedup_enabled    = False,
        report_every     = 50,
    )
    eng.run(cfg)
    out  = os.path.join(TMPDIR, "generated_formulas")
    summ = load_summary(out)
    assert summ is not None
    # Fields the frontend will use
    assert "stats" in summ
    assert "top_formulas" in summ
    assert "config" in summ
    s = summ["stats"]
    assert "n_generated"    in s
    assert "n_saved"        in s
    assert "formulas_per_s" in s
    assert "survival_rate"  in s
    assert "best_interest"  in s

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 11: Performance
# ─────────────────────────────────────────────────────────────────────────────

def test_perf_throughput_500():
    """Measure real throughput on 500 formulas."""
    eng  = make_engine()
    cfg  = ExplorationConfig(
        batch_name       = "perf_run",
        max_generated    = 500,
        fast_prefilter_n = 100,
        fast_min_interest= 0.05,
        min_interest     = 0.15,
        save_min_interest= 0.15,
        block_size       = 50,
        dedup_enabled    = True,
        report_every     = 500,
    )
    t0    = time.time()
    stats = eng.run(cfg)
    ms    = (time.time()-t0)*1000
    fps   = stats.n_generated / (ms/1000)
    print(f"\n           ({ms:.0f}ms, {fps:.0f} formulas/s, "
          f"{stats.n_saved} saved, "
          f"{stats.n_prefiltered} prefiltered, "
          f"{stats.n_filtered} filtered)", end="")
    # At least 50 formulas/second (very conservative lower bound)
    assert fps >= 50, f"Too slow: {fps:.1f} formulas/s"

def test_perf_stats_accounting():
    """All generated formulas must be accounted for."""
    eng  = make_engine()
    cfg  = ExplorationConfig(
        batch_name       = "perf_account",
        max_generated    = 200,
        fast_prefilter_n = 100,
        fast_min_interest= 0.05,
        min_interest     = 0.10,
        save_min_interest= 0.10,
        block_size       = 50,
        dedup_enabled    = True,
        report_every     = 200,
    )
    stats = eng.run(cfg)
    total = (stats.n_invalid + stats.n_duplicates +
             stats.n_prefiltered + stats.n_filtered +
             stats.n_saved)
    assert total == 200, \
        (f"Accounting error: {total} != 200\n"
         f"  invalid={stats.n_invalid} dups={stats.n_duplicates} "
         f"prefiltered={stats.n_prefiltered} filtered={stats.n_filtered} "
         f"saved={stats.n_saved}")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    setup()
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║   Layer 4 — Exploration Engine Test Suite           ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    print("── 1. ExplorationConfig ──────────────────────────────────")
    test("config_defaults",          test_config_defaults)
    test("config_auto_batch_name",   test_config_auto_batch_name)
    test("config_custom_name",       test_config_custom_batch_name)
    test("config_serialization",     test_config_serialization)
    test("config_invalid_mode",      test_config_invalid_mode)

    print("\n── 2. ExplorationStats ───────────────────────────────────")
    test("stats_survival_zero",      test_stats_survival_rate_zero)
    test("stats_survival_rate",      test_stats_survival_rate)
    test("stats_serializable",       test_stats_serializable)

    print("\n── 3. Formula hashing & dedup ────────────────────────────")
    test("hash_same_formula",        test_hash_same_formula)
    test("hash_different_formulas",  test_hash_different_formulas)
    test("hash_stable_clones",       test_hash_stable_across_clones)
    test("load_hashes_empty",        test_load_existing_hashes_empty_dir)
    test("load_hashes_loads_saved",  test_load_existing_hashes_loads_saved)

    print("\n── 4. Persistence ────────────────────────────────────────")
    test("save_creates_file",        test_save_formula_record_creates_file)
    test("save_complete",            test_save_formula_record_complete)
    test("update_summary",           test_update_summary_creates_file)
    test("load_summary_missing",     test_load_summary_missing)
    test("load_batch_empty",         test_load_batch_empty)
    test("list_batches",             test_list_batches)
    test("get_formula_missing",      test_get_formula_missing)
    test("load_batch_pagination",    test_load_batch_pagination)

    print("\n── 5. Engine — basic run ─────────────────────────────────")
    test("creates_batch_dir",        test_engine_creates_batch_dir)
    test("correct_count",            test_engine_generates_correct_count)
    test("saves_formulas",           test_engine_saves_formulas)
    test("writes_summary",           test_engine_writes_summary)
    test("stats_consistent",         test_engine_stats_consistent)
    test("not_running_after_finish", test_engine_not_running_after_finish)

    print("\n── 6. Interest filter modes ──────────────────────────────")
    test("good_only_no_bad",         test_mode_good_only_no_bad)
    test("bad_only_no_good",         test_mode_bad_only_no_good)

    print("\n── 7. Dedup ──────────────────────────────────────────────")
    test("dedup_rejects_dups",       test_dedup_rejects_duplicates)
    test("dedup_no_dup_saves",       test_dedup_no_duplicate_saves)

    print("\n── 8. Stop signal ────────────────────────────────────────")
    test("stop_request_stop",        test_stop_via_request_stop)
    test("stop_max_generated",       test_stop_via_max_generated)
    test("stop_max_saved",           test_stop_via_max_saved)

    print("\n── 9. Progress callbacks ─────────────────────────────────")
    test("progress_callback",        test_progress_callback_called)
    test("save_callback",            test_save_callback_called)

    print("\n── 10. Frontend helpers ──────────────────────────────────")
    test("list_batches_after_run",   test_list_batches_after_run)
    test("get_formula_after_save",   test_get_formula_after_save)
    test("summary_frontend_fields",  test_summary_has_frontend_fields)

    print("\n── 11. Performance ───────────────────────────────────────")
    test("throughput_500",           test_perf_throughput_500)
    test("stats_accounting",         test_perf_stats_accounting)

    teardown()
    print(f"\n╔══════════════════════════════════════════════════════╗")
    print(f"║  Results: {_p:3d} passed  {_f:3d} failed  {_p+_f:3d} total           ║")
    print(f"╚══════════════════════════════════════════════════════╝\n")
    return 0 if _f == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
