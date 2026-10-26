#!/usr/bin/env python3
"""Read-only free-source checks; saves publisher timestamps separately from match dates."""
import argparse
import concurrent.futures
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import urllib.parse
import urllib.request

from core.data import ROOT, atomic_json

INDEX='https://stats.tennismylife.org/api/data-files'


def download(url,path):
    request=urllib.request.Request(url,headers={'User-Agent':'ForeGateTennis/1.0 free-source-readonly-audit'})
    with urllib.request.urlopen(request,timeout=60) as response:
        raw=response.read();headers=dict(response.headers)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    meta={'url':url,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),
          'status':200,'headers':headers,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    atomic_json(path.with_suffix(path.suffix+'.meta.json'),meta)
    return raw,meta


def csv_summary(raw,item,meta):
    rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    dates=[r['tourney_date'] for r in rows if r.get('tourney_date')]
    modified=dt.datetime.fromisoformat(item['mtime'].replace('Z','+00:00'))
    checked=dt.datetime.fromisoformat(meta['checked_at'])
    return {'name':item['name'],'url':item['url'],'publisher_modified_at':item['mtime'],
            'file_age_hours_at_check':round((checked-modified).total_seconds()/3600,2),
            'rows':len(rows),'columns':list(rows[0]) if rows else [],
            'latest_source_tourney_date':max(dates) if dates else None,
            'levels':sorted({r.get('tourney_level','') for r in rows}),
            'rounds':sorted({r.get('round','') for r in rows}),
            'tournaments':sorted({r.get('tourney_name','') for r in rows}),
            'note':'Publisher mtime measures file age, not court-to-feed delay. tourney_date is tournament week.'}


def espn_summary(value,meta):
    events=[]
    for e in value.get('events',[]):
        counts={g['grouping']['slug']:len(g.get('competitions',[])) for g in e.get('groupings',[])}
        events.append({'id':e['id'],'name':e['name'],'from':e.get('date'),'to':e.get('endDate'),'draw_counts':counts})
    return {'url':meta['url'],'checked_at':meta['checked_at'],
            'cache_control':next((v for k,v in meta['headers'].items() if k.lower()=='cache-control'),None),
            'events':events,'note':'Date query may include whole tournament draws; filter individual competition.date. No latency SLA established.'}


def audit(day,destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    raw,index_meta=download(INDEX,destination/'tml-index.json');files=json.loads(raw)['files']
    year=day.year
    names={f'{year}.csv',f'{year}_wta.csv',f'{year}_challenger.csv',f'atp_quali/{year}_atp_quali.csv',
           'ongoing_tourneys.csv','wta_ongoing_tourneys.csv','challenger_ongoing_tourneys.csv'}
    selected=[r for r in files if r['name'] in names]
    if len(selected)!=len(names):raise ValueError('Publisher index missing requested free file')
    def one(item):
        url=urllib.parse.urlparse(item['url'])
        if url.scheme!='https' or url.hostname!='stats.tennismylife.org':raise ValueError('Unexpected publisher URL')
        raw,meta=download(item['url'],destination/'csv'/Path(item['name']).name)
        return csv_summary(raw,item,meta)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        csv_checks=list(pool.map(one,selected))
    def scoreboard(tour):
        url=f'https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard?dates={day:%Y%m%d}&limit=1000'
        raw,meta=download(url,destination/f'espn-{tour}.json')
        return tour,espn_summary(json.loads(raw),meta)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        espn=dict(pool.map(scoreboard,('atp','wta')))
    result={'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'scoreboard_query_date':day.isoformat(),
            'csv':csv_checks,'espn':espn,'csv_index_checked_at':index_meta['checked_at']}
    atomic_json(destination/'summary.json',result)
    atomic_json(ROOT/'reports/free-source-latest.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',default=dt.datetime.now(dt.timezone.utc).date().isoformat())
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();day=dt.date.fromisoformat(args.date)
    result=audit(day,args.output or ROOT/'data/market-audit'/day.isoformat()/'free-sources')
    print(json.dumps(result,ensure_ascii=False,indent=2))
