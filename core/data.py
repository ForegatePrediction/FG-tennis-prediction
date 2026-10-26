"""Validated TennisMyLife ingestion. Tournament-only dates are never match times."""
import collections
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {'tourney_id', 'tourney_date', 'winner_id', 'loser_id', 'winner_name',
            'loser_name', 'score', 'surface', 'best_of', 'winner_rank', 'loser_rank'}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def read_csv(raw, allow_empty=False):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if not REQUIRED.issubset(reader.fieldnames or []):
        raise ValueError('Missing required CSV fields; refuse HTML/error/incomplete source')
    rows = list(reader)
    if not rows and not allow_empty:
        raise ValueError('Empty source CSV')
    for row in rows:
        if not row['winner_id'] or not row['loser_id'] or row['winner_id'] == row['loser_id']:
            raise ValueError('Invalid player IDs')
        dt.datetime.strptime(row['tourney_date'], '%Y%m%d')
    return rows


def number(value, default=None):
    try:
        out = float(value)
        return out if out == out and abs(out) < 1e10 else default
    except (ValueError, TypeError):
        return default


def regular_score(row):
    score = row.get('score', '').strip()
    if re.search(r'RET|W/O|DEF|ABN|ABD|WALK|UNFIN|\[', score, re.I):
        return False
    if int(row.get('best_of') or 0) not in (3, 5):
        return False
    tokens = score.split()
    sets = []
    for token in tokens:
        match = re.fullmatch(r'(\d+)-(\d+)(?:\(\d+\))?', token)
        if not match:
            return False
        a, b = map(int, match.groups())
        hi, lo = max(a, b), min(a, b)
        if not (hi == 6 and lo <= 4 or hi == 7 and lo in (5, 6) or hi >= 8 and hi - lo == 2):
            return False
        sets.append((a, b))
    target = (int(row['best_of']) + 1) // 2
    return sum(a > b for a, b in sets) == target and sum(b > a for a, b in sets) < target


def load_tour(tour, as_of, root=ROOT, scope='main_tour'):
    """Return pre-event feature times and conservative result-availability times.

    The publisher defines tourney_date as the tournament week. Even if a file
    contains multiple dates, that alone cannot certify actual match times.
    Release a whole event after its conservative duration window and last source
    date. Every match uses pre-event history. No in-event updates are assumed.
    """
    end = dt.date.fromisoformat(as_of).toordinal()
    if scope not in ('main_tour','expanded_atp') or scope=='expanded_atp' and tour!='atp':raise ValueError('Unsupported data scope')
    directory = Path(root) / 'data/raw' / tour
    paths=list(directory.glob('*.csv'))
    if scope=='expanded_atp':
        extra=Path(root)/'data/expanded'
        paths+=list(extra.glob('*_challenger.csv'))+list((extra/'atp_quali').glob('*_atp_quali.csv'))
    rows_by_key = {}
    audit = collections.Counter()
    for path in sorted(paths):
        raw = path.read_bytes()
        for row in read_csv(raw, allow_empty=path.name in ('ongoing_tourneys.csv', 'wta_ongoing_tourneys.csv')):
            audit['raw_rows'] += 1
            level=row.get('tourney_level','').upper()
            if level in (('D','S') if scope=='expanded_atp' else ('C','D','S')):
                audit['excluded_team_challenger_special'] += 1
                continue
            row['_competition']=('atp_qualifying' if path.parent.name=='atp_quali' or row.get('round') in ('Q1','Q2','Q3','Q4') else
                                 'challenger_main_draw' if level=='C' else 'main_tour')
            if any(name in row.get('tourney_name','').lower() for name in ('laver cup','united cup','hopman','billie jean','bjk cup')):
                audit['excluded_team_challenger_special'] += 1
                continue
            if 'next gen' in row.get('tourney_name', '').lower() or not regular_score(row):
                audit['excluded_retirement_walkover_or_nonstandard'] += 1
                continue
            if row.get('surface', '').title() not in ('Hard', 'Clay', 'Grass', 'Carpet'):
                audit['excluded_unknown_surface'] += 1
                continue
            key = (row['tourney_id'], row['match_num'], row['winner_id'], row['loser_id'])
            if scope=='expanded_atp':key+=(row['_competition'],row.get('round',''))
            if key in rows_by_key:
                prior = rows_by_key[key]
                if prior['score'] != row['score']:
                    raise ValueError('Conflicting duplicated result: ' + str(key))
                audit['duplicates'] += 1
            rows_by_key[key] = row
    groups = collections.defaultdict(list)
    for row in rows_by_key.values():
        groups[row['tourney_id']].append(row)
    matches = []
    tournaments = []
    for identifier, rows in groups.items():
        dates = [dt.datetime.strptime(r['tourney_date'], '%Y%m%d').date().toordinal() for r in rows]
        start = min(dates)
        precise = False
        levels={r.get('tourney_level','').upper() for r in rows}
        # Slams can start on Sunday and end 14 days later; two-week Masters
        # must never use the ordinary one-week release assumption.
        window=15 if 'G' in levels else 14 if levels & {'M','1000','PM','P'} else 8 if 'F' in levels else 7
        release = max(max(dates)+1, start+window)
        accepted_here = 0
        for row, day in zip(rows, dates):
            available = day + 1 if precise else release
            if day > end or available > end:
                audit['not_yet_safely_available'] += 1
                continue
            a, b = sorted((row['winner_id'], row['loser_id']))
            suffix=':'+row['_competition']+':'+row.get('round','') if scope=='expanded_atp' else ''
            match = {'id': f'{tour}:{identifier}:{row["match_num"]}:{a}:{b}'+suffix,
                     'tour': tour, 'event': identifier, 'event_name': row['tourney_name'],
                     'start': start, 'source_day': day, 'available': available,
                     'date_precision': 'day' if precise else 'tournament',
                     'surface': row['surface'].title(), 'best_of': int(row['best_of']),
                     'a': a, 'b': b, 'y': int(a == row['winner_id']), 'raw': row}
            matches.append(match)
            accepted_here += 1
            audit['accepted'] += 1
            audit['accepted_with_both_rankings'] += int(all(number(row.get(p+'_rank'),0)>0 for p in ('winner','loser')))
            audit['accepted_with_point_totals'] += int(all(number(row.get(p+'_svpt'),0)>0 for p in ('w','l')))
            audit['accepted_with_minutes'] += int(number(row.get('minutes'),0)>0)
            audit['accepted_with_known_indoor'] += int(row.get('indoor') in ('I','O'))
            audit['precise_date_rows' if precise else 'tournament_date_rows'] += 1
        tournaments.append({'id': identifier, 'name': rows[0]['tourney_name'],
                            'surface': rows[0]['surface'], 'source_date': dt.date.fromordinal(max(dates)).isoformat(),
                            'date_precision': 'day' if precise else 'tournament', 'rows': len(rows),
                            'accepted_rows': accepted_here,'safe_available_after':dt.date.fromordinal(release).isoformat(),
                            'source_levels':sorted(set(r.get('tourney_level','') for r in rows))})
    rounds = {'RR': 0, 'R128': 1, 'R64': 2, 'R32': 3, 'R16': 4, 'QF': 5, 'SF': 6, 'BR': 7, 'F': 8}
    matches.sort(key=lambda m: (m['start'], m['event'], m['source_day'],
                               rounds.get(m['raw'].get('round'), -1),
                               number(m['raw']['match_num'], 0), m['id']))
    if not matches:
        raise ValueError('No validated matches for ' + tour)
    return matches, {'counts': dict(audit),'scope':scope,
                     'competition_counts':dict(collections.Counter(m['raw']['_competition'] for m in matches)),
                     'tournaments': sorted(tournaments, key=lambda e: e['source_date'], reverse=True),
                     'latest_source_date': dt.date.fromordinal(max(m['source_day'] for m in matches)).isoformat(),
                     'latest_history_available': dt.date.fromordinal(max(m['available'] for m in matches)).isoformat()}


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()
