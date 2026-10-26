#!/usr/bin/env python3
"""Export Poly's tennis taxonomy and participant namespace; no model or trading changes."""
import argparse
import collections
import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import re
import unicodedata
import urllib.parse

from audit_polymarket import get, tennis_sports
from core.data import ROOT, atomic_json


def normalized(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower())


def values(value):
    if isinstance(value, list): return value
    if isinstance(value, str):
        try:
            result = json.loads(value)
            return result if isinstance(result, list) else []
        except ValueError: pass
    return []


def classify(event):
    meta = event.get('eventMetadata') or {}
    sport = event.get('sport') or {}
    slug = sport.get('sport') or 'unknown'
    league = meta.get('league') or event.get('title', '').split(':', 1)[0]
    winner = [m for m in event.get('markets', []) if m.get('sportsMarketType') == 'moneyline']
    intro = winner[0].get('description', '').split('\n\n', 1)[0] if winner else ''
    text = ' '.join([event.get('title', ''), league, intro, meta.get('tennisFixtureSource', '')])
    issues = []
    indicators = set()
    if meta.get('format') in ('singles', 'doubles'): indicators.add(meta['format'])
    if 'doubles' in slug or re.search(r'\bdoubles\b', text, re.I): indicators.add('doubles')
    # A generic ATP/WTA sport is not enough to override an explicit doubles marker.
    if not indicators and slug in ('atp', 'wta', 'itf'): indicators.add('singles')
    discipline = next(iter(indicators)) if len(indicators) == 1 else 'unknown'
    if len(indicators) > 1: issues.append('conflicting_format')
    gender = 'male' if slug in ('atp', 'atp-doubles', 'daviscup') else 'female' if slug in ('wta', 'wta-doubles', 'bjkcup') else 'unknown'
    if gender == 'unknown':
        if re.match(r'^M\d+\b', league) or re.search(r'\bboys\b', text, re.I): gender = 'male'
        elif re.match(r'^W\d+\b', league) or re.search(r'\bgirls\b', text, re.I): gender = 'female'
    qualifying = bool(re.search(r'\bqualif(?:ying|ication)\b', text, re.I))
    competition_text = ' '.join([league, event.get('title', '').split(':', 1)[0]])
    junior = bool(re.search(r'\bjuniors?\b', competition_text, re.I))
    level = 'challenger' if 'challenger' in text.lower() else 'itf' if slug == 'itf' else 'unverified'
    if junior: level = 'junior'
    elif slug in ('daviscup', 'bjkcup'): level = 'national_team_competition'
    sides = values(winner[0].get('outcomes')) if winner else []
    versus_title = bool(re.search(r'\bvs\.?\s', event.get('title', ''), re.I))
    is_match = versus_title and len(sides) == 2 and {str(s).lower() for s in sides} != {'yes', 'no'}
    legacy_outcomes = [values(m.get('outcomes')) for m in event.get('markets', []) if not m.get('sportsMarketType')]
    legacy_match = versus_title and not winner and any(len(s) == 2 and {str(x).lower() for x in s} != {'yes', 'no'} for s in legacy_outcomes)
    if legacy_match: issues.append('legacy_untyped_match_requires_review')
    participants = [{k: t.get(k) for k in ('id', 'name', 'league', 'alias', 'abbreviation', 'providerId', 'ordering')}
                    for t in event.get('teams') or []]
    outcome_map = []
    for index, name in enumerate(sides if is_match else []):
        matched = [t for t in participants if normalized(str(name)) in {normalized(t.get(k) or '') for k in ('name', 'alias')}]
        outcome_map.append({'index': index, 'label': name, 'poly_participant_id': str(matched[0]['id']) if len(matched) == 1 and matched[0]['id'] is not None else None,
                            'match_basis': ('name' if normalized(matched[0].get('name') or '') == normalized(str(name)) else 'explicit_poly_alias') if len(matched) == 1 else None})
    if is_match and any(x['poly_participant_id'] is None for x in outcome_map): issues.append('outcome_identity_unresolved')
    if is_match and discipline == 'unknown': issues.append('discipline_unresolved')
    return {'poly_event_id': str(event['id']), 'title': event.get('title'), 'slug': event.get('slug'),
            'poly_sport': slug, 'poly_sport_id': sport.get('id'),
            'poly_series': [{k: s.get(k) for k in ('id', 'slug', 'title')} for s in event.get('series') or []],
            'poly_tags': [{k: t.get(k) for k in ('id', 'slug', 'label')} for t in event.get('tags') or []],
            'league_raw': league, 'league_source': 'eventMetadata.league' if meta.get('league') else 'title_fallback',
            'gender_hint': gender, 'discipline_hint': discipline,
            'age_group_hint': 'junior' if junior else 'not_marked_junior',
            'draw_stage_hint': 'qualifying' if qualifying else 'not_marked_qualifying',
            'level_hint': level, 'event_kind': 'match' if is_match else 'legacy_match_candidate' if legacy_match else 'other_contract',
            'closed': bool(event.get('closed')), 'active': bool(event.get('active')),
            'participants': participants, 'moneyline_outcome_map': outcome_map,
            'legacy_candidate_outcomes': legacy_outcomes if legacy_match else [],
            'game_id': event.get('gameId'), 'start_time': event.get('startTime'),
            'source_metadata': meta, 'surface': None, 'best_of': None,
            'poly_markets': [{k: m.get(k) for k in ('id', 'slug', 'conditionId', 'clobTokenIds', 'outcomes',
                            'sportsMarketType', 'line', 'groupItemTitle', 'gameStartTime', 'active', 'closed', 'acceptingOrders')}
                            for m in event.get('markets', [])],
            'market_types': dict(collections.Counter(m.get('sportsMarketType') or 'unspecified' for m in event.get('markets', []))),
            'issues': issues}


def registry(records):
    """Keep source entities distinct. Names/providerId are review clues, not join keys."""
    grouped = collections.defaultdict(list)
    for record in records:
        if record.get('id') is not None: grouped[str(record['id'])].append(record)
    result = []
    for identifier, rows in sorted(grouped.items()):
        names = sorted({r['name'] for r in rows if r.get('name')})
        leagues = sorted({r['league'] for r in rows if r.get('league')})
        result.append({'poly_participant_id': identifier, 'names': names, 'poly_leagues': leagues,
                       'aliases': sorted({r['alias'] for r in rows if r.get('alias')}),
                       'provider_ids_unscoped': sorted({str(r['providerId']) for r in rows if r.get('providerId') is not None}),
                       'entity_hint': 'pair' if any('doubles' in x for x in leagues) or any('/' in x for x in names) else 'player',
                       'canonical_player_id': None, 'identity_status': 'poly_entity_only'})
    by_name = collections.defaultdict(set)
    for row in result:
        for name in row['names']: by_name[normalized(name)].add(row['poly_participant_id'])
    collisions = [{'normalized_name': name, 'poly_participant_ids': sorted(ids)} for name, ids in sorted(by_name.items()) if name and len(ids) > 1]
    return result, collisions


def fetch_rosters(scan, sports, maximum=100):
    folder = scan / 'rosters'
    folder.mkdir(exist_ok=True)
    def one(sport):
        name = sport['sport']; records = {}; complete = False
        for page in range(maximum):
            params = urllib.parse.urlencode({'league': name, 'limit': 100, 'offset': page * 100, 'order': 'id', 'ascending': 'true'})
            path = folder / f'{name}-{page:03}.json'
            rows = get('/teams?' + params, path)
            if not isinstance(rows, list) or any(r.get('league') != name for r in rows): raise ValueError('Roster filter mismatch: ' + name)
            before = len(records)
            for row in rows: records[str(row['id'])] = row
            if len(rows) < 100: complete = True; break
            if len(records) == before: raise ValueError('Repeated roster page: ' + name)
        print('Roster', name, len(records), 'exhausted', complete, flush=True)
        return name, {'records': len(records), 'pagination_exhausted': complete, 'pages': page + 1}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool: status = dict(pool.map(one, sports))
    atomic_json(folder / 'pagination.json', status)
    return status


def build(scan, extra_history=()):
    sports = tennis_sports(json.loads((scan / 'sports.json').read_text()))
    rows = {}; current_open = set(); files = []
    for path in sorted(scan.glob('*.json')) + list(extra_history):
        if path.name.endswith('.meta.json') or not path.name.startswith(('open-', 'closed-', 'category-', 'wimbledon-history-')): continue
        data = json.loads(path.read_text())
        if not isinstance(data, list): continue
        try: evidence_path = path.resolve().relative_to(ROOT)
        except ValueError: evidence_path = path.resolve()
        files.append(str(evidence_path))
        for event in data:
            identifier = str(event['id'])
            if path.parent == scan and path.name.startswith('open-'): current_open.add(identifier)
            if identifier not in rows or path.parent == scan and path.name.startswith('open-'):
                rows[identifier] = event
    inventory = [classify(e) for e in rows.values()]
    for event in inventory: event['in_current_open_scan'] = event['poly_event_id'] in current_open
    entities = [t for e in rows.values() for t in e.get('teams') or []]
    for path in (scan / 'rosters').glob('*.json'):
        if path.name.endswith('.meta.json') or path.name == 'pagination.json': continue
        entities.extend(json.loads(path.read_text()))
    participants, collisions = registry(entities)
    rosters = json.loads((scan / 'rosters/pagination.json').read_text()) if (scan / 'rosters/pagination.json').exists() else {}
    opened = [e for e in inventory if e['in_current_open_scan']]
    taxonomy = []
    for sport in sports:
        matches = [e for e in inventory if any(str(s['id']) == str(sport['series']) for s in e['poly_series'])]
        taxonomy.append({**sport, 'sample_events_by_series': len(matches),
                         'observed_event_sports': dict(collections.Counter(e['poly_sport'] for e in matches)),
                         'observed_disciplines': dict(collections.Counter(e['discipline_hint'] for e in matches)),
                         'roster_scan': rosters.get(sport['sport'])})
    leagues = collections.defaultdict(list)
    for e in inventory: leagues[e['poly_sport'], e['league_raw']].append(e)
    league_rows = [{'poly_sport': s, 'league_raw': league, 'sample_events': len(events),
                    'current_open_events': sum(e['in_current_open_scan'] for e in events),
                    'series_ids': sorted({str(x['id']) for e in events for x in e['poly_series']}),
                    'level_hints': sorted({e['level_hint'] for e in events}),
                    'example_event_id': events[0]['poly_event_id']} for (s, league), events in sorted(leagues.items())]
    summary = {'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'source': 'https://gamma-api.polymarket.com',
               'sports': taxonomy, 'current_open_events': len(opened), 'sample_events': len(inventory),
               'current_open_by_sport': dict(collections.Counter(e['poly_sport'] for e in opened)),
               'current_open_by_gender': dict(collections.Counter(e['gender_hint'] for e in opened)),
               'event_kinds': dict(collections.Counter(e['event_kind'] for e in inventory)),
               'unique_poly_entities': len(participants), 'entities_by_hint': dict(collections.Counter(p['entity_hint'] for p in participants)),
               'name_collision_groups': len(collisions), 'raw_league_groups': len(league_rows),
               'open_participant_slots': sum(len(e['participants']) for e in opened if e['event_kind'] == 'match'),
               'open_unresolved_outcomes': sum('outcome_identity_unresolved' in e['issues'] for e in opened),
               'open_level_hints': dict(collections.Counter(e['level_hint'] for e in opened)),
               'open_metadata_fields': dict(collections.Counter(k for e in opened for k in e['source_metadata'])),
               'evidence_files': files, 'notes': [
                   'Open snapshot is bounded in time, closed history is sampled. Roster pagination exhaustion is per current query, not proof of all-time completeness.',
                   'Poly participant IDs identify source entities, including pairs; canonical individual identities remain unverified. Do not merge by names, abbreviations or unscoped providerId.',
                   'Level/discipline/gender hints are evidence-based classifications, not normalized official tournament identities. Unmarked age/stage does not prove adult/main draw.',
                   'Surface and best_of were not established from these records; they remain null. No prediction-readiness claim.',
                   'Other contracts stay inventoried but do not enter single-match coverage.']}
    tags = {}
    for event in inventory:
        for tag in event['poly_tags']:
            key = str(tag['id'])
            if key not in tags: tags[key] = {**tag, 'sample_events': 0, 'current_open_events': 0}
            tags[key]['sample_events'] += 1
            tags[key]['current_open_events'] += event['in_current_open_scan']
    payloads = {'poly-taxonomy-latest.json': summary, 'poly-event-catalog.json': inventory,
                'poly-tag-inventory.json': {'checked_at': summary['checked_at'], 'tags': list(tags.values())},
                'poly-participant-registry.json': {'checked_at': summary['checked_at'], 'entities': participants, 'name_collision_candidates': collisions},
                'poly-league-mapping-input.json': {'checked_at': summary['checked_at'], 'rows': league_rows}}
    for name, payload in payloads.items(): atomic_json(ROOT / 'reports' / name, payload)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan', type=Path, required=True)
    parser.add_argument('--refresh-rosters', action='store_true')
    parser.add_argument('--max-roster-pages', type=int, default=100)
    parser.add_argument('--extra-history', type=Path, nargs='*', default=[])
    args = parser.parse_args(); scan = args.scan.resolve()
    if args.max_roster_pages < 1: parser.error('max-roster-pages must be positive')
    if args.refresh_rosters: fetch_rosters(scan, tennis_sports(json.loads((scan / 'sports.json').read_text())), args.max_roster_pages)
    result = build(scan, args.extra_history)
    print(json.dumps({k: v for k, v in result.items() if k not in ('sports', 'evidence_files')}, ensure_ascii=False, indent=2))
