#!/usr/bin/env python3
"""Independent ESPN result cross-check; never feeds outcomes into model features."""
import argparse
import collections
import datetime as dt
import json
import re
from pathlib import Path
from core.data import ROOT, read_csv, regular_score, atomic_json
from core.inference import normalize

SLAMS={'Australian Open':'Australian Open','Roland Garros':'Roland Garros','French Open':'Roland Garros',
       'Wimbledon':'Wimbledon','US Open':'US Open'}


def crosscheck(tour,path,year=2024,root=ROOT):
    primary=read_csv((Path(root)/'data/raw'/tour/f'{year}{"_wta" if tour=="wta" else ""}.csv').read_bytes())
    lookup={};expected=collections.Counter()
    for row in primary:
        event=SLAMS.get(row['tourney_name'])
        if not event or not regular_score(row):continue
        pair=tuple(sorted(normalize(row[k+'_name']) for k in ('winner','loser')))
        lookup[(event,pair)]=row;expected[event]+=1
    events=json.loads(Path(path).read_text())['events'];counts=collections.Counter();details=[];seen=set()
    for event in events:
        name=SLAMS.get(event['name'])
        if not name:continue
        for grouping in event.get('groupings',[]):
            if grouping.get('grouping',{}).get('slug')!=('mens-singles' if tour=='atp' else 'womens-singles'):continue
            for match in grouping.get('competitions',[]):
                if match['id'] in seen:continue
                seen.add(match['id'])
                if 'qualif' in match.get('round',{}).get('displayName','').lower():continue
                if not match.get('status',{}).get('type',{}).get('completed'):continue
                competitors=match.get('competitors',[])
                if len(competitors)!=2 or sum(bool(p.get('winner')) for p in competitors)!=1:continue
                winner=next(p for p in competitors if p.get('winner'));loser=next(p for p in competitors if not p.get('winner'))
                wn=normalize(winner['athlete']['displayName']);ln=normalize(loser['athlete']['displayName'])
                pair=tuple(sorted((wn,ln)));row=lookup.get((name,pair))
                if not row:
                    counts['unmatched_name_pair_or_nonstandard_result']+=1;continue
                counts['matched_completed_results']+=1
                win_ok=wn==normalize(row['winner_name'])
                espn_score=[(int(a['value']),int(b['value'])) for a,b in zip(winner.get('linescores',[]),loser.get('linescores',[]))]
                source_score=[tuple(map(int,re.match(r'(\d+)-(\d+)',s).groups())) for s in row['score'].split()]
                score_ok=espn_score==source_score
                counts['winner_agreement']+=int(win_ok);counts['set_score_agreement']+=int(score_ok)
                if not win_ok or not score_ok:details.append({'event':name,'espn_id':match['id'],'primary_score':row['score'],'espn_score':espn_score,'winner_agreement':win_ok})
    return {'tour':tour,'year':year,'scope':'four Grand Slam main-draw singles; exact normalized full-name pairs; excludes nonstandard primary scores',
            'source_url':f'https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard?dates={year}0101-{year}1231&limit=1000',
            'primary_completed_by_event':dict(expected),'counts':dict(counts),'disagreements':details,
            'note':'A sample cross-check does not prove all matches or data fields are correct; unmatched names are not automatically treated as data errors.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--atp',required=True);parser.add_argument('--wta',required=True);parser.add_argument('--year',type=int,default=2024)
    args=parser.parse_args();out={'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'results':[crosscheck('atp',args.atp,args.year),crosscheck('wta',args.wta,args.year)]}
    atomic_json(ROOT/'reports/independent-source-check.json',out);print(json.dumps(out,ensure_ascii=False,indent=2))
