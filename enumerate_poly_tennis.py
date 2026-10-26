#!/usr/bin/env python3
"""Enumerate public Poly tennis history and global tag/series dictionaries.

No open/closed/active filter. Compressed source pages retain provenance and
can be resumed; reports distinguish query exhaustion from universal coverage.
"""
import argparse
import concurrent.futures
import datetime as dt
import gzip
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request

from core.data import ROOT, atomic_json

BASE = 'https://gamma-api.polymarket.com'


def page(path, destination):
    if destination.exists():
        with gzip.open(destination, 'rt') as stream: return json.load(stream)
    for attempt in range(4):
        try:
            request = urllib.request.Request(BASE + path, headers={'User-Agent': 'ForeGateTennis/1.0 taxonomy-enumeration'})
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read(); headers = dict(response.headers)
            data = json.loads(raw)
            temporary = destination.with_suffix('.tmp')
            with gzip.open(temporary, 'wb') as stream: stream.write(raw)
            temporary.replace(destination)
            atomic_json(destination.with_suffix('.meta.json'), {'url': BASE + path,
                        'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'headers': headers})
            return data
        except (OSError, ValueError):
            if attempt == 3: raise
            time.sleep(2 ** attempt)


def compact(event):
    meta = event.get('eventMetadata') or {}
    return {'id': str(event['id']), 'title': event.get('title'), 'slug': event.get('slug'),
            'createdAt': event.get('createdAt'), 'startTime': event.get('startTime'),
            'active': event.get('active'), 'closed': event.get('closed'),
            'sport': event.get('sport'), 'series': [{k: s.get(k) for k in ('id', 'slug', 'title')} for s in event.get('series') or []],
            'tags': [{k: t.get(k) for k in ('id', 'slug', 'label')} for t in event.get('tags') or []],
            'metadata': meta,
            'league_raw': meta.get('league') or (event.get('title') or '').split(':', 1)[0],
            'teams': event.get('teams'),
            'market_types': sorted({m.get('sportsMarketType') or 'unspecified' for m in event.get('markets') or []})}


def walk_events(folder, maximum=2000, tag=864, series=None, exclude_tag=None):
    folder.mkdir(parents=True, exist_ok=True)
    cursor = None; cursors = set(); seen = set(); result = []; exhausted = False
    for index in range(maximum):
        params = {'limit': 100, 'order': 'id', 'ascending': 'true'}
        if tag is not None: params['tag_id'] = tag
        if series is not None: params['series_id'] = series
        if exclude_tag is not None: params['exclude_tag_id'] = exclude_tag
        if cursor: params['after_cursor'] = cursor
        data = page('/events/keyset?' + urllib.parse.urlencode(params), folder / f'page-{index:04}.json.gz')
        if not isinstance(data, dict) or not isinstance(data.get('events'), list): raise ValueError('Unexpected event page')
        rows = data['events']
        if tag is not None and any(not any(str(t.get('id')) == str(tag) for t in e.get('tags', [])) for e in rows):
            raise ValueError('Tag filter mismatch')
        if series is not None and any(not any(str(s.get('id')) == str(series) for s in e.get('series') or []) for e in rows):
            raise ValueError('Series filter mismatch')
        if exclude_tag is not None and any(any(str(t.get('id')) == str(exclude_tag) for t in e.get('tags') or []) for e in rows):
            raise ValueError('Excluded tag filter mismatch')
        additions = [e for e in rows if str(e['id']) not in seen]
        if rows and not additions: raise ValueError('Repeated event page')
        for event in additions: seen.add(str(event['id'])); result.append(compact(event))
        cursor = data.get('next_cursor')
        if index % 10 == 0 or not cursor:
            print(folder.name, 'page', index, 'unique', len(result), 'last', rows[-1].get('createdAt') if rows else None, flush=True)
        if not cursor: exhausted = True; break
        if cursor in cursors: raise ValueError('Repeated cursor')
        cursors.add(cursor)
    status = {'query': {'tag_id': tag, 'series_id': series, 'exclude_tag_id': exclude_tag, 'status_filters': None}, 'pages': index + 1,
              'unique_events': len(result), 'pagination_exhausted': exhausted,
              'finished_at': dt.datetime.now(dt.timezone.utc).isoformat()}
    atomic_json(folder / 'status.json', status)
    atomic_json(folder / 'events-compact.json', result)
    return status


def walk_dictionary(folder, endpoint, size, maximum=2000):
    folder.mkdir(parents=True, exist_ok=True)
    rows = {}; exhausted = False; offset = 0
    for index in range(maximum):
        params = urllib.parse.urlencode({'limit': size, 'offset': offset, 'order': 'id', 'ascending': 'true'})
        data = page('/' + endpoint + '?' + params, folder / f'page-{index:04}.json.gz')
        if not isinstance(data, list): raise ValueError('Unexpected dictionary page')
        additions = [r for r in data if str(r['id']) not in rows]
        if data and not additions: raise ValueError('Repeated dictionary page')
        for row in additions:
            if endpoint == 'series':
                # Full source is retained in gzip. The dictionary includes child event evidence.
                row = {**{k: v for k, v in row.items() if k != 'events'},
                       'event_summaries': [compact(e) for e in row.get('events') or []]}
            rows[str(row['id'])] = row
        if index % 10 == 0 or not data: print(endpoint, 'page', index, 'unique', len(rows), flush=True)
        # An upstream endpoint can silently cap page size below the requested
        # limit. Only an empty page proves exhaustion for offset pagination.
        if not data: exhausted = True; break
        offset += len(data)
    status = {'endpoint': endpoint, 'pages': index + 1, 'records': len(rows), 'pagination_exhausted': exhausted,
              'finished_at': dt.datetime.now(dt.timezone.utc).isoformat()}
    atomic_json(folder / 'status.json', status)
    atomic_json(folder / 'dictionary.json', list(rows.values()))
    return status


def cross_checks(folder, maximum=2000):
    from build_poly_enumeration import TAG_CANDIDATE, EXCLUDE_TAG_SLUGS, known_other_sport, outside_root_decision
    def read(path): return json.loads(path.read_text())
    for kind in ('tags', 'series', 'tennis-history'):
        if not read(folder / kind / 'status.json')['pagination_exhausted']:
            raise ValueError('Finish primary enumeration before cross-checks')
    tags = read(folder / 'tags/dictionary.json')
    events = read(folder / 'tennis-history/events-compact.json')
    seeds = {str(t['id']) for e in events for t in e.get('tags') or []}
    seeds |= {str(t['id']) for t in tags if TAG_CANDIDATE.search(t.get('label', '') + ' ' + t.get('slug', '')) and t.get('slug') not in EXCLUDE_TAG_SLUGS}
    # Broad editorial/sport tags cannot identify additional tennis on their own.
    broad_tags = {'1', '864', '100248', '100398', '100639', '100864', '102169', '100401',
                  '286', '596', '100292', '100215', '104245'}
    seeds -= broad_tags
    seeds -= {str(t['id']) for t in tags if t.get('slug') in EXCLUDE_TAG_SLUGS}
    series = read(folder / 'series/dictionary.json')
    observed = {str(s['id']) for e in events if not known_other_sport(e) for s in e.get('series') or []}
    series_seeds = {str(s['id']) for s in series if str(s['id']) in observed or TAG_CANDIDATE.search(s.get('title', '')) and 'table tennis' not in s.get('title', '').lower()}
    completed = set(); statuses = []
    def one(item):
        kind, identifier = item
        return walk_events(folder / f'outside-root-{kind}-{identifier}', maximum,
                           tag=identifier if kind == 'tag' else None,
                           series=identifier if kind == 'series' else None, exclude_tag=864)
    while True:
        jobs = [item for item in [('tag', i) for i in sorted(seeds, key=int)] + [('series', i) for i in sorted(series_seeds, key=int)] if item not in completed]
        if not jobs: break
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool: statuses.extend(pool.map(one, jobs))
        completed.update(jobs)
        # Follow new dedicated tags found on recovered tennis events, e.g.
        # Barcelona Open 102062, which never co-occurred with the root tag.
        for kind, identifier in jobs:
            for event in read(folder / f'outside-root-{kind}-{identifier}/events-compact.json'):
                if outside_root_decision(event) == 'confirmed_tennis':
                    seeds.update(str(t['id']) for t in event.get('tags') or [] if str(t['id']) not in broad_tags and t.get('slug') not in EXCLUDE_TAG_SLUGS)
    manifest = {'tag_seeds': sorted(seeds, key=int), 'series_seeds': sorted(series_seeds, key=int),
                'broad_tags_not_walked_outside_root': sorted(broad_tags, key=int),
                'queries': len(completed), 'all_pagination_exhausted': all(s['pagination_exhausted'] for s in statuses),
                'finished_at': dt.datetime.now(dt.timezone.utc).isoformat()}
    atomic_json(folder / 'cross-check-manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/market-audit/2026-10-26/enumeration')
    parser.add_argument('--only', choices=['all', 'events', 'tags', 'series', 'cross-checks'], default='all')
    parser.add_argument('--cross-checks', action='store_true', help='After base enumeration, check source tags/series outside the root tag')
    parser.add_argument('--max-pages', type=int, default=2000)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    jobs = {'events': lambda: walk_events(args.output / 'tennis-history', args.max_pages),
            'tags': lambda: walk_dictionary(args.output / 'tags', 'tags', 100, args.max_pages),
            'series': lambda: walk_dictionary(args.output / 'series', 'series', 50, args.max_pages)}
    if args.only != 'cross-checks':
        selected = jobs if args.only == 'all' else {args.only: jobs[args.only]}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(selected)) as pool:
            futures = {name: pool.submit(job) for name, job in selected.items()}
            for name, future in futures.items(): print(name, json.dumps(future.result()), flush=True)
    if args.only == 'cross-checks' or args.cross_checks: print('cross-checks', json.dumps(cross_checks(args.output, args.max_pages)), flush=True)
