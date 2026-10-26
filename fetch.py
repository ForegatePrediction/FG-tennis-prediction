#!/usr/bin/env python3
"""Download only publisher-advertised free CSVs. No key, payment or scraping."""
import argparse
import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import time
import urllib.request
from urllib.parse import urlparse
from core.data import ROOT, atomic_json, read_csv, sha256

INDEX = 'https://stats.tennismylife.org/api/data-files'


def get(url):
    if urlparse(url).hostname != 'stats.tennismylife.org' or not url.startswith('https://'):
        raise ValueError('Unexpected source host')
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'ForeGateTennis/1.0 (free public CSV research)'})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def fetch(start=2010, end=None, force=False, root=ROOT):
    end = end or dt.datetime.now(dt.timezone.utc).year
    files = json.loads(get(INDEX))['files']
    advertised = {x['name']: x for x in files}
    jobs = []
    for tour in ('atp', 'wta'):
        names = [f'{year}{"_wta" if tour == "wta" else ""}.csv' for year in range(start, end + 1)]
        names += ['wta_ongoing_tourneys.csv' if tour == 'wta' else 'ongoing_tourneys.csv']
        for name in names:
            if name not in advertised:
                raise RuntimeError('Required season missing from publisher index: ' + name)
            jobs.append((tour, name, advertised[name]))
    def one(job):
        tour, name, item = job
        path = Path(root) / 'data/raw' / tour / name
        cached = path.exists() and not force and name[:4].isdigit() and int(name[:4]) < end
        raw = path.read_bytes() if cached else get(item['url'])
        rows = read_csv(raw)
        if name[:4].isdigit() and int(name[:4]) < end and len(rows)<500:
            raise ValueError('Incomplete historical season: '+name)
        if not cached and path.exists() and name[:4].isdigit():
            previous=read_csv(path.read_bytes())
            if len(rows)<len(previous)*.95:
                raise ValueError('Unexpected >5% source row regression: '+name)
        if not cached:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix('.csv.tmp')
            tmp.write_bytes(raw)
            tmp.replace(path)
        print(f'{tour} {name}: {len(rows)} rows ({"cache" if cached else "download"})', flush=True)
        return {'tour': tour, 'name': name, 'url': item['url'], 'rows': len(rows),
                'bytes': len(raw), 'sha256': sha256(raw)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        manifest = list(pool.map(one, jobs))
    value = {'source': INDEX, 'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
             'start_year': start, 'end_year': end, 'files': manifest}
    atomic_json(Path(root) / 'data/source-manifest.json', value)
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=int, default=2010)
    parser.add_argument('--end', type=int)
    parser.add_argument('--force', action='store_true', help='Revalidate historical corrections too')
    args = parser.parse_args()
    fetch(args.start, args.end, args.force)
