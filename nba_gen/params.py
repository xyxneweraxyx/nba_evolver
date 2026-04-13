"""
nba_gen/params.py
=================
Real NBA league-average anchors per season, plus all generation constants.

Sources: Basketball-Reference league averages, NBA.com stats surveys.
Values are PER TEAM PER GAME unless noted.

Trend summary (what changed 2013→2024):
  - 3PA:    20.0 → 35.9  (+80%)   massive 3-point revolution
  - Pace:   93.9 → 99.6  (+6%)    faster game
  - PTS:   101.8 → 114.7 (+13%)   more scoring
  - FG%:   44.7% → 47.0% (+2.3pp) more efficient
  - FT rate: down (less drawing fouls)
  - AST:   22.1 → 26.0   (+18%)   more ball movement
  - TOV:   14.0 → 13.6   (-3%)    slightly fewer turnovers
"""

from __future__ import annotations
from datetime import date
from typing import Dict

# ─────────────────────────────────────────────────────────────────────────────
# SEASONS TO GENERATE
# ─────────────────────────────────────────────────────────────────────────────

TRAINING_SEASONS = [
    "2013-14", "2014-15", "2015-16", "2016-17",
    "2017-18", "2018-19",
    "2020-21", "2021-22",   # skip 2019-20 COVID bubble
]
TESTING_SEASONS = ["2022-23", "2023-24"]
ALL_SEASONS     = TRAINING_SEASONS + TESTING_SEASONS

SEASON_STARTS: Dict[str, date] = {
    "2013-14": date(2013, 10, 29),
    "2014-15": date(2014, 10, 28),
    "2015-16": date(2015, 10, 27),
    "2016-17": date(2016, 10, 25),
    "2017-18": date(2017, 10, 17),
    "2018-19": date(2018, 10, 16),
    "2020-21": date(2020, 12, 22),
    "2021-22": date(2021, 10, 19),
    "2022-23": date(2022, 10, 18),
    "2023-24": date(2023, 10, 24),
}

# ─────────────────────────────────────────────────────────────────────────────
# REAL NBA LEAGUE AVERAGES — anchors for simulation
# Each dict is one anchor season; we interpolate between them.
# ─────────────────────────────────────────────────────────────────────────────

# fmt: off
LEAGUE_ANCHORS: Dict[str, dict] = {
    "2013-14": dict(
        pts=101.8, fga=84.7, fg_pct=0.447, fg3a=20.0, fg3_pct=0.356,
        fta=24.5,  ft_pct=0.749, oreb=10.4, dreb=31.3,
        ast=22.1,  tov=14.0, stl=7.7, blk=4.7, pf=19.8,
        pace=93.9, off_rtg=105.6,
    ),
    "2015-16": dict(
        pts=105.6, fga=87.0, fg_pct=0.452, fg3a=24.1, fg3_pct=0.354,
        fta=23.1,  ft_pct=0.760, oreb=9.9, dreb=32.1,
        ast=23.4,  tov=13.9, stl=7.7, blk=4.8, pf=20.4,
        pace=95.8, off_rtg=108.8,
    ),
    "2017-18": dict(
        pts=106.3, fga=87.3, fg_pct=0.456, fg3a=27.0, fg3_pct=0.363,
        fta=22.0,  ft_pct=0.770, oreb=9.5, dreb=32.5,
        ast=23.8,  tov=14.2, stl=7.5, blk=5.0, pf=20.0,
        pace=97.3, off_rtg=108.6,
    ),
    "2019-20": dict(
        pts=111.8, fga=88.7, fg_pct=0.461, fg3a=34.1, fg3_pct=0.358,
        fta=22.3,  ft_pct=0.772, oreb=9.7, dreb=33.1,
        ast=24.8,  tov=14.1, stl=7.7, blk=5.1, pf=19.8,
        pace=100.3, off_rtg=112.4,
    ),
    "2021-22": dict(
        pts=112.0, fga=88.3, fg_pct=0.463, fg3a=35.2, fg3_pct=0.354,
        fta=21.5,  ft_pct=0.774, oreb=9.5, dreb=33.4,
        ast=25.2,  tov=14.1, stl=7.5, blk=5.0, pf=19.5,
        pace=98.2, off_rtg=112.5,
    ),
    "2023-24": dict(
        pts=114.7, fga=89.3, fg_pct=0.470, fg3a=35.9, fg3_pct=0.361,
        fta=21.4,  ft_pct=0.781, oreb=9.4, dreb=33.6,
        ast=26.0,  tov=13.6, stl=7.4, blk=4.8, pf=19.5,
        pace=99.6, off_rtg=116.4,
    ),
}
# fmt: on

def _interp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def _year(season: str) -> float:
    """Convert '2017-18' → 2017.5 for interpolation."""
    y = int(season[:4])
    return y + 0.5

def league_params_for_season(season: str) -> dict:
    """
    Return interpolated league averages for the given season string.
    """
    sy = _year(season)
    anchors = sorted(LEAGUE_ANCHORS.items(), key=lambda kv: _year(kv[0]))
    # Find surrounding anchors
    if sy <= _year(anchors[0][0]):
        return dict(anchors[0][1])
    if sy >= _year(anchors[-1][0]):
        return dict(anchors[-1][1])
    for i in range(len(anchors) - 1):
        ay = _year(anchors[i][0])
        by = _year(anchors[i+1][0])
        if ay <= sy <= by:
            t = (sy - ay) / (by - ay)
            base = anchors[i][1]
            nxt  = anchors[i+1][1]
            return {k: _interp(base[k], nxt[k], t) for k in base}
    return dict(anchors[-1][1])

# ─────────────────────────────────────────────────────────────────────────────
# GAME CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

HOME_WIN_PCT       = 0.594    # real NBA home win % (~60%)
HOME_POINT_BONUS   = 3.2      # avg pts advantage at home
B2B_WIN_PENALTY    = 0.042    # home win % drop when home team on B2B
B2B_SCORE_PENALTY  = 2.1      # points lost on B2B
REST_ADVANTAGE_PTS = 0.8      # pts gained per extra day of rest (vs opponent)

UPSET_FLOOR        = 0.18     # even the best team loses 18% of games

# ─────────────────────────────────────────────────────────────────────────────
# TEAM STRENGTH DISTRIBUTION (30 teams)
# ─────────────────────────────────────────────────────────────────────────────
# Tier label → (count, win_pct_mean, win_pct_std)
# Real NBA distribution over 2013-2024:
#   Elite  (5 teams): ~0.63 avg
#   Good   (7 teams): ~0.56 avg
#   Average(9 teams): ~0.49 avg
#   Bad    (6 teams): ~0.40 avg
#   Terrible(3 teams):~0.29 avg
TEAM_TIERS = [
    ("elite",    5,  0.630, 0.040),
    ("good",     7,  0.560, 0.030),
    ("average",  9,  0.488, 0.025),
    ("bad",      6,  0.400, 0.030),
    ("terrible", 3,  0.290, 0.035),
]

# Strength dims derived from win% with added noise
# Each team gets: off_str, def_str, pace_str, consistency, clutch_str
STRENGTH_NOISE = 0.04   # std of per-dimension noise around team tier

# ─────────────────────────────────────────────────────────────────────────────
# SEASON EVOLUTION
# ─────────────────────────────────────────────────────────────────────────────
# Teams drift slightly across the season
# Good teams tend to peak mid-late season (playoff push)
# Bad teams often get worse (tanking)
GOOD_TEAM_LATE_BONUS   =  0.025   # added to win% after game 55 for top 10 teams
BAD_TEAM_LATE_PENALTY  = -0.020   # subtracted after game 55 for bottom 10 teams

# ─────────────────────────────────────────────────────────────────────────────
# PLAYER ARCHETYPE DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────
# (pts_share, ast_share, reb_share, fg3a_share, usg_mean, role)
# These are relative shares of team totals for each position archetype.

PLAYER_ARCHETYPES = {
    # name: (pts_weight, ast_weight, reb_weight, three_weight, stl_w, blk_w)
    "star_guard":     (0.230, 0.200, 0.060, 0.220, 0.90, 0.10),
    "combo_guard":    (0.140, 0.130, 0.055, 0.170, 0.80, 0.08),
    "wing":           (0.120, 0.085, 0.090, 0.160, 0.70, 0.12),
    "stretch_four":   (0.110, 0.070, 0.140, 0.130, 0.65, 0.15),
    "big":            (0.090, 0.045, 0.200, 0.020, 0.60, 0.30),
    "bench_guard":    (0.085, 0.090, 0.040, 0.120, 0.55, 0.06),
    "bench_wing":     (0.070, 0.050, 0.075, 0.090, 0.50, 0.10),
    "bench_big":      (0.060, 0.030, 0.150, 0.010, 0.45, 0.25),
    "end_rotation_g": (0.040, 0.040, 0.030, 0.070, 0.35, 0.04),
    "end_rotation_f": (0.035, 0.025, 0.060, 0.040, 0.30, 0.12),
    "deep_reserve_g": (0.020, 0.020, 0.020, 0.030, 0.20, 0.03),
    "deep_reserve_b": (0.015, 0.010, 0.040, 0.005, 0.15, 0.18),
}

# Slot index → archetype name (12 slots per team)
SLOT_ARCHETYPES = [
    "star_guard", "combo_guard", "wing", "stretch_four", "big",
    "bench_guard", "bench_wing", "bench_big",
    "end_rotation_g", "end_rotation_f",
    "deep_reserve_g", "deep_reserve_b",
]

# Minutes per game expected for each slot (sums to ~240 = 5 players × 48)
SLOT_MINUTES = [
    34.0, 31.0, 28.5, 26.0, 24.0,
    22.0, 19.0, 17.0,
    13.0, 11.0,
    7.0, 5.0,
]

# Availability probability per slot (injuries)
SLOT_AVAILABILITY = [
    0.900, 0.890, 0.895, 0.900, 0.895,
    0.920, 0.925, 0.930,
    0.940, 0.945,
    0.960, 0.970,
]

# ─────────────────────────────────────────────────────────────────────────────
# VARIANCE PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
# Real NBA games have HIGH variance. Underdogs win ~35% of games.
# We model this with a per-game "chaos" factor.
GAME_CHAOS_STD   = 0.18   # std of random upset factor per game
PLAYER_GAME_STD  = 0.22   # std of player performance factor vs season avg

# Score variance: real NBA games range roughly 85-145 pts per team
SCORE_STD_EXTRA  = 7.5    # extra std on top of team strength for game score

# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT CONFIG
# ─────────────────────────────────────────────────────────────────────────────
OUTPUT_DIR = "./nba_data"
GAMES_PER_TEAM = 82
