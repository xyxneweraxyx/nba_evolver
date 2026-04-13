"""
nba_gen/teams.py
================
Generates 30 teams with realistic strength profiles and 12-man rosters.
Player stats are anchored to position archetypes and team strength.
"""

from __future__ import annotations
import random
import math
from typing import Dict, List, Tuple

from .params import (
    TEAM_TIERS, STRENGTH_NOISE,
    SLOT_ARCHETYPES, SLOT_MINUTES, SLOT_AVAILABILITY,
    PLAYER_ARCHETYPES,
)

# ─────────────────────────────────────────────────────────────────────────────
# TEAMS
# ─────────────────────────────────────────────────────────────────────────────

TEAMS = [
    {"id":  1, "abbr": "ATL", "city": "Atlanta",       "tz": -5, "lat": 33.757, "lon": -84.396},
    {"id":  2, "abbr": "BOS", "city": "Boston",        "tz": -5, "lat": 42.366, "lon": -71.062},
    {"id":  3, "abbr": "BKN", "city": "Brooklyn",      "tz": -5, "lat": 40.683, "lon": -73.975},
    {"id":  4, "abbr": "CHA", "city": "Charlotte",     "tz": -5, "lat": 35.225, "lon": -80.839},
    {"id":  5, "abbr": "CHI", "city": "Chicago",       "tz": -6, "lat": 41.881, "lon": -87.674},
    {"id":  6, "abbr": "CLE", "city": "Cleveland",     "tz": -5, "lat": 41.497, "lon": -81.688},
    {"id":  7, "abbr": "DAL", "city": "Dallas",        "tz": -6, "lat": 32.790, "lon": -96.810},
    {"id":  8, "abbr": "DEN", "city": "Denver",        "tz": -7, "lat": 39.749, "lon": -104.990},
    {"id":  9, "abbr": "DET", "city": "Detroit",       "tz": -5, "lat": 42.341, "lon": -83.055},
    {"id": 10, "abbr": "GSW", "city": "Golden State",  "tz": -8, "lat": 37.768, "lon": -122.388},
    {"id": 11, "abbr": "HOU", "city": "Houston",       "tz": -6, "lat": 29.751, "lon": -95.362},
    {"id": 12, "abbr": "IND", "city": "Indiana",       "tz": -5, "lat": 39.764, "lon": -86.156},
    {"id": 13, "abbr": "LAC", "city": "LA Clippers",   "tz": -8, "lat": 34.043, "lon": -118.267},
    {"id": 14, "abbr": "LAL", "city": "LA Lakers",     "tz": -8, "lat": 34.043, "lon": -118.267},
    {"id": 15, "abbr": "MEM", "city": "Memphis",       "tz": -6, "lat": 35.138, "lon": -90.050},
    {"id": 16, "abbr": "MIA", "city": "Miami",         "tz": -5, "lat": 25.781, "lon": -80.188},
    {"id": 17, "abbr": "MIL", "city": "Milwaukee",     "tz": -6, "lat": 43.045, "lon": -87.917},
    {"id": 18, "abbr": "MIN", "city": "Minnesota",     "tz": -6, "lat": 44.979, "lon": -93.276},
    {"id": 19, "abbr": "NOP", "city": "New Orleans",   "tz": -6, "lat": 29.949, "lon": -90.082},
    {"id": 20, "abbr": "NYK", "city": "New York",      "tz": -5, "lat": 40.750, "lon": -73.994},
    {"id": 21, "abbr": "OKC", "city": "Oklahoma City", "tz": -6, "lat": 35.463, "lon": -97.515},
    {"id": 22, "abbr": "ORL", "city": "Orlando",       "tz": -5, "lat": 28.539, "lon": -81.384},
    {"id": 23, "abbr": "PHI", "city": "Philadelphia",  "tz": -5, "lat": 39.901, "lon": -75.172},
    {"id": 24, "abbr": "PHX", "city": "Phoenix",       "tz": -7, "lat": 33.445, "lon": -112.071},
    {"id": 25, "abbr": "POR", "city": "Portland",      "tz": -8, "lat": 45.532, "lon": -122.667},
    {"id": 26, "abbr": "SAC", "city": "Sacramento",    "tz": -8, "lat": 38.580, "lon": -121.500},
    {"id": 27, "abbr": "SAS", "city": "San Antonio",   "tz": -6, "lat": 29.427, "lon": -98.437},
    {"id": 28, "abbr": "TOR", "city": "Toronto",       "tz": -5, "lat": 43.643, "lon": -79.379},
    {"id": 29, "abbr": "UTA", "city": "Utah",          "tz": -7, "lat": 40.768, "lon": -111.901},
    {"id": 30, "abbr": "WAS", "city": "Washington",    "tz": -5, "lat": 38.898, "lon": -77.021},
]

TEAM_IDS   = [t["id"] for t in TEAMS]
TEAM_BY_ID = {t["id"]: t for t in TEAMS}

# ─────────────────────────────────────────────────────────────────────────────
# MATH HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def _gauss(mean: float, std: float, lo: float = None, hi: float = None) -> float:
    v = random.gauss(mean, std)
    if lo is not None: v = max(lo, v)
    if hi is not None: v = min(hi, v)
    return v

def haversine_km(tid1: int, tid2: int) -> float:
    """Great-circle distance between two team arenas."""
    t1, t2 = TEAM_BY_ID[tid1], TEAM_BY_ID[tid2]
    lat1, lon1 = t1["lat"], t1["lon"]
    lat2, lon2 = t2["lat"], t2["lon"]
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return round(R * 2 * math.asin(math.sqrt(a)), 1)

def tz_shift(from_id: int, to_id: int) -> int:
    return TEAM_BY_ID[to_id]["tz"] - TEAM_BY_ID[from_id]["tz"]

# ─────────────────────────────────────────────────────────────────────────────
# TEAM STRENGTH
# ─────────────────────────────────────────────────────────────────────────────

def generate_team_strengths() -> Dict[int, dict]:
    """
    Assign each team to a tier and generate a 5-dimensional strength profile.
    Returns {team_id: {win_pct, off_str, def_str, pace_str, consistency, clutch}}
    where all str values are 0-1 and correspond to that dimension's quality.
    """
    # Build ordered list of 30 teams shuffled
    team_list = list(TEAM_IDS)
    random.shuffle(team_list)

    strengths = {}
    idx = 0
    for tier_name, count, wm, ws in TEAM_TIERS:
        for _ in range(count):
            if idx >= len(team_list):
                break
            tid = team_list[idx]; idx += 1
            win_pct = _clamp(_gauss(wm, ws), 0.18, 0.75)

            # Derive off/def/pace from win_pct with noise
            # Better teams tend to have better offense AND defense
            # but with independent variation
            base = (win_pct - 0.30) / 0.45   # 0-1 scale from win%
            off_str    = _clamp(base + _gauss(0, STRENGTH_NOISE), 0.05, 1.0)
            def_str    = _clamp(base + _gauss(0, STRENGTH_NOISE), 0.05, 1.0)
            pace_str   = _clamp(0.50 + _gauss(0, STRENGTH_NOISE * 1.5), 0.05, 1.0)
            consistency = _clamp(base * 0.6 + 0.2 + _gauss(0, 0.08), 0.15, 0.95)
            clutch     = _clamp(base * 0.5 + 0.25 + _gauss(0, 0.12), 0.10, 0.90)

            strengths[tid] = {
                "win_pct":     round(win_pct, 3),
                "tier":        tier_name,
                "off_str":     round(off_str, 3),
                "def_str":     round(def_str, 3),
                "pace_str":    round(pace_str, 3),
                "consistency": round(consistency, 3),
                "clutch":      round(clutch, 3),
            }

    return strengths

def evolve_team_strengths(prev: Dict[int, dict]) -> Dict[int, dict]:
    """
    Evolve team strengths between seasons.
    Most teams stay similar; a few improve/decline significantly (trades, drafts).
    """
    new = {}
    for tid, s in prev.items():
        # 20% chance of a major change (trade, star development, tank)
        if random.random() < 0.20:
            delta_w = _gauss(0, 0.08)   # major shift
        else:
            delta_w = _gauss(0, 0.03)   # minor drift

        new_wp  = _clamp(s["win_pct"] + delta_w, 0.18, 0.75)
        base    = (new_wp - 0.30) / 0.45
        new[tid] = {
            "win_pct":     round(new_wp, 3),
            "tier":        _classify_tier(new_wp),
            "off_str":     _clamp(s["off_str"]    + _gauss(0, 0.04), 0.05, 1.0),
            "def_str":     _clamp(s["def_str"]    + _gauss(0, 0.04), 0.05, 1.0),
            "pace_str":    _clamp(s["pace_str"]   + _gauss(0, 0.03), 0.05, 1.0),
            "consistency": _clamp(s["consistency"]+ _gauss(0, 0.03), 0.15, 0.95),
            "clutch":      _clamp(s["clutch"]     + _gauss(0, 0.04), 0.10, 0.90),
        }
        # Round all
        for k in ("off_str","def_str","pace_str","consistency","clutch"):
            new[tid][k] = round(new[tid][k], 3)

    return new

def _classify_tier(wp: float) -> str:
    if wp >= 0.60:  return "elite"
    if wp >= 0.53:  return "good"
    if wp >= 0.45:  return "average"
    if wp >= 0.35:  return "bad"
    return "terrible"

# ─────────────────────────────────────────────────────────────────────────────
# PLAYER GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def generate_roster(tid: int, team_str: dict) -> List[dict]:
    """
    Generate 12 players for a team.
    Player skill is correlated with team strength but with individual variance.
    """
    # Overall team skill (0-1)
    team_skill = (team_str["win_pct"] - 0.18) / 0.57

    players = []
    for slot, arch_name in enumerate(SLOT_ARCHETYPES):
        arch = PLAYER_ARCHETYPES[arch_name]
        # Individual skill: team baseline + archetype importance + noise
        slot_decay   = 1.0 - slot * 0.055
        player_skill = _clamp(
            team_skill * slot_decay + _gauss(0, 0.12),
            0.02, 0.98
        )

        players.append({
            "slot":           slot,
            "archetype":      arch_name,
            "skill":          round(player_skill, 3),
            "exp_minutes":    SLOT_MINUTES[slot],
            "available_prob": SLOT_AVAILABILITY[slot],
            # Store archetype weights for game simulation
            "_arch":          arch,
        })

    return players

def _r2(x: float) -> float:
    return round(float(x), 2)

def _r3(x: float) -> float:
    return round(float(x), 3)

def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b else default
