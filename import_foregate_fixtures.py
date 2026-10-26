#!/usr/bin/env python3
"""Build the local GET prediction index from archived events and reviewed context.

No API keys and no request-time scraping. Missing context is reported, never guessed.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
from core.data import atomic_json
from core.foregate_detail import fixture_record


def build(events,reviews):
    if isinstance(events,dict):events=[events]
    if not isinstance(events,list):raise ValueError('Event object or array required')
    records={};errors=[];seen=set()
    for event in events:
        slug=event.get('eventSlug') or event.get('slug')
        if not slug or slug in seen:raise ValueError('Unique eventSlug required')
        seen.add(slug)
        try:records[slug]=fixture_record(event,reviews['fixtures'][slug],foregate='matches' in event)
        except (ValueError,KeyError,TypeError) as exc:errors.append({'eventSlug':slug,'reason':str(exc)})
    categories=reviews.get('categories',{})
    if not isinstance(categories,dict) or any(not isinstance(k,str) or v not in ('atp','wta') for k,v in categories.items()):
        raise ValueError('Categories require string IDs mapped to atp or wta')
    return {'schema':1,'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'fixtures':records,'categories':categories,'import_errors':errors}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--events',type=Path,required=True);p.add_argument('--contexts',type=Path,required=True)
    p.add_argument('--output',type=Path,default=Path('data/foregate-fixtures.json'))
    args=p.parse_args();value=build(json.loads(args.events.read_text()),json.loads(args.contexts.read_text()))
    # Publishing a partial file must be a deliberate operator decision; keep the previous index on errors.
    if value['import_errors']:raise SystemExit(json.dumps(value['import_errors'],ensure_ascii=False))
    atomic_json(args.output,value)
    print(json.dumps({'fixtures':len(value['fixtures']),'output':str(args.output)}))
