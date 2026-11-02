#!/usr/bin/env python3
"""
update_tenure_from_player_data.py: build tenure_data.json (seasons with the
current team) from nba-player-data's public rsStats.json instead of
stats.nba.com, which does not answer GitHub's runners.

rsStats.json has one row per player, season and team (YEAR is the season's
end year: 2027 = 2026-27). The rules are the ones update_tenure.py used:
  - current season = the latest YEAR in the file; a player's current team is
    his team that season (the one with more games if he played for two)
  - walk back one season at a time: tenure extends while he has a row with
    that same team; a season with no row, or only other teams, ends it

Output keeps the same fields the Contracts page reads (joined_season,
continuous_seasons) plus team, team_id and player_id (carried over from the
previous file by name, since rsStats.json has no NBA ids).
"""

import json, os, sys, urllib.request
from collections import defaultdict
from datetime import datetime, timezone

SOURCE = os.environ.get(
    'RS_STATS_URL',
    'https://raw.githubusercontent.com/jsierrahoopshype/nba-player-data/main/rsStats.json')
OUTPUT = 'tenure_data.json'
MIN_PLAYERS = 300  # refuse to write a list that looks truncated

TEAM_IDS = {
    'ATL': 1610612737, 'BOS': 1610612738, 'BKN': 1610612751, 'CHA': 1610612766,
    'CHI': 1610612741, 'CLE': 1610612739, 'DAL': 1610612742, 'DEN': 1610612743,
    'DET': 1610612765, 'GSW': 1610612744, 'HOU': 1610612745, 'IND': 1610612754,
    'LAC': 1610612746, 'LAL': 1610612747, 'MEM': 1610612763, 'MIA': 1610612748,
    'MIL': 1610612749, 'MIN': 1610612750, 'NOP': 1610612740, 'NYK': 1610612752,
    'OKC': 1610612760, 'ORL': 1610612753, 'PHI': 1610612755, 'PHX': 1610612756,
    'POR': 1610612757, 'SAC': 1610612758, 'SAS': 1610612759, 'TOR': 1610612761,
    'UTA': 1610612762, 'WAS': 1610612764,
}


def season_str(end_year):
    """2027 -> '2026-27'"""
    return f"{end_year - 1}-{str(end_year)[-2:]}"


def load_rows(src):
    if os.path.exists(src):
        with open(src) as f:
            return json.load(f)
    req = urllib.request.Request(src, headers={'User-Agent': 'contracts-tenure-bot/1.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def build(rows, previous=None):
    # (player, year) -> {team: games}
    teams = defaultdict(dict)
    for r in rows:
        try:
            year = int(r['YEAR'])
            gp = int(float(r.get('GP') or 0))
        except (KeyError, ValueError):
            continue
        name, team = (r.get('PLAYER') or '').strip(), (r.get('TEAM') or '').strip()
        if not name or team not in TEAM_IDS:
            continue
        teams[(name, year)][team] = teams[(name, year)].get(team, 0) + gp

    current = max(y for (_, y) in teams)
    prev_ids = {n: v.get('player_id') for n, v in ((previous or {}).get('players') or {}).items()}
    out = {}
    for (name, year), by_team in teams.items():
        if year != current:
            continue
        team = max(sorted(by_team), key=lambda t: by_team[t])  # more games wins
        joined = current
        while team in teams.get((name, joined - 1), {}):
            joined -= 1
        out[name] = {
            'team': team,
            'team_id': TEAM_IDS[team],
            'player_id': prev_ids.get(name),
            'joined_season': season_str(joined),
            'continuous_seasons': current - joined + 1,
        }
    players = dict(sorted(out.items(), key=lambda x: (x[1]['team'], -x[1]['continuous_seasons'], x[0])))
    return {
        'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'season': season_str(current),
        'source': 'nba-player-data rsStats.json',
        'players': players,
    }


def main():
    previous = None
    if os.path.exists(OUTPUT):
        with open(OUTPUT) as f:
            previous = json.load(f)
    data = build(load_rows(SOURCE), previous)
    n = len(data['players'])
    print(f"{data['season']}: {n} players")
    if n < MIN_PLAYERS:
        print(f"FATAL: only {n} players (minimum {MIN_PLAYERS}), keeping the old file")
        sys.exit(1)
    with open(OUTPUT, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    print(f"Wrote {OUTPUT}")


if __name__ == '__main__':
    main()
