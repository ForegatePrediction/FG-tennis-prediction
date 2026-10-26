"""Offline import of Foregate detail or Gamma events; prices are ignored."""
import datetime as dt
import json

from .inference import normalize
from .markets import compile_market


def string_id(value):
    if not isinstance(value,str) or not value.strip():raise ValueError('Platform and asset IDs must be nonempty strings')
    return value


def market_type(row):
    a=row.get('sportsMarketType');b=row.get('marketSportsType')
    if a and b and a!=b:raise ValueError('Conflicting sportsMarketType and marketSportsType')
    return a or b


def iso_milliseconds(value):
    if not isinstance(value,str) or not value.isdigit():raise ValueError('Millisecond timestamp string required')
    return dt.datetime.fromtimestamp(int(value)/1000,dt.timezone.utc).isoformat()


def detail_event(detail):
    match=detail['matches'];a=match['homeTeam']['name'];b=match['awayTeam']['name']
    start=match.get('matchStartTime') or detail.get('matchStartTime')
    if detail.get('matchStartTime') and str(start)!=str(detail['matchStartTime']):raise ValueError('Conflicting matchStartTime fields')
    rows=detail['outcomes']
    if not isinstance(rows,list) or not 1<=len(rows)<=200:raise ValueError('Expected 1..200 Foregate outcomes')
    markets=[]
    for row in rows:
        kind=market_type(row)
        market={'id':string_id(row['outcomeId']),'conditionId':row.get('conditionId'),
                'sportsMarketType':kind,'question':row.get('title') or row.get('name') or detail.get('title'),
                'description':row.get('rules') or (detail.get('rules') if len(rows)==1 else ''),
                'outcomes':[row['yesOptionTitle'],row['noOptionTitle']],
                'clobTokenIds':[string_id(row['yesAssetId']),string_id(row['noAssetId'])]}
        for key in ('line','score','score_player','groupItemTitle'):
            if key in row:market[key]=row[key]
        market['_foregate_options']=[{'optionId':string_id(row[side+'OptionId']),
            'assetId':string_id(row[side+'AssetId']),'title':row[side+'OptionTitle']} for side in ('yes','no')]
        if row.get('status') not in (None,'open') or row.get('isOnline') in (0,False,'false'):
            market['_unavailable_reason']='Foregate outcome is not open/online'
        markets.append(market)
    league=str(match.get('leagueName','')).lower()
    tour=league if league in ('atp','wta') else None
    return {'id':string_id(detail['marketId']),'slug':detail['eventSlug'],'title':detail['title'],
            'startTime':iso_milliseconds(start),'markets':markets,'tour':tour,'a':a,'b':b,
            'status':match.get('matchStatus'),'closed':detail.get('status')!='open',
            'categoryIds':detail.get('categoryIds',[])}


def fixture_record(event,review,foregate=False):
    if not isinstance(review,dict) or review.get('verified') is not True or not review.get('source'):
        raise ValueError('Every imported event requires a reviewed context with provenance')
    if foregate:event=detail_event(event)
    markets=event['markets'];anchors=[m for m in markets if market_type(m)=='moneyline']
    if len(anchors)!=1:raise ValueError('Unique match moneyline required')
    labels=anchors[0]['outcomes'];labels=json.loads(labels) if isinstance(labels,str) else labels
    if not isinstance(labels,list) or len(labels)!=2 or any(normalize(x) in ('yes','no') for x in labels):
        raise ValueError('Named singles moneyline anchor required')
    a,b=(event['a'],event['b']) if foregate else labels
    tour=review['tour']
    if tour not in ('atp','wta') or event.get('tour') and event['tour']!=tour:raise ValueError('Reviewed tour contradicts detail')
    if [normalize(x) for x in (a,b)]!=[normalize(review[k]) for k in ('a','b')]:raise ValueError('Reviewed players contradict event ordering')
    context=review.get('context')
    if not isinstance(context,dict) or any(k not in context for k in ('surface','best_of','final_tiebreak_points','competition','format','indoor')):
        raise ValueError('Complete reviewed fixture context required')
    if context['surface'] not in ('Hard','Clay','Grass','Carpet') or type(context['best_of']) is not int or context['best_of'] not in (3,5):
        raise ValueError('Invalid reviewed court or match format')
    from .completion import timestamp
    timestamp(review['checked_at'])
    mapping={side:{'poly_name':name,'aliases':review.get('aliases',{}).get(side,[])} for side,name in (('a',a),('b',b))}
    specs=[];bindings={};issues=[];ids=set()
    for raw in markets:
        mid=string_id(raw['id'])
        if mid in ids:raise ValueError('Duplicate market/outcome ID')
        ids.add(mid);raw={**raw,'sportsMarketType':market_type(raw)}
        try:
            if raw.get('closed'):raise ValueError('Market is closed')
            if raw.get('_unavailable_reason'):raise ValueError(raw['_unavailable_reason'])
            bound=compile_market(raw,mapping)
            spec={**bound['spec'],'id':mid}
            if foregate:bindings[mid]={'order':bound['order'],'options':raw['_foregate_options']}
            else:bindings[mid]={'order':bound['order'],'polyMarketId':mid,
                               'poly_options':[{'assetId':token,'title':name}
                                               for token,name in zip(bound['token_ids'],bound['outcomes'])]}
        except (ValueError,KeyError,TypeError) as exc:
            # Keep one unavailable result for the exact original outcome; no nearest-line substitution.
            spec={'id':mid,'market_type':'unmapped_contract'}
            issues.append({'outcomeId':mid,'reason':str(exc)})
        specs.append(spec)
    start=event.get('startTime')
    if not foregate:start=anchors[0].get('gameStartTime') or start
    status=event.get('status','NOT_STARTED')
    if event.get('closed') or event.get('live') or event.get('ended'):status='UNAVAILABLE'
    record={'eventSlug':event['slug'],'tour':tour,'a':a,'b':b,'startTime':start,
            'status':status,'checked_at':review['checked_at'],'source':review['source'],
            'verified':True,'context':review.get('context'),'markets':specs,'bindings':bindings,'import_issues':issues}
    # Explicit unsupported metadata wins over broad ATP/WTA classification.
    meta=event.get('eventMetadata') or {};source=str(meta.get('tennisFixtureSource','')).lower()
    intro=str(anchors[0].get('description','')).split('\n\n',1)[0].lower()
    competition=context.get('competition','')
    if any(word in source for word in ('itf','double','junior')):
        record['status']='UNSUPPORTED_FORMAT'
    if 'challenger' in source and competition not in ('challenger_main_draw','challenger_qualifying'):
        raise ValueError('Fixture source contradicts reviewed Challenger context')
    import re
    qualifying='qual' in source or bool(re.search(r'\bqualif(?:ying|ication)\b',intro,re.I))
    if qualifying and competition not in ('atp_qualifying','wta_qualifying','challenger_qualifying'):
        raise ValueError('Qualifying event cannot be imported as a main draw')
    return record
