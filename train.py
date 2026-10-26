#!/usr/bin/env python3
"""Walk-forward research and model build. Hyperparameters never use the test set."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from core.data import ROOT, atomic_json, load_tour, number
from core.features import FEATURES, GROUPS, build_features
from core.linear import fit, probabilities, metrics, calibrate, sigmoid


def ordinal(day):return dt.date.fromisoformat(day).toordinal()


def train_tour(tour,as_of,root=ROOT,scope='main_tour'):
    started=time.time();print(f'{tour}: validating and building causal history',flush=True)
    matches,audit=load_tour(tour,as_of,root,scope)
    vectors,meta,state=build_features(tour,matches,as_of)
    x=np.asarray(vectors,dtype=float);y=np.asarray([m['y'] for m in meta],dtype=float)
    days=np.asarray([m['start'] for m in meta]);available=np.asarray([m['available'] for m in meta])
    # 2010-11 initialize player ratings; they do not fit global coefficients.
    training=(days>=ordinal('2012-01-01'))&(available<ordinal('2023-01-01'))
    validation=(days>=ordinal('2023-01-01'))&(available<ordinal('2024-01-01'))
    calibration=(days>=ordinal('2024-01-01'))&(available<ordinal('2025-01-01'))
    test=days>=ordinal('2025-01-01')
    for name,mask in [('training',training),('validation',validation),('calibration',calibration),('test',test)]:
        if mask.sum()<300:raise ValueError(f'{tour}: insufficient {name} rows: {mask.sum()}')
    candidates=[]
    for group,names in GROUPS.items():
        cols=[FEATURES.index(k) for k in names];xx=x[:,cols]
        for penalty in (1.,10.,100.):
            model=fit(xx[training],y[training],penalty)
            score=metrics(y[validation],probabilities(xx[validation],model))
            candidates.append({'group':group,'penalty':penalty,'validation':score})
        print(f'{tour}: {group} validation loss {min(c["validation"]["log_loss"] for c in candidates if c["group"]==group):.5f}',flush=True)
    selected=min(candidates,key=lambda c:c['validation']['log_loss'])
    names=GROUPS[selected['group']];cols=[FEATURES.index(k) for k in names];xx=x[:,cols]
    fitted=fit(xx[training|validation],y[training|validation],selected['penalty'])
    fitted['temperature']=calibrate(xx[calibration],y[calibration],fitted)
    predicted=probabilities(xx,fitted)
    baseline=sigmoid(x[:,FEATURES.index('elo')]*np.log(10))
    surface_baseline=sigmoid(x[:,FEATURES.index('surface_elo')]*np.log(10))
    ranking_model=fit(x[training|validation][:,[FEATURES.index(k) for k in GROUPS['ranking']]],y[training|validation],10.)
    ranking_pred=probabilities(x[:,[FEATURES.index(k) for k in GROUPS['ranking']]],ranking_model)
    results={'model':metrics(y[test],predicted[test]),'elo':metrics(y[test],baseline[test]),
             'surface_elo':metrics(y[test],surface_baseline[test]),'ranking_logistic':metrics(y[test],ranking_pred[test])}
    both_ranked=test & np.asarray([all(number(m['raw'].get(p+'_rank'),0)>0 for p in ('winner','loser')) for m in matches])
    results['higher_rank_only']={'n':int(both_ranked.sum()),
                                'accuracy':float(np.mean((x[both_ranked,FEATURES.index('rank')]>=0)==y[both_ranked]))}
    # Event-block bootstrap respects correlation between matches in a tournament.
    eps=1e-9
    def losses(p):return -y*np.log(np.clip(p,eps,1-eps))-(1-y)*np.log(np.clip(1-p,eps,1-eps))
    diff=losses(predicted)-losses(baseline)
    blocks={}
    for i,m in enumerate(meta):
        if test[i]:blocks.setdefault(m['event'],[]).append(i)
    block_sum=np.asarray([float(diff[ids].sum()) for ids in blocks.values()]);block_n=np.asarray([len(ids) for ids in blocks.values()])
    rng=np.random.default_rng(20261025);draws=rng.integers(0,len(blocks),size=(1000,len(blocks)))
    intervals=block_sum[draws].sum(axis=1)/block_n[draws].sum(axis=1)
    by_year={str(year):metrics(y[mask],predicted[mask]) for year in (2025,2026)
             for mask in [test&(days>=ordinal(f'{year}-01-01'))&(days<ordinal(f'{year+1}-01-01'))] if mask.any()}
    by_surface={surface:metrics(y[mask],predicted[mask]) for surface in ('Hard','Clay','Grass','Carpet')
                for mask in [test&np.asarray([m['surface']==surface for m in meta])] if mask.any()}
    by_format={str(bo):metrics(y[mask],predicted[mask]) for bo in (3,5)
               for mask in [test&np.asarray([m['best_of']==bo for m in meta])] if mask.any()}
    by_competition={name:{'model':metrics(y[mask],predicted[mask]),'elo':metrics(y[mask],baseline[mask])}
                    for name in sorted({m['raw']['_competition'] for m in matches})
                    for mask in [test&np.asarray([m['raw']['_competition']==name for m in matches])] if mask.any()}
    # Ablation fits the same dates; diagnostic only, not used for model selection.
    ablation={}
    for group in ('core','enhanced_no_h2h','enhanced'):
        best=min((c for c in candidates if c['group']==group),key=lambda c:c['validation']['log_loss'])
        col=[FEATURES.index(k) for k in GROUPS[group]];xs=x[:,col]
        alt=fit(xs[training|validation],y[training|validation],best['penalty'])
        alt['temperature']=calibrate(xs[calibration],y[calibration],alt)
        ablation[group]={'penalty':best['penalty'],'temperature':alt['temperature'],'test':metrics(y[test],probabilities(xs[test],alt))}
    source=json.loads((Path(root)/'data/source-manifest.json').read_text())
    if scope=='expanded_atp':
        expanded=json.loads((Path(root)/'data/expanded/source-manifest.json').read_text())
        for item in expanded['files']:
            if hashlib.sha256((Path(root)/'data/expanded'/item['name']).read_bytes()).hexdigest()!=item['sha256']:
                raise ValueError('Expanded source manifest mismatch: '+item['name'])
    # Reject a partial data refresh rather than publish mismatched provenance.
    for item in source['files']:
        if item['tour']==tour:
            raw=(Path(root)/'data/raw'/tour/item['name']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Source manifest mismatch: '+item['name'])
    report={'tour':tour,'as_of':as_of,'protocol':{'warmup':'2010-2011','fit':'2012-2022','select':'2023',
            'refit':'2012-2023','calibrate':'2024','test':'2025 through as_of; global coefficients frozen',
            'features':'pre-event only; release ordinary events +7 days, Finals +8, Masters/Premier +14, Slams +15; also last source date +1 day'},
            'accepted_matches':len(matches),'split_counts':{k:int(v.sum()) for k,v in [('fit',training),('select',validation),('calibrate',calibration),('test',test)]},
            'selected':selected,'temperature':fitted['temperature'],'test':results,'by_year':by_year,
            'by_surface':by_surface,'by_best_of':by_format,'scope':scope,'by_competition':by_competition,'ablation':ablation,'candidates':candidates,
            'model_minus_elo_logloss_95pct_event_bootstrap':np.quantile(intervals,[.025,.975]).tolist(),
            'runtime_seconds':round(time.time()-started,2)}
    model={'schema':1,'tour':tour,'as_of':as_of,'built_at':dt.datetime.now(dt.timezone.utc).isoformat(),
           'features':names,'selected_group':selected['group'],'penalty':selected['penalty'],**fitted,
           'state':state.export(),'data':{'checked_at':source['checked_at'],'accepted_matches':len(matches),
           'latest_source_date':audit['latest_source_date'],'latest_history_available':audit['latest_history_available'],
           'source':'https://stats.tennismylife.org/tennis-match-database',
           'manifest_sha256':hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()},
           'test_metrics':results['model'],'coefficient_fit_through':'2023-12-31','calibrated_on':'2024','scope':scope,
           'by_competition_test':by_competition}
    if scope=='expanded_atp':model['data']['expanded_manifest_sha256']=hashlib.sha256(json.dumps(expanded,sort_keys=True).encode()).hexdigest()
    print(f'{tour}: {selected["group"]}, test n={test.sum()}, accuracy={results["model"]["accuracy"]:.4%}, logloss={results["model"]["log_loss"]:.5f}, {report["runtime_seconds"]}s',flush=True)
    return model,report,audit


def main(as_of=None,root=ROOT):
    as_of=as_of or (dt.datetime.now(dt.timezone.utc).date()-dt.timedelta(days=1)).isoformat()
    built={tour:train_tour(tour,as_of,root) for tour in ('atp','wta')}
    # Publish one combined file only after both tours and checks pass.
    atomic_json(Path(root)/'models/current.json',{'schema':1,'as_of':as_of,'tours':{t:v[0] for t,v in built.items()}})
    for tour,(_,report,audit) in built.items():
        atomic_json(Path(root)/f'reports/{tour}-backtest.json',report)
        atomic_json(Path(root)/f'reports/{tour}-data-audit.json',audit)
    return built


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--as-of')
    args=parser.parse_args();main(args.as_of)
