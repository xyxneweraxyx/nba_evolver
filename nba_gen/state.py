"""
nba_gen/state.py
================
Tracks running per-team statistics across the season.
Computes all pre-game snapshot data (cumulative, rolling windows, splits).
"""

from __future__ import annotations
import math
from datetime import date
from typing import Dict, List, Optional

from .teams import haversine_km, tz_shift, TEAM_BY_ID, _r2, _r3

# ─────────────────────────────────────────────────────────────────────────────
# FLAT KEY LIST (all stats we track per game)
# ─────────────────────────────────────────────────────────────────────────────

ALL_FLAT_KEYS = [
    # box
    "pts","fgm","fga","fg_pct","fg3m","fg3a","fg3_pct",
    "ftm","fta","ft_pct","oreb","dreb","reb",
    "ast","tov","stl","blk","blka","pf","pfd","plus_minus","ast_tov_ratio",
    # advanced
    "off_rtg","def_rtg","net_rtg","pace",
    "efg_pct","ts_pct","oreb_pct","dreb_pct","ast_pct","tov_pct","pie",
    # situational
    "pitp","pts_2nd_chance","pts_fb","pts_off_tov",
    # tracking
    "drives","catch_shoot_pct","pull_up_shot_pct",
    "elbow_touch_pts","post_touch_pts","paint_touch_pts",
    "dist_miles","dist_miles_off","dist_miles_def",
    "avg_speed","avg_speed_off","avg_speed_def",
    # hustle
    "contested_shots","contested_shots_2pt","contested_shots_3pt",
    "deflections","charges_drawn","screen_asts","screen_ast_pts",
    "loose_balls_recovered","off_boxouts","def_boxouts","box_outs",
    # defense zone
    "threep_dfgpct","twop_dfgpct","def_rim_pct",
]

QUARTER_KEYS = ["pts","fgm","fga","fg_pct","fg3m","fg3a","ast","ftm","fta"]
CLUTCH_KEYS  = ["pts","fgm","fga","fg_pct","fg3m","fg3a","ftm","fta",
                 "ast","tov","plus_minus","possessions"]

PLAYER_STAT_KEYS = {
    "box":      ["pts","reb","oreb","dreb","ast","stl","blk","tov","pf",
                 "fgm","fga","fg_pct","fg3m","fg3a","fg3_pct","ftm","fta","ft_pct"],
    "advanced": ["efg_pct","ts_pct","usg_pct","bpm","per",
                 "plus_minus","off_rtg","def_rtg","vorp","ws_48"],
    "tracking": ["drives","pull_up_pts","catch_shoot_pct",
                 "contested_shot_pct","avg_speed"],
}

# ─────────────────────────────────────────────────────────────────────────────
# FLATTEN game stats dict
# ─────────────────────────────────────────────────────────────────────────────

def flatten(gs: dict) -> dict:
    flat = {}
    flat.update(gs["box"])
    flat.update(gs["advanced"])
    flat.update(gs["situational"])
    flat.update(gs["tracking"])
    flat.update(gs["hustle"])
    flat.update(gs["defense_zone"])
    return flat

# ─────────────────────────────────────────────────────────────────────────────
# AVERAGING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _avg_block(dicts: list, keys: list) -> Optional[dict]:
    if not dicts: return None
    n = len(dicts)
    out = {}
    for k in keys:
        vals = [d[k] for d in dicts if isinstance(d.get(k), (int, float))]
        out[k] = _r2(sum(vals) / len(vals)) if vals else 0.0
    out["gp"] = n
    return out

def _avgs_with_record(games: list, results: list) -> Optional[dict]:
    if not games: return None
    avgs = _avg_block(games, ALL_FLAT_KEYS)
    w = sum(1 for r in results if r == "W")
    avgs["w"]     = w
    avgs["l"]     = len(results) - w
    avgs["w_pct"] = _r3(w / len(results) if results else 0.0)
    return avgs

def _player_avgs(hist: list, n: Optional[int] = None) -> Optional[dict]:
    if not hist: return None
    subset = hist[-n:] if n else hist
    if not subset: return None
    out = {
        "gp":      len(subset),
        "minutes": _r2(sum(p["minutes"] for p in subset) / len(subset)),
    }
    for section, keys in PLAYER_STAT_KEYS.items():
        sd = {}
        for k in keys:
            vals = [p[section][k] for p in subset if isinstance(p[section].get(k), (int, float))]
            sd[k] = _r2(sum(vals) / len(vals)) if vals else 0.0
        out[section] = sd
    return out

# ─────────────────────────────────────────────────────────────────────────────
# TEAM STATE
# ─────────────────────────────────────────────────────────────────────────────

class TeamState:
    def __init__(self, team_id: int, roster: list):
        self.team_id      = team_id
        self.roster       = roster

        self.games:     List[dict] = []   # flat stat dicts
        self.results:   List[str]  = []   # "W" / "L"
        self.dates:     List[str]  = []
        self.is_home:   List[bool] = []
        self.is_b2b:    List[bool] = []
        self.vs_above500: List[bool] = []
        self.arena_ids: List[int]  = []   # home team's arena per game
        self.home_dates: List[str] = []
        self.home_results: List[str] = []

        self.q1_games:     List[dict] = []
        self.q4_games:     List[dict] = []
        self.clutch_games: List[dict] = []   # includes "won" key

        self.player_hist: Dict[int, list] = {p["slot"]: [] for p in roster}
        self.last_date:   Optional[str]   = None

    # ── ingest ─────────────────────────────────────────────────────────────

    def record_game(self, flat: dict, won: bool, dt: str, home: bool,
                    b2b: bool, opp_above500: bool, arena_id: int,
                    q1: dict, q4: dict, clutch: dict):
        self.games.append(flat)
        self.results.append("W" if won else "L")
        self.dates.append(dt)
        self.is_home.append(home)
        self.is_b2b.append(b2b)
        self.vs_above500.append(opp_above500)
        self.arena_ids.append(arena_id)
        q1c = dict(q1); q1c["won"] = won
        q4c = dict(q4); q4c["won"] = won
        clc = dict(clutch); clc["won"] = won
        self.q1_games.append(q1c)
        self.q4_games.append(q4c)
        self.clutch_games.append(clc)
        if home:
            self.home_dates.append(dt)
            self.home_results.append("W" if won else "L")
        self.last_date = dt

    def record_player(self, slot: int, pstats: dict):
        self.player_hist[slot].append(pstats)

    # ── context helpers ────────────────────────────────────────────────────

    def gp(self) -> int:
        return len(self.games)

    def rest_days(self, today: str) -> int:
        if not self.last_date: return 7
        return (date.fromisoformat(today) - date.fromisoformat(self.last_date)).days

    def win_streak(self) -> int:
        if not self.results: return 0
        val = self.results[-1]
        n = 0
        for r in reversed(self.results):
            if r == val: n += 1 if val == "W" else -1
            else: break
        return n

    def home_win_streak(self) -> int:
        if not self.home_results: return 0
        val = self.home_results[-1]
        n = 0
        for r in reversed(self.home_results):
            if r == val: n += 1 if val == "W" else -1
            else: break
        return n

    def games_last_n_days(self, today: str, n: int = 7) -> int:
        td = date.fromisoformat(today)
        return sum(1 for d in self.dates if (td - date.fromisoformat(d)).days <= n)

    def days_since_last_home(self, today: str) -> int:
        if not self.home_dates: return 14
        return (date.fromisoformat(today) - date.fromisoformat(self.home_dates[-1])).days

    def km_traveled(self, today_arena: int) -> float:
        if not self.arena_ids: return 0.0
        last = self.arena_ids[-1]
        if last == today_arena: return 0.0
        return haversine_km(last, today_arena)

    def tz_shift_val(self, today_arena: int) -> int:
        if not self.arena_ids: return 0
        return tz_shift(self.arena_ids[-1], today_arena)

    def current_w_pct(self) -> float:
        if not self.results: return 0.500
        w = sum(1 for r in self.results if r == "W")
        return w / len(self.results)

    # ── stat aggregates ────────────────────────────────────────────────────

    def season_avgs(self)       -> Optional[dict]:
        return _avgs_with_record(self.games, self.results)

    def last_n_avgs(self, n: int) -> Optional[dict]:
        return _avgs_with_record(self.games[-n:], self.results[-n:])

    def home_avgs(self) -> Optional[dict]:
        idx = [i for i, h in enumerate(self.is_home) if h]
        return _avgs_with_record(
            [self.games[i] for i in idx],
            [self.results[i] for i in idx]
        )

    def away_avgs(self) -> Optional[dict]:
        idx = [i for i, h in enumerate(self.is_home) if not h]
        return _avgs_with_record(
            [self.games[i] for i in idx],
            [self.results[i] for i in idx]
        )

    def b2b_avgs(self) -> Optional[dict]:
        idx = [i for i, b in enumerate(self.is_b2b) if b]
        return _avgs_with_record(
            [self.games[i] for i in idx],
            [self.results[i] for i in idx]
        )

    def vs_above500_avgs(self) -> Optional[dict]:
        idx = [i for i, v in enumerate(self.vs_above500) if v]
        return _avgs_with_record(
            [self.games[i] for i in idx],
            [self.results[i] for i in idx]
        )

    def q1_avgs(self) -> Optional[dict]:
        return _avg_block(self.q1_games, QUARTER_KEYS)

    def q4_avgs(self) -> Optional[dict]:
        return _avg_block(self.q4_games, QUARTER_KEYS)

    def clutch_avgs(self) -> Optional[dict]:
        if not self.clutch_games: return None
        base = _avg_block(self.clutch_games, CLUTCH_KEYS)
        w    = sum(1 for c in self.clutch_games if c["won"])
        base["w"]     = w
        base["l"]     = len(self.clutch_games) - w
        base["w_pct"] = _r3(w / len(self.clutch_games))
        return base

    def player_avgs(self, slot: int, n: Optional[int] = None) -> Optional[dict]:
        return _player_avgs(self.player_hist.get(slot, []), n)
