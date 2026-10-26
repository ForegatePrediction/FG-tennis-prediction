#!/usr/bin/env python3
"""Refresh actual Poly singles fixtures only for date-scoped reviewed competitions."""
import argparse
import collections
import datetime as dt
import json
from pathlib import Path
from core.completion import timestamp
from core.data import ROOT,atomic_json
from core.foregate_detail import fixture_record
from core.poly_feed import pages


def collect(feed,registry,now=None):
    now=now or dt.datetime.now(dt.timezone.utc);fixtures={};skipped=collections.Counter();seen=set()
    for events,url in feed:
        for event in events:
            identifier=str(event['id'])
            if identifier in seen:raise ValueError('Repeated event in feed')
            seen.add(identifier)
            try:
                if event.get('closed') or event.get('live') or event.get('ended'):raise ValueError('closed_or_started')
                start=timestamp(event['startTime'])
                if not now<start<=now+dt.timedelta(days=14):raise ValueError('outside_future_window')
                teams=event.get('teams') or []
                tours={t.get('league') for t in teams}
                if len(teams)!=2 or len(tours)!=1 or next(iter(tours)) not in ('atp','wta'):raise ValueError('not_main_singles')
                tour=next(iter(tours));league=(event.get('eventMetadata') or {}).get('league')
                matches=[r for r in registry['competitions'] if league in r['names'] and r['tour']==tour
                         and r['from']<=start.date().isoformat()<=r['through']]
                if len(matches)!=1:raise ValueError('unreviewed_competition_or_date')
                reviewed=matches[0]
                money=[m for m in event.get('markets',[]) if m.get('sportsMarketType')=='moneyline']
                if len(money)!=1:raise ValueError('ambiguous_moneyline')
                if money[0].get('closed'):raise ValueError('closed_moneyline')
                names=money[0]['outcomes'];names=json.loads(names) if isinstance(names,str) else names
                if len(names)!=2 or set(names)!={t['name'] for t in teams}:raise ValueError('player_identity_mismatch')
                context={k:reviewed[k] for k in ('surface','best_of','indoor','final_tiebreak_points')}
                context.update(competition='main_tour',format='main_tour_singles')
                review={'verified':True,'a':names[0],'b':names[1],'tour':tour,'checked_at':now.isoformat(),
                        'source':url+' ; '+reviewed['source']+' ; '+registry['rules_source'],'context':context}
                record=fixture_record(event,review)
                if record['status']!='NOT_STARTED':raise ValueError('unsupported_format')
                if event['slug'] in fixtures:raise ValueError('Duplicate fixture slug')
                fixtures[event['slug']]=record
            except (ValueError,KeyError,TypeError) as exc:skipped[str(exc)]+=1
    return {'schema':1,'checked_at':now.isoformat(),'fixtures':fixtures,'categories':{'30157':'atp'},
            'collection':{'automatic':True,'seen':len(seen),'imported':len(fixtures),'skipped':dict(skipped),
                          'reviewed_competitions':len(registry['competitions']),'scope':'Date-scoped reviewed main-tour singles only'}}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--registry',type=Path,default=ROOT/'config/competitions-reviewed.json')
    args=parser.parse_args();result=collect(pages(),json.loads(args.registry.read_text()))
    atomic_json(args.output,result)
    print(json.dumps(result['collection'],ensure_ascii=False))
