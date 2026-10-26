#!/usr/bin/env python3
"""Read-only inventory of actual Poly tennis scope. Never submits orders."""
import argparse
import collections
import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
from core.data import ROOT, atomic_json

BASE='https://gamma-api.polymarket.com'


def get(path,destination):
    url=BASE+path
    for attempt in range(3):
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'ForeGateTennis/1.0 public-data-coverage-audit'})
            with urllib.request.urlopen(request,timeout=45) as response:
                raw=response.read();headers=dict(response.headers)
            value=json.loads(raw)
            atomic_json(destination,value)
            atomic_json(Path(destination).with_suffix('.meta.json'),{'url':url,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'headers':headers})
            return value
        except (OSError,ValueError):
            if attempt==2:raise
            time.sleep(2**attempt)


def tennis_sports(rows):
    return [r for r in rows if '864' in [t.strip() for t in str(r.get('tags','')).split(',')]]


def sport_of(event):
    if (event.get('sport') or {}).get('sport'):return event['sport']['sport']
    for series in event.get('series') or []:
        if series.get('slug'):return series['slug']
    return 'outright_or_other'


def describe(event):
    sport=sport_of(event);markets=event.get('markets') or [];metadata=event.get('eventMetadata') or {}
    league=metadata.get('league') or event['title'].split(':',1)[0]
    moneyline=next((m for m in markets if m.get('sportsMarketType')=='moneyline'),None)
    # Settlement boilerplate says "disqualification" even in main-draw finals.
    # Only inspect the match introduction and actual fixture metadata.
    introduction=(moneyline or {}).get('description','').split('\n\n',1)[0]
    text=' '.join([event['title'],league,introduction,metadata.get('tennisFixtureSource','')])
    qualifying=bool(re.search(r'\bqualif(?:ying|ication)\b',text,re.I))
    doubles=metadata.get('format')=='doubles' or 'doubles' in sport or '(doubles)' in event['title'].lower()
    is_match=bool(re.search(r'\bvs\.?\s',event['title'],re.I)) and bool(moneyline)
    tradable=lambda m:bool(m.get('active')) and not m.get('closed') and bool(m.get('acceptingOrders'))
    return {'id':str(event['id']),'title':event['title'],'slug':event['slug'],
            'url':'https://polymarket.com/event/'+event['slug'],'sport':sport,'league':league,
            'qualifying':qualifying,'doubles':doubles,'junior':bool(re.search(r'\bjuniors?\b',' '.join([league,event['title'].split(':',1)[0]]),re.I)),
            'is_match':is_match,'fixture_source':metadata.get('tennisFixtureSource'),
            'series_ids':[str(s['id']) for s in event.get('series') or [] if 'id' in s],
            'closed':bool(event.get('closed')),
            'market_types':dict(collections.Counter(m.get('sportsMarketType') or 'outright_or_unspecified' for m in markets)),
            'tradable_markets':sum(tradable(m) for m in markets),
            'tradable_match_moneyline':is_match and any(tradable(m) and m.get('sportsMarketType')=='moneyline' for m in markets),
            'game_start':moneyline.get('gameStartTime') if moneyline else None,
            'sides':json.loads(moneyline['outcomes']) if moneyline and isinstance(moneyline.get('outcomes'),str) else (moneyline or {}).get('outcomes',[])}


def league_inventory(inventories):
    groups=collections.defaultdict(list)
    for event in inventories:groups[event['sport'],event['league']].append(event)
    return [{'sport':sport,'league':league,'sample_events':len(rows),
             'open_events':sum(not e['closed'] for e in rows),
             'qualifying_seen':any(e['qualifying'] for e in rows),
             'doubles_seen':any(e['doubles'] for e in rows),
             'junior_seen':any(e['junior'] for e in rows),'example_url':rows[0]['url']}
            for (sport,league),rows in sorted(groups.items())]


def scan(destination,max_open_pages=40,closed_pages=10):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    sports=tennis_sports(get('/sports',destination/'sports.json'))
    tag=get('/tags/slug/tennis',destination/'tennis-tag.json')
    if str(tag['id'])!='864':raise ValueError('Tennis tag changed; review taxonomy before scanning')
    def pages(closed,maximum):
        records={};complete=False;name='closed' if closed else 'open'
        for page in range(maximum):
            params={'tag_id':864,'closed':str(closed).lower(),'limit':100,'offset':page*100,'order':'id','ascending':'false'}
            if not closed:params['active']='true'
            rows=get('/events?'+urllib.parse.urlencode(params),destination/f'{name}-{page:03}.json')
            if not isinstance(rows,list):raise ValueError('Unexpected events response')
            for row in rows:
                if not any(str(t.get('id'))=='864' for t in row.get('tags',[])):raise ValueError('Tag filter not respected by source')
                records[str(row['id'])]=row
            print(f'{name} page {page}: {len(rows)}, unique {len(records)}',flush=True)
            if len(rows)<100:complete=True;break
        return list(records.values()),complete
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        opened=pool.submit(pages,False,max_open_pages);closed=pool.submit(pages,True,closed_pages)
        open_rows,open_complete=opened.result();closed_rows,closed_complete=closed.result()
    # Additional per-category evidence includes out-of-season Davis/BJK/Wimbledon.
    def category(row):
        params=urllib.parse.urlencode({'series_id':row['series'],'closed':'true','limit':20,'order':'id','ascending':'false'})
        return get('/events?'+params,destination/f'category-{row["sport"]}.json')
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        samples=list(pool.map(category,sports))
    all_rows={str(e['id']):e for group in [open_rows,closed_rows]+samples for e in group}
    inventories=[describe(e) for e in all_rows.values()]
    open_inventory=[describe(e) for e in open_rows]
    summary={'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'source':'https://gamma-api.polymarket.com',
             'tennis_tag':864,'sports':sports,'open_events':len(open_rows),'open_pagination_complete':open_complete,
             'closed_recent_sample':len(closed_rows),'closed_pagination_exhausted':closed_complete,
             'open_by_sport':dict(collections.Counter(sport_of(e) for e in open_rows)),
             'open_market_types':dict(collections.Counter(m.get('sportsMarketType') or 'outright_or_unspecified' for e in open_rows for m in e.get('markets',[]))),
             'tradable_open_market_types':dict(collections.Counter(m.get('sportsMarketType') or 'outright_or_unspecified' for e in open_rows for m in e.get('markets',[]) if m.get('active') and not m.get('closed') and m.get('acceptingOrders'))),
             'unique_events_all_samples':len(inventories),'inventory':inventories,
             'category_sample_sizes':{s['sport']:len(a) for s,a in zip(sports,samples)},
             'open_tradable_match_events':sum(e['tradable_match_moneyline'] for e in open_inventory),
             'open_tradable_matches_by_sport':dict(collections.Counter(e['sport'] for e in open_inventory if e['tradable_match_moneyline'])),
             'open_qualifying_by_sport':dict(collections.Counter(e['sport'] for e in open_inventory if e['qualifying'])),
             'note':'Open-event pagination exhausted if true; closed history is a bounded sample, not all-time coverage. Counts can move during pagination. Catalog/market discovery is not prediction readiness.'}
    atomic_json(destination/'summary.json',summary)
    atomic_json(ROOT/'reports/poly-coverage-latest.json',summary)
    atomic_json(ROOT/'reports/poly-league-inventory.json',{'checked_at':summary['checked_at'],
                'rows':league_inventory(inventories),'note':summary['note']})
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(ROOT/'data/market-audit'/dt.datetime.now(dt.timezone.utc).date().isoformat()/'scan'))
    parser.add_argument('--max-open-pages',type=int,default=40);parser.add_argument('--closed-pages',type=int,default=10)
    args=parser.parse_args();summary=scan(args.output,args.max_open_pages,args.closed_pages)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('sports','inventory')},ensure_ascii=False,indent=2))
