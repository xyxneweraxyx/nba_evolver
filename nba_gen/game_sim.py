"""
nba_gen/game_sim.py
===================
Simulates a single NBA game and produces realistic, internally-correlated stats.

Key realism improvements vs v1:
  1. All stats derived from a shared PACE and POSSESSIONS base
  2. Strong correlations: pace→FGA, FGA→pts, oreb→pts_2nd_chance, ast/fgm ratio
  3. Realistic 3PT revolution reflected per-season (higher 3PA in later seasons)
  4. Score variance matching real NBA (games range 85-145 per team)
  5. B2B fatigue affects multiple stat lines coherently
  6. Player archetypes produce position-appropriate stat distributions
"""

from __future__ import annotations
import random
import math
from typing import Dict, List, Optional, Tuple

from .params import (
    B2B_SCORE_PENALTY, GAME_CHAOS_STD, PLAYER_GAME_STD, SCORE_STD_EXTRA,
)
from .teams import _clamp, _gauss, SLOT_ARCHETYPES, SLOT_MINUTES

# ─────────────────────────────────────────────────────────────────────────────
# MATH HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _ri(x: float) -> int:
    return int(round(x))

def _r2(x: float) -> float:
    return round(float(x), 2)

def _r3(x: float) -> float:
    return round(float(x), 3)

def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b else default

# ─────────────────────────────────────────────────────────────────────────────
# WIN PROBABILITY
# ─────────────────────────────────────────────────────────────────────────────

def win_probability(
    home_str: dict,
    away_str: dict,
    home_b2b: bool = False,
    away_b2b: bool = False,
    home_rest: int = 2,
    away_rest: int = 2,
    league: dict = None,  # league_params for this season
) -> float:
    """
    Compute P(home wins) using logistic model on strength difference.
    Calibrated so that:
      - Equal teams → ~59.4% home win (real NBA avg)
      - Elite vs terrible → ~82-88%
      - B2B penalty applied
    """
    # Net rating proxy: off - def, scaled
    h_net = home_str["off_str"] - home_str["def_str"]
    a_net = away_str["off_str"] - away_str["def_str"]
    diff  = (h_net - a_net) * 3.0

    # Home advantage (calibrated to real ~60% home win)
    diff += 0.42

    # B2B penalty
    if home_b2b: diff -= 0.20
    if away_b2b: diff += 0.20

    # Rest differential (each extra day vs opponent = small advantage)
    rest_diff = (home_rest - away_rest)
    diff += rest_diff * 0.05

    # Logistic
    p = 1.0 / (1.0 + math.exp(-diff))
    # Clamp to avoid 100% certainty (real NBA: even best vs worst ~82%)
    return _clamp(p, 0.12, 0.88)

# ─────────────────────────────────────────────────────────────────────────────
# TEAM GAME STATS
# ─────────────────────────────────────────────────────────────────────────────

def simulate_team_game(
    team_str:   dict,
    opp_str:    dict,
    league:     dict,   # season league averages
    won:        bool,
    b2b:        bool = False,
    game_chaos: float = 0.0,  # per-game randomness factor
) -> dict:
    """
    Generate one team's full game stats, correlated and anchored to
    real NBA league averages for the given season.

    Architecture:
      1. Compute PACE → POSSESSIONS
      2. Derive FGA from possessions
      3. Derive shooting %s from team strength + opponent defense
      4. Compute all other stats from the above
      5. Add realistic noise
    """
    # League averages for this season
    lg_pts    = league["pts"]
    lg_fga    = league["fga"]
    lg_fg_pct = league["fg_pct"]
    lg_fg3a   = league["fg3a"]
    lg_fg3_pct= league["fg3_pct"]
    lg_fta    = league["fta"]
    lg_ft_pct = league["ft_pct"]
    lg_oreb   = league["oreb"]
    lg_dreb   = league["dreb"]
    lg_ast    = league["ast"]
    lg_tov    = league["tov"]
    lg_stl    = league["stl"]
    lg_blk    = league["blk"]
    lg_pf     = league["pf"]
    lg_pace   = league["pace"]
    lg_off_rtg= league["off_rtg"]

    # ── Team-specific modifiers (how much better/worse than league avg) ──
    off_mod  = team_str["off_str"] - 0.50     # -0.5 to +0.5
    def_mod  = team_str["def_str"] - 0.50
    pace_mod = team_str["pace_str"] - 0.50

    opp_def  = opp_str["def_str"] - 0.50
    opp_pace = opp_str["pace_str"] - 0.50

    # ── B2B fatigue: reduces efficiency and pace ──
    b2b_factor = -0.03 if b2b else 0.0

    # ── 1. PACE ──
    pace = _gauss(
        lg_pace * (1 + 0.04 * pace_mod + 0.02 * opp_pace + b2b_factor),
        2.5, 84, 116
    )

    # ── 2. POSSESSIONS (both teams have same possessions per game) ──
    poss = max(55, pace * _gauss(0.97, 0.03, 0.88, 1.06))

    # ── 3. FGA (from possessions) ──
    # FGA ≈ poss * 0.92 - oreb_factor (offensive rebounds extend possessions)
    fga = max(70, _ri(poss * _gauss(0.935, 0.025, 0.85, 1.02)))

    # ── 4. 3-POINT attempts ──
    # Ratio of 3PA/FGA grows each season (tracked in league params)
    base_fg3a_rate = lg_fg3a / lg_fga
    # Better offensive teams shoot more 3s
    fg3a_rate  = _clamp(
        _gauss(base_fg3a_rate * (1 + 0.06 * off_mod), 0.03),
        0.22, 0.55
    )
    fg3a = max(0, _ri(fga * fg3a_rate))
    fg2a = max(0, fga - fg3a)

    # ── 5. SHOOTING % ──
    # FG3%: offense quality + opponent defense - noise
    fg3_pct = _clamp(
        _gauss(
            lg_fg3_pct + 0.030 * off_mod - 0.025 * opp_def + b2b_factor * 0.5,
            0.030
        ), 0.27, 0.48
    )
    # FG2%: anchored higher, also affected by defense
    fg2_base = (lg_fg_pct * lg_fga - lg_fg3_pct * lg_fg3a) / max(1, lg_fga - lg_fg3a)
    fg2_pct  = _clamp(
        _gauss(
            fg2_base + 0.035 * off_mod - 0.030 * opp_def + b2b_factor * 0.5,
            0.030
        ), 0.37, 0.66
    )

    fg3m = _ri(fg3a * fg3_pct)
    fg2m = _ri(fg2a * fg2_pct)
    fgm  = fg3m + fg2m
    fg_pct = _r3(_safe_div(fgm, fga))

    # ── 6. FREE THROWS ──
    # FTA rate (FTA per FGA) has been declining in real NBA
    fta_rate = _clamp(
        _gauss(
            (lg_fta / lg_fga) * (1 + 0.04 * off_mod - 0.03 * opp_def),
            0.025
        ), 0.16, 0.42
    )
    fta = max(0, _ri(fga * fta_rate))
    ft_pct = _clamp(_gauss(lg_ft_pct + 0.015 * off_mod, 0.025), 0.62, 0.93)
    ftm = _ri(fta * ft_pct)

    # ── 7. POINTS ──
    pts_raw = fg2m * 2 + fg3m * 3 + ftm
    # Add game chaos (hot/cold shooting nights)
    pts = max(72, _ri(pts_raw * (1 + game_chaos * 0.08) + _gauss(0, SCORE_STD_EXTRA * 0.4)))
    # Winning team tends to have more points
    pts_bonus = _ri(_gauss(4.5 if won else -4.5, 3.0))
    pts = max(72, pts + pts_bonus)

    # ── 8. REBOUNDS ──
    oreb = max(2, _ri(_gauss(
        lg_oreb * (1 + 0.08 * off_mod - 0.06 * opp_def),
        2.0
    )))
    dreb = max(18, _ri(_gauss(
        lg_dreb * (1 + 0.06 * def_mod),
        2.5
    )))
    reb = oreb + dreb
    oreb_pct = _r3(_safe_div(oreb, oreb + dreb))

    # ── 9. ASSISTS ──
    # Correlated with FGM (good teams have higher AST/FGM ratio)
    ast_fgm_ratio = _clamp(
        _gauss(0.595 + 0.08 * off_mod, 0.05),
        0.42, 0.82
    )
    ast = max(14, _ri(fgm * ast_fgm_ratio))

    # ── 10. TURNOVERS ──
    tov = max(7, _ri(_gauss(
        lg_tov * (1 - 0.04 * off_mod + 0.03 * opp_def),
        1.8
    )))

    # ── 11. STEALS & BLOCKS ──
    stl = max(3, _ri(_gauss(
        lg_stl * (1 + 0.06 * def_mod),
        1.3
    )))
    blk = max(1, _ri(_gauss(
        lg_blk * (1 + 0.08 * def_mod),
        1.2
    )))
    blka = max(1, _ri(_gauss(lg_blk * 1.05, 1.2)))
    pf   = max(12, _ri(_gauss(lg_pf, 2.0)))
    pfd  = max(12, _ri(_gauss(lg_pf, 2.0)))

    pm = _ri(_gauss(4.5 if won else -4.5, 9.0, -45, 45))
    ast_tov = _r2(_safe_div(ast, tov))

    # ── 12. ADVANCED ──
    poss_est  = max(1, fga - oreb + tov + 0.44 * fta)
    off_rtg   = _r2(_safe_div(pts, poss_est) * 100)
    # def_rtg filled after both teams generated
    efg_pct   = _r3(_safe_div(fgm + 0.5 * fg3m, fga))
    ts_pct    = _r3(_safe_div(pts, 2 * (fga + 0.44 * fta)))
    tov_pct   = _r3(_safe_div(tov, fga + 0.44 * fta + tov))
    ast_pct   = _r3(_safe_div(ast, fgm))
    dreb_pct  = _r3(1 - oreb_pct)
    pie       = _r3(_clamp(_gauss(0.500 + (0.08 if won else -0.08), 0.055), 0.22, 0.78))

    # ── 13. SITUATIONAL ──
    # Points in paint: correlated with fg2m
    pitp           = max(10, _ri(fg2m * _gauss(1.55, 0.12, 1.1, 2.0)))
    pts_2nd_chance = max(0, _ri(oreb * _gauss(1.05, 0.15, 0.5, 1.8)))
    pts_fb         = max(0, _ri(_gauss(lg_pts * 0.115 * (1 + 0.08 * pace_mod), 2.5)))
    pts_off_tov    = max(0, _ri(_gauss(
        _safe_div(lg_pts * 0.14, max(1, lg_tov)) * opp_str["off_str"] * 25,
        3.0, 4, 30
    )))

    # ── 14. TRACKING ──
    drives           = max(20, _ri(_gauss(42 + 16 * off_mod, 5, 22, 72)))
    catch_shoot_pct  = _r3(_clamp(_gauss(0.375 + 0.07 * off_mod - 0.05 * opp_def, 0.04), 0.22, 0.56))
    pull_up_pct      = _r3(_clamp(_gauss(0.350 + 0.06 * off_mod - 0.04 * opp_def, 0.04), 0.20, 0.52))
    elbow_pts        = max(2, _ri(_gauss(14 + 7 * off_mod, 3)))
    post_pts         = max(1, _ri(_gauss(10 + 5 * off_mod, 3)))
    paint_pts        = max(8, _ri(pitp * _gauss(0.62, 0.07)))
    dist_miles       = _r2(_gauss(215 + 16 * off_mod, 9, 175, 265))
    off_share        = _clamp(_gauss(0.46, 0.02), 0.38, 0.56)
    avg_speed        = _r2(_gauss(4.42 + 0.30 * off_mod, 0.20, 3.8, 5.8))

    # ── 15. HUSTLE ──
    cont_total       = max(8, _ri(_gauss(26 + 8 * def_mod, 5, 10, 50)))
    cont_3pt         = _ri(cont_total * _clamp(_gauss(0.42, 0.06), 0.28, 0.60))
    cont_2pt         = cont_total - cont_3pt
    deflections      = max(3, _ri(_gauss(12 + 4 * def_mod, 3)))
    charges          = max(0, _ri(_gauss(1.4, 0.8, 0, 6)))
    scr_asts         = max(2, _ri(_gauss(10, 2.5)))
    scr_ast_pts      = max(0, _ri(scr_asts * _gauss(2.8, 0.4, 1.6, 4.5)))
    loose            = max(0, _ri(_gauss(4, 1.5)))
    off_bo           = max(0, _ri(oreb * _gauss(0.83, 0.12)))
    def_bo           = max(4, _ri(dreb * _gauss(0.70, 0.10)))
    box_outs         = off_bo + def_bo

    # ── 16. DEFENSE ZONE ──
    # How well the team defends each shooting zone (% allowed to opponent)
    threep_dfgpct    = _r3(_clamp(_gauss(0.355 - 0.045 * def_mod, 0.035), 0.26, 0.47))
    twop_dfgpct      = _r3(_clamp(_gauss(0.495 - 0.055 * def_mod, 0.035), 0.38, 0.62))
    def_rim_pct      = _r3(_clamp(_gauss(0.615 - 0.080 * def_mod, 0.050), 0.44, 0.78))

    return {
        "box": {
            "pts": pts, "fgm": fgm, "fga": fga, "fg_pct": fg_pct,
            "fg3m": fg3m, "fg3a": fg3a, "fg3_pct": _r3(fg3_pct),
            "ftm": ftm, "fta": fta, "ft_pct": _r3(ft_pct),
            "oreb": oreb, "dreb": dreb, "reb": reb,
            "ast": ast, "tov": tov, "stl": stl, "blk": blk,
            "blka": blka, "pf": pf, "pfd": pfd,
            "plus_minus": pm, "ast_tov_ratio": ast_tov,
        },
        "advanced": {
            "off_rtg": off_rtg, "def_rtg": 0.0, "net_rtg": 0.0,
            "pace": _r2(pace),
            "efg_pct": efg_pct, "ts_pct": ts_pct,
            "oreb_pct": oreb_pct, "dreb_pct": dreb_pct,
            "ast_pct": ast_pct, "tov_pct": tov_pct, "pie": pie,
        },
        "situational": {
            "pitp": pitp, "pts_2nd_chance": pts_2nd_chance,
            "pts_fb": pts_fb, "pts_off_tov": pts_off_tov,
        },
        "tracking": {
            "drives": drives,
            "catch_shoot_pct": catch_shoot_pct,
            "pull_up_shot_pct": pull_up_pct,
            "elbow_touch_pts": elbow_pts,
            "post_touch_pts": post_pts,
            "paint_touch_pts": paint_pts,
            "dist_miles": dist_miles,
            "dist_miles_off": _r2(dist_miles * off_share),
            "dist_miles_def": _r2(dist_miles * (1 - off_share)),
            "avg_speed": avg_speed,
            "avg_speed_off": _r2(avg_speed * _clamp(_gauss(0.97, 0.02), 0.90, 1.05)),
            "avg_speed_def": _r2(avg_speed * _clamp(_gauss(1.03, 0.02), 0.95, 1.10)),
        },
        "hustle": {
            "contested_shots": cont_total,
            "contested_shots_2pt": cont_2pt,
            "contested_shots_3pt": cont_3pt,
            "deflections": deflections,
            "charges_drawn": charges,
            "screen_asts": scr_asts,
            "screen_ast_pts": scr_ast_pts,
            "loose_balls_recovered": loose,
            "off_boxouts": off_bo,
            "def_boxouts": def_bo,
            "box_outs": box_outs,
        },
        "defense_zone": {
            "threep_dfgpct": threep_dfgpct,
            "twop_dfgpct": twop_dfgpct,
            "def_rim_pct": def_rim_pct,
        },
        "_pts": pts,
        "_pace": pace,
    }

# ─────────────────────────────────────────────────────────────────────────────
# QUARTER & CLUTCH STATS
# ─────────────────────────────────────────────────────────────────────────────

def simulate_quarter(off_str: dict, opp_def_str: dict, league: dict) -> dict:
    """Simulate one quarter's worth of stats (≈ 1/4 of game)."""
    off_mod = off_str["off_str"] - 0.50
    def_mod = opp_def_str["def_str"] - 0.50
    lg_pts  = league["pts"] / 4
    lg_fga  = league["fga"] / 4

    fga  = max(8, _ri(_gauss(lg_fga, 2.0)))
    fg3a = max(0, min(fga, _ri(_gauss(fga * (league["fg3a"]/league["fga"]), 1.5))))
    fg2a = max(0, fga - fg3a)
    fg3m = _ri(fg3a * _clamp(_gauss(league["fg3_pct"] + 0.04 * off_mod - 0.03 * def_mod, 0.04), 0.20, 0.50))
    fg2m = _ri(fg2a * _clamp(_gauss(0.475 + 0.04 * off_mod - 0.03 * def_mod, 0.04), 0.30, 0.65))
    fgm  = max(fg3m, fg2m + fg3m)
    fta  = max(0, _ri(_gauss(league["fta"] / 4, 1.5)))
    ftm  = _ri(fta * _clamp(_gauss(league["ft_pct"], 0.03), 0.60, 0.95))
    pts  = (fgm - fg3m)*2 + fg3m*3 + ftm
    ast  = max(0, _ri(_gauss(league["ast"] / 4, 1.2)))
    return {
        "pts": pts, "fgm": fgm, "fga": fga, "fg_pct": _r3(_safe_div(fgm,fga)),
        "fg3m": fg3m, "fg3a": fg3a, "ast": ast, "ftm": ftm, "fta": fta,
    }

def simulate_clutch(off_str: dict, opp_def_str: dict, won: bool) -> dict:
    """Simulate clutch stats (last 5 min, game within 5 pts)."""
    off_mod = off_str["off_str"] - 0.50
    def_mod = opp_def_str["def_str"] - 0.50
    clutch  = off_str.get("clutch", 0.50) - 0.50

    fga  = max(3, _ri(_gauss(11, 2.0, 5, 20)))
    fg3a = max(0, min(fga, _ri(_gauss(fga * 0.44, 1.5))))
    fg2a = max(0, fga - fg3a)
    fg3m = _ri(fg3a * _clamp(_gauss(0.35 + 0.05 * off_mod + 0.04 * clutch, 0.05), 0.15, 0.60))
    fg2m = _ri(fg2a * _clamp(_gauss(0.47 + 0.05 * off_mod - 0.04 * def_mod, 0.06), 0.25, 0.70))
    fgm  = max(fg3m, fg2m + fg3m)
    fta  = max(0, _ri(_gauss(4, 1.5, 0, 12)))
    ftm  = _ri(fta * _clamp(_gauss(0.77 + 0.04 * off_mod, 0.05), 0.45, 1.0))
    pts  = (fgm - fg3m)*2 + fg3m*3 + ftm
    ast  = max(0, _ri(_gauss(2.8, 1.2)))
    tov  = max(0, _ri(_gauss(1.6, 0.9, 0, 6)))
    pm   = _ri(_gauss(2.5 if won else -2.5, 5, -15, 15))
    return {
        "pts": pts, "fgm": fgm, "fga": fga, "fg_pct": _r3(_safe_div(fgm,fga)),
        "fg3m": fg3m, "fg3a": fg3a, "ftm": ftm, "fta": fta,
        "ast": ast, "tov": tov, "plus_minus": pm,
        "possessions": max(4, _ri(_gauss(11, 2))),
    }

# ─────────────────────────────────────────────────────────────────────────────
# PLAYER GAME STATS
# ─────────────────────────────────────────────────────────────────────────────

def simulate_player_game(player: dict, team_str: dict, opp_str: dict,
                          league: dict, won: bool) -> dict:
    """
    Simulate one player's game stats.
    Uses archetype weights to produce position-appropriate distributions.
    """
    skill    = player["skill"]
    slot     = player["slot"]
    arch     = player.get("_arch")   # tuple from PLAYER_ARCHETYPES
    if arch is None:
        arch = (0.10, 0.06, 0.10, 0.08, 0.60, 0.10)

    pts_w, ast_w, reb_w, three_w, stl_w, blk_w = arch

    # Expected minutes (with real variance)
    exp_min = SLOT_MINUTES[slot] if slot < len(SLOT_MINUTES) else 5.0
    mins    = _clamp(_gauss(exp_min, exp_min * 0.18), 0, 48)
    mf      = mins / 36.0   # minute factor

    # Per-game performance factor (good nights / bad nights)
    perf = _clamp(_gauss(1.0, PLAYER_GAME_STD), 0.25, 2.0)

    # Points
    lg_pts_per_player = league["pts"] / 5   # ~20-23 for a "share"
    pts_base = lg_pts_per_player * pts_w * 5 * skill * mf * perf
    pts = max(0, _ri(_gauss(pts_base, pts_base * 0.30)))

    # Shooting profile (3PT shooters vs finishers)
    fg3a_ratio = _clamp(_gauss(three_w * 3.5, 0.08), 0, 0.80)
    total_fga = max(0, _ri(pts / max(0.1, _gauss(1.10, 0.08))))  # pts per shot attempt
    fg3a = max(0, _ri(total_fga * fg3a_ratio))
    fg2a = max(0, total_fga - fg3a)
    fg3_pct = _clamp(_gauss(league["fg3_pct"] + 0.04 * skill - 0.02, 0.04), 0.20, 0.52)
    fg2_pct = _clamp(_gauss(0.490 + 0.08 * skill, 0.04), 0.30, 0.70)
    fg3m = _ri(fg3a * fg3_pct)
    fg2m = _ri(fg2a * fg2_pct)
    fgm  = max(fg3m, fg2m + fg3m)

    # Free throws
    fta     = max(0, _ri(_gauss(pts * 0.18 * (1 + 0.1 * skill), 1.0)))
    ft_pct  = _clamp(_gauss(0.70 + 0.18 * skill, 0.04), 0.45, 0.98)
    ftm     = _ri(fta * ft_pct)

    # Rebounds (by archetype)
    reb_base = (league["oreb"] + league["dreb"]) / 5 * reb_w * 5 * skill * mf
    reb  = max(0, _ri(_gauss(reb_base, reb_base * 0.35)))
    oreb = max(0, _ri(reb * _clamp(_gauss(0.25, 0.07), 0, 0.60)))
    dreb = max(0, reb - oreb)

    # Assists
    ast_base = league["ast"] / 5 * ast_w * 5 * skill * mf * perf
    ast  = max(0, _ri(_gauss(ast_base, ast_base * 0.40)))

    # Steals, blocks, turnovers, fouls
    stl  = max(0, _ri(_gauss(stl_w * 2.5 * skill * mf, 0.5)))
    blk  = max(0, _ri(_gauss(blk_w * 2.0 * skill * mf, 0.4)))
    tov  = max(0, _ri(_gauss(1.5 + 1.5 * skill * mf * (ast_w * 5), 0.7)))
    pf   = max(0, _ri(_gauss((2.5 + 0.5 * skill) * mf, 0.7)))

    # Advanced
    efg_pct  = _r3(_safe_div(fgm + 0.5 * fg3m, max(1, total_fga)))
    ts_pct   = _r3(_safe_div(pts, 2 * (total_fga + 0.44 * fta) + 0.001))
    usg_pct  = _r3(_clamp(_gauss(0.12 + 0.22 * skill, 0.04), 0.04, 0.46))
    bpm      = _r2(_gauss(-2 + skill * 12, 2, -10, 16))
    per      = _r2(_gauss(6 + skill * 24, 3, 0, 40))
    pm       = _ri(_gauss(3 if won else -3, 7, -30, 30))
    off_rtg  = _r2(_gauss(95 + skill * 28, 8, 68, 150))
    def_rtg  = _r2(_gauss(120 - skill * 18, 8, 90, 148))
    vorp     = _r2(_clamp(_gauss(-0.5 + skill * 4.5, 0.9), -3.0, 9.0))
    ws_48    = _r3(_clamp(_gauss(-0.04 + skill * 0.28, 0.055), -0.15, 0.38))

    return {
        "slot": slot,
        "archetype": player["archetype"],
        "available": 1,
        "minutes": _r2(mins),
        "box": {
            "pts": pts, "reb": reb, "oreb": oreb, "dreb": dreb,
            "ast": ast, "stl": stl, "blk": blk, "tov": tov, "pf": pf,
            "fgm": fgm, "fga": total_fga, "fg_pct": _r3(_safe_div(fgm, max(1, total_fga))),
            "fg3m": fg3m, "fg3a": fg3a, "fg3_pct": _r3(fg3_pct),
            "ftm": ftm, "fta": fta, "ft_pct": _r3(ft_pct),
        },
        "advanced": {
            "efg_pct": efg_pct, "ts_pct": ts_pct,
            "usg_pct": usg_pct, "bpm": bpm, "per": per,
            "plus_minus": pm, "off_rtg": off_rtg, "def_rtg": def_rtg,
            "vorp": vorp, "ws_48": ws_48,
        },
        "tracking": {
            "drives":             max(0, _ri(_gauss(3 + skill * 8, 2))),
            "pull_up_pts":        max(0, _ri(_gauss(2 + skill * 7, 2))),
            "catch_shoot_pct":    _r3(_clamp(_gauss(0.36 + skill * 0.09, 0.05), 0.15, 0.68)),
            "contested_shot_pct": _r3(_clamp(_gauss(0.44, 0.08), 0.18, 0.78)),
            "avg_speed":          _r2(_clamp(_gauss(4.20 + skill * 0.85, 0.30), 3.0, 6.5)),
        },
    }
