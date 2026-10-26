"""Batch semantic quotes and explicit Gamma outcome/token binding.

Prices are never inputs. A mapped conditional probability is not a settlement
probability: cancellations/retirements remain outside the score model.
"""
import datetime as dt
import hashlib
import json
import math
import re
from .inference import normalize
from .scoring import SCORE_TYPES


def screenshot_markets(best_of=3):
    """All fifteen score contracts shown in the user's screenshots (BO3)."""
    rows=[{'market_type':'moneyline'}, {'market_type':'tennis_completed_match'},
          {'market_type':'tennis_set_totals','line':2.5}]
    for n in (1,2):
        rows.append({'market_type':'tennis_first_set_winner' if n==1 else 'tennis_set_winner','set_number':n})
        rows.extend({'market_type':'tennis_first_set_totals' if n==1 else 'tennis_set_games_totals',
                     'set_number':n,'line':line} for line in (8.5,9.5,10.5))
    rows.extend({'market_type':'tennis_match_totals','line':line} for line in (21.5,22.5,23.5))
    rows.extend({'market_type':'tennis_set_handicap','line':-1.5,'selection':side} for side in ('a','b'))
    if best_of!=3:raise ValueError('Screenshot template is BO3; provide explicit markets for BO5')
    return rows


def _specs(payload):
    specs=payload.get('markets')
    if specs is None:specs=screenshot_markets(payload.get('best_of',3))
    if not isinstance(specs,list) or not 1<=len(specs)<=200 or not all(isinstance(x,dict) for x in specs):
        raise ValueError('markets must contain 1..200 objects')
    return specs


def _context(payload):
    if not isinstance(payload,dict):raise ValueError('JSON object required')
    if payload.get('format') not in ('main_tour_singles','expanded_atp_singles'):raise ValueError('Explicit format=main_tour_singles or expanded_atp_singles required')
    required=('tour','a','b','surface','best_of','final_tiebreak_points')
    if any(k not in payload for k in required):raise ValueError('Required: '+','.join(required))
    return {k:payload[k] for k in required+('date','rank_a','rank_b','indoor') if k in payload}


def _unavailable(kind,reason):
    return {'sports_market_type':kind,'status':'unavailable','probabilities':None,
            'contract_ready':False,'reason':reason}


def predict_markets(engine,payload):
    if not isinstance(payload,dict):raise ValueError('JSON object required')
    args=_context(payload);specs=_specs(payload)
    scope=engine.model(args['tour']).get('scope','main_tour')
    competition=payload.get('competition','main_tour' if scope=='main_tour' else None)
    allowed=('main_tour','challenger_main_draw','atp_qualifying') if scope=='expanded_atp' else ('main_tour',)
    if competition not in allowed:raise ValueError('Explicit competition required within model scope: '+','.join(allowed))
    if payload['format']=='expanded_atp_singles' and engine.model(args['tour']).get('scope')!='expanded_atp':
        raise ValueError('Expanded format requires the separate models/expanded/current.json snapshot')
    # One score distribution for every line and period. No internally inconsistent
    # independent winner/sets/games predictions for the same fixture.
    try:dist,context=engine.score_distribution(**args)
    except (ValueError,TypeError) as exc:dist=None;context={'score_model_error':str(exc)}
    rows=[]
    for index,spec in enumerate(specs):
        kind=spec.get('market_type')
        try:
            if kind=='tennis_completed_match':
                row=engine.predict_completion(args['tour'],payload.get('competition'),args.get('date'),spec.get('rule_version'))
            elif kind=='tennis_exact_score' and spec.get('score') in ('Not Completed','not_completed'):
                from .completion import not_completed_quote
                c=engine.predict_completion(args['tour'],payload.get('competition'),args.get('date'),spec.get('rule_version'))
                row=not_completed_quote(c)
            else:
                if kind not in SCORE_TYPES:raise ValueError('Unsupported score market type')
                if dist is None:raise ValueError(context['score_model_error'])
                row=engine.quote_market(dist,args['tour'],kind,competition=competition,
                                        **{k:spec[k] for k in ('line','set_number','selection','score') if k in spec})
                if kind=='tennis_exact_score' and engine.completion_config:
                    c=engine.predict_completion(args['tour'],payload.get('competition'),args.get('date'),spec.get('rule_version'))
                    p=row['probabilities'][0]*c['probabilities'][0]
                    row.update(probabilities_including_noncompletion=[p,1-p],completion_baseline=c)
        except (ValueError,TypeError) as exc:row=_unavailable(kind,str(exc))
        rows.append({'request_index':index,'request_id':spec.get('id'),**row})
    n=sum(x['status']!='unavailable' for x in rows)
    return {'markets':rows,'summary':{'requested':len(rows),'predicted':n,'unavailable':len(rows)-n},
            'contract_ready':False,**context}


def _array(value):
    if isinstance(value,str):value=json.loads(value)
    if not isinstance(value,list):raise ValueError('Expected outcomes/token array')
    return value


def _names(mapping):
    if not isinstance(mapping,dict) or set(mapping)!={'a','b'}:raise ValueError('player_mapping must contain a and b')
    names={}
    for side in ('a','b'):
        item=mapping[side]
        if not isinstance(item,dict) or not isinstance(item.get('poly_name'),str) or not item['poly_name'].strip():
            raise ValueError('Each side requires an explicit poly_name')
        aliases=item.get('aliases',[])
        if not isinstance(aliases,list) or not all(isinstance(x,str) and normalize(x) for x in aliases):raise ValueError('aliases must contain names')
        for name in [item['poly_name']]+aliases:
            key=normalize(name)
            if key in names and names[key]!=side:raise ValueError('Ambiguous player aliases')
            names[key]=side
    return names


def compile_market(market,mapping):
    """Map exactly two outcome slots; handicap sign is bound to named player.

    Raw Gamma `line` can be unsigned for handicap contracts and can mean a set
    index for set winners. Neither ambiguity may silently reverse the quote.
    """
    names=_names(mapping);kind=market.get('sportsMarketType')
    labels=_array(market.get('outcomes'));tokens=_array(market.get('clobTokenIds'))
    if len(labels)!=2 or len(tokens)!=2 or not all(isinstance(x,str) and x for x in labels+tokens) or len(set(tokens))!=2:
        raise ValueError('Two distinct token IDs and two named outcomes required')
    if not all(x.isdigit() and int(x)>0 for x in tokens):raise ValueError('Invalid CLOB token ID')
    spec={'market_type':kind};text=market.get('question') or ''
    if kind in ('moneyline','tennis_first_set_winner','tennis_set_winner','tennis_game_handicap','tennis_set_handicap'):
        sides=[names.get(normalize(x)) for x in labels]
        if set(sides)!={'a','b'}:raise ValueError('Outcomes do not uniquely match verified players; outright markets cannot use match model')
        if 'handicap' in kind:
            signed=[]
            for name in labels:
                found=re.findall(re.escape(name)+r'\s*\(([+-]\d+(?:\.\d+)?)\)',text,re.I)
                if len(found)!=1:raise ValueError('Explicit signed handicap for each outcome name required in question')
                signed.append(float(found[0]))
            if signed[0]!=-signed[1]:raise ValueError('Contradictory handicap selections')
            spec.update(line=signed[0],selection=sides[0]);order=[0,1]
        else:order=[0 if side=='a' else 1 for side in sides]
    elif kind in ('tennis_first_set_totals','tennis_set_games_totals','tennis_match_totals','tennis_set_totals'):
        line=market.get('line')
        if line is None:raise ValueError('Explicit total line required')
        try:line=float(line)
        except (ValueError,TypeError):raise ValueError('Invalid total line')
        if not math.isfinite(line):raise ValueError('Invalid total line')
        question_line=re.search(r'\bO/U\s+(\d+(?:\.\d+)?)',text,re.I)
        if question_line and float(question_line[1])!=line:raise ValueError('Question threshold contradicts raw line')
        sides=[]
        for name in labels:
            found=re.fullmatch(r'(Over|Under)(?:\s+(\d+(?:\.\d+)?))?',name,re.I)
            if not found:raise ValueError('Expected Over/Under labels')
            if found[2] is not None and float(found[2])!=line:raise ValueError('Outcome threshold contradicts raw line')
            sides.append(found[1].lower())
        if set(sides)!={'over','under'}:raise ValueError('Distinct Over and Under required')
        order=[0 if side=='over' else 1 for side in sides];spec['line']=line
    elif kind=='tennis_completed_match':
        if {x.lower() for x in labels}!={'yes','no'}:raise ValueError('Completed Match requires Yes/No outcomes')
        order=[0 if name.lower()=='yes' else 1 for name in labels]
    else:raise ValueError('No automatic contract mapper for '+str(kind)+'; use explicit semantic /predict/markets')
    if kind in ('tennis_set_winner','tennis_set_games_totals','tennis_first_set_winner','tennis_first_set_totals'):
        found=re.search(r'\bset\s+(\d+)\b',text,re.I)
        if not found:raise ValueError('Set index required in question')
        n=int(found[1])
        if kind.startswith('tennis_first_set') and n!=1:raise ValueError('First-set type contradicts question')
        if kind=='tennis_set_winner' and market.get('line') is not None and float(market['line'])!=n:raise ValueError('Set winner line contradicts question')
        spec['set_number']=n
    description=market.get('description')
    if not isinstance(description,str) or not description.strip():raise ValueError('Full resolution description required')
    return {'spec':spec,'order':order,'outcomes':labels,'token_ids':tokens,'line_raw':market.get('line'),
            'description_sha256':hashlib.sha256(description.encode()).hexdigest(),
            'rules_status':'preserved_for_review_not_automatically_settled'}


def predict_poly_event(engine,payload):
    if not isinstance(payload,dict):raise ValueError('JSON object required')
    event=payload.get('event');match=payload.get('match');mapping=payload.get('player_mapping')
    if not isinstance(event,dict) or not isinstance(match,dict):raise ValueError('event and match objects required')
    _names(mapping)
    markets=event.get('markets')
    if not isinstance(markets,list) or not 1<=len(markets)<=200 or not all(isinstance(m,dict) for m in markets):raise ValueError('event.markets must contain 1..200 objects')
    ids=[str(m.get('id','')) for m in markets]
    if any(not i or i=='None' for i in ids) or len(ids)!=len(set(ids)):raise ValueError('Unique market IDs required')
    if payload.get('mapping_verified') is not True or not isinstance(payload.get('source'),str) or not payload['source'].strip():
        raise ValueError('mapping_verified=true and mapping source required; identity verification is caller responsibility')
    blockers=[]
    args=None
    try:args=_context(match)
    except ValueError as exc:blockers.append(str(exc))
    meta=event.get('eventMetadata') or {}
    if not isinstance(meta,dict):raise ValueError('eventMetadata must be an object')
    source=str(meta.get('tennisFixtureSource','')).lower()
    expanded=engine.snapshot.get('tours',{}).get(match.get('tour'),{}).get('scope')=='expanded_atp'
    competition=match.get('competition')
    allowed=('main_tour','challenger_main_draw','atp_qualifying') if expanded else ('main_tour',)
    if competition not in allowed:blockers.append('Verified competition required within model scope: '+','.join(allowed))
    detected=('challenger_qualifying' if 'challenger' in source and 'qual' in source else
              'challenger_main_draw' if 'challenger' in source else 'atp_qualifying' if 'qual' in source else None)
    if detected and competition!=detected:blockers.append('Declared competition contradicts Poly fixture source: '+detected)
    if match.get('format')=='expanded_atp_singles' and not expanded:blockers.append('Expanded format requires the separate expanded snapshot')
    excluded=('challenger-qualifying','itf','double','junior') if expanded else ('challenger','qualifying','itf','double','junior')
    if any(x in source for x in excluded):
        blockers.append('Poly fixture source outside validated model scope: '+source)
    for side in ('a','b'):
        try:engine.resolve(match.get('tour'),match.get(side))
        except (ValueError,KeyError):blockers.append('Missing internal player history: '+mapping[side]['poly_name'])
    # Require a same-event named match-winner anchor; do not quote an outright
    # or an unrelated event using a caller-supplied pair of known players.
    anchors=[m for m in markets if m.get('sportsMarketType')=='moneyline']
    try:
        if len(anchors)!=1 or not re.search(r'\bvs\.?\s',event.get('title',''),re.I):raise ValueError('Unique singles moneyline anchor required')
        compile_market(anchors[0],mapping)
        names=_names(mapping)
        for side in ('a','b'):
            identifier=engine.resolve(match['tour'],match[side])
            actual=normalize(engine.states[match['tour']].player(identifier)['profile']['name'])
            if names.get(actual)!=side:raise ValueError('Mapped internal name must be explicitly listed among verified Poly names/aliases')
    except (ValueError,KeyError,TypeError) as exc:blockers.append('Player/event identity: '+str(exc))
    try:
        start=dt.datetime.fromisoformat(str(event['startTime']).replace('Z','+00:00'))
        if start.utcoffset() is None:raise ValueError('Timezone required')
        if start<=dt.datetime.now(dt.timezone.utc):blockers.append('Event already started: requires live model or archived pre-match inputs; no current pre-match quote')
        if args is not None:
            if args.get('date',start.date().isoformat())!=start.date().isoformat():raise ValueError('Prediction date must equal event start date')
            args['date']=start.date().isoformat()
    except (ValueError,KeyError,TypeError):blockers.append('Verified UTC event startTime required and prediction date must agree')
    if event.get('closed') is True or event.get('live') is True or event.get('ended') is True:blockers.append('Event closed/live/ended: pre-match model unavailable')
    dist=context=None
    if not blockers:
        try:dist,context=engine.score_distribution(**args)
        except (ValueError,TypeError) as exc:blockers.append(str(exc))
    rows=[]
    for market in markets:
        kind=market.get('sportsMarketType');bound=None
        try:
            bound=compile_market(market,mapping)
            if kind=='tennis_completed_match':
                # Completion base rate is independent of player-history coverage.
                # A past/live event still cannot receive a current pre-match quote.
                temporal=[s for s in blockers if any(word in s for word in ('already started','closed/live/ended','startTime','Prediction date'))]
                if temporal:raise ValueError('; '.join(temporal))
                from .completion import cohort,rule_days
                t,c=cohort(event);days=rule_days(market['description'])
                if days is None:raise ValueError('Unrecognized completion deadline rules')
                q=engine.predict_completion(t,c,rule_version=days)
            else:
                if blockers:raise ValueError('; '.join(blockers))
                spec=bound['spec'];q=engine.quote_market(dist,args['tour'],spec['market_type'],competition=competition,
                                                      **{k:v for k,v in spec.items() if k!='market_type'})
            row={**q,'outcome_predictions':[{'outcome':name,'token_id':token,
                'probability':q['probabilities'][i],'probability_scope':q['condition'],
                'conditional_probability':q['probabilities'][i] if kind!='tennis_completed_match' else None,
                'conditional_probability_given_period_reached':q['probabilities_given_period_reached'][i] if kind!='tennis_completed_match' else None}
                for name,token,i in zip(bound['outcomes'],bound['token_ids'],bound['order'])]}
        except (ValueError,TypeError) as exc:row={**_unavailable(kind,str(exc)),'outcome_predictions':None}
        rows.append({'market_id':str(market['id']),'condition_id':market.get('conditionId'),'question':market.get('question'),
                     'mapping_status':'mapped' if bound else 'unavailable','binding':bound,**row})
    n=sum(x['status']!='unavailable' for x in rows)
    return {'event_id':str(event.get('id','')),'event_title':event.get('title'),'source':payload['source'],
            'mapping_verification':'caller_asserted','markets':rows,'blockers':blockers,
            'summary':{'requested':len(rows),'mapped':sum(x['mapping_status']=='mapped' for x in rows),
                       'predicted':n,'unavailable':len(rows)-n},
            'contract_ready':False,'context':context,
            'probability_scope':'Conditional on normal completed standard singles; retirement, walkover, cancellation and settlement probabilities excluded.'}
