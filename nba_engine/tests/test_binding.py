#!/usr/bin/env python3
"""
tests/test_binding.py — Python binding test suite
===================================================
Tests the Python <-> C interface via nba_engine.py.
Run: python3 tests/test_binding.py
"""

import sys
import os
import json
import time
import math

# Add parent dir to path so we can import nba_engine
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nba_engine_binding import (
    FormulaEngine, Formula, CDataset, CGame,
    build_dataset, build_var_registry, var_names_list,
    OP, ScoreResult,
)

# ─────────────────────────────────────────────────────────────────────────────
# TEST FRAMEWORK
# ─────────────────────────────────────────────────────────────────────────────

_passed = 0
_failed = 0

def test(name, fn):
    global _passed, _failed
    try:
        fn()
        print(f"  {'PASS':6}  {name}")
        _passed += 1
    except AssertionError as e:
        print(f"  {'FAIL':6}  {name}")
        print(f"           {e}")
        _failed += 1
    except Exception as e:
        print(f"  {'ERROR':6}  {name}")
        print(f"           {type(e).__name__}: {e}")
        _failed += 1

def approx(a, b, tol=1e-4):
    assert abs(a - b) <= tol, f"{a} != {b} (tol={tol})"

# ─────────────────────────────────────────────────────────────────────────────
# ENGINE INIT
# ─────────────────────────────────────────────────────────────────────────────

ENGINE = None

def test_engine_loads():
    global ENGINE
    ENGINE = FormulaEngine()
    assert ENGINE is not None

# ─────────────────────────────────────────────────────────────────────────────
# HELPER: build a simple synthetic dataset
# ─────────────────────────────────────────────────────────────────────────────

def make_synthetic_games(n: int, home_w_pct: float = 0.60) -> list:
    """Build n synthetic game dicts that look like real data."""
    games = []
    for i in range(n):
        won = (i / n) < home_w_pct
        home_pts = 108 + (5 if won else -3)
        away_pts = 105 + (3 if not won else -2)
        games.append({
            "meta":   {"game_id": f"test_{i:04d}", "season": "2023-24",
                       "game_number": i+1},
            "result": {"winner": "home" if won else "away",
                       "home_pts": home_pts, "away_pts": away_pts},
            "home": {
                "team_id": 1,
                "binary":  {"is_home": 1, "is_back_to_back": 0,
                             "opponent_is_back_to_back": 0},
                "context": {"match_number": i+1, "rest_days": 2,
                             "opponent_rest_days": 2, "win_streak": 1,
                             "home_win_streak": 1, "games_last_7_days": 3,
                             "days_since_last_home_game": 4,
                             "players_available": 11,
                             "km_traveled": 0, "timezone_shift": 0},
                "season_stats": {
                    "pts": home_pts, "fga": 89.0, "fg_pct": 0.465,
                    "fg3a": 34.0, "fg3_pct": 0.36, "ast": 25.0,
                    "tov": 13.5, "oreb": 9.5, "dreb": 33.0,
                    "off_rtg": 115.0 + (3 if won else -3),
                    "def_rtg": 112.0, "net_rtg": 3.0 + (3 if won else -3),
                    "pace": 99.0, "w_pct": home_w_pct, "w": int(i*home_w_pct),
                    "l": i - int(i*home_w_pct), "gp": i+1,
                    "efg_pct": 0.54, "ts_pct": 0.57,
                    "plus_minus": 3.0 if won else -2.0,
                },
                "last10_stats": None,
                "last5_stats":  None,
                "home_stats":   None,
                "away_stats":   None,
                "b2b_stats":    None,
                "vs_above500_stats": None,
                "q1_stats":  None,
                "q4_stats":  None,
                "clutch_stats": None,
                "players": [
                    {"slot": s, "archetype": "wing", "available": 1,
                     "season_avg": {
                         "gp": i+1, "minutes": 28.0 - s*2,
                         "box": {"pts": 18.0 - s*2, "reb": 4.0, "ast": 3.0,
                                 "stl": 1.0, "blk": 0.5, "tov": 1.5, "pf": 2.0,
                                 "fgm": 7.0, "fga": 14.0, "fg_pct": 0.46,
                                 "fg3m": 2.0, "fg3a": 5.0, "fg3_pct": 0.36,
                                 "ftm": 2.0, "fta": 2.5, "ft_pct": 0.80},
                         "advanced": {"efg_pct": 0.54, "ts_pct": 0.57,
                                       "usg_pct": 0.22, "bpm": 2.0, "per": 18.0,
                                       "plus_minus": 3.0, "off_rtg": 115.0,
                                       "def_rtg": 112.0, "vorp": 1.5, "ws_48": 0.12},
                         "tracking": {"drives": 5, "pull_up_pts": 4,
                                      "catch_shoot_pct": 0.38,
                                      "contested_shot_pct": 0.44,
                                      "avg_speed": 4.5},
                     },
                     "last10_avg": None, "last5_avg": None}
                    for s in range(12)
                ],
            },
            "away": {
                "team_id": 2,
                "binary":  {"is_home": 0, "is_back_to_back": 0,
                             "opponent_is_back_to_back": 0},
                "context": {"match_number": i+1, "rest_days": 2,
                             "opponent_rest_days": 2, "win_streak": -1,
                             "home_win_streak": 0, "games_last_7_days": 3,
                             "days_since_last_home_game": 5,
                             "players_available": 10,
                             "km_traveled": 1200, "timezone_shift": -2},
                "season_stats": {
                    "pts": away_pts, "fga": 88.0, "fg_pct": 0.455,
                    "fg3a": 33.0, "fg3_pct": 0.35, "ast": 24.0,
                    "tov": 14.0, "oreb": 9.2, "dreb": 32.5,
                    "off_rtg": 112.0, "def_rtg": 115.0, "net_rtg": -3.0,
                    "pace": 98.5, "w_pct": 1 - home_w_pct,
                    "w": i - int(i*home_w_pct),
                    "l": int(i*home_w_pct), "gp": i+1,
                    "efg_pct": 0.52, "ts_pct": 0.55,
                    "plus_minus": -3.0 if won else 2.0,
                },
                "last10_stats": None, "last5_stats": None,
                "home_stats": None, "away_stats": None,
                "b2b_stats": None, "vs_above500_stats": None,
                "q1_stats": None, "q4_stats": None, "clutch_stats": None,
                "players": [
                    {"slot": s, "archetype": "wing", "available": 1,
                     "season_avg": {
                         "gp": i+1, "minutes": 26.0 - s*2,
                         "box": {"pts": 16.0 - s*2, "reb": 3.5, "ast": 2.8,
                                 "stl": 0.9, "blk": 0.4, "tov": 1.6, "pf": 2.1,
                                 "fgm": 6.5, "fga": 13.5, "fg_pct": 0.45,
                                 "fg3m": 1.8, "fg3a": 5.0, "fg3_pct": 0.35,
                                 "ftm": 1.8, "fta": 2.3, "ft_pct": 0.78},
                         "advanced": {"efg_pct": 0.52, "ts_pct": 0.55,
                                       "usg_pct": 0.20, "bpm": 0.5, "per": 15.0,
                                       "plus_minus": -3.0, "off_rtg": 112.0,
                                       "def_rtg": 115.0, "vorp": 0.5, "ws_48": 0.08},
                         "tracking": {"drives": 4, "pull_up_pts": 3,
                                      "catch_shoot_pct": 0.36,
                                      "contested_shot_pct": 0.45,
                                      "avg_speed": 4.3},
                     },
                     "last10_avg": None, "last5_avg": None}
                    for s in range(12)
                ],
            },
        })
    return games

# ─────────────────────────────────────────────────────────────────────────────
# VARIABLE REGISTRY TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_registry_has_basic_stats():
    reg = build_var_registry()
    assert "season_stats.off_rtg" in reg
    assert "season_stats.net_rtg" in reg
    assert "season_stats.w_pct" in reg
    assert "binary.is_home" in reg
    assert "context.rest_days" in reg
    assert "player0.pts" in reg
    assert "player11.ws_48" in reg

def test_registry_no_duplicate_indices():
    reg = build_var_registry()
    indices = list(reg.values())
    assert len(indices) == len(set(indices)), "Duplicate indices in registry"

def test_registry_size():
    reg = build_var_registry()
    from nba_engine_binding import MAX_VARS
    assert len(reg) <= MAX_VARS, f"Registry too large: {len(reg)} > {MAX_VARS}"
    print(f"\n           (registry has {len(reg)} variables)", end="")

def test_var_names_list():
    names = var_names_list()
    assert len(names) > 0
    assert all(isinstance(n, str) for n in names)

# ─────────────────────────────────────────────────────────────────────────────
# DATASET BUILDER TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_build_dataset_small():
    games = make_synthetic_games(100)
    ds    = build_dataset(games)
    assert ds.n_games == 100
    assert ds.n_vars  > 0

def test_build_dataset_correct_results():
    games = make_synthetic_games(100, home_w_pct=0.60)
    ds    = build_dataset(games)
    home_wins = sum(1 for i in range(100) if ds.games[i].result == 1)
    assert home_wins == 60, f"Expected 60 home wins, got {home_wins}"

def test_build_dataset_off_rtg_extracted():
    games = make_synthetic_games(50)
    ds    = build_dataset(games)
    reg   = build_var_registry()
    idx   = reg["season_stats.off_rtg"]
    # Check that off_rtg is non-zero for most games
    nonzero = sum(1 for i in range(50) if ds.games[i].home[idx] > 0)
    assert nonzero >= 40, f"off_rtg was 0 for too many games ({50-nonzero}/50)"

def test_build_dataset_is_home_correct():
    games = make_synthetic_games(50)
    ds    = build_dataset(games)
    reg   = build_var_registry()
    idx   = reg["binary.is_home"]
    # Home team should have is_home=1, away team is_home=0
    all_home_correct = all(ds.games[i].home[idx] == 1.0 for i in range(50))
    all_away_correct = all(ds.games[i].away[idx] == 0.0 for i in range(50))
    assert all_home_correct, "is_home not 1.0 for home team"
    assert all_away_correct, "is_home not 0.0 for away team"

def test_build_dataset_player_stats():
    games = make_synthetic_games(30)
    ds    = build_dataset(games)
    reg   = build_var_registry()
    idx   = reg["player0.pts"]
    pts0  = ds.games[10].home[idx]
    assert pts0 > 0, f"player0.pts should be > 0, got {pts0}"

def test_build_dataset_null_stats_ok():
    """Games with None season_stats should not crash and give 0.0"""
    games = make_synthetic_games(10)
    for g in games:
        g["home"]["season_stats"] = None
    ds  = build_dataset(games)
    reg = build_var_registry()
    idx = reg["season_stats.off_rtg"]
    # All home off_rtg should be 0 when season_stats is None
    for i in range(10):
        assert ds.games[i].home[idx] == 0.0

# ─────────────────────────────────────────────────────────────────────────────
# FORMULA BUILDING TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_formula_from_ops_simple():
    f = Formula.from_ops([("CONST", 0, 42.0)])
    assert f.length == 1
    assert f._c.ops[0].op == OP["CONST"]
    approx(f._c.ops[0].value, 42.0)

def test_formula_from_ops_load():
    f = Formula.from_ops([("LOAD", 5, 0)])
    assert f._c.ops[0].op == OP["LOAD"]
    assert f._c.ops[0].var_index == 5

def test_formula_serialization():
    ops = [("LOAD", 3, 0), ("CONST", 0, 0.4), ("MUL",), ("LOAD", 7, 0), ("ADD",)]
    f   = Formula.from_ops(ops)
    d   = f.to_dict()
    f2  = Formula.from_dict(d)
    assert f2.length == 5
    assert f2._c.ops[2].op == OP["MUL"]

def test_formula_repr():
    f = Formula.from_ops([("CONST", 0, 1.0)])
    assert "Formula" in repr(f)

# ─────────────────────────────────────────────────────────────────────────────
# ENGINE EVALUATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_engine_validate_valid():
    f = Formula.from_ops([("CONST", 0, 1.0)])
    assert ENGINE.validate(f) == True

def test_engine_validate_invalid():
    f = Formula.from_ops([("ADD",)])  # ADD with nothing on stack
    assert ENGINE.validate(f) == False

def test_engine_accuracy_home_predictor():
    """Formula that always predicts home (const > 0)"""
    f     = Formula.from_ops([("CONST", 0, 1.0)])
    games = make_synthetic_games(200, home_w_pct=0.60)
    ds    = build_dataset(games)
    acc   = ENGINE.accuracy(f, ds)
    approx(acc, 0.60, tol=0.01)

def test_engine_accuracy_net_rtg():
    """net_rtg should be a decent predictor"""
    reg = build_var_registry()
    idx = reg["season_stats.net_rtg"]
    f   = Formula.from_ops([("LOAD", idx, 0)])
    games = make_synthetic_games(500, home_w_pct=0.65)
    ds    = build_dataset(games)
    acc   = ENGINE.accuracy(f, ds)
    # Better team (higher net_rtg) should win more → accuracy > 50%
    assert acc > 0.50, f"net_rtg predictor should beat random: {acc:.4f}"
    print(f"\n           (net_rtg accuracy: {acc:.4f})", end="")

def test_engine_score_result():
    f     = Formula.from_ops([("CONST", 0, 1.0)])
    games = make_synthetic_games(100, home_w_pct=0.70)
    ds    = build_dataset(games)
    score = ENGINE.score(f, ds)
    assert isinstance(score, ScoreResult)
    approx(score.accuracy, 0.70, tol=0.01)
    approx(score.interest, 0.40, tol=0.02)   # |0.70 - 0.50| * 2 = 0.40
    assert score.direction == 1
    assert score.label == "GOOD"

def test_engine_score_bad_predictor():
    """Formula with a negative LOAD (lower is better for away) → direction -1"""
    # Use LOAD var where away team has higher value → predicts away → 30% on 70% home wins
    # We need a formula where home_score < away_score consistently
    # Use NEG of a var where home > away
    reg = build_var_registry()
    idx = reg.get("season_stats.off_rtg", 0)
    # NEG(off_rtg): higher off_rtg team gets negative score → predicts away
    f = Formula.from_ops([("LOAD", idx, 0), ("NEG",)])
    games = make_synthetic_games(200, home_w_pct=0.70)
    ds    = build_dataset(games)
    score = ENGINE.score(f, ds)
    # Home has better off_rtg → NEG makes home score lower → predicts away
    # 70% home wins → ~30% correct when always predicting away
    assert score.direction == -1, f"direction should be -1, got {score.direction}"
    assert score.accuracy < 0.45, f"accuracy should be low, got {score.accuracy:.3f}"

def test_engine_filter_survives():
    f     = Formula.from_ops([("CONST", 0, 1.0)])
    games = make_synthetic_games(1000, home_w_pct=0.75)
    ds    = build_dataset(games)
    score, eliminated = ENGINE.filter(f, ds, block_size=100, min_interest=0.20)
    assert not eliminated
    approx(score.interest, 0.50, tol=0.05)  # |0.75-0.5|*2 = 0.5

def test_engine_filter_eliminated():
    """Formula with ~50% accuracy should be eliminated (interest ≈ 0)"""
    # CONST 1.0 always predicts home (diff=0 >= 0)
    # Dataset alternates win/loss → exactly 50% per block → interest=0 → eliminated
    f = Formula.from_ops([("CONST", 0, 1.0)])

    # Build alternating dataset manually so each 100-game block is exactly 50/50
    import copy
    games_alt = []
    base = make_synthetic_games(2)  # just for template
    for i in range(1000):
        g = copy.deepcopy(base[0] if i % 2 == 0 else base[1])
        # Force alternating result
        g["result"] = {"winner": "home" if i % 2 == 0 else "away",
                       "home_pts": 110, "away_pts": 108 if i%2==0 else 112}
        games_alt.append(g)

    ds = build_dataset(games_alt)
    score, eliminated = ENGINE.filter(f, ds, block_size=100, min_interest=0.10)
    assert eliminated, f"Should be eliminated (accuracy={score.accuracy:.3f}, interest={score.interest:.3f})"
    assert score.n_games_eval <= 200

# ─────────────────────────────────────────────────────────────────────────────
# PERFORMANCE TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_perf_build_dataset_10k():
    games = make_synthetic_games(5000)
    t0    = time.time()
    ds    = build_dataset(games)
    t1    = time.time()
    ms    = (t1 - t0) * 1000
    print(f"\n           ({ms:.0f}ms for 5000 games)", end="")
    assert ms < 30000, f"Dataset build took {ms:.0f}ms (max 30s)"

def test_perf_eval_1k_formulas():
    """1000 formula evaluations over 5000 games"""
    games = make_synthetic_games(5000)
    ds    = build_dataset(games)
    reg   = build_var_registry()
    idx   = reg.get("season_stats.net_rtg", 0)

    formulas = [
        Formula.from_ops([("LOAD", idx, 0)])
        for _ in range(1000)
    ]

    t0 = time.time()
    for f in formulas:
        ENGINE.accuracy(f, ds)
    t1  = time.time()
    ms  = (t1 - t0) * 1000
    per = ms / 1000
    print(f"\n           ({ms:.0f}ms total, {per:.2f}ms/formula)", end="")
    assert per < 50.0, f"Too slow: {per:.2f}ms per formula"

def test_perf_filter_throughput():
    """Throughput test: filter 500 formulas with early stopping"""
    games = make_synthetic_games(3000)
    ds    = build_dataset(games)
    reg   = build_var_registry()
    idx   = reg.get("season_stats.net_rtg", 0)

    t0 = time.time()
    survived = 0
    for i in range(500):
        # Mix of good and bad formulas
        if i % 3 == 0:
            f = Formula.from_ops([("CONST", 0, 1.0)])  # 60% → probably survives
        else:
            f = Formula.from_ops([("CONST", 0, 0.001)])  # near-tie → eliminated
        _, elim = ENGINE.filter(f, ds, block_size=100, min_interest=0.05)
        if not elim:
            survived += 1

    t1  = time.time()
    ms  = (t1 - t0) * 1000
    print(f"\n           ({ms:.0f}ms, {survived}/500 survived)", end="")
    assert ms < 30000, f"Too slow: {ms:.0f}ms"

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║   NBA Engine Python Binding — Test Suite             ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    print("── Engine init ───────────────────────────────────────────")
    test("engine_loads", test_engine_loads)

    print("\n── Variable registry ─────────────────────────────────────")
    test("registry_has_basic_stats",   test_registry_has_basic_stats)
    test("registry_no_duplicate_idx",  test_registry_no_duplicate_indices)
    test("registry_size",              test_registry_size)
    test("var_names_list",             test_var_names_list)

    print("\n── Dataset builder ───────────────────────────────────────")
    test("build_dataset_small",        test_build_dataset_small)
    test("build_dataset_results",      test_build_dataset_correct_results)
    test("build_dataset_off_rtg",      test_build_dataset_off_rtg_extracted)
    test("build_dataset_is_home",      test_build_dataset_is_home_correct)
    test("build_dataset_players",      test_build_dataset_player_stats)
    test("build_dataset_null_stats",   test_build_dataset_null_stats_ok)

    print("\n── Formula building ──────────────────────────────────────")
    test("formula_from_ops_const",     test_formula_from_ops_simple)
    test("formula_from_ops_load",      test_formula_from_ops_load)
    test("formula_serialization",      test_formula_serialization)
    test("formula_repr",               test_formula_repr)

    print("\n── Engine evaluation ─────────────────────────────────────")
    test("validate_valid",             test_engine_validate_valid)
    test("validate_invalid",           test_engine_validate_invalid)
    test("accuracy_home_predictor",    test_engine_accuracy_home_predictor)
    test("accuracy_net_rtg",           test_engine_accuracy_net_rtg)
    test("score_result",               test_engine_score_result)
    test("score_bad_predictor",        test_engine_score_bad_predictor)
    test("filter_survives",            test_engine_filter_survives)
    test("filter_eliminated",          test_engine_filter_eliminated)

    print("\n── Performance ───────────────────────────────────────────")
    test("perf_build_dataset_5k",      test_perf_build_dataset_10k)
    test("perf_eval_1k_formulas",      test_perf_eval_1k_formulas)
    test("perf_filter_throughput",     test_perf_filter_throughput)

    print(f"\n╔══════════════════════════════════════════════════════╗")
    print(f"║  Results: {_passed:3d} passed  {_failed:3d} failed"
          f"  {_passed+_failed:3d} total           ║")
    print(f"╚══════════════════════════════════════════════════════╝\n")

    return 0 if _failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
