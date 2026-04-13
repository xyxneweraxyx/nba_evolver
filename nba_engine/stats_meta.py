"""
stats_meta.py — Metadata for all variables in the formula engine registry
==========================================================================
Used by /api/data/variables to power the Stats reference page.

Each variable has:
  - desc:  human-readable description
  - unit:  unit of measurement
  - range: typical [min, max] on NBA data
  - tier:  1 (high signal), 2 (medium), 3 (low/contextual)
  - cat:   category slug for grouping
"""

from typing import Dict, Any

# ─────────────────────────────────────────────────────────────────────────────
# CATEGORY DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

CATEGORIES = {
    "binary":           { "label": "Binary flags",        "color": "#1A5FA3" },
    "context":          { "label": "Game context",         "color": "#C9942A" },
    "season_stats":     { "label": "Season stats",         "color": "#E8520A" },
    "last10_stats":     { "label": "Last 10 games",        "color": "#FF6B2B" },
    "last5_stats":      { "label": "Last 5 games",         "color": "#FF6B2B" },
    "home_stats":       { "label": "Home splits",          "color": "#1A7A45" },
    "away_stats":       { "label": "Away splits",          "color": "#1A7A45" },
    "b2b_stats":        { "label": "Back-to-back splits",  "color": "#7A7870" },
    "vs_above500_stats":{ "label": "vs .500+ teams",       "color": "#7A7870" },
    "q1_stats":         { "label": "Q1 stats",             "color": "#1A5FA3" },
    "q4_stats":         { "label": "Q4 / clutch time",     "color": "#C0392B" },
    "clutch_stats":     { "label": "Clutch stats (≤5 pts, ≤5 min)", "color": "#C0392B" },
    "player":           { "label": "Player slots (0–11)",  "color": "#7A7870" },
}

# ─────────────────────────────────────────────────────────────────────────────
# STAT KEY METADATA
# ─────────────────────────────────────────────────────────────────────────────

STAT_META: Dict[str, Dict[str, Any]] = {
    # ── Scoring ──────────────────────────────────────────────────────────────
    "pts":        {"desc": "Points per game",                    "unit": "pts/g",  "range": [85, 130],   "tier": 2},
    "fgm":        {"desc": "Field goals made per game",          "unit": "fgm/g",  "range": [30, 50],    "tier": 3},
    "fga":        {"desc": "Field goal attempts per game",       "unit": "fga/g",  "range": [75, 100],   "tier": 3},
    "fg_pct":     {"desc": "Field goal percentage",              "unit": "%",      "range": [0.40, 0.52],"tier": 2},
    "fg3m":       {"desc": "3-pointers made per game",           "unit": "3pm/g",  "range": [7, 20],     "tier": 2},
    "fg3a":       {"desc": "3-point attempts per game",          "unit": "3pa/g",  "range": [20, 45],    "tier": 2},
    "fg3_pct":    {"desc": "3-point percentage",                 "unit": "%",      "range": [0.30, 0.42],"tier": 2},
    "ftm":        {"desc": "Free throws made per game",          "unit": "ftm/g",  "range": [10, 30],    "tier": 3},
    "fta":        {"desc": "Free throw attempts per game",       "unit": "fta/g",  "range": [12, 35],    "tier": 3},
    "ft_pct":     {"desc": "Free throw percentage",              "unit": "%",      "range": [0.68, 0.84],"tier": 3},

    # ── Rebounds ─────────────────────────────────────────────────────────────
    "oreb":       {"desc": "Offensive rebounds per game",        "unit": "reb/g",  "range": [6, 14],     "tier": 2},
    "dreb":       {"desc": "Defensive rebounds per game",        "unit": "reb/g",  "range": [28, 40],    "tier": 2},
    "reb":        {"desc": "Total rebounds per game",            "unit": "reb/g",  "range": [36, 52],    "tier": 2},

    # ── Playmaking & Turnovers ────────────────────────────────────────────────
    "ast":        {"desc": "Assists per game",                   "unit": "ast/g",  "range": [18, 32],    "tier": 2},
    "tov":        {"desc": "Turnovers per game",                 "unit": "tov/g",  "range": [10, 18],    "tier": 2},
    "ast_tov_ratio":{"desc":"Assist-to-turnover ratio",          "unit": "ratio",  "range": [1.2, 2.8],  "tier": 2},

    # ── Defense ──────────────────────────────────────────────────────────────
    "stl":        {"desc": "Steals per game",                    "unit": "stl/g",  "range": [5, 11],     "tier": 2},
    "blk":        {"desc": "Blocks per game",                    "unit": "blk/g",  "range": [3, 8],      "tier": 2},
    "blka":       {"desc": "Blocks against (shots blocked) per game","unit":"blka/g","range":[3,8],       "tier": 3},
    "pf":         {"desc": "Personal fouls per game",            "unit": "pf/g",   "range": [16, 24],    "tier": 3},
    "pfd":        {"desc": "Personal fouls drawn per game",      "unit": "pfd/g",  "range": [16, 26],    "tier": 3},

    # ── Four Factors / Efficiency ─────────────────────────────────────────────
    "off_rtg":    {"desc": "Offensive rating — points scored per 100 possessions", "unit": "pts/100", "range": [100, 125], "tier": 1},
    "def_rtg":    {"desc": "Defensive rating — points allowed per 100 possessions","unit": "pts/100", "range": [100, 125], "tier": 1},
    "net_rtg":    {"desc": "Net rating (off_rtg - def_rtg). Best overall efficiency metric.", "unit": "pts/100", "range": [-15, 15], "tier": 1},
    "pace":       {"desc": "Estimated possessions per 48 minutes",                 "unit": "poss/48", "range": [92, 106],  "tier": 2},
    "efg_pct":    {"desc": "Effective FG% — weights 3-pointers at 1.5x",          "unit": "%",       "range": [0.48, 0.58],"tier": 1},
    "ts_pct":     {"desc": "True shooting % — includes FTs in efficiency",         "unit": "%",       "range": [0.52, 0.62],"tier": 1},
    "oreb_pct":   {"desc": "Offensive rebound rate (% of available OReb captured)","unit": "%",       "range": [0.18, 0.32],"tier": 2},
    "dreb_pct":   {"desc": "Defensive rebound rate",                               "unit": "%",       "range": [0.68, 0.82],"tier": 2},
    "ast_pct":    {"desc": "Assist rate — % of FGM assisted",                      "unit": "%",       "range": [0.48, 0.70],"tier": 2},
    "tov_pct":    {"desc": "Turnover rate — TOV per 100 plays",                    "unit": "%",       "range": [0.10, 0.18],"tier": 2},
    "pie":        {"desc": "Player Impact Estimate — team version. % of game events involving this team.", "unit": "%", "range": [0.44, 0.56], "tier": 1},
    "plus_minus": {"desc": "Average point differential when team is playing",      "unit": "pts",     "range": [-12, 12],  "tier": 2},

    # ── Second-chance / paint / transition ───────────────────────────────────
    "pitp":            {"desc": "Points in the paint per game",           "unit": "pts/g",  "range": [35, 60],    "tier": 2},
    "pts_2nd_chance":  {"desc": "Second-chance points per game",          "unit": "pts/g",  "range": [8, 18],     "tier": 2},
    "pts_fb":          {"desc": "Fast break points per game",             "unit": "pts/g",  "range": [8, 22],     "tier": 2},
    "pts_off_tov":     {"desc": "Points off turnovers per game",          "unit": "pts/g",  "range": [12, 22],    "tier": 2},

    # ── Tracking — offensive ─────────────────────────────────────────────────
    "drives":           {"desc": "Drive attempts per game",               "unit": "drv/g",  "range": [30, 60],    "tier": 3},
    "catch_shoot_pct":  {"desc": "Catch-and-shoot FG% on 3-pointers",    "unit": "%",      "range": [0.33, 0.42],"tier": 3},
    "pull_up_shot_pct": {"desc": "Pull-up jump shot FG%",                "unit": "%",      "range": [0.35, 0.45],"tier": 3},
    "elbow_touch_pts":  {"desc": "Points from elbow (mid-range) touches", "unit": "pts/g",  "range": [5, 20],     "tier": 3},
    "post_touch_pts":   {"desc": "Points from post-up touches",           "unit": "pts/g",  "range": [3, 15],     "tier": 3},
    "paint_touch_pts":  {"desc": "Points from paint touches",             "unit": "pts/g",  "range": [20, 45],    "tier": 3},

    # ── Tracking — movement ───────────────────────────────────────────────────
    "dist_miles":     {"desc": "Total distance run per game (miles)",     "unit": "mi/g",   "range": [130, 175],  "tier": 3},
    "dist_miles_off": {"desc": "Distance on offense",                     "unit": "mi/g",   "range": [60, 90],    "tier": 3},
    "dist_miles_def": {"desc": "Distance on defense",                     "unit": "mi/g",   "range": [65, 90],    "tier": 3},
    "avg_speed":      {"desc": "Average speed per game",                  "unit": "mph",    "range": [4.2, 5.0],  "tier": 3},
    "avg_speed_off":  {"desc": "Average speed on offense",                "unit": "mph",    "range": [4.0, 5.0],  "tier": 3},
    "avg_speed_def":  {"desc": "Average speed on defense",                "unit": "mph",    "range": [4.2, 5.1],  "tier": 3},

    # ── Tracking — hustle / defense ──────────────────────────────────────────
    "contested_shots":      {"desc": "Contested shots per game (defender within 4ft)", "unit": "shots/g", "range": [40, 65],  "tier": 3},
    "contested_shots_2pt":  {"desc": "Contested 2-point shots per game",               "unit": "shots/g", "range": [20, 40],  "tier": 3},
    "contested_shots_3pt":  {"desc": "Contested 3-point shots per game",               "unit": "shots/g", "range": [15, 30],  "tier": 3},
    "deflections":          {"desc": "Deflections per game (disrupted passes/drives)", "unit": "def/g",   "range": [10, 22],  "tier": 3},
    "charges_drawn":        {"desc": "Charges drawn per game",                         "unit": "chg/g",   "range": [0.5, 3],  "tier": 3},
    "screen_asts":          {"desc": "Screen assists per game",                        "unit": "scr/g",   "range": [10, 25],  "tier": 3},
    "screen_ast_pts":       {"desc": "Points generated by screens",                   "unit": "pts/g",   "range": [10, 30],  "tier": 3},
    "loose_balls_recovered":{"desc": "Loose balls recovered per game",                "unit": "lb/g",    "range": [2, 8],    "tier": 3},
    "off_boxouts":          {"desc": "Offensive box-outs per game",                   "unit": "bxo/g",   "range": [5, 14],   "tier": 3},
    "def_boxouts":          {"desc": "Defensive box-outs per game",                   "unit": "bxo/g",   "range": [15, 30],  "tier": 3},
    "box_outs":             {"desc": "Total box-outs per game",                       "unit": "bxo/g",   "range": [20, 42],  "tier": 3},

    # ── Defensive shooting charts ─────────────────────────────────────────────
    "threep_dfgpct":  {"desc": "Opponent 3-point FG% allowed",           "unit": "%",      "range": [0.32, 0.40],"tier": 2},
    "twop_dfgpct":    {"desc": "Opponent 2-point FG% allowed",           "unit": "%",      "range": [0.45, 0.56],"tier": 2},
    "def_rim_pct":    {"desc": "Opponent FG% at the rim allowed",        "unit": "%",      "range": [0.55, 0.72],"tier": 2},

    # ── Win/loss record ───────────────────────────────────────────────────────
    "w":      {"desc": "Wins (season to date)",                           "unit": "wins",   "range": [0, 82],     "tier": 2},
    "l":      {"desc": "Losses (season to date)",                         "unit": "losses", "range": [0, 82],     "tier": 2},
    "w_pct":  {"desc": "Win percentage. Very predictive of future wins.", "unit": "%",      "range": [0.15, 0.85],"tier": 1},
    "gp":     {"desc": "Games played (season to date)",                   "unit": "games",  "range": [1, 82],     "tier": 3},
}

# Player-specific stats
PLAYER_STAT_META: Dict[str, Dict[str, Any]] = {
    "pts":     {"desc": "Points per game",                   "unit": "pts/g",  "range": [0, 35],    "tier": 2},
    "reb":     {"desc": "Rebounds per game",                  "unit": "reb/g",  "range": [0, 14],    "tier": 2},
    "ast":     {"desc": "Assists per game",                   "unit": "ast/g",  "range": [0, 12],    "tier": 2},
    "stl":     {"desc": "Steals per game",                    "unit": "stl/g",  "range": [0, 3],     "tier": 2},
    "blk":     {"desc": "Blocks per game",                    "unit": "blk/g",  "range": [0, 4],     "tier": 2},
    "tov":     {"desc": "Turnovers per game",                 "unit": "tov/g",  "range": [0, 5],     "tier": 2},
    "fg_pct":  {"desc": "Field goal percentage",              "unit": "%",      "range": [0.35, 0.60],"tier": 2},
    "fg3_pct": {"desc": "3-point percentage",                 "unit": "%",      "range": [0.25, 0.45],"tier": 2},
    "ft_pct":  {"desc": "Free throw percentage",              "unit": "%",      "range": [0.55, 0.95],"tier": 3},
    "minutes": {"desc": "Minutes per game",                   "unit": "min/g",  "range": [0, 40],    "tier": 2},
    "bpm":     {"desc": "Box Plus/Minus — value above average per 100 poss", "unit": "pts/100", "range": [-5, 12], "tier": 1},
    "per":     {"desc": "Player Efficiency Rating (avg = 15)", "unit": "PER",   "range": [0, 35],    "tier": 1},
    "usg_pct": {"desc": "Usage rate — % of team plays used while on court",  "unit": "%", "range": [0.10, 0.38], "tier": 2},
    "off_rtg": {"desc": "Individual offensive rating",        "unit": "pts/100","range": [95, 130],  "tier": 1},
    "def_rtg": {"desc": "Individual defensive rating",        "unit": "pts/100","range": [95, 125],  "tier": 1},
    "vorp":    {"desc": "Value Over Replacement Player (season)",  "unit": "pts", "range": [-1, 8],  "tier": 1},
    "ws_48":   {"desc": "Win Shares per 48 minutes (avg good player ≈ 0.100)", "unit": "ws/48", "range": [-0.05, 0.25], "tier": 1},
}

# Binary flags
BINARY_META = {
    "is_home":                    {"desc": "1 if this team is the home team",         "unit": "0/1", "range": [0, 1], "tier": 2},
    "is_back_to_back":            {"desc": "1 if this team played yesterday",          "unit": "0/1", "range": [0, 1], "tier": 1},
    "opponent_is_back_to_back":   {"desc": "1 if the opponent played yesterday",       "unit": "0/1", "range": [0, 1], "tier": 1},
}

# Context variables
CONTEXT_META = {
    "match_number":             {"desc": "Game number in the season (1–82)",             "unit": "game #",  "range": [1, 82],    "tier": 3},
    "rest_days":                {"desc": "Days of rest since last game (0=B2B, 1=1 day rest, etc.)", "unit": "days", "range": [0, 10], "tier": 1},
    "opponent_rest_days":       {"desc": "Days of rest for the opponent",                "unit": "days",    "range": [0, 10],    "tier": 1},
    "win_streak":               {"desc": "Current win streak (negative = losing streak)","unit": "games",   "range": [-15, 15],  "tier": 1},
    "home_win_streak":          {"desc": "Current home win/loss streak",                 "unit": "games",   "range": [-10, 10],  "tier": 2},
    "games_last_7_days":        {"desc": "Number of games played in last 7 days (fatigue indicator)", "unit": "games", "range": [1, 5], "tier": 2},
    "days_since_last_home_game":{"desc": "Days since last home game (home comfort)",     "unit": "days",    "range": [0, 21],    "tier": 3},
    "players_available":        {"desc": "Number of available (non-injured) players",   "unit": "players", "range": [7, 15],    "tier": 2},
    "km_traveled":              {"desc": "Kilometers traveled to reach this game",       "unit": "km",      "range": [0, 5000],  "tier": 2},
    "timezone_shift":           {"desc": "Timezone difference vs home city (hours)",    "unit": "hours",   "range": [-3, 3],    "tier": 2},
}

# ─────────────────────────────────────────────────────────────────────────────
# BUILD FULL VARIABLE LIST
# ─────────────────────────────────────────────────────────────────────────────

def build_variable_list() -> list:
    """
    Returns a flat list of variable dicts, one per registry entry.
    Each dict: { name, index, cat, label, desc, unit, range, tier }
    """
    from nba_engine_binding import get_registry
    reg = get_registry()

    results = []

    SPLITS = ["season_stats","last10_stats","last5_stats",
              "home_stats","away_stats","b2b_stats","vs_above500_stats"]
    Q_KEYS = ["pts","fgm","fga","fg_pct","fg3m","fg3a","ast","ftm","fta"]
    CLUTCH_KEYS = ["pts","fgm","fga","fg_pct","fg3m","fg3a","ftm","fta","ast","tov","plus_minus","w_pct"]

    for name, idx in sorted(reg.items(), key=lambda x: x[1]):
        parts = name.split(".", 1)
        prefix = parts[0]
        key    = parts[1] if len(parts) > 1 else ""

        entry = {
            "name":  name,
            "index": idx,
            "cat":   prefix,
            "tier":  3,
            "desc":  f"{name}",
            "unit":  "",
            "range": None,
        }

        # Binary
        if prefix == "binary" and key in BINARY_META:
            m = BINARY_META[key]
            entry.update({"cat":"binary","desc":m["desc"],"unit":m["unit"],"range":m["range"],"tier":m["tier"]})

        # Context
        elif prefix == "context" and key in CONTEXT_META:
            m = CONTEXT_META[key]
            entry.update({"cat":"context","desc":m["desc"],"unit":m["unit"],"range":m["range"],"tier":m["tier"]})

        # Stat splits
        elif prefix in SPLITS and key in STAT_META:
            m = STAT_META[key]
            split_label = {
                "season_stats":      "Season",
                "last10_stats":      "Last 10",
                "last5_stats":       "Last 5",
                "home_stats":        "Home split",
                "away_stats":        "Away split",
                "b2b_stats":         "B2B split",
                "vs_above500_stats": "vs .500+",
            }.get(prefix, prefix)
            entry.update({
                "cat":   prefix,
                "desc":  f"[{split_label}] {m['desc']}",
                "unit":  m["unit"],
                "range": m["range"],
                "tier":  m["tier"],
            })

        # Q1 / Q4 stats
        elif prefix in ("q1_stats","q4_stats") and key in STAT_META:
            m = STAT_META[key]
            label = "Q1" if prefix == "q1_stats" else "Q4"
            entry.update({
                "cat":   prefix,
                "desc":  f"[{label}] {m['desc']}",
                "unit":  m["unit"],
                "range": m["range"],
                "tier":  m["tier"],
            })

        # Clutch stats
        elif prefix == "clutch_stats" and key in STAT_META:
            m = STAT_META[key]
            entry.update({
                "cat":   "clutch_stats",
                "desc":  f"[Clutch] {m['desc']}",
                "unit":  m["unit"],
                "range": m["range"],
                "tier":  m["tier"],
            })

        # Player stats
        elif prefix.startswith("player"):
            slot_str = prefix[6:]  # "0" through "11"
            slot = int(slot_str) if slot_str.isdigit() else 0
            role = ["Starter 1 (best player)", "Starter 2", "Starter 3",
                    "Starter 4", "Starter 5 (5th starter)",
                    "Bench 1 (6th man)", "Bench 2", "Bench 3",
                    "Bench 4", "Bench 5", "Bench 6", "Bench 7 (12th man)"]
            slot_label = role[slot] if slot < len(role) else f"Slot {slot}"
            if key in PLAYER_STAT_META:
                m = PLAYER_STAT_META[key]
                entry.update({
                    "cat":   "player",
                    "desc":  f"[{slot_label}] {m['desc']}",
                    "unit":  m["unit"],
                    "range": m["range"],
                    "tier":  m["tier"],
                })
            else:
                entry["cat"] = "player"

        results.append(entry)

    return results


_VARIABLE_LIST = None

def get_variable_list() -> list:
    global _VARIABLE_LIST
    if _VARIABLE_LIST is None:
        _VARIABLE_LIST = build_variable_list()
    return _VARIABLE_LIST