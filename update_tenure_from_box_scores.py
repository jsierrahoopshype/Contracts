#!/usr/bin/env python3
"""
update_tenure_from_box_scores.py: rebuild tenure_data.json (seasons with the
current team) without stats.nba.com, which does not answer GitHub's runners.

Baseline: tenure_baseline_2025-26.json, the Mar 20 2026 tenure_data.json
(stats.nba.com, correct through 2025-26). Past seasons are never rebuilt.

Current season: nba-player-data's box-score build,
data/stats/rs-season-<end year>.csv (one row per player; TEAM is the team of
his latest game, so after a mid-season trade the new team wins).

Per baseline player:
  - same team as the baseline  -> same joined_season, continuous_seasons + 1
  - a different team           -> joined 2026-27, continuous_seasons 1
  - no game this season yet    -> his baseline line, unchanged
Players with a game this season and no baseline line are added, joined this
season.

Names are matched the way the Contracts page matches them (its norm(): accents
and full stops dropped, spaces collapsed, lowercase; plus its TENURE_ALIASES),
then through the light sheet's HM Codes (NBA name -> HoopsHype name, which
drops Jr./II/III), then by the name without its suffix when only one player
has it. Every match after the first kind is printed, so a wrong one shows.
"""

import csv, hashlib, io, json, os, re, sys, unicodedata, urllib.request
from datetime import datetime, timezone

BASELINE = 'tenure_baseline_2025-26.json'
OUTPUT = 'tenure_data.json'
DATA_BASE = os.environ.get(
    'PLAYER_DATA_BASE', 'https://raw.githubusercontent.com/jsierrahoopshype/nba-player-data/main')
HM_CODES_URL = ('https://docs.google.com/spreadsheets/d/1Wxqb2qD848ZEb0jVpVkJfN4-XzKy5qhOmdWMeFTe1ow'
                '/export?format=csv&gid=1892686525')
UA = {'User-Agent': 'contracts-tenure-bot/1.0'}
# Columns of data/stats/rs-season-YYYY.csv (rows only, the RS Stats layout).
COL_NBA, COL_HH, COL_YEAR, COL_TEAM, COL_GP = 2, 3, 4, 5, 6
MIN_SEASON_ROWS = 100   # fewer means the build is broken, not early season

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
# index.html's TENURE_ALIASES (contract spelling -> tenure spelling), both ways.
PAGE_ALIASES = {
    'nicolas claxton': 'nic claxton', 'santiago aldama': 'santi aldama',
    'herb jones': 'herbert jones', 'cameron payne': 'cam payne',
    'sviatoslav mykhailiuk': 'svi mykhailiuk', 'carlton carrington': 'bub carrington',
    'jeenathan williams': 'nate williams', 'dennis schroeder': 'dennis schroder',
    'david jones': 'david jones-garcia',
}
SUFFIX = re.compile(r'\s+(jr|sr|ii|iii|iv)$')


def norm(s):
    """The Contracts page's norm()."""
    s = unicodedata.normalize('NFD', s or '')
    s = re.sub('[̀-ͯ]', '', s).replace('.', '')
    return re.sub(r'\s+', ' ', s).strip().lower()


def season_str(end_year):
    return f"{end_year - 1}-{str(end_year)[-2:]}"


def current_end_year(now):
    return now.year + 1 if now.month >= 8 else now.year


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode('utf-8')


def load_season(end_year):
    src = os.environ.get('SEASON_CSV') or f"{DATA_BASE}/data/stats/rs-season-{end_year}.csv"
    text = open(src, encoding='utf-8').read() if os.path.exists(src) else get(src)
    load_season.sha256 = hashlib.sha256(text.encode('utf-8')).hexdigest()
    rows = {}
    for r in csv.reader(io.StringIO(text)):
        if len(r) <= COL_GP or r[COL_YEAR].strip() != str(end_year):
            continue
        team = r[COL_TEAM].strip()
        if team not in TEAM_IDS:
            continue
        rows[r[COL_NBA].strip()] = {'nba': r[COL_NBA].strip(), 'hh': r[COL_HH].strip(), 'team': team}
    return rows


def load_hm_codes():
    try:
        rows = list(csv.reader(io.StringIO(get(HM_CODES_URL))))
    except Exception as e:  # optional: the other match kinds still run
        print(f"HM Codes unavailable ({e}); matching without them")
        return {}
    if not rows or [c.strip() for c in rows[0][:2]] != ['NBA Name', 'HH Name']:
        print("HM Codes did not come back as its CSV; matching without them")
        return {}
    return {r[0].strip(): r[1].strip() for r in rows[1:] if len(r) > 1 and r[0].strip() and r[1].strip()}


def build(baseline, season_rows, end_year, hm):
    season = season_str(end_year)
    # Every key a season row can be found by, from the strongest to the weakest.
    by_norm, by_alias, by_hm, by_bare = {}, {}, {}, {}
    for nba, row in season_rows.items():
        for name in (nba, row['hh']):
            by_norm.setdefault(norm(name), row)
        for a, b in PAGE_ALIASES.items():
            if norm(nba) in (a, b) or norm(row['hh']) in (a, b):
                by_alias[a] = by_alias[b] = row
        if nba in hm:
            by_hm.setdefault(norm(hm[nba]), row)
        by_bare.setdefault(SUFFIX.sub('', norm(nba)), []).append(row)

    def find(name):
        n = norm(name)
        if n in by_norm:
            return by_norm[n], None
        if n in by_alias:
            return by_alias[n], 'page alias'
        if name in hm and norm(hm[name]) in by_norm:
            return by_norm[norm(hm[name])], 'HM Codes'
        if n in by_hm:
            return by_hm[n], 'HM Codes'
        bare = by_bare.get(SUFFIX.sub('', n), [])
        if len(bare) == 1:
            return bare[0], 'suffix'
        return None, None

    players, used, notes = {}, set(), []
    for name, old in baseline['players'].items():
        row, how = find(name)
        if row is None:
            players[name] = dict(old)          # no game this season yet
            continue
        used.add(row['nba'])
        if how:
            notes.append(f"  {name} <- {row['nba']} ({how})")
        if row['team'] == old['team']:
            players[name] = {**old, 'continuous_seasons': old['continuous_seasons'] + 1}
        else:
            players[name] = {**old, 'team': row['team'], 'team_id': TEAM_IDS[row['team']],
                             'joined_season': season, 'continuous_seasons': 1}
    for nba, row in season_rows.items():
        if nba not in used:
            players[nba] = {'team': row['team'], 'team_id': TEAM_IDS[row['team']], 'player_id': None,
                            'joined_season': season, 'continuous_seasons': 1}
    players = dict(sorted(players.items(), key=lambda x: (x[1]['team'], -x[1]['continuous_seasons'], x[0])))
    return {
        'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'season': season,
        'source': f"{BASELINE} + nba-player-data rs-season-{end_year}.csv (team of latest game)",
        'players': players,
    }, notes


def main():
    with open(BASELINE) as f:
        baseline = json.load(f)
    end_year = int(os.environ.get('SEASON_END_YEAR') or current_end_year(datetime.now(timezone.utc)))
    rows = load_season(end_year)
    # Runs daily: when neither the box-score file nor the baseline changed
    # since the last run, leave tenure_data.json untouched (no commit).
    inputs = hashlib.sha256((load_season.sha256 + open(BASELINE, 'rb').read().hex()).encode()).hexdigest()
    try:
        with open(OUTPUT) as f:
            if json.load(f).get('inputs_sha256') == inputs:
                print(f"{season_str(end_year)}: box-score file unchanged since the last run, nothing to do")
                return
    except (OSError, ValueError):
        pass
    print(f"{season_str(end_year)}: {len(rows)} players with a game")
    if len(rows) < MIN_SEASON_ROWS:
        print(f"FATAL: fewer than {MIN_SEASON_ROWS} players in the season file, keeping the old file")
        sys.exit(1)
    data, notes = build(baseline, rows, end_year, load_hm_codes())
    if notes:
        print("Matched by alias, HM Codes or suffix:\n" + "\n".join(notes))
    data['inputs_sha256'] = inputs
    if len(data['players']) < len(baseline['players']):
        print("FATAL: fewer players than the baseline, keeping the old file")
        sys.exit(1)
    with open(OUTPUT, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    print(f"Wrote {OUTPUT}: {len(data['players'])} players")


if __name__ == '__main__':
    main()
