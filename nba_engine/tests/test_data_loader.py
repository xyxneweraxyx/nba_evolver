#!/usr/bin/env python3
"""
tests/test_data_loader.py — Layer 3 test suite
===============================================
Run: python3 tests/test_data_loader.py [--data-dir ./nba_data]

Tests run in two modes:
  - With real data  (--data-dir points to generated nba_data/)
  - Without data    (synthetic fallback — most tests still run)
"""

import sys, os, time, json, tempfile, shutil, argparse
from typing import Optional, List
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import (
    DataLoader,
    list_seasons, list_season_dirs,
    load_season_games, load_split_games,
    validate_game, validate_dataset_games, validate_cdataset,
    games_to_cdataset, subset_cdataset,
    save_cache, load_cache,
)
from nba_engine_binding import get_registry, MAX_VARS, CDataset

# ── framework ─────────────────────────────────────────────────────────────────
_p = _f = _skip = 0

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

def skip(name, reason=""):
    global _skip
    print(f"  {'SKIP':6}  {name}  [{reason}]")
    _skip += 1

def eq(a, b, tol=1e-5): assert abs(float(a)-float(b))<=tol, f"{a} != {b}"

# ─────────────────────────────────────────────────────────────────────────────
# SYNTHETIC DATA BUILDER (used when no real data available)
# ─────────────────────────────────────────────────────────────────────────────

def make_game(i: int, won: bool, season: str = "2021-22") -> dict:
    return {
        "meta":   {"game_id": f"{season}_{i:04d}", "season": season,
                   "game_number": i+1, "date": "2021-12-01"},
        "result": {"winner": "home" if won else "away",
                   "home_pts": 112 if won else 105,
                   "away_pts": 105 if won else 112},
        "home": {
            "team_id": 1,
            "binary":  {"is_home": 1, "is_back_to_back": 0,
                         "opponent_is_back_to_back": 0},
            "context": {"match_number": i+1, "rest_days": 2,
                         "opponent_rest_days": 2, "win_streak": 2,
                         "home_win_streak": 1, "games_last_7_days": 3,
                         "days_since_last_home_game": 4,
                         "players_available": 11,
                         "km_traveled": 0, "timezone_shift": 0},
            "season_stats": {
                "pts": 112, "off_rtg": 116.0, "def_rtg": 112.0,
                "net_rtg": 4.0, "pace": 99.0, "w_pct": 0.62,
                "w": 40, "l": 25, "gp": 65,
            },
            **{k: None for k in ["last10_stats","last5_stats","home_stats",
               "away_stats","b2b_stats","vs_above500_stats",
               "q1_stats","q4_stats","clutch_stats"]},
            "players": [],
        },
        "away": {
            "team_id": 2,
            "binary":  {"is_home": 0, "is_back_to_back": 0,
                         "opponent_is_back_to_back": 0},
            "context": {"match_number": i+1, "rest_days": 2,
                         "opponent_rest_days": 2, "win_streak": -1,
                         "home_win_streak": 0, "games_last_7_days": 3,
                         "days_since_last_home_game": 7,
                         "players_available": 10,
                         "km_traveled": 900, "timezone_shift": -2},
            "season_stats": {
                "pts": 108, "off_rtg": 112.0, "def_rtg": 116.0,
                "net_rtg": -4.0, "pace": 98.5, "w_pct": 0.45,
                "w": 29, "l": 36, "gp": 65,
            },
            **{k: None for k in ["last10_stats","last5_stats","home_stats",
               "away_stats","b2b_stats","vs_above500_stats",
               "q1_stats","q4_stats","clutch_stats"]},
            "players": [],
        },
    }


def build_temp_data(tmpdir: str, n_per_season: int = 100):
    """Build a minimal synthetic data directory."""
    seasons = {
        "training": ["2020-21", "2021-22"],
        "testing":  ["2022-23"],
    }
    for split, season_list in seasons.items():
        for season in season_list:
            path = os.path.join(tmpdir, split, season)
            os.makedirs(path)
            for i in range(n_per_season):
                g = make_game(i, won=(i < int(n_per_season * 0.60)),
                               season=season)
                with open(os.path.join(path, f"{season}_{i:04d}.json"), "w") as f:
                    json.dump(g, f)
    return seasons

# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

TMPDIR   = None
REAL_DIR = None   # set if --data-dir provided
HAS_REAL = False

def setup(data_dir: Optional[str] = None):
    global TMPDIR, REAL_DIR, HAS_REAL
    TMPDIR = tempfile.mkdtemp(prefix="nba_test_")
    build_temp_data(TMPDIR, n_per_season=120)
    if data_dir and os.path.isdir(data_dir):
        REAL_DIR = data_dir
        HAS_REAL = True
        print(f"  (real data: {data_dir})")
    else:
        print(f"  (synthetic data only — pass --data-dir to test real data)")

def teardown():
    if TMPDIR and os.path.isdir(TMPDIR):
        shutil.rmtree(TMPDIR)

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 1: filesystem helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_list_seasons_training():
    seasons = list_seasons(TMPDIR, "training")
    assert "2020-21" in seasons
    assert "2021-22" in seasons

def test_list_seasons_testing():
    seasons = list_seasons(TMPDIR, "testing")
    assert "2022-23" in seasons

def test_list_seasons_empty_split():
    seasons = list_seasons(TMPDIR, "nonexistent")
    assert seasons == []

def test_list_season_dirs_sorted():
    dirs = list_season_dirs(TMPDIR, "training")
    assert dirs == sorted(dirs)

def test_load_season_games_count():
    games = load_season_games(TMPDIR, "training", "2021-22")
    assert len(games) == 120

def test_load_season_games_structure():
    games = load_season_games(TMPDIR, "training", "2021-22")
    g = games[0]
    assert "result" in g
    assert "home" in g
    assert "away" in g
    assert g["result"]["winner"] in ("home", "away")

def test_load_season_games_missing_raises():
    try:
        load_season_games(TMPDIR, "training", "9999-00")
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError:
        pass

def test_load_split_games_all():
    games = load_split_games(TMPDIR, "training", verbose=False)
    assert len(games) == 240  # 2 seasons × 120

def test_load_split_games_subset():
    games = load_split_games(TMPDIR, "training", seasons=["2020-21"],
                              verbose=False)
    assert len(games) == 120

def test_load_split_games_missing_season_raises():
    try:
        load_split_games(TMPDIR, "training", seasons=["9999-00"],
                          verbose=False)
        assert False
    except ValueError:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 2: validation
# ─────────────────────────────────────────────────────────────────────────────

def test_validate_game_valid():
    g = make_game(0, True)
    assert validate_game(g) == []

def test_validate_game_missing_result():
    g = make_game(0, True)
    del g["result"]
    errs = validate_game(g)
    assert any("result" in e for e in errs)

def test_validate_game_invalid_winner():
    g = make_game(0, True)
    g["result"]["winner"] = "draw"
    errs = validate_game(g)
    assert any("winner" in e for e in errs)

def test_validate_game_missing_home():
    g = make_game(0, True)
    del g["home"]
    errs = validate_game(g)
    assert len(errs) > 0

def test_validate_dataset_clean():
    games = [make_game(i, i < 60) for i in range(100)]
    report = validate_dataset_games(games)
    assert report["total"] == 100
    assert report["invalid"] == 0
    eq(report["home_win_pct"], 0.60, tol=0.01)

def test_validate_dataset_with_errors():
    games  = [make_game(i, True) for i in range(50)]
    bad    = make_game(99, True)
    del bad["result"]
    games.append(bad)
    report = validate_dataset_games(games)
    assert report["invalid"] == 1
    assert len(report["sample_errors"]) == 1

def test_validate_cdataset_clean():
    games  = [make_game(i, i < 60) for i in range(100)]
    ds     = games_to_cdataset(games)
    reg    = get_registry()
    report = validate_cdataset(ds, reg)
    assert report["ok"], f"Unexpected issues: {report['issues']}"

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 3: CDataset building
# ─────────────────────────────────────────────────────────────────────────────

def test_games_to_cdataset_count():
    games = [make_game(i, True) for i in range(200)]
    ds    = games_to_cdataset(games)
    assert ds.n_games == 200

def test_games_to_cdataset_results():
    games = [make_game(i, i < 60) for i in range(100)]
    ds    = games_to_cdataset(games)
    home_wins = sum(1 for i in range(100) if ds.games[i].result == 1)
    assert home_wins == 60

def test_games_to_cdataset_stat_extracted():
    games = [make_game(0, True)]
    ds    = games_to_cdataset(games)
    reg   = get_registry()
    idx   = reg["season_stats.net_rtg"]
    # Home team net_rtg = 4.0
    eq(ds.games[0].home[idx], 4.0, tol=0.01)

def test_games_to_cdataset_is_home():
    games = [make_game(0, True)]
    ds    = games_to_cdataset(games)
    reg   = get_registry()
    idx   = reg["binary.is_home"]
    assert ds.games[0].home[idx] == 1.0
    assert ds.games[0].away[idx] == 0.0

def test_subset_cdataset():
    games = [make_game(i, True) for i in range(500)]
    ds    = games_to_cdataset(games)
    sub   = subset_cdataset(ds, 100)
    assert sub.n_games == 100
    # Original unchanged
    assert ds.n_games == 500

def test_subset_clamps_to_max():
    games = [make_game(i, True) for i in range(100)]
    ds    = games_to_cdataset(games)
    sub   = subset_cdataset(ds, 9999)
    assert sub.n_games == 100   # clamped to actual n_games

def test_subset_min_one():
    games = [make_game(i, True) for i in range(50)]
    ds    = games_to_cdataset(games)
    sub   = subset_cdataset(ds, 0)
    assert sub.n_games == 1

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 4: disk cache
# ─────────────────────────────────────────────────────────────────────────────

def test_save_load_cache_roundtrip():
    games = [make_game(i, i < 60) for i in range(100)]
    ds    = games_to_cdataset(games)
    save_cache(ds, games, TMPDIR, "training", ["2021-22"])
    ds2   = load_cache(TMPDIR, "training", ["2021-22"])
    assert ds2 is not None
    assert ds2.n_games == ds.n_games
    assert ds2.n_vars  == ds.n_vars

def test_load_cache_missing_returns_none():
    result = load_cache(TMPDIR, "training", ["9999-00"])
    assert result is None

def test_cache_preserves_stats():
    games = [make_game(0, True)]
    ds    = games_to_cdataset(games)
    reg   = get_registry()
    idx   = reg["season_stats.net_rtg"]
    orig  = ds.games[0].home[idx]
    save_cache(ds, games, TMPDIR, "testing", ["2022-23"])
    ds2   = load_cache(TMPDIR, "testing", ["2022-23"])
    assert ds2 is not None
    eq(ds2.games[0].home[idx], orig, tol=0.01)

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 5: DataLoader class
# ─────────────────────────────────────────────────────────────────────────────

def test_loader_get_training():
    loader = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    ds     = loader.get_training()
    assert ds.n_games == 240

def test_loader_get_testing():
    loader = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    ds     = loader.get_testing()
    assert ds.n_games == 120

def test_loader_get_season():
    loader = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    ds     = loader.get_season("2021-22")
    assert ds.n_games == 120

def test_loader_get_subset():
    loader = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    ds     = loader.get_subset(50)
    assert ds.n_games == 50

def test_loader_memory_cache_hit():
    loader = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    ds1    = loader.get_training()
    t0     = time.time()
    ds2    = loader.get_training()   # should be instant from cache
    ms     = (time.time()-t0)*1000
    assert ds1 is ds2                # same object
    assert ms < 10, f"Cache hit took {ms:.1f}ms (should be <10ms)"

def test_loader_disk_cache():
    loader = DataLoader(TMPDIR, use_disk_cache=True, verbose=False)
    # First load: build + save
    ds1 = loader.get_testing()
    # Clear memory cache, reload from disk
    loader.clear_memory_cache()
    ds2 = loader.get_testing()
    assert ds1.n_games == ds2.n_games

def test_loader_available_seasons():
    loader   = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    seasons  = loader.available_seasons("training")
    assert "2020-21" in seasons
    assert "2021-22" in seasons

def test_loader_info():
    loader = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    info   = loader.info()
    assert "training" in info
    assert "testing"  in info
    assert info["training"]["total_games"] == 240
    assert info["testing"]["total_games"]  == 120

def test_loader_validate():
    loader = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    report = loader.validate("training")
    assert report["json"]["invalid"] == 0
    assert report["cdataset"]["ok"]

def test_loader_clear_disk_cache():
    loader = DataLoader(TMPDIR, use_disk_cache=True, verbose=False)
    loader.get_training()   # creates cache file
    loader.clear_disk_cache()
    # After clearing, disk cache should be gone
    result = load_cache(TMPDIR, "training", None)
    assert result is None

def test_loader_unknown_season_raises():
    loader = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    try:
        loader.get_season("9999-00")
        assert False
    except ValueError:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 6: Integration with C engine
# ─────────────────────────────────────────────────────────────────────────────

def test_integration_accuracy_on_loaded_data():
    """Load data and evaluate a formula — should give plausible accuracy."""
    from nba_engine_binding import FormulaEngine
    from formula_engine import VarNode, ast_to_c_formula

    engine = FormulaEngine()
    loader = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    ds     = loader.get_training()
    reg    = get_registry()

    idx  = reg["season_stats.net_rtg"]
    f    = VarNode("season_stats.net_rtg", idx)
    cf   = ast_to_c_formula(f)
    acc  = engine.accuracy(cf, ds)

    # net_rtg should do better than random on our synthetic data
    assert 0.50 < acc < 1.0, f"Unexpected accuracy: {acc:.4f}"

def test_integration_subset_consistent():
    """Subset of dataset should give same accuracy direction as full."""
    from nba_engine_binding import FormulaEngine
    from formula_engine import VarNode, ast_to_c_formula

    engine = FormulaEngine()
    loader = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    full   = loader.get_training()
    sub    = loader.get_subset(50)
    reg    = get_registry()

    idx    = reg["season_stats.net_rtg"]
    cf     = ast_to_c_formula(VarNode("season_stats.net_rtg", idx))

    acc_full = engine.accuracy(cf, full)
    acc_sub  = engine.accuracy(cf, sub)

    # Both should be above 0.5 (net_rtg is predictive in synthetic data)
    assert acc_full > 0.5
    assert acc_sub  > 0.5

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 7: Performance
# ─────────────────────────────────────────────────────────────────────────────

def test_perf_load_240_games():
    t0    = time.time()
    games = load_split_games(TMPDIR, "training", verbose=False)
    ms    = (time.time()-t0)*1000
    print(f"\n           ({ms:.0f}ms for {len(games)} games)", end="")
    assert ms < 5000

def test_perf_build_cdataset_240():
    games = load_split_games(TMPDIR, "training", verbose=False)
    t0    = time.time()
    ds    = games_to_cdataset(games)
    ms    = (time.time()-t0)*1000
    print(f"\n           ({ms:.0f}ms build, {ds.n_games} games)", end="")
    assert ms < 30000

def test_perf_subset_instant():
    loader = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    full   = loader.get_training()
    t0     = time.time()
    for _ in range(10):   # realistic: called a few times at startup, not 100
        subset_cdataset(full, 50)
    ms = (time.time()-t0)*1000
    print(f"\n           ({ms:.1f}ms for 10 subsets, {ms/10:.1f}ms each)", end="")
    assert ms < 2000  # 200ms per subset is acceptable for a 128MB struct

def test_perf_cache_hit_speed():
    loader = DataLoader(TMPDIR, use_disk_cache=False, verbose=False)
    loader.get_training()  # warm cache
    t0 = time.time()
    for _ in range(1000):
        loader.get_training()
    ms = (time.time()-t0)*1000
    print(f"\n           ({ms:.1f}ms for 1000 cache hits, {ms/1000:.3f}ms each)", end="")
    assert ms < 100

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 8: Real data tests (only if --data-dir provided)
# ─────────────────────────────────────────────────────────────────────────────

def test_real_data_seasons_exist():
    if not HAS_REAL: skip("real_seasons_exist", "no --data-dir"); return
    loader  = DataLoader(REAL_DIR, use_disk_cache=False, verbose=False)
    seasons = loader.available_seasons("training")
    assert len(seasons) >= 6, f"Expected >= 6 training seasons, got {seasons}"

def test_real_data_home_win_pct():
    if not HAS_REAL: skip("real_home_win_pct", "no --data-dir"); return
    games  = load_split_games(REAL_DIR, "training", verbose=False)
    report = validate_dataset_games(games)
    hw     = report["home_win_pct"]
    assert 0.55 <= hw <= 0.65, f"Home win % {hw:.3f} out of expected range [0.55, 0.65]"
    print(f"\n           (home win%: {hw:.3f})", end="")

def test_real_data_no_invalid_games():
    if not HAS_REAL: skip("real_no_invalid", "no --data-dir"); return
    games  = load_split_games(REAL_DIR, "training", verbose=False)
    report = validate_dataset_games(games)
    rate   = report["error_rate"]
    assert rate < 0.01, f"Error rate {rate:.3%} too high"

def test_real_data_build_training():
    if not HAS_REAL: skip("real_build_training", "no --data-dir"); return
    loader = DataLoader(REAL_DIR, use_disk_cache=False, verbose=False)
    t0     = time.time()
    ds     = loader.get_training()
    ms     = (time.time()-t0)*1000
    print(f"\n           ({ms:.0f}ms, {ds.n_games:,} games)", end="")
    assert ds.n_games > 5000

def test_real_data_net_rtg_predictive():
    if not HAS_REAL: skip("real_net_rtg_pred", "no --data-dir"); return
    from nba_engine_binding import FormulaEngine
    from formula_engine import VarNode, ast_to_c_formula
    engine = FormulaEngine()
    loader = DataLoader(REAL_DIR, use_disk_cache=False, verbose=False)
    ds     = loader.get_training()
    reg    = get_registry()
    idx    = reg["season_stats.net_rtg"]
    cf     = ast_to_c_formula(VarNode("season_stats.net_rtg", idx))
    acc    = engine.accuracy(cf, ds)
    print(f"\n           (net_rtg accuracy on real data: {acc:.4f})", end="")
    assert acc > 0.55, f"net_rtg should be predictive, got {acc:.4f}"

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

from typing import Optional, List

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None,
                        help="Path to real nba_data/ (optional)")
    args = parser.parse_args()

    setup(args.data_dir)

    print("\n╔══════════════════════════════════════════════════════╗")
    print("║   Layer 3 — Data Loader Test Suite                  ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    print("── 1. Filesystem helpers ─────────────────────────────────")
    test("list_seasons_training",       test_list_seasons_training)
    test("list_seasons_testing",        test_list_seasons_testing)
    test("list_seasons_empty",          test_list_seasons_empty_split)
    test("list_season_dirs_sorted",     test_list_season_dirs_sorted)
    test("load_season_count",           test_load_season_games_count)
    test("load_season_structure",       test_load_season_games_structure)
    test("load_season_missing_raises",  test_load_season_games_missing_raises)
    test("load_split_all",              test_load_split_games_all)
    test("load_split_subset",           test_load_split_games_subset)
    test("load_split_missing_raises",   test_load_split_games_missing_season_raises)

    print("\n── 2. Validation ─────────────────────────────────────────")
    test("validate_game_valid",         test_validate_game_valid)
    test("validate_game_no_result",     test_validate_game_missing_result)
    test("validate_game_bad_winner",    test_validate_game_invalid_winner)
    test("validate_game_no_home",       test_validate_game_missing_home)
    test("validate_dataset_clean",      test_validate_dataset_clean)
    test("validate_dataset_errors",     test_validate_dataset_with_errors)
    test("validate_cdataset_clean",     test_validate_cdataset_clean)

    print("\n── 3. CDataset building ──────────────────────────────────")
    test("cdataset_count",              test_games_to_cdataset_count)
    test("cdataset_results",            test_games_to_cdataset_results)
    test("cdataset_stat_extracted",     test_games_to_cdataset_stat_extracted)
    test("cdataset_is_home",            test_games_to_cdataset_is_home)
    test("subset_cdataset",             test_subset_cdataset)
    test("subset_clamps_max",           test_subset_clamps_to_max)
    test("subset_min_one",              test_subset_min_one)

    print("\n── 4. Disk cache ─────────────────────────────────────────")
    test("cache_roundtrip",             test_save_load_cache_roundtrip)
    test("cache_missing_none",          test_load_cache_missing_returns_none)
    test("cache_preserves_stats",       test_cache_preserves_stats)

    print("\n── 5. DataLoader class ───────────────────────────────────")
    test("loader_training",             test_loader_get_training)
    test("loader_testing",              test_loader_get_testing)
    test("loader_season",               test_loader_get_season)
    test("loader_subset",               test_loader_get_subset)
    test("loader_memory_cache",         test_loader_memory_cache_hit)
    test("loader_disk_cache",           test_loader_disk_cache)
    test("loader_available_seasons",    test_loader_available_seasons)
    test("loader_info",                 test_loader_info)
    test("loader_validate",             test_loader_validate)
    test("loader_clear_disk_cache",     test_loader_clear_disk_cache)
    test("loader_unknown_season",       test_loader_unknown_season_raises)

    print("\n── 6. Integration with C engine ──────────────────────────")
    test("integration_accuracy",        test_integration_accuracy_on_loaded_data)
    test("integration_subset",          test_integration_subset_consistent)

    print("\n── 7. Performance ────────────────────────────────────────")
    test("perf_load_json",              test_perf_load_240_games)
    test("perf_build_cdataset",         test_perf_build_cdataset_240)
    test("perf_subset_instant",         test_perf_subset_instant)
    test("perf_cache_hit",              test_perf_cache_hit_speed)

    print("\n── 8. Real data ──────────────────────────────────────────")
    test("real_seasons_exist",          test_real_data_seasons_exist)
    test("real_home_win_pct",           test_real_data_home_win_pct)
    test("real_no_invalid_games",       test_real_data_no_invalid_games)
    test("real_build_training",         test_real_data_build_training)
    test("real_net_rtg_predictive",     test_real_data_net_rtg_predictive)

    teardown()

    total = _p + _f + _skip
    print(f"\n╔══════════════════════════════════════════════════════╗")
    print(f"║  Results: {_p:3d} passed  {_f:3d} failed  "
          f"{_skip:3d} skipped  {total:3d} total  ║")
    print(f"╚══════════════════════════════════════════════════════╝\n")
    return 0 if _f == 0 else 1

if __name__ == "__main__":
    sys.exit(main())