#!/usr/bin/env python3
"""Incrementally recheck resolved free Gamma completion labels before daily fitting."""
import collections
import datetime as dt
import gzip
import json
from pathlib import Path
from core.completion import timestamp
from core.data import ROOT,atomic_json
from core.poly_feed import pages
from train_completion import fit_labels,label


def merge_labels(checkpoint,feed,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    checked=timestamp(checkpoint['checked_at'])
    if checked>now+dt.timedelta(minutes=5):raise ValueError('Future completion checkpoint')
    # A 45-day overlap exceeds the 17-day maturity embargo and ordinary 7/14-day rules.
    # Keep the complete verified historical seed; do not start a fresh biased recent-only sample.
    cutoff=min(checked,now)-dt.timedelta(days=45)
    rows={r['market_id']:r for r in checkpoint['labels']};excluded=collections.Counter();count=0;finished=False
    if len(rows)!=len(checkpoint['labels']) or len(rows)<1000:raise ValueError('Invalid verified completion seed')
    seen=set()
    for page_index,(events,url) in enumerate(feed):
        if page_index%10==0:print(json.dumps({'completion_page':page_index,'labels':len(rows)}),flush=True)
        if not events:finished=True;break
        for event in events:
            identifier=str(event['id'])
            if identifier in seen:raise ValueError('Repeated completion event')
            seen.add(identifier)
            for market in event.get('markets') or []:
                if market.get('sportsMarketType')!='tennis_completed_match':continue
                row,reason=label(event,market)
                if row is None:excluded[reason]+=1;continue
                old=rows.get(row['market_id'])
                if old and any(old.get(k)!=v for k,v in row.items() if k not in ('tour','competition')):raise ValueError('Conflicting historical settlement')
                if old and any(old.get(k)!=row.get(k) for k in ('tour','competition')):
                    excluded['historical_cohort_metadata_drift_kept_original']+=1
                    continue
                row['source_page']=url;rows[row['market_id']]=row;count+=1
        if max(timestamp(e['createdAt']) for e in events)<cutoff:finished=True;break
    else:finished=True  # Natural pagination exhaustion is also a complete bounded recheck.
    if not finished:raise ValueError('Incomplete completion recheck')
    return {'schema':1,'checked_at':now.isoformat(),'labels':sorted(rows.values(),key=lambda r:(r['available'],r['market_id'])),
            'collection':{'rechecked_resolved':count,'excluded':dict(excluded),'overlap_days':45,
                          'limitation':'Unresolved or newly revised contracts older than overlap may be missed; archived seed is retained.'}}


if __name__=='__main__':
    path=ROOT/'data/completion-checkpoint.json.gz'
    with gzip.open(path,'rt') as stream:seed=json.load(stream)
    value=merge_labels(seed,pages(closed=True))
    now=timestamp(value['checked_at']);as_of=(now.date()-dt.timedelta(days=1)).isoformat()
    config=fit_labels(value['labels'],as_of,value['checked_at'])
    config['incremental_collection']=value['collection'];atomic_json(ROOT/'models/completion.json',config)
    temporary=path.with_suffix('.tmp')
    with gzip.open(temporary,'wt') as stream:json.dump(value,stream)
    temporary.replace(path)
