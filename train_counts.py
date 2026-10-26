#!/usr/bin/env python3
"""Train coherent length/set-score models with pre-event features only."""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import time
from pathlib import Path
import numpy as np
from core.counts import features,kernel_key,predict,loser_score_probabilities
from core.data import ROOT as DEFAULT_ROOT,atomic_json,load_tour
from core.features import FEATURES,build_features
from core.evaluation import MarketEvaluation
from core.linear import fit,probabilities,metrics,calibrate
from backtest_score import observed,outcomes


def main(expanded=False,root=DEFAULT_ROOT):
    ROOT=Path(root)
    started=time.time();path=ROOT/('models/expanded/current.json' if expanded else 'models/current.json')
    snapshot=json.loads(path.read_text());configs={};reports={}
    for tour,base_model in snapshot['tours'].items():
        print(tour,'expanded' if expanded else 'main','building causal count features',flush=True)
        matches,audit=load_tour(tour,snapshot['as_of'],root=ROOT,scope='expanded_atp' if expanded else 'main_tour')
        source=json.loads((ROOT/'data/source-manifest.json').read_text())
        if base_model['data']['manifest_sha256']!=hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest():raise ValueError('Main source/snapshot mismatch')
        for item in source['files']:
            if item['tour']==tour and hashlib.sha256((ROOT/'data/raw'/tour/item['name']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Main source file hash mismatch')
        if expanded:
            extra=json.loads((ROOT/'data/expanded/source-manifest.json').read_text())
            if base_model['data']['expanded_manifest_sha256']!=hashlib.sha256(json.dumps(extra,sort_keys=True).encode()).hexdigest():raise ValueError('Expanded source/snapshot mismatch')
            for item in extra['files']:
                if hashlib.sha256((ROOT/'data/expanded'/item['name']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Expanded source file hash mismatch')
        vectors,meta,_=build_features(tour,matches,snapshot['as_of'],include_score_context=True)
        data=[];cols=[FEATURES.index(k) for k in base_model['features']]
        for m,v,c in zip(matches,vectors,meta):
            actual=observed(m)
            if actual is None:continue
            year=dt.date.fromordinal(m['start']).year;available_year=dt.date.fromordinal(m['available']).year
            if year<2012:continue
            # Exclude unavailable year-boundary results from selection/calibration.
            if year<=2024 and year!=available_year:continue
            pa,pb,_=c['serve_context']
            logit=sum(max(-8,min(8,v[i]/s))*w/base_model['temperature'] for i,s,w in zip(cols,base_model['scale'],base_model['weights']))
            p=1/(1+math.exp(-max(-35,min(35,logit))))
            data.append((m,v,pa,pb,actual,year,p))
        config={'length_models':{},'kernel_global':[0]*7,'kernel_surfaces':{},'kernel_cells':{},'kernel_prior_strength':100}
        length_selection={}
        for bo in sorted({r[0]['best_of'] for r in data}):
            config['length_models'][str(bo)]={}
            for threshold in ([3] if bo==3 else [4,5]):
                subset=[r for r in data if r[0]['best_of']==bo and (threshold!=5 or len(r[4]['sets'])>=4)]
                x=np.asarray([features(v,pa,pb,m['surface'],1 if m['y'] else -1) for m,v,pa,pb,a,year,p in subset])
                y=np.asarray([float(len(r[4]['sets'])>=threshold) for r in subset]);years=np.asarray([r[5] for r in subset])
                train=years<2023;selection=years==2023;calibration=years==2024
                if any(mask.sum()<150 for mask in (train,selection,calibration)):raise ValueError('Insufficient length fit/selection/calibration sample')
                candidates=[]
                for penalty in (1.,10.,100.):
                    candidate=fit(x[train],y[train],penalty)
                    candidates.append((metrics(y[selection],probabilities(x[selection],candidate))['log_loss'],penalty))
                _,penalty=min(candidates);model=fit(x[train|selection],y[train|selection],penalty)
                model['temperature']=calibrate(x[calibration],y[calibration],model)
                config['length_models'][str(bo)][str(threshold)]=model
                length_selection[f'{bo}:{threshold}']={'penalty':penalty,'candidates':candidates,'fit_n':int(train.sum()),
                                                       'selection_n':int(selection.sum()),'calibration_n':int(calibration.sum())}
        def histogram(rows):
            model={'kernel_global':[0]*7,'kernel_surfaces':{},'kernel_cells':{},'kernel_prior_strength':100,
                   'kernel_period_global':{},'kernel_period_cells':{},'kernel_format_global':{}}
            for m,v,pa,pb,actual,year,p in rows:
                for period,(ga,gb) in enumerate(actual['sets'],1):
                    loser=min(ga,gb);sign=1 if ga>gb else -1
                    key=kernel_key(v,pa,pb,m['surface'],sign)
                    model['kernel_global'][loser]+=1
                    model['kernel_surfaces'].setdefault(m['surface'],[0]*7)[loser]+=1
                    model['kernel_cells'].setdefault(key,[0]*7)[loser]+=1
                    prefix=f"{m['best_of']}:{period}"
                    model['kernel_format_global'].setdefault(str(m['best_of']),[0]*7)[loser]+=1
                    model['kernel_period_global'].setdefault(prefix,[0]*7)[loser]+=1
                    model['kernel_period_cells'].setdefault(prefix+'|'+key,[0]*7)[loser]+=1
            return model
        hist=histogram([r for r in data if r[5]<2023]);candidates=[]
        for strength in (20,100,500):
            hist['kernel_prior_strength']=strength;losses=[]
            for m,v,pa,pb,actual,year,p in data:
                if year!=2023:continue
                for ga,gb in actual['sets']:
                    q=loser_score_probabilities(hist,v,pa,pb,m['surface'],1 if ga>gb else -1)
                    losses.append(-math.log(q[min(ga,gb)]))
            candidates.append((sum(losses)/len(losses),strength))
        _,strength=min(candidates)
        # Select period-specific shrinkage strictly on 2023 set-score labels.
        hist['kernel_prior_strength']=strength;period_candidates=[]
        for period_strength in (None,20,100,500):
            hist['kernel_period_strength']=period_strength;losses=[]
            for m,v,pa,pb,actual,year,p in data:
                if year!=2023:continue
                for period,(ga,gb) in enumerate(actual['sets'],1):
                    q=loser_score_probabilities(hist,v,pa,pb,m['surface'],1 if ga>gb else -1,period,m['best_of'])
                    losses.append(-math.log(q[min(ga,gb)]))
            period_candidates.append({'strength':period_strength,'selection_log_loss':sum(losses)/len(losses)})
        selected_period=min(period_candidates,key=lambda row:row['selection_log_loss'])['strength']
        config.update(histogram([r for r in data if r[5]<=2023]))
        config.update(kernel_prior_strength=strength,kernel_period_strength=selected_period)
        evaluator=MarketEvaluation()
        for m,v,pa,pb,actual,year,p in data:
            if year<2024:continue
            dist=predict(config,v,pa,pb,m['surface'],m['best_of'],p,10 if m['best_of']==5 else 7)
            evaluator.add(year,m['raw']['_competition'],m['best_of'],outcomes(dist,actual,m['best_of']),
                          dist['scores'],actual['score'])
        evaluation=evaluator.summary();result=evaluation['markets']
        score_test=evaluation['exact_score_top_pick']['all']
        kind='learned_length_and_period_set_scores' if selected_period is not None else 'learned_length_and_empirical_set_scores'
        config.update(market_validation=result,by_best_of=evaluation['by_best_of'],
                      by_competition=evaluation['by_competition'],by_competition_best_of=evaluation['by_competition_best_of'],
                      exact_score_top_pick=evaluation['exact_score_top_pick'],
                      test={'n':score_test['n'],'exact_score_log_loss':score_test['multiclass_log_loss']},
                      model_kind=kind,validation_schema=2,
                      protocol='2012-22 fit, 2023 selection/refit, 2024 temperature, reused 2025+ retrospective comparison; requires future validation')
        configs[tour]=config
        report={'tour':tour,'scope':'expanded_atp' if expanded else 'main_tour','as_of':snapshot['as_of'],
                'test_matches':score_test['n'],**evaluation,'length_selection':length_selection,'kernel_selection':candidates,
                'period_kernel_selection':period_candidates,'selected_period_strength':selected_period,
                'model_kind':kind,'selected_kernel_strength':strength,'protocol':config['protocol'],
                'baseline_protocol':'Frozen 2024 frequency by best_of/parameter/handicap side; competition tables additionally split by competition',
                'limitations':['Test period was inspected in earlier model development; improvements are retrospective and need forward validation.',
                               'Standard completed singles only; no live state, injury or nonstandard match-tiebreak format.'],
                'exact_score_multiclass_log_loss':score_test['multiclass_log_loss']}
        reports[tour]=report
        atomic_json(ROOT/f'reports/{tour}{"-expanded" if expanded else ""}-counts-backtest.json',report)
        print(tour,'test',score_test['n'],'totals22.5',result['tennis_match_totals:{"line": 22.5}']['model']['log_loss'],
              'sets2.5',result['tennis_set_totals:{"line": 2.5}']['model']['log_loss'],flush=True)
    bundle={'schema':1,'base_model_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'as_of':snapshot['as_of'],
            'tours':configs,'runtime_seconds':round(time.time()-started,2)}
    atomic_json(path.parent/'count-config.json',bundle)
    return reports


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--expanded',action='store_true');args=parser.parse_args();main(args.expanded)
