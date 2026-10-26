"""Player-first GET predictions with disclosed, unverified scenario assumptions.

Missing surface is marginalized over both players' historical court counts, not
silently treated as a verified hard-court fixture. Existing score models are
reused; the context-mixture strategy has no separate historical accuracy claim.
"""
import copy
import json


def normalize_params(params):
    result={k:v.strip() if isinstance(v,str) else v for k,v in params.items()}
    for key in ('type','view','tour','mode','lang','indoor','competition','format'):
        if isinstance(result.get(key),str):result[key]=result[key].casefold()
    if isinstance(result.get('surface'),str):result['surface']=result['surface'].title()
    return result


def resolve_tour(engine,params,categories):
    requested=params.get('tour');cid=params.get('categoryId')
    category=categories.get(str(cid)) if cid else None
    if requested and requested not in ('atp','wta'):raise ValueError('tour must be atp or wta')
    if category and requested and requested!=category:raise ValueError('categoryId contradicts tour')
    if not requested and cid and not category:raise ValueError('Unknown categoryId; supply tour=atp or wta')
    if requested or category:return requested or category
    candidates=[]
    for tour in ('atp','wta'):
        try:
            engine.resolve(tour,params['a']);engine.resolve(tour,params['b']);candidates.append(tour)
        except ValueError:pass
    if len(candidates)!=1:raise ValueError('Both players must uniquely identify one tour; supply tour=atp or wta')
    return candidates[0]


def scenario_context(engine,tour,ids,params):
    best_of=params.get('best_of','3');tiebreak=params.get('final_tiebreak_points','7')
    if str(best_of) not in ('3','5') or tour=='wta' and str(best_of)!='3':raise ValueError('best_of must be 3 or 5; WTA singles uses 3')
    if str(tiebreak) not in ('7','10'):raise ValueError('final_tiebreak_points must be 7 or 10')
    indoor=params.get('indoor','false')
    if indoor not in ('true','false'):raise ValueError('indoor must be true or false')
    if params.get('format','main_tour_singles')!='main_tour_singles' or params.get('competition','main_tour')!='main_tour':
        raise ValueError('Player baseline uses the main-tour standard-singles model; explicit expanded competition requires its separate model')
    assumptions=[]
    for field,value in (('best_of',int(best_of)),('final_tiebreak_points',int(tiebreak)),('indoor',indoor=='true')):
        if field not in params:assumptions.append({'field':field,'value':value,'source':'baseline_default'})
    common={'best_of':int(best_of),'final_tiebreak_points':int(tiebreak),'indoor':indoor=='true',
            'format':'main_tour_singles','competition':'main_tour'}
    # Missing competition never certifies the actual event's level.
    if 'competition' not in params:assumptions.append({'field':'competition','value':'main_tour','source':'model_scope_not_actual_event_classification'})
    for key in ('date','rank_a','rank_b'):
        if key in params:common[key]=params[key]
    if 'surface' in params:
        surface=params['surface']
        if surface not in ('Hard','Clay','Grass','Carpet'):raise ValueError('surface must be Hard, Clay, Grass or Carpet')
        surfaces=[{'surface':surface,'weight':1.}]
    else:
        # Symmetric in player order; preserve minority-court scenarios with one
        # pseudo-observation each. These are explicit modelling weights, not
        # probabilities that the referenced event is on a particular surface.
        counts={s:1+sum(engine.states[tour].player(i)['surfaces'].get(s,{}).get('n',0) for i in ids)
                for s in ('Hard','Clay','Grass')}
        total=sum(counts.values());surfaces=[{'surface':s,'weight':n/total} for s,n in counts.items()]
        assumptions.append({'field':'surface','value':'historical_surface_mixture',
                            'source':'pooled_player_history_plus_one_per_surface','scenarios':surfaces})
    return common,surfaces,assumptions


def mixed_markets(engine,tour,ids,common,surfaces,specs):
    results=[]
    for scenario in surfaces:
        value=engine.predict_markets({**common,'tour':tour,'a':ids[0],'b':ids[1],
                                      'surface':scenario['surface'],'markets':specs})
        # Do not return only the population completion rate when the requested
        # player comparison failed (bad date/ranks/stale mismatched score files).
        if 'base' not in value:raise ValueError(value.get('score_model_error','Player model unavailable'))
        results.append((scenario['weight'],value))
    rows=[]
    for index in range(len(specs)):
        items=[(w,r['markets'][index]) for w,r in results]
        row=copy.deepcopy(items[0][1])
        failed=next((r for _,r in items if r['status']=='unavailable'),None)
        if failed:rows.append(copy.deepcopy(failed));continue
        row['probabilities']=[sum(w*r['probabilities'][i] for w,r in items) for i in (0,1)]
        for field in ('period_reached_probability','period_not_reached_probability'):
            if field in row:row[field]=sum(w*r[field] for w,r in items)
        if 'period_reached_probability' in row:
            reach=row['period_reached_probability']
            row['probabilities_given_period_reached']=[p/reach for p in row['probabilities']] if reach else None
        if 'probabilities_including_noncompletion' in row:
            row['probabilities_including_noncompletion']=[sum(w*r['probabilities_including_noncompletion'][i] for w,r in items) for i in (0,1)]
        if row['sports_market_type'] not in ('tennis_completed_match',) and row.get('status')!='historical_baseline':
            row.update(market_validation=None,exact_score_top_pick_validation=None,
                       validation_gate='research_only_unverified_context',
                       validation_protocol='player_scenarios_not_independently_backtested',
                       retrospective_accuracy_above_baseline=False)
        rows.append(row)
    base=copy.deepcopy(results[0][1]['base'])
    base.update(probability_a=sum(w*r['base']['probability_a'] for w,r in results),
                probability_b=sum(w*r['base']['probability_b'] for w,r in results))
    # Scenario-specific features and backtest scores must not masquerade as an
    # independently validated context-free prediction.
    for field in ('test_metrics','test_metrics_scope','test_metrics_best_of','top_logit_contributions'):base.pop(field,None)
    if len(surfaces)>1:
        base['surface']=None;base['h2h'].pop('same_surface_matches',None)
        for side in ('a','b'):base[side].pop('surface_matches',None)
    warnings=list(dict.fromkeys(warning for _,r in results for warning in r['base']['warnings']))
    n=sum(r['status']!='unavailable' for r in rows)
    return {'markets':rows,'base':base,'warnings':warnings,
            'summary':{'requested':len(rows),'predicted':n,'unavailable':len(rows)-n}}


def predict_players(service,params,catalog=None):
    from .foregate import default_markets,identity
    out={'type':'tennis','eventSlug':params.get('eventSlug'),'marketId':params.get('marketId'),
         'A':params['a'],'B':params['b'],'ready':False,'matched_exact':False,'platform_markets':{},
         'market_results':[],'reasons':{},'unavailable':[],'contract_ready':False,
         'prediction_mode':'player_baseline','fixture_matched':False,'context_verified':False,
         'matchStartTime':None,'demo_only':False}
    try:
        engine=service.engine
        # Classification can select the model pool but never gates a particular
        # tournament. Only the known ATP ID is hard-coded; WTA is not guessed.
        categories={'30157':'atp',**(catalog or {}).get('categories',{})}
        tour=resolve_tour(engine,params,categories);ids=[engine.resolve(tour,params[k]) for k in ('a','b')]
        if ids[0]==ids[1]:raise ValueError('Players must differ')
        common,surfaces,assumptions=scenario_context(engine,tour,ids,params)
        specs=json.loads(params['markets']) if 'markets' in params else default_markets(common['best_of'])
        result=mixed_markets(engine,tour,ids,common,surfaces,specs)
        names=[engine.states[tour].player(i)['profile']['name'] for i in ids]
        lang=params.get('lang','zh')
        notice={'zh':'未核实具体赛事背景；当前为球员基础预测，场地和赛制假设见 assumptions，不代表已匹配实际盘口。',
                'en':'Player baseline without verified event context. See assumptions for court and format; actual market selections are not bound.',
                'vi':'Dự đoán cơ bản theo người chơi, chưa xác minh bối cảnh trận. Xem assumptions về sân và thể thức; chưa liên kết lựa chọn thị trường.'}[lang]
        out.update(tour=tour,A=names[0],B=names[1],matched_exact=True,
                   name_matching={'a':{'input':params['a'],'id':ids[0],'canonical':names[0]},
                                  'b':{'input':params['b'],'id':ids[1],'canonical':names[1]},
                                  'method':'unique_full_name_or_reviewed_alias_ignoring_case_spacing_punctuation'},
                   assumptions=assumptions,context={**common,'surface':surfaces[0]['surface'] if len(surfaces)==1 else None},
                   surface_scenarios=surfaces,market_specs_origin='query' if 'markets' in params else 'reference_grid',
                   model_revision=engine.snapshot_sha256,history_as_of=engine.snapshot['as_of'],
                   warnings=[notice,*result['warnings']],base=result['base'],summary=result['summary'])
        for spec,row in zip(specs,result['markets']):
            if row['status']=='unavailable':out['unavailable'].append(row);continue
            kind=row['sports_market_type'];key=identity(spec)
            entry={**row,'key':key,'pairs':list(zip(service.labels(row,names,lang),row['probabilities'])),
                   'context_verified':False,'prediction_mode':'player_baseline'}
            if kind=='moneyline':entry.update(home=row['probabilities'][0],away=row['probabilities'][1])
            out['platform_markets'][kind]=entry if kind=='moneyline' else out['platform_markets'].get(kind,[])+[entry]
            out['reasons'][key]=[notice,*service.reason(row,names,lang,result['base'])]
            out['reasons'].setdefault(kind,out['reasons'][key]);out['market_results'].append(entry)
        out['ready']=bool(out['market_results'])
    except (ValueError,TypeError,KeyError,OSError) as exc:
        out.update(ready=False,platform_markets={},market_results=[],reasons={})
        out['unavailable'].append({'reason':str(exc)})
    out['status']='ready' if out['ready'] and not out['unavailable'] else 'partial' if out['ready'] else 'unavailable'
    return out
