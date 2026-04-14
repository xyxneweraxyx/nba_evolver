"""
formula_dashboard.py — Formula situational evaluation
======================================================
Evaluates a formula on training + testing datasets and
returns a full situational breakdown for the dashboard.

All filtering is done in Python after a single C-level evaluation pass,
so the total cost is: 1 C eval (fast) + 1 Python loop per dataset.
"""

from __future__ import annotations

import ctypes
from typing import Optional

from nba_engine_binding import FormulaEngine, get_registry
from formula_engine import node_from_dict, ast_to_c_formula
from data_loader import DataLoader


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_predictions(engine: FormulaEngine, cf, ds) -> list:
    """Evaluate formula on full dataset, return list of int predictions."""
    n        = ds.n_games
    pred_arr = (ctypes.c_int * n)()
    engine._lib.nba_eval_dataset(
        ctypes.byref(cf._c),
        ctypes.byref(ds),
        pred_arr,
    )
    return list(pred_arr[:n])


def _acc(preds: list, results: list, indices: list) -> Optional[dict]:
    """Compute accuracy stats for a subset of game indices."""
    if not indices:
        return None
    n       = len(indices)
    correct = sum(1 for i in indices if preds[i] == results[i])
    return {
        "accuracy":  round(correct / n, 4),
        "n_games":   n,
        "n_correct": correct,
    }


def _read_col(ds, reg: dict, key: str, side: str = "home") -> list:
    """Read one registry variable for all games, home or away side."""
    idx = reg.get(key, -1)
    if idx < 0:
        return [0.0] * ds.n_games
    if side == "home":
        return [ds.games[i].home[idx] for i in range(ds.n_games)]
    else:
        return [ds.games[i].away[idx] for i in range(ds.n_games)]


# ─────────────────────────────────────────────────────────────────────────────
# CORE EVALUATION
# ─────────────────────────────────────────────────────────────────────────────

def _evaluate_dataset(engine: FormulaEngine, cf, ds, reg: dict) -> dict:
    """Full situational breakdown for one dataset."""
    n = ds.n_games
    if n == 0:
        return None

    # ── Single C-level pass ──────────────────────────────────────────────────
    preds   = _get_predictions(engine, cf, ds)
    results = [ds.games[i].result for i in range(n)]

    # ── Context columns ──────────────────────────────────────────────────────
    home_b2b    = _read_col(ds, reg, "binary.is_back_to_back",           "home")
    away_b2b    = _read_col(ds, reg, "binary.is_back_to_back",           "away")
    opp_b2b     = _read_col(ds, reg, "binary.opponent_is_back_to_back",  "home")
    home_rest   = _read_col(ds, reg, "context.rest_days",                "home")
    away_rest   = _read_col(ds, reg, "context.rest_days",                "away")
    match_num   = _read_col(ds, reg, "context.match_number",             "home")
    home_streak = _read_col(ds, reg, "context.win_streak",               "home")
    home_wpct   = _read_col(ds, reg, "season_stats.w_pct",              "home")
    away_wpct   = _read_col(ds, reg, "season_stats.w_pct",              "away")
    km_away     = _read_col(ds, reg, "context.km_traveled",              "away")
    gp_home     = _read_col(ds, reg, "season_stats.gp",                 "home")

    all_idx = list(range(n))

    # ── Overall ──────────────────────────────────────────────────────────────
    overall = _acc(preds, results, all_idx)

    # Baseline: always predict home
    home_wins = sum(results)
    baseline  = round(home_wins / n, 4)

    # ── Prediction distribution ──────────────────────────────────────────────
    n_pred_home   = sum(preds)
    n_pred_away   = n - n_pred_home
    corr_home     = sum(1 for i in all_idx if preds[i] == 1 and results[i] == 1)
    corr_away     = sum(1 for i in all_idx if preds[i] == 0 and results[i] == 0)
    pred_dist = {
        "n_predict_home":              n_pred_home,
        "n_predict_away":              n_pred_away,
        "pct_predict_home":            round(n_pred_home / n, 4),
        "accuracy_when_predict_home":  round(corr_home / max(1, n_pred_home), 4),
        "accuracy_when_predict_away":  round(corr_away / max(1, n_pred_away), 4),
    }

    # ── Situational filters ──────────────────────────────────────────────────
    situations = {
        "Home team B2B":              [i for i in all_idx if home_b2b[i]  > 0.5],
        "Away team B2B":              [i for i in all_idx if away_b2b[i]  > 0.5],
        "Neither team B2B":           [i for i in all_idx if home_b2b[i]  < 0.5 and away_b2b[i] < 0.5],
        "Home rested (2d+)":          [i for i in all_idx if home_rest[i] >= 2],
        "Away rested (2d+)":          [i for i in all_idx if away_rest[i] >= 2],
        "vs above .500 opponent":     [i for i in all_idx if away_wpct[i] >= 0.500],
        "vs below .500 opponent":     [i for i in all_idx if away_wpct[i] <  0.500],
        "Home team strong (60%+)":    [i for i in all_idx if home_wpct[i] >= 0.600],
        "Home team weak (<40%)":      [i for i in all_idx if home_wpct[i] <  0.400],
        "Home win streak (3+)":       [i for i in all_idx if home_streak[i] >= 3],
        "Home losing streak (3+)":    [i for i in all_idx if home_streak[i] <= -3],
        "High travel away (800km+)":  [i for i in all_idx if km_away[i]   > 800],
        "Short trip away (<800km)":   [i for i in all_idx if 0 < km_away[i] <= 800],
        "Away team at home (<1km)":   [i for i in all_idx if km_away[i]   < 1],
    }
    situational = {}
    for label, indices in situations.items():
        situational[label] = _acc(preds, results, indices)

    # ── Season slices ────────────────────────────────────────────────────────
    slices = [
        ("Early (1–20)",   1,  20),
        ("Mid (21–60)",   21,  60),
        ("Late (61–82)",  61, 999),
    ]
    by_season_slice = []
    for s_label, lo, hi in slices:
        idx = [i for i in all_idx if lo <= match_num[i] <= hi]
        r   = _acc(preds, results, idx)
        if r:
            by_season_slice.append({"label": s_label, **r})

    # ── Rest days breakdown ──────────────────────────────────────────────────
    rest_buckets = [
        ("B2B (0 days)",  0, 0),
        ("1 day rest",    1, 1),
        ("2 days rest",   2, 2),
        ("3+ days rest",  3, 99),
    ]
    by_rest = []
    for r_label, lo, hi in rest_buckets:
        idx = [i for i in all_idx if lo <= home_rest[i] <= hi]
        r   = _acc(preds, results, idx)
        if r:
            by_rest.append({"label": r_label, **r})

    # ── Home/away record breakdown ───────────────────────────────────────────
    # True home wins vs predicted home wins
    true_home = [i for i in all_idx if results[i] == 1]
    true_away = [i for i in all_idx if results[i] == 0]
    by_true_result = {
        "true_home_wins": _acc(preds, results, true_home),
        "true_away_wins": _acc(preds, results, true_away),
    }

    return {
        "overall":         overall,
        "baseline":        baseline,
        "situational":     situational,
        "by_season_slice": by_season_slice,
        "by_rest":         by_rest,
        "by_true_result":  by_true_result,
        "pred_dist":       pred_dist,
        "n_games":         n,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_formula_dashboard(tree: dict, loader: DataLoader) -> dict:
    """
    Full situational evaluation of a formula on training + testing datasets.

    Args:
        tree:   formula AST dict (as stored in formula JSON files)
        loader: DataLoader instance (already initialized)

    Returns:
        dict with keys: formula_repr, train, test, formula_size, formula_depth
    """
    engine = FormulaEngine()
    reg    = get_registry()

    # Compile
    node = node_from_dict(tree)
    cf   = ast_to_c_formula(node)
    if cf is None or not engine.validate(cf):
        raise ValueError("Formula does not compile to a valid C formula")

    # Evaluate
    ds_train = loader.get_training()
    train    = _evaluate_dataset(engine, cf, ds_train, reg)

    test = None
    try:
        ds_test = loader.get_testing()
        if ds_test.n_games > 0:
            test = _evaluate_dataset(engine, cf, ds_test, reg)
    except Exception:
        pass  # no test data — fine

    return {
        "formula_repr":  repr(node),
        "formula_size":  node.size(),
        "formula_depth": node.depth(),
        "train":         train,
        "test":          test,
    }