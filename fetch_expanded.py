#!/usr/bin/env python3
"""Download advertised free ATP Challenger/qualifying files in isolation.

These files do not silently change the trained main-tour model or its manifest.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
from pathlib import Path
import urllib.request
from core.data import ROOT,atomic_json,read_csv

CATALOG='https://stats.tennismylife.org/api/data-files'


def main(root=ROOT,start=2010,end=None):
    root=Path(root);end=end or dt.datetime.now(dt.timezone.utc).year
    if not 2007<=start<=end<=dt.datetime.now(dt.timezone.utc).year:raise ValueError('Valid historical year range required, starting 2007 or later')
    checked=dt.datetime.now(dt.timezone.utc).isoformat()
    raw=urllib.request.urlopen(CATALOG,timeout=45).read();catalog=json.loads(raw)
    advertised={f['name']:f for f in catalog['files']}
    names=[n for y in range(start,end+1) for n in (f'{y}_challenger.csv',f'atp_quali/{y}_atp_quali.csv')]
    if any(n not in advertised for n in names):raise ValueError('Source does not advertise every requested season')
    directory=root/'data/expanded'
    def fetch(name):
        url=advertised[name]['url']
        if not url.startswith('https://stats.tennismylife.org/data/'):raise ValueError('Untrusted source URL')
        dest=directory/name;meta=dest.with_suffix('.meta.json')
        # Cache completed older seasons only after validating their stored hash.
        prior=json.loads(meta.read_text()) if meta.exists() else None
        body=dest.read_bytes() if dest.exists() else None
        if (body is None or not prior or hashlib.sha256(body).hexdigest()!=prior.get('sha256') or str(end) in name
                or prior.get('source_mtime')!=advertised[name]['mtime']):
            body=urllib.request.urlopen(url,timeout=60).read()
        rows=read_csv(body)
        if len(rows)<100:raise ValueError('Implausibly short historical file: '+name)
        if prior and len(rows)<prior.get('rows',0)*.95:raise ValueError('Source row regression: '+name)
        dest.parent.mkdir(parents=True,exist_ok=True)
        tmp=dest.with_suffix('.csv.tmp');tmp.write_bytes(body);tmp.replace(dest)
        item={'name':name,'url':url,'checked_at':checked,'source_mtime':advertised[name]['mtime'],
              'rows':len(rows),'sha256':hashlib.sha256(body).hexdigest()}
        atomic_json(meta,item)
        return item
    with ThreadPoolExecutor(max_workers=3) as pool:files=list(pool.map(fetch,names))
    atomic_json(directory/'source-manifest.json',{'checked_at':checked,'catalog_url':CATALOG,
                'catalog_sha256':hashlib.sha256(raw).hexdigest(),'files':files,
                'scope':'ATP Challenger main draws and ATP qualifying; NOT verified Challenger qualifying or ITF'})
    print(json.dumps({'files':len(files),'rows':sum(f['rows'] for f in files),'scope':'Challenger main draw + ATP qualifying; Challenger qualifying missing'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--start',type=int,default=2010);parser.add_argument('--end',type=int)
    args=parser.parse_args();main(start=args.start,end=args.end)
