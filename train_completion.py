#!/usr/bin/env python3
"""Completion baseline using resolved Completed Match contracts, not odds."""
import collections
import argparse
import datetime as dt
import hashlib
import json
import re
from core.completion import cohort,timestamp,wilson,rule_days
from core.data import ROOT,atomic_json
from audit_poly_market_types import array,evidence_events


def label(event,market):
    if market.get('sportsMarketType')!='tennis_completed_match':return None,'not_completion'
    if market.get('closed') is not True or market.get('umaResolutionStatus')!='resolved':return None,'not_confirmed_resolved'
    try:
        names=[s.lower() for s in array(market.get('outcomes'))];prices=[float(s) for s in array(market.get('outcomePrices'))]
        if len(names)!=2 or set(names)!={'yes','no'} or sorted(prices)!=[0.,1.]:return None,'ambiguous_settlement'
        start=timestamp(event.get('startTime') or market.get('gameStartTime'))
        available=max(timestamp(market['closedTime']),timestamp(market['umaEndDate']))
        issued=timestamp(market['createdAt'])
    except (ValueError,TypeError,KeyError):return None,'missing_time_or_label'
    text=market.get('description') or ''
    # Avoid pooling an unrelated similarly named proposition into completion.
    if not re.search(r'normal play',text,re.I) or not re.search(r'walkover|retirement|forfeit',text,re.I):return None,'unrecognized_completion_rules'
    deadline=rule_days(text)
    if not deadline:return None,'unparsed_deadline'
    if deadline not in (7,14):return None,'unsupported_deadline'
    yes=int(prices[names.index('yes')])
    if issued>=start:return None,'created_after_scheduled_start'
    if available<issued or available<start and yes:return None,'invalid_label_timing'
    tour,competition=cohort(event)
    return {'market_id':str(market['id']),'event_id':str(event['id']),'start':start.isoformat(),'available':available.isoformat(),
            'issued_at':issued.isoformat(),'tour':tour,'competition':competition,'rule_version':deadline,'yes':yes,
            'description_sha256':hashlib.sha256(text.encode()).hexdigest()},None


def groups(rows):
    out=collections.defaultdict(lambda:{'n':0,'yes':0,'no':0})
    for r in rows:
        for t in (r['tour'],'*'):
            for c in (r['competition'],'*'):
                for v in (str(r['rule_version']),'*'):
                    g=out['|'.join((t,c,v))];g['n']+=1;g['yes']+=r['yes'];g['no']+=1-r['yes']
    for g in out.values():g['probability']=(g['yes']+1)/(g['n']+2)
    return dict(out)


def loss(rows,base,cohorts=None,strength=100):
    import math
    ll=brier=0.
    for r in rows:
        g=(cohorts or {}).get('|'.join((r['tour'],r['competition'],str(r['rule_version']))))
        p=(g['yes']+strength*base)/(g['n']+strength) if g and g['n']>=50 else base
        p=max(1e-9,min(1-1e-9,p));y=r['yes'];ll-=y*math.log(p)+(1-y)*math.log(1-p);brier+=(p-y)**2
    return {'n':len(rows),'log_loss':ll/len(rows),'brier':brier/len(rows),'observed_completion_rate':sum(r['yes'] for r in rows)/len(rows)} if rows else None


def split_rows(rows,as_of):
    cutoff=timestamp(as_of+'T00:00:00Z')+dt.timedelta(days=1)
    mature=cutoff-dt.timedelta(days=17)
    test_start=mature.replace(day=1)
    select_start=(test_start-dt.timedelta(days=1)).replace(day=1)
    def matured(r,at):return timestamp(r['available'])<at and timestamp(r['start'])<at-dt.timedelta(days=17)
    accepted=[r for r in rows if matured(r,cutoff)]
    fit=[r for r in rows if matured(r,select_start)]
    validation=[r for r in rows if timestamp(r['issued_at'])>=select_start and matured(r,test_start)]
    frozen=[r for r in rows if matured(r,test_start)]
    test=[r for r in accepted if timestamp(r['issued_at'])>=test_start]
    return accepted,fit,validation,frozen,test,select_start,test_start


def main(as_of=None,base=None):
    summary=json.loads((ROOT/'reports/poly-enumeration-summary.json').read_text())
    rows=[];excluded=collections.Counter();seen={}
    base=base or ROOT/'data/market-audit/2026-10-26/enumeration'
    for event,source in evidence_events(base,summary):
        for market in event.get('markets') or []:
            if market.get('sportsMarketType')!='tennis_completed_match':continue
            row,reason=label(event,market)
            if row is None:excluded[reason]+=1;continue
            row['source_page']=source
            if row['market_id'] in seen:
                if {k:v for k,v in row.items() if k!='source_page'}!={k:v for k,v in seen[row['market_id']].items() if k!='source_page'}:raise ValueError('Conflicting completion settlement')
                continue
            seen[row['market_id']]=row;rows.append(row)
    rows.sort(key=lambda r:(r['available'],r['market_id']))
    source_day=timestamp(summary['built_at']).date()
    as_of=as_of or (source_day-dt.timedelta(days=1)).isoformat()
    if dt.date.fromisoformat(as_of)>source_day:raise ValueError('Baseline cannot postdate source snapshot')
    return fit_labels(rows,as_of,summary['built_at'],excluded=excluded)


def fit_labels(rows,as_of,checked_at,root=ROOT,excluded=None):
    """Fit the unchanged chronological protocol from previously verified labels."""
    from pathlib import Path
    root=Path(root)
    if dt.date.fromisoformat(as_of)>timestamp(checked_at).date():raise ValueError('Baseline cannot postdate source snapshot')
    # Uniform 17-day maturity window avoids preferentially including fast Yes
    # resolutions while delayed/cancelled outcomes are still awaiting settlement.
    accepted,fit,validation,frozen,test,select_start,test_start=split_rows(rows,as_of)
    if any(len(part)<100 for part in (fit,validation,test)):raise ValueError('Insufficient mature chronological completion samples')
    prior=groups(fit);base_p=prior['*|*|*']['probability']
    candidates=[{'strength':s,'validation':loss(validation,base_p,prior,s)} for s in (50,200,1000)]
    chosen=min(candidates,key=lambda x:x['validation']['log_loss'])
    known=groups(frozen);global_p=known['*|*|*']['probability']
    scores={'grouped':loss(test,global_p,known,chosen['strength']),'global_frequency':loss(test,global_p),
            'always_complete_probability_0_999':loss(test,.999)}
    # Selection is fixed using September, never switch methods using October.
    global_validation=loss(validation,base_p)
    grouped_selected=chosen['validation']['log_loss']<global_validation['log_loss']
    config_groups=groups(accepted)
    config={'schema':1,'as_of':as_of,'source_checked_at':checked_at,'global':config_groups['*|*|*'],
            'groups':config_groups,'minimum_group_n':50,'prior_strength':chosen['strength'],
            'selected_method':'cohort_shrinkage' if grouped_selected else 'global_frequency',
            'test':{'protocol':f'Fit before {select_start.date()}; select subsequent issuance cohort; refit before {test_start.date()}; test subsequent issuance cohort. 17-day scheduled-start maturity embargo at each cutoff; only then-available resolved labels.',
                    'selected':scores['grouped'] if grouped_selected else scores['global_frequency'],'comparisons':scores},
            'source':'Archived public Gamma Completed Match, UMA-resolved with exact 1/0 settlement; no live price forecasting inputs',
            'label_sha256':hashlib.sha256(json.dumps(accepted,sort_keys=True).encode()).hexdigest()}
    atomic_json(root/'data/completion-labels.json',accepted)
    atomic_json(root/'models/completion.json',config)
    if (root/'models/expanded').exists():atomic_json(root/'models/expanded/completion.json',config)
    report={**config,'excluded':dict(excluded or {}),'raw_unique_resolved':len(rows),'accepted':len(accepted),
            'split_counts':{'fit':len(fit),'select':len(validation),'refit':len(frozen),'test':len(test)},
            'validation_candidates':candidates,'validation_global':global_validation,
            'raw_rate_95pct_wilson':wilson(config['global']['yes'],config['global']['n'])}
    atomic_json(root/'reports/completion-backtest.json',report)
    print(json.dumps({k:report[k] for k in ('accepted','global','selected_method','split_counts','test','excluded')},ensure_ascii=False,indent=2))
    return config


if __name__=='__main__':
    from pathlib import Path
    parser=argparse.ArgumentParser();parser.add_argument('--as-of');parser.add_argument('--base',type=Path);args=parser.parse_args();main(args.as_of,args.base)
