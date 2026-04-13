#!/usr/bin/env python3
"""
generate_nba_data_v3.py — NBA Synthetic Data Generator v3
===========================================================
Generates realistic synthetic NBA game data anchored on real league averages.

Key improvements vs v2:
  - Stats anchored to real NBA league averages by season (with interpolation)
  - Realistic team strength distribution (elite/good/average/bad/terrible tiers)
  - All stats internally correlated via shared pace/possessions base
  - 3-point revolution trend properly modeled (20→36 3PA/game 2013→2024)
  - Realistic home win% (~59.4%, not 70%+)
  - Player archetypes (position-appropriate stat profiles)
  - Better variance: real NBA games range 85-145 pts per team
  - Proper fatigue effects on multiple stats simultaneously

Output structure:
  nba_data/
    training/{season}/*.json    (8 seasons, 2013-14 to 2021-22)
    testing/{season}/*.json     (2 seasons, 2022-23 to 2023-24)
    meta/teams.json
    meta/strengths.json
    meta/league_params.json

Usage:
  python generate_nba_data_v3.py
  python generate_nba_data_v3.py --output ./my_data --seed 123
"""

import argparse
import json
import os
import random
import time
from datetime import date

from nba_gen.params import (
    ALL_SEASONS, TRAINING_SEASONS, TESTING_SEASONS,
    SEASON_STARTS, OUTPUT_DIR, GAMES_PER_TEAM,
    GAME_CHAOS_STD, GOOD_TEAM_LATE_BONUS, BAD_TEAM_LATE_PENALTY,
    league_params_for_season,
)
from nba_gen.teams import (
    TEAMS, TEAM_IDS, TEAM_BY_ID,
    generate_team_strengths, evolve_team_strengths,
    generate_roster,
)
from nba_gen.schedule import generate_schedule
from nba_gen.game_sim import (
    win_probability, simulate_team_game,
    simulate_player_game, simulate_quarter, simulate_clutch,
)
from nba_gen.state import TeamState, flatten

# ─────────────────────────────────────────────────────────────────────────────
# SEASON SIMULATION
# ─────────────────────────────────────────────────────────────────────────────

def simulate_season(season: str, strengths: dict, set_name: str,
                    output_dir: str) -> int:
    league = league_params_for_season(season)
    season_start = SEASON_STARTS[season]

    print(f"  [{set_name.upper()}] {season}")
    print(f"    League: pts={league['pts']:.1f}  3PA={league['fg3a']:.1f}"
          f"  pace={league['pace']:.1f}  OffRtg={league['off_rtg']:.1f}")

    # Generate rosters
    rosters = {tid: generate_roster(tid, strengths[tid]) for tid in TEAM_IDS}
    states  = {tid: TeamState(tid, rosters[tid])          for tid in TEAM_IDS}

    # Generate schedule
    schedule = generate_schedule(season_start)
    print(f"    Simulating {len(schedule)} games...")

    out_dir = os.path.join(output_dir, set_name, season)
    os.makedirs(out_dir, exist_ok=True)

    # Sort schedule by date so team states build up chronologically
    schedule_sorted = sorted(schedule, key=lambda g: g["date"])

    for gi, game_info in enumerate(schedule_sorted):
        home_id  = game_info["home_id"]
        away_id  = game_info["away_id"]
        dt_str   = game_info["date"]
        gnum     = game_info["game_number"]

        hs  = states[home_id]
        as_ = states[away_id]

        home_rest = hs.rest_days(dt_str)
        away_rest = as_.rest_days(dt_str)
        home_b2b  = home_rest <= 1
        away_b2b  = away_rest <= 1

        # Season-phase adjustments (late-season form)
        home_str = dict(strengths[home_id])
        away_str = dict(strengths[away_id])
        match_num_home = hs.gp() + 1
        if match_num_home > 55:
            tier = home_str.get("tier", "average")
            if tier in ("elite", "good"):
                home_str["off_str"] = min(1.0, home_str["off_str"] + GOOD_TEAM_LATE_BONUS)
            elif tier in ("bad", "terrible"):
                home_str["def_str"] = max(0.05, home_str["def_str"] + BAD_TEAM_LATE_PENALTY)

        match_num_away = as_.gp() + 1
        if match_num_away > 55:
            tier = away_str.get("tier", "average")
            if tier in ("elite", "good"):
                away_str["off_str"] = min(1.0, away_str["off_str"] + GOOD_TEAM_LATE_BONUS)
            elif tier in ("bad", "terrible"):
                away_str["def_str"] = max(0.05, away_str["def_str"] + BAD_TEAM_LATE_PENALTY)

        # vs_above500 context
        home_opp_above500 = as_.current_w_pct() >= 0.500
        away_opp_above500 = hs.current_w_pct() >= 0.500

        # ── Pre-game snapshots (STRICTLY no look-ahead) ──────────────────────
        home_snap = _build_snapshot(hs, dt_str, home_id, True,  home_b2b,
                                    away_rest, home_opp_above500)
        away_snap = _build_snapshot(as_, dt_str, home_id, False, away_b2b,
                                    home_rest, away_opp_above500)

        # ── Determine winner ─────────────────────────────────────────────────
        p_hw   = win_probability(home_str, away_str, home_b2b, away_b2b,
                                  home_rest, away_rest, league)
        home_w = random.random() < p_hw

        # Per-game chaos factor (hot/cold shooting nights for both teams)
        game_chaos = random.gauss(0, GAME_CHAOS_STD)

        # ── Simulate team game stats ─────────────────────────────────────────
        h_gs = simulate_team_game(home_str, away_str, league,
                                   won=home_w,     b2b=home_b2b,
                                   game_chaos=game_chaos)
        a_gs = simulate_team_game(away_str, home_str, league,
                                   won=not home_w, b2b=away_b2b,
                                   game_chaos=-game_chaos * 0.5)

        # Ensure winner has strictly more points
        if home_w:
            if a_gs["_pts"] >= h_gs["_pts"]:
                a_gs["box"]["pts"] = max(72, h_gs["_pts"] - random.randint(1, 14))
        else:
            if h_gs["_pts"] >= a_gs["_pts"]:
                h_gs["box"]["pts"] = max(72, a_gs["_pts"] - random.randint(1, 14))

        # Cross-fill ratings (def_rtg = opponent's off_rtg)
        h_gs["advanced"]["def_rtg"] = a_gs["advanced"]["off_rtg"]
        a_gs["advanced"]["def_rtg"] = h_gs["advanced"]["off_rtg"]
        h_gs["advanced"]["net_rtg"] = round(h_gs["advanced"]["off_rtg"] - h_gs["advanced"]["def_rtg"], 2)
        a_gs["advanced"]["net_rtg"] = round(a_gs["advanced"]["off_rtg"] - a_gs["advanced"]["def_rtg"], 2)

        # ── Quarter + clutch ─────────────────────────────────────────────────
        h_q1 = simulate_quarter(home_str, away_str, league)
        h_q4 = simulate_quarter(home_str, away_str, league)
        a_q1 = simulate_quarter(away_str, home_str, league)
        a_q4 = simulate_quarter(away_str, home_str, league)
        h_cl = simulate_clutch(home_str, away_str, home_w)
        a_cl = simulate_clutch(away_str, home_str, not home_w)

        # ── Player games ─────────────────────────────────────────────────────
        h_players = [simulate_player_game(p, home_str, away_str, league, home_w)
                     for p in rosters[home_id]]
        a_players = [simulate_player_game(p, away_str, home_str, league, not home_w)
                     for p in rosters[away_id]]

        # ── Update running states ────────────────────────────────────────────
        h_flat = flatten(h_gs)
        a_flat = flatten(a_gs)

        hs.record_game(h_flat, home_w, dt_str, True, home_b2b,
                       home_opp_above500, home_id, h_q1, h_q4, h_cl)
        as_.record_game(a_flat, not home_w, dt_str, False, away_b2b,
                        away_opp_above500, home_id, a_q1, a_q4, a_cl)

        for pp in h_players: hs.record_player(pp["slot"], pp)
        for pp in a_players: as_.record_player(pp["slot"], pp)

        # ── Write game file ──────────────────────────────────────────────────
        game_id = f"{season}_{gnum:04d}"
        record  = {
            "meta": {
                "game_id":     game_id,
                "date":        dt_str,
                "season":      season,
                "set":         set_name,
                "game_number": gnum,
            },
            "result": {
                "winner":    "home" if home_w else "away",
                "home_pts":  h_gs["box"]["pts"],
                "away_pts":  a_gs["box"]["pts"],
            },
            "home": home_snap,
            "away": away_snap,
        }

        fpath = os.path.join(out_dir, f"{game_id}.json")
        with open(fpath, "w") as f:
            json.dump(record, f, separators=(",", ":"))

        if (gi + 1) % 250 == 0:
            print(f"    ... {gi+1}/{len(schedule)}")

    n = len(schedule)
    print(f"    Wrote {n} files -> {out_dir}")
    return n

# ─────────────────────────────────────────────────────────────────────────────
# PRE-GAME SNAPSHOT
# ─────────────────────────────────────────────────────────────────────────────

def _build_snapshot(state: TeamState, today: str, home_id: int,
                    is_home: bool, is_b2b: bool,
                    opp_rest: int, opp_above500: bool) -> dict:
    rest = state.rest_days(today)
    km   = state.km_traveled(home_id)
    tz   = state.tz_shift_val(home_id)
    dlh  = state.days_since_last_home(today)

    player_entries = []
    for p in state.roster:
        slot  = p["slot"]
        avail = int(random.random() < p["available_prob"])
        player_entries.append({
            "slot":       slot,
            "archetype":  p["archetype"],
            "available":  avail,
            "season_avg": state.player_avgs(slot),
            "last10_avg": state.player_avgs(slot, 10),
            "last5_avg":  state.player_avgs(slot, 5),
        })

    return {
        "team_id": state.team_id,
        "binary": {
            "is_home":                  int(is_home),
            "is_back_to_back":          int(is_b2b),
            "opponent_is_back_to_back": int(opp_rest <= 1),
        },
        "context": {
            "match_number":              state.gp() + 1,
            "rest_days":                 rest,
            "opponent_rest_days":        opp_rest,
            "win_streak":                state.win_streak(),
            "home_win_streak":           state.home_win_streak(),
            "games_last_7_days":         state.games_last_n_days(today, 7),
            "days_since_last_home_game": dlh,
            "players_available":         sum(1 for pe in player_entries if pe["available"]),
            "km_traveled":               km,
            "timezone_shift":            tz,
        },
        "season_stats":      state.season_avgs(),
        "last10_stats":      state.last_n_avgs(10),
        "last5_stats":       state.last_n_avgs(5),
        "home_stats":        state.home_avgs(),
        "away_stats":        state.away_avgs(),
        "b2b_stats":         state.b2b_avgs(),
        "vs_above500_stats": state.vs_above500_avgs(),
        "q1_stats":          state.q1_avgs(),
        "q4_stats":          state.q4_avgs(),
        "clutch_stats":      state.clutch_avgs(),
        "players":           player_entries,
    }

# ─────────────────────────────────────────────────────────────────────────────
# META OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

def write_meta(strengths_log: dict, league_log: dict, output_dir: str):
    meta = os.path.join(output_dir, "meta")
    os.makedirs(meta, exist_ok=True)
    with open(os.path.join(meta, "teams.json"), "w") as f:
        json.dump(TEAMS, f, indent=2)
    with open(os.path.join(meta, "strengths.json"), "w") as f:
        json.dump(strengths_log, f, indent=2)
    with open(os.path.join(meta, "league_params.json"), "w") as f:
        json.dump(league_log, f, indent=2)
    print(f"  Meta -> {meta}")

# ─────────────────────────────────────────────────────────────────────────────
# SANITY CHECK
# ─────────────────────────────────────────────────────────────────────────────

def sanity_check(output_dir: str):
    """Print key stats from a random game to verify realism."""
    import glob
    files = glob.glob(os.path.join(output_dir, "training", "**", "*.json"),
                      recursive=True)
    if not files: return
    sample_file = files[len(files) // 3]
    with open(sample_file) as f:
        g = json.load(f)

    h = g["home"]
    ss = h.get("season_stats") or {}

    print(f"\n  Sample: {g['meta']['game_id']}  date={g['meta']['date']}")
    print(f"  Result: home {g['result']['home_pts']} — away {g['result']['away_pts']}")
    print(f"  Match # {h['context']['match_number']}, "
          f"rest={h['context']['rest_days']}d, "
          f"streak={h['context']['win_streak']}")
    if ss:
        print(f"  Season avg: pts={ss.get('pts')} "
              f"fg3a={ss.get('fg3a')} "
              f"pace={ss.get('pace')} "
              f"off_rtg={ss.get('off_rtg')} "
              f"w_pct={ss.get('w_pct')}")

    # Home win % across all training data
    training_dir = os.path.join(output_dir, "training")
    all_files = glob.glob(os.path.join(training_dir, "**", "*.json"), recursive=True)
    total = len(all_files)
    home_wins = 0
    pts_list  = []
    for fp in all_files[:3000]:   # sample for speed
        with open(fp) as f:
            rec = json.load(f)
        if rec["result"]["winner"] == "home":
            home_wins += 1
        pts_list.append(rec["result"]["home_pts"])
        pts_list.append(rec["result"]["away_pts"])

    print(f"\n  === REALISM CHECK (sample 3000 games) ===")
    print(f"  Home win %: {home_wins/3000:.3f}  (real NBA: ~0.594)")
    print(f"  Avg team score: {sum(pts_list)/len(pts_list):.1f}  (expect ~100-115 by season)")
    print(f"  Score range: {min(pts_list)} - {max(pts_list)}")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NBA Synthetic Data Generator v3")
    parser.add_argument("--output", default=OUTPUT_DIR,
                        help=f"Output directory (default: {OUTPUT_DIR})")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip seasons that already have output files")
    args = parser.parse_args()

    random.seed(args.seed)
    t_start = time.time()

    print("=" * 62)
    print("  NBA Synthetic Data Generator v3")
    print("  Anchored on real NBA league averages 2013-2024")
    print("=" * 62)

    import shutil
    if not args.skip_existing and os.path.exists(args.output):
        shutil.rmtree(args.output)
    os.makedirs(args.output, exist_ok=True)

    strengths      = generate_team_strengths()
    strengths_log  = {}
    league_log     = {}
    total_files    = 0

    for season in ALL_SEASONS:
        set_name  = "training" if season in TRAINING_SEASONS else "testing"
        league    = league_params_for_season(season)
        strengths_log[season] = {str(k): v for k, v in strengths.items()}
        league_log[season]    = {k: round(v, 4) for k, v in league.items()}

        t0 = time.time()
        n  = simulate_season(season, strengths, set_name, args.output)
        total_files += n
        print(f"    Time: {time.time()-t0:.1f}s\n")

        strengths = evolve_team_strengths(strengths)

    write_meta(strengths_log, league_log, args.output)

    elapsed = time.time() - t_start
    print("=" * 62)
    print(f"  Done! {total_files:,} game files in {args.output}/")
    print(f"  Total time: {elapsed:.1f}s")
    print("=" * 62)

    sanity_check(args.output)


if __name__ == "__main__":
    main()
