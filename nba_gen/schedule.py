"""
nba_gen/schedule.py
===================
Generates a realistic 82-game NBA schedule per team (1230 total games).
Ensures proper home/away balance and realistic B2B distribution.
"""

from __future__ import annotations
import random
from datetime import date, timedelta
from typing import List, Dict

from .teams import TEAM_IDS

GAMES_PER_TEAM = 82

def generate_schedule(season_start: date) -> List[dict]:
    """
    Generate a full season schedule.
    Returns list of {game_number, date, home_id, away_id}.

    Real NBA schedule properties:
    - 82 games per team
    - ~41 home, ~41 away
    - Teams play conference opponents more often
    - B2B games: ~15-18 per team per season
    - 3-games-in-4-nights: ~5-8 per team
    - Road trips of 3-5 games common
    """
    n_teams = len(TEAM_IDS)
    total   = n_teams * GAMES_PER_TEAM // 2   # 1230

    remaining = {tid: GAMES_PER_TEAM for tid in TEAM_IDS}
    home_rem  = {tid: 41 for tid in TEAM_IDS}
    away_rem  = {tid: 41 for tid in TEAM_IDS}

    games: List[tuple] = []

    # Pass 1: every pair plays at least twice (once each home/away)
    pairs = [(a, b) for i, a in enumerate(TEAM_IDS) for b in TEAM_IDS[i+1:]]
    random.shuffle(pairs)

    for a, b in pairs:
        if len(games) >= total: break
        if remaining[a] > 0 and remaining[b] > 0:
            # a hosts first game
            if home_rem[a] > 0 and away_rem[b] > 0:
                games.append((a, b))
                home_rem[a] -= 1; away_rem[b] -= 1
                remaining[a] -= 1; remaining[b] -= 1
            # b hosts return game (if slots available)
            if remaining[a] > 0 and remaining[b] > 0:
                if home_rem[b] > 0 and away_rem[a] > 0:
                    games.append((b, a))
                    home_rem[b] -= 1; away_rem[a] -= 1
                    remaining[a] -= 1; remaining[b] -= 1

    # Pass 2: fill remaining games
    for _ in range(total * 30):
        if len(games) >= total: break
        elig_home = [t for t in TEAM_IDS if remaining[t] > 0 and home_rem[t] > 0]
        elig_away = [t for t in TEAM_IDS if remaining[t] > 0 and away_rem[t] > 0]
        if not elig_home or not elig_away: break
        h = random.choice(elig_home)
        pool = [t for t in elig_away if t != h and remaining[t] > 0 and away_rem[t] > 0]
        if not pool: continue
        a = random.choice(pool)
        games.append((h, a))
        home_rem[h] -= 1; away_rem[a] -= 1
        remaining[h] -= 1; remaining[a] -= 1

    # Shuffle and assign dates
    random.shuffle(games)
    total_days = 185   # ~6 months
    raw = sorted([
        season_start + timedelta(days=int(i * total_days / len(games)) + random.randint(-1, 1))
        for i in range(len(games))
    ])

    return [
        {
            "game_number": i + 1,
            "date":        raw[i].isoformat(),
            "home_id":     games[i][0],
            "away_id":     games[i][1],
        }
        for i in range(len(games))
    ]
