"""
nba_engine.py — Python binding for the C formula engine
=========================================================
Loads nba_engine.so via ctypes and exposes a clean Python API.

Usage:
    from nba_engine import FormulaEngine, Formula, Dataset, build_dataset

    engine  = FormulaEngine()           # loads the .so
    ds      = build_dataset(games)      # list of JSON game dicts
    formula = Formula.from_ops([...])   # list of (opcode, var_idx, value)
    score   = engine.score(formula, ds)
    print(score.accuracy, score.interest)
"""

import ctypes
import os
import json
import struct
from typing import List, Optional, Tuple
from dataclasses import dataclass

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS (must match nba_formula.h)
# ─────────────────────────────────────────────────────────────────────────────

MAX_FORMULA_OPS = 256
MAX_STACK_DEPTH = 64
MAX_VARS        = 800
MAX_GAMES       = 20000

# Opcodes
OP = {
    "LOAD":    0,
    "CONST":   1,
    "ADD":     2,
    "SUB":     3,
    "MUL":     4,
    "DIV":     5,
    "MAX2":    6,
    "MIN2":    7,
    "POW":     8,
    "NEG":     9,
    "ABS":     10,
    "LOG":     11,
    "SQRT":    12,
    "SQ":      13,
    "INV":     14,
    "IF_GT":   15,
    "IF_LT":   16,
    "IF_GTE":  17,
    "IF_LTE":  18,
}
OP_NAMES = {v: k for k, v in OP.items()}

# ─────────────────────────────────────────────────────────────────────────────
# CTYPES STRUCTURES (must match C structs exactly)
# ─────────────────────────────────────────────────────────────────────────────

class CInstruction(ctypes.Structure):
    # NO _pack_ — let the compiler pad naturally (matches C: 8 bytes)
    # Layout: op(1) + pad(1) + var_index(2) + value(4) = 8 bytes
    _fields_ = [
        ("op",        ctypes.c_uint8),
        ("var_index", ctypes.c_uint16),
        ("value",     ctypes.c_float),
    ]

class CFormula(ctypes.Structure):
    _fields_ = [
        ("ops",    CInstruction * MAX_FORMULA_OPS),
        ("length", ctypes.c_int),
    ]

class CGame(ctypes.Structure):
    _fields_ = [
        ("home",   ctypes.c_float * MAX_VARS),
        ("away",   ctypes.c_float * MAX_VARS),
        ("result", ctypes.c_int),
    ]

class CDataset(ctypes.Structure):
    _fields_ = [
        ("games",   CGame * MAX_GAMES),
        ("n_games", ctypes.c_int),
        ("n_vars",  ctypes.c_int),
    ]

class CFormulaScore(ctypes.Structure):
    _fields_ = [
        ("accuracy",      ctypes.c_double),
        ("interest",      ctypes.c_double),
        ("n_games_eval",  ctypes.c_int),
        ("direction",     ctypes.c_int),
    ]

# ─────────────────────────────────────────────────────────────────────────────
# VARIABLE REGISTRY — maps stat name → flat index
# ─────────────────────────────────────────────────────────────────────────────

def build_var_registry() -> dict:
    """
    Builds the mapping {variable_name: index} for all stats
    we extract from the game JSON snapshots.
    Each team has its own namespace (home/away handled at dataset build time).
    """
    registry = {}
    idx = 0

    def reg(name: str):
        nonlocal idx
        if name not in registry:
            registry[name] = idx
            idx += 1

    # Binary context
    for k in ["is_home", "is_back_to_back", "opponent_is_back_to_back"]:
        reg(f"binary.{k}")

    # Context
    for k in ["match_number", "rest_days", "opponent_rest_days", "win_streak",
              "home_win_streak", "games_last_7_days", "days_since_last_home_game",
              "players_available", "km_traveled", "timezone_shift"]:
        reg(f"context.{k}")

    # Main stat keys
    MAIN_KEYS = [
        "pts", "fgm", "fga", "fg_pct", "fg3m", "fg3a", "fg3_pct",
        "ftm", "fta", "ft_pct", "oreb", "dreb", "reb",
        "ast", "tov", "stl", "blk", "blka", "pf", "pfd",
        "plus_minus", "ast_tov_ratio",
        "off_rtg", "def_rtg", "net_rtg", "pace",
        "efg_pct", "ts_pct", "oreb_pct", "dreb_pct", "ast_pct", "tov_pct", "pie",
        "pitp", "pts_2nd_chance", "pts_fb", "pts_off_tov",
        "drives", "catch_shoot_pct", "pull_up_shot_pct",
        "elbow_touch_pts", "post_touch_pts", "paint_touch_pts",
        "dist_miles", "dist_miles_off", "dist_miles_def",
        "avg_speed", "avg_speed_off", "avg_speed_def",
        "contested_shots", "contested_shots_2pt", "contested_shots_3pt",
        "deflections", "charges_drawn", "screen_asts", "screen_ast_pts",
        "loose_balls_recovered", "off_boxouts", "def_boxouts", "box_outs",
        "threep_dfgpct", "twop_dfgpct", "def_rim_pct",
        "w", "l", "w_pct", "gp",
    ]

    SPLITS = ["season_stats", "last10_stats", "last5_stats",
              "home_stats", "away_stats", "b2b_stats", "vs_above500_stats"]

    for split in SPLITS:
        for k in MAIN_KEYS:
            reg(f"{split}.{k}")

    # Quarter / clutch stats
    Q_KEYS = ["pts", "fgm", "fga", "fg_pct", "fg3m", "fg3a", "ast", "ftm", "fta"]
    for split in ["q1_stats", "q4_stats"]:
        for k in Q_KEYS:
            reg(f"{split}.{k}")

    CLUTCH_KEYS = ["pts", "fgm", "fga", "fg_pct", "fg3m", "fg3a",
                   "ftm", "fta", "ast", "tov", "plus_minus", "w_pct"]
    for k in CLUTCH_KEYS:
        reg(f"clutch_stats.{k}")

    # Player slots (season_avg only — 12 slots × key stats)
    P_KEYS = ["pts", "reb", "ast", "stl", "blk", "tov",
              "fg_pct", "fg3_pct", "ft_pct", "minutes",
              "bpm", "per", "usg_pct", "off_rtg", "def_rtg", "vorp", "ws_48"]
    for slot in range(12):
        for k in P_KEYS:
            reg(f"player{slot}.{k}")

    return registry

# Singleton registry
_VAR_REGISTRY: Optional[dict] = None

def get_registry() -> dict:
    global _VAR_REGISTRY
    if _VAR_REGISTRY is None:
        _VAR_REGISTRY = build_var_registry()
    return _VAR_REGISTRY

def var_names_list() -> List[str]:
    reg = get_registry()
    return [name for name, _ in sorted(reg.items(), key=lambda x: x[1])]

# ─────────────────────────────────────────────────────────────────────────────
# DATASET BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _nav(obj: dict, path: str, default: float = 0.0) -> float:
    """Navigate a nested dict using dot notation, return float."""
    if obj is None:
        return default
    parts = path.split(".", 1)
    if len(parts) == 1:
        v = obj.get(parts[0], default)
        if v is None:
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default
    sub = obj.get(parts[0])
    if not isinstance(sub, dict):
        return default
    return _nav(sub, parts[1], default)

def _extract_team_stats(team: dict, registry: dict) -> List[float]:
    """Extract all variables from a team snapshot into a flat float array."""
    arr = [0.0] * MAX_VARS

    # Binary
    binary = team.get("binary", {})
    for k in ["is_home", "is_back_to_back", "opponent_is_back_to_back"]:
        key = f"binary.{k}"
        if key in registry:
            arr[registry[key]] = float(binary.get(k, 0))

    # Context
    context = team.get("context", {})
    for k in ["match_number", "rest_days", "opponent_rest_days", "win_streak",
              "home_win_streak", "games_last_7_days", "days_since_last_home_game",
              "players_available", "km_traveled", "timezone_shift"]:
        key = f"context.{k}"
        if key in registry:
            arr[registry[key]] = float(context.get(k, 0) or 0)

    # Stat splits
    SPLITS = ["season_stats", "last10_stats", "last5_stats",
              "home_stats", "away_stats", "b2b_stats", "vs_above500_stats"]
    MAIN_KEYS = [
        "pts","fgm","fga","fg_pct","fg3m","fg3a","fg3_pct",
        "ftm","fta","ft_pct","oreb","dreb","reb",
        "ast","tov","stl","blk","blka","pf","pfd","plus_minus","ast_tov_ratio",
        "off_rtg","def_rtg","net_rtg","pace",
        "efg_pct","ts_pct","oreb_pct","dreb_pct","ast_pct","tov_pct","pie",
        "pitp","pts_2nd_chance","pts_fb","pts_off_tov",
        "drives","catch_shoot_pct","pull_up_shot_pct",
        "elbow_touch_pts","post_touch_pts","paint_touch_pts",
        "dist_miles","dist_miles_off","dist_miles_def",
        "avg_speed","avg_speed_off","avg_speed_def",
        "contested_shots","contested_shots_2pt","contested_shots_3pt",
        "deflections","charges_drawn","screen_asts","screen_ast_pts",
        "loose_balls_recovered","off_boxouts","def_boxouts","box_outs",
        "threep_dfgpct","twop_dfgpct","def_rim_pct",
        "w","l","w_pct","gp",
    ]
    for split in SPLITS:
        sdata = team.get(split) or {}
        for k in MAIN_KEYS:
            key = f"{split}.{k}"
            if key in registry:
                arr[registry[key]] = float(sdata.get(k, 0) or 0)

    # Quarter/clutch
    Q_KEYS = ["pts","fgm","fga","fg_pct","fg3m","fg3a","ast","ftm","fta"]
    for split in ["q1_stats", "q4_stats"]:
        sdata = team.get(split) or {}
        for k in Q_KEYS:
            key = f"{split}.{k}"
            if key in registry:
                arr[registry[key]] = float(sdata.get(k, 0) or 0)

    CLUTCH_KEYS = ["pts","fgm","fga","fg_pct","fg3m","fg3a",
                   "ftm","fta","ast","tov","plus_minus","w_pct"]
    cdata = team.get("clutch_stats") or {}
    for k in CLUTCH_KEYS:
        key = f"clutch_stats.{k}"
        if key in registry:
            arr[registry[key]] = float(cdata.get(k, 0) or 0)

    # Players (season_avg only)
    P_KEYS = ["pts","reb","ast","stl","blk","tov",
              "fg_pct","fg3_pct","ft_pct","minutes",
              "bpm","per","usg_pct","off_rtg","def_rtg","vorp","ws_48"]
    players = team.get("players", [])
    for pe in players:
        slot = pe.get("slot", 0)
        if slot >= 12:
            continue
        avg = pe.get("season_avg") or {}
        for k in P_KEYS:
            key = f"player{slot}.{k}"
            if key not in registry:
                continue
            # Navigate box/advanced/tracking
            val = 0.0
            if k == "minutes":
                val = float(avg.get("minutes", 0) or 0)
            else:
                for section in ("box", "advanced", "tracking"):
                    sec = avg.get(section, {})
                    if isinstance(sec, dict) and k in sec:
                        val = float(sec[k] or 0)
                        break
            arr[registry[key]] = val

    return arr

def build_dataset(games: List[dict]) -> "CDataset":
    """
    Convert a list of game JSON dicts into a CDataset ready for C evaluation.
    """
    reg = get_registry()
    n   = min(len(games), MAX_GAMES)

    ds = CDataset()
    ds.n_games = n
    ds.n_vars  = len(reg)

    for i, g in enumerate(games[:n]):
        home_arr = _extract_team_stats(g["home"], reg)
        away_arr = _extract_team_stats(g["away"], reg)
        result   = 1 if g["result"]["winner"] == "home" else 0

        game = ds.games[i]
        for j, v in enumerate(home_arr):
            game.home[j] = v
        for j, v in enumerate(away_arr):
            game.away[j] = v
        game.result = result

    return ds

def load_games_from_dir(data_dir: str, split: str = "training") -> List[dict]:
    """Load all game JSONs from data_dir/{split}/"""
    import glob
    pattern = os.path.join(data_dir, split, "**", "*.json")
    files   = sorted(glob.glob(pattern, recursive=True))
    games   = []
    for fp in files:
        with open(fp) as f:
            games.append(json.load(f))
    return games

# ─────────────────────────────────────────────────────────────────────────────
# FORMULA PYTHON WRAPPER
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScoreResult:
    accuracy:     float
    interest:     float
    n_games_eval: int
    direction:    int   # +1 good, -1 bad

    @property
    def label(self) -> str:
        return "GOOD" if self.direction > 0 else "BAD"

    def __repr__(self):
        return (f"Score(acc={self.accuracy:.4f}, interest={self.interest:.4f}, "
                f"n={self.n_games_eval}, dir={self.label})")


class Formula:
    """Python wrapper around CFormula."""

    def __init__(self):
        self._c = CFormula()
        self._c.length = 0

    @classmethod
    def from_ops(cls, ops: List[Tuple]) -> "Formula":
        """
        Build formula from list of tuples:
          (opcode_str_or_int, var_index=0, value=0.0)

        Examples:
          [("LOAD", 5, 0), ("CONST", 0, 0.4), ("MUL",), ("LOAD", 12, 0), ("ADD",)]
        """
        f = cls()
        for i, op_tuple in enumerate(ops):
            if i >= MAX_FORMULA_OPS:
                break
            op_name = op_tuple[0]
            var_idx = op_tuple[1] if len(op_tuple) > 1 else 0
            value   = op_tuple[2] if len(op_tuple) > 2 else 0.0

            if isinstance(op_name, str):
                opcode = OP.get(op_name.upper(), 0)
            else:
                opcode = int(op_name)

            f._c.ops[i].op        = opcode
            f._c.ops[i].var_index = int(var_idx)
            f._c.ops[i].value     = float(value)

        f._c.length = min(len(ops), MAX_FORMULA_OPS)
        return f

    @classmethod
    def from_dict(cls, d: dict) -> "Formula":
        """Deserialize from JSON dict (as saved in generations/)."""
        return cls.from_ops(d.get("ops", []))

    def to_dict(self) -> dict:
        ops = []
        for i in range(self._c.length):
            ins = self._c.ops[i]
            ops.append([ins.op, ins.var_index, ins.value])
        return {"ops": ops, "length": self._c.length}

    @property
    def length(self) -> int:
        return self._c.length

    def __repr__(self):
        return f"Formula({self._c.length} ops)"

# ─────────────────────────────────────────────────────────────────────────────
# ENGINE (loads the .so)
# ─────────────────────────────────────────────────────────────────────────────

class FormulaEngine:
    """
    Loads nba_engine.so and exposes evaluation methods.
    """

    def __init__(self, so_path: str = None):
        if so_path is None:
            # Look next to this file
            here    = os.path.dirname(os.path.abspath(__file__))
            so_path = os.path.join(here, "nba_engine.so")

        if not os.path.exists(so_path):
            raise FileNotFoundError(
                f"Compiled engine not found: {so_path}\n"
                f"Run: make   (or: bash build.sh)"
            )

        self._lib = ctypes.CDLL(so_path)
        self._setup_signatures()

    def _setup_signatures(self):
        lib = self._lib

        lib.nba_eval_single.restype  = ctypes.c_float
        lib.nba_eval_single.argtypes = [
            ctypes.POINTER(CFormula),
            ctypes.POINTER(CGame),
        ]

        lib.nba_eval_accuracy.restype  = ctypes.c_double
        lib.nba_eval_accuracy.argtypes = [
            ctypes.POINTER(CFormula),
            ctypes.POINTER(CDataset),
        ]

        lib.nba_eval_dataset.restype  = ctypes.c_double
        lib.nba_eval_dataset.argtypes = [
            ctypes.POINTER(CFormula),
            ctypes.POINTER(CDataset),
            ctypes.POINTER(ctypes.c_int),
        ]

        lib.nba_score_formula.restype  = CFormulaScore
        lib.nba_score_formula.argtypes = [
            ctypes.POINTER(CFormula),
            ctypes.POINTER(CDataset),
        ]

        lib.nba_filter_formula.restype  = CFormulaScore
        lib.nba_filter_formula.argtypes = [
            ctypes.POINTER(CFormula),
            ctypes.POINTER(CDataset),
            ctypes.c_int,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_int),
        ]

        

        lib.nba_validate_formula.restype  = ctypes.c_int
        lib.nba_validate_formula.argtypes = [ctypes.POINTER(CFormula)]

        lib.nba_print_formula.restype  = None
        lib.nba_print_formula.argtypes = [
            ctypes.POINTER(CFormula),
            ctypes.POINTER(ctypes.c_char_p),
        ]

    # ── Public API ─────────────────────────────────────────────────────────

    def validate(self, formula: Formula) -> bool:
        return bool(self._lib.nba_validate_formula(ctypes.byref(formula._c)))

    def eval_single(self, formula: Formula, game: CGame) -> float:
        return self._lib.nba_eval_single(
            ctypes.byref(formula._c), ctypes.byref(game))

    def accuracy(self, formula: Formula, ds: CDataset) -> float:
        return self._lib.nba_eval_accuracy(
            ctypes.byref(formula._c), ctypes.byref(ds))

    def score(self, formula: Formula, ds: CDataset) -> ScoreResult:
        cs = self._lib.nba_score_formula(
            ctypes.byref(formula._c), ctypes.byref(ds))
        return ScoreResult(cs.accuracy, cs.interest, cs.n_games_eval, cs.direction)

    def filter(self, formula: Formula, ds: CDataset,
               block_size: int = 100, min_interest: float = 0.10,
               start_fraction: float =1.0) -> Tuple[ScoreResult, bool]:
        """
        Apply interest filter with early stopping.
        Returns (ScoreResult, was_eliminated).
        """
        elim = ctypes.c_int(0)
        cs   = self._lib.nba_filter_formula(
            ctypes.byref(formula._c), ctypes.byref(ds),
            ctypes.c_int(block_size), ctypes.c_double(min_interest),
            ctypes.c_double(start_fraction),
            ctypes.byref(elim)
        )
        return ScoreResult(cs.accuracy, cs.interest, cs.n_games_eval, cs.direction), bool(elim.value)

    def print_formula(self, formula: Formula):
        names = var_names_list()
        c_names = (ctypes.c_char_p * MAX_VARS)()
        for i, n in enumerate(names):
            if i < MAX_VARS:
                c_names[i] = n.encode()
        self._lib.nba_print_formula(ctypes.byref(formula._c), c_names)
