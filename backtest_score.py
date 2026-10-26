#!/usr/bin/env python3
"""Causal 2024 selection / 2025+ test of completed-match score probabilities."""
import collections
import argparse
import datetime as dt
import hashlib
import json
import math
import re
import time
from pathlib import Path
import numpy as np
from core.data import ROOT as DEFAULT_ROOT, atomic_json, load_tour
from core.features import FEATURES, build_features
from core.linear import metrics
from core.scoring import distribution, quote
from core.validation import market_key


def observed(match):
    sets=[];target=match['best_of']//2+1;wa=wb=0
    for token in match['raw']['score'].split():
        found=re.fullmatch(r'(\d+)-(\d+)(?:\(\d+\))?',token)
        if not found or max(wa,wb)==target:return None
        a,b=map(int,found.groups())
        if not (max(a,b)==6 and min(a,b)<=4 or max(a,b)==7 and min(a,b) in (5,6)):return None
        if not match['y']:a,b=b,a
        sets.append((a,b));wa+=a>b;wb+=b>a
    if max(wa,wb)!=target:return None
    return {'sets':sets,'score':f'{wa}-{wb}','games':sum(a+b for a,b in sets),'margin':sum(a-b for a,b in sets)}


def tasks(bo):
    values=[('moneyline',{}),('tennis_first_set_winner',{}),('tennis_exact_score',{})]
    values += [('tennis_set_winner',{'set_number':i}) for i in range(2,bo+1)]
    values += [('tennis_first_set_totals',{'line':line}) for line in (7.5,8.5,9.5,10.5,11.5,12.5)]
    values += [('tennis_set_games_totals',{'line':line,'set_number':i}) for i in range(2,bo+1) for line in (8.5,9.5,10.5)]
    values += [('tennis_match_totals',{'line':line}) for line in (20.5,21.5,22.5,23.5,36.5,38.5,40.5)]
    values += [('tennis_set_totals',{'line':line}) for line in (2.5,3.5,4.5)]
    values += [('tennis_game_handicap',{'line':-line}) for line in (.5,1.5,2.5,3.5,4.5,5.5,6.5,7.5,8.5)]
    values += [('tennis_set_handicap',{'line':-line}) for line in (1.5,2.5)]
    values += [('match_winner_and_game_margin',{'line':-line}) for line in (3.5,4.5,5.5,7.5)]
    # Evaluate both named players and both handicap signs. A negative handicap
    # on B is a different event from a negative handicap on A.
    handicaps=[(kind,params) for kind,params in values if 'handicap' in kind or kind=='match_winner_and_game_margin']
    for kind,params in handicaps:
        values += [(kind,{**params,'selection':'b'}),
                   (kind,{**params,'line':-params['line']}),
                   (kind,{**params,'line':-params['line'],'selection':'b'})]
    return values


def outcomes(dist,actual,bo):
    for kind,params in tasks(bo):
        if kind=='tennis_exact_score':
            for score,p in dist['scores'].items():yield kind+':'+score,int(actual['score']==score),p
            continue
        period=1 if 'first_set' in kind else params.get('set_number')
        if period and period>len(actual['sets']):continue
        q=quote(dist,kind,**params);line=params.get('line');sets=actual['sets']
        if kind=='moneyline':y=int(int(actual['score'][0])>int(actual['score'][2]))
        elif kind in ('tennis_first_set_winner','tennis_set_winner'):y=int(sets[period-1][0]>sets[period-1][1])
        elif kind in ('tennis_first_set_totals','tennis_set_games_totals'):y=int(sum(sets[period-1])>line)
        elif kind=='tennis_match_totals':y=int(actual['games']>line)
        elif kind=='tennis_set_totals':y=int(len(sets)>line)
        elif kind=='tennis_set_handicap':
            sign=1 if params.get('selection','a')=='a' else -1
            y=int(sign*(int(actual['score'][0])-int(actual['score'][2]))+line>0)
        else:
            sign=1 if params.get('selection','a')=='a' else -1
            y=int(sign*actual['margin']+line>0 and (kind!='match_winner_and_game_margin' or
                  (actual['score'][0]>actual['score'][2])==(sign==1)))
        key=market_key(kind,params)
        yield key,y,q['probabilities_given_period_reached'][0]


def evaluate(expanded=False,root=DEFAULT_ROOT):
    ROOT=Path(root)
    started=time.time();snapshot_path=ROOT/('models/expanded/current.json' if expanded else 'models/current.json');snapshot=json.loads(snapshot_path.read_text());as_of=snapshot['as_of']
    source=json.loads((ROOT/'data/source-manifest.json').read_text())
    provenance=hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()
    if any(m['data']['manifest_sha256']!=provenance for m in snapshot['tours'].values()):raise ValueError('Winner snapshot and source manifest differ')
    for item in source['files']:
        if hashlib.sha256((ROOT/'data/raw'/item['tour']/item['name']).read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('Source file hash mismatch: '+item['name'])
    if expanded:
        extra=json.loads((ROOT/'data/expanded/source-manifest.json').read_text())
        fingerprint=hashlib.sha256(json.dumps(extra,sort_keys=True).encode()).hexdigest()
        if snapshot['tours']['atp']['data'].get('expanded_manifest_sha256')!=fingerprint:raise ValueError('Expanded manifest and snapshot differ')
        for item in extra['files']:
            if hashlib.sha256((ROOT/'data/expanded'/item['name']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Expanded source hash mismatch: '+item['name'])
    configs={};reports={}
    for tour in snapshot['tours']:
        print(tour,'causal score context',flush=True)
        matches,audit=load_tour(tour,as_of,root=ROOT,scope='expanded_atp' if expanded else 'main_tour')
        vectors,meta,_=build_features(tour,matches,as_of,include_score_context=True)
        model=snapshot['tours'][tour];cols=[FEATURES.index(k) for k in model['features']]
        # Same portable scalar formula as production inference; avoids platform
        # BLAS warnings and explicitly rejects any non-finite feature/logit.
        preds=[]
        for vector in vectors:
            logit=sum(max(-8,min(8,vector[c]/scale))*weight/model['temperature']
                      for c,scale,weight in zip(cols,model['scale'],model['weights']))
            if not math.isfinite(logit):raise ValueError('Non-finite score backtest logit')
            preds.append(1/(1+math.exp(-max(-35,min(35,logit)))))
        data=[];excluded=collections.Counter()
        for m,context,p in zip(matches,meta,preds):
            year=dt.date.fromordinal(m['start']).year
            if year<2024:continue
            a=observed(m)
            if a is None:excluded['nonstandard_score']+=1;continue
            if year==2024 and dt.date.fromordinal(m['available']).year!=2024:excluded['boundary_not_available']+=1;continue
            data.append((m,context,float(p),a,year))
        def scored(row,offset):
            m,c,p,a,year=row;pa,pb,_=c['serve_context']
            def shift(v):return 1/(1+math.exp(-(math.log(v/(1-v))+offset)))
            return distribution(shift(pa),shift(pb),p,m['best_of'],10 if m['best_of']==5 else 7)
        candidates=[]
        for offset in (-.08,0.,.08):
            losses=[]
            for row in data:
                if row[4]!=2024:continue
                d=scored(row,offset);a=row[3];bo=row[0]['best_of']
                for kind,params,y in [('tennis_first_set_winner',{},int(a['sets'][0][0]>a['sets'][0][1])),
                                      ('tennis_match_totals',{'line':22.5 if bo==3 else 38.5},int(a['games']>(22.5 if bo==3 else 38.5))),
                                      ('tennis_set_totals',{'line':2.5 if bo==3 else 3.5},int(len(a['sets'])>(2.5 if bo==3 else 3.5)))]:
                    p=quote(d,kind,**params)['probabilities'][0];p=max(1e-9,min(1-1e-9,p))
                    losses.append(-y*math.log(p)-(1-y)*math.log(1-p))
            if not losses:raise ValueError('Missing 2024 score-selection sample')
            candidates.append({'serve_logit_offset':offset,'selection_log_loss':sum(losses)/len(losses)})
        selected=min(candidates,key=lambda c:c['selection_log_loss']);offset=selected['serve_logit_offset']
        # 2024 empirical frequency is a simple frozen baseline, split by format.
        priors=collections.defaultdict(list);test=collections.defaultdict(lambda:[[],[],[]]);multiclass=[]
        cohorts=collections.defaultdict(lambda:collections.defaultdict(lambda:[[],[],[]]))
        for row in data:
            m,_,p,actual,year=row;dist=scored(row,offset)
            for key,y,pred in outcomes(dist,actual,m['best_of']):
                group=(m['best_of'],key)
                if year==2024:priors[group].append(y)
                else:
                    baseline=(sum(priors[group])+1)/(len(priors[group])+2)
                    target=test[key];target[0].append(y);target[1].append(pred);target[2].append(baseline)
                    target=cohorts[m['raw']['_competition']][key]
                    target[0].append(y);target[1].append(pred);target[2].append(baseline)
            if year>=2025:
                multiclass.append(-math.log(max(1e-9,dist['scores'][actual['score']])))
        result={key:{'model':metrics(np.asarray(y),np.asarray(p)),
                     '2024_empirical_baseline':metrics(np.asarray(y),np.asarray(base))}
                for key,(y,p,base) in test.items()}
        by_competition={name:{key:{'model':metrics(np.asarray(y),np.asarray(p)),
                                   '2024_empirical_baseline':metrics(np.asarray(y),np.asarray(base))}
                              for key,(y,p,base) in values.items()} for name,values in cohorts.items()}
        report={'tour':tour,'history_as_of':as_of,'scope':'expanded_atp' if expanded else 'main_tour','protocol':{'winner_model':'existing frozen 2012-2023 coefficients / 2024 temperature',
                'score_selection':'2024 only, three prespecified shared service-logit offsets',
                'independent_test':'2025 through available cutoff; pre-event histories only',
                'scope':('Main tour, Challenger main draw and ATP qualifying; no Challenger qualifying or ITF. ' if expanded else 'Completed main-tour singles. ')+
                        'Standard sets to 6 with tiebreak at 6-all; 2024+ Slam final tiebreak to 10; others to 7',
                'period_metrics':'Conditional on observed period being reached; non-reach is not a losing outcome',
                'baseline':'2024 smoothed empirical frequency per best_of and market parameter; no bookmaker odds'},
                'selection':selected,'candidates':candidates,'excluded':dict(excluded),
                'test_matches':len(multiclass),'exact_score_multiclass_log_loss':sum(multiclass)/len(multiclass),
                'markets':result,'by_competition':by_competition,'status':'experimental; indirect market probabilities have not passed live contract settlement acceptance'}
        reports[tour]=report
        configs[tour]={'serve_logit_offset':offset,'market_validation':result,'by_competition':by_competition,'test':{'n':len(multiclass),'exact_score_log_loss':report['exact_score_multiclass_log_loss'],
                                                         'first_set_winner':result['tennis_first_set_winner']['model']}}
        atomic_json(ROOT/f'reports/{tour}{"-expanded" if expanded else ""}-score-backtest.json',report)
        print(tour,'offset',offset,'test',len(multiclass),'first set LL',result['tennis_first_set_winner']['model']['log_loss'],flush=True)
    config={'schema':1,'history_as_of':as_of,'base_model_sha256':hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
            'tours':configs,'runtime_seconds':round(time.time()-started,2)}
    atomic_json(snapshot_path.parent/'score-config.json',config)
    return reports


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--expanded',action='store_true');args=parser.parse_args();evaluate(args.expanded)
