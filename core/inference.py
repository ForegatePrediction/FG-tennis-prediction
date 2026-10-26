"""Portable inference: JSON snapshot plus Python standard library only."""
import datetime as dt
import json
import math
import re
import unicodedata
import hashlib
from pathlib import Path
from .data import ROOT
from .features import State, FEATURES


def normalize(value):
    plain=unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().lower()
    return re.sub('[^a-z0-9]','',plain)


class Engine:
    def __init__(self,path=None):
        self.path=Path(path or ROOT/'models/current.json')
        from .bundle import bundle_lock
        with bundle_lock(self.path.parent):self._load()

    def _load(self):
        raw=self.path.read_bytes();self.snapshot=json.loads(raw)
        self.snapshot_sha256=hashlib.sha256(raw).hexdigest()
        config_path=self.path.parent/'score-config.json'
        self.score_config=json.loads(config_path.read_text()) if config_path.exists() else None
        counts_path=self.path.parent/'count-config.json'
        self.count_config=json.loads(counts_path.read_text()) if counts_path.exists() else None
        completion_path=self.path.parent/'completion.json'
        self.completion_config=json.loads(completion_path.read_text()) if completion_path.exists() else None
        if self.snapshot.get('schema')!=1:raise ValueError('Unsupported snapshot schema')
        self.states={tour:State(tour,m['state']) for tour,m in self.snapshot['tours'].items()}

    def model(self,tour):
        if tour not in self.states:raise ValueError('tour must be atp or wta')
        return self.snapshot['tours'][tour]

    def players(self,tour,query='',limit=30):
        self.model(tour);search=normalize(query)
        values=[{'id':i,'name':p['profile'].get('name',i),'rank':p['profile'].get('rank'),
                 'rank_observed_on':p['profile'].get('observed_on'),'matches':p['n']}
                for i,p in self.states[tour].players.items()
                if not query or search in normalize(p['profile'].get('name','')) or search==normalize(i)]
        return sorted(values,key=lambda p:(p['rank'] or 99999,-p['matches']))[:max(1,min(100,limit))]

    def resolve(self,tour,value):
        state=self.states[tour]
        if str(value) in state.players:return str(value)
        norm=normalize(value)
        exact=[i for i,p in state.players.items() if normalize(p['profile'].get('name',''))==norm]
        if len(exact)==1:return exact[0]
        aliases=ROOT/'config/player-aliases.json'
        if not exact and aliases.exists():
            matches={row['id'] for row in json.loads(aliases.read_text())['players']
                     if row['tour']==tour and any(normalize(name)==norm for name in row['aliases'])}
            if len(matches)==1 and next(iter(matches)) in state.players:return next(iter(matches))
        raise ValueError('Use an existing player ID or unique full name; search /players first: '+str(value))

    def predict(self,tour,a,b,surface,best_of=3,date=None,rank_a=None,rank_b=None,indoor=False):
        model=self.model(tour);state=self.states[tour]
        a=self.resolve(tour,a);b=self.resolve(tour,b)
        if a==b:raise ValueError('Players must differ')
        if not isinstance(surface,str):raise ValueError('surface must be a string')
        surface=surface.title()
        if surface not in ('Hard','Clay','Grass','Carpet'):raise ValueError('surface must be Hard, Clay, Grass or Carpet')
        if isinstance(best_of,bool) or str(best_of) not in ('3','5'):raise ValueError('best_of must be integer 3 or 5')
        best_of=int(best_of)
        if best_of not in (3,5) or tour=='wta' and best_of!=3:raise ValueError('best_of must be 3 or 5; WTA singles uses 3')
        date=date or dt.datetime.now(dt.timezone.utc).date().isoformat()
        day=dt.date.fromisoformat(date)
        if day<dt.date.fromisoformat(model['as_of']):raise ValueError('Historical inference requires a historical snapshot; refusing future-data leakage')
        if day>dt.datetime.now(dt.timezone.utc).date()+dt.timedelta(days=14):raise ValueError('Prediction date must be within 14 days of today')
        profiles={i:dict(state.player(i)['profile']) for i in (a,b)}
        for identifier,rank in ((a,rank_a),(b,rank_b)):
            if rank is not None:
                rank=float(rank)
                if not math.isfinite(rank) or rank<1 or rank>100000 or not rank.is_integer():raise ValueError('Rank override must be a positive integer')
                profiles[identifier]['rank']=rank
                # Do not combine current ranking with stale ranking points.
                profiles[identifier]['points']=None
        if not isinstance(indoor,bool):raise ValueError('indoor must be boolean')
        vector=state.features(a,b,surface,best_of,day.toordinal(),profiles,indoor)
        values=dict(zip(FEATURES,vector))
        contributions={k:max(-8,min(8,values[k]/s))*w/model['temperature']
                       for k,s,w in zip(model['features'],model['scale'],model['weights'])}
        logit=sum(contributions.values());p=1/(1+math.exp(-max(-35,min(35,logit))))
        warnings=['No live injury, medical, weather or travel data; probabilities are conditional on normal completed singles matches.',
                  'History uses conservative event-week availability; this is a pre-event baseline, not an in-play model.']
        scope=model.get('scope','main_tour')
        if scope=='expanded_atp':warnings.append('Expanded research model: main tour, Challenger main draws and ATP qualifying; no Challenger-qualifying or ITF validation.')
        if surface=='Carpet':warnings.append('No independent 2025+ Carpet test sample: treat this surface as experimental.')
        if day.toordinal()-dt.date.fromisoformat(model['as_of']).toordinal()>3:warnings.append('Snapshot older than 3 days: refresh before operational use.')
        checked=dt.datetime.fromisoformat(model['data']['checked_at'])
        if dt.datetime.now(dt.timezone.utc)-checked>dt.timedelta(days=3):warnings.append('Free source has not been checked in more than 3 days.')
        for identifier in (a,b):
            player=state.player(identifier);prof=player['profile']
            if player['n']<20:warnings.append(prof.get('name',identifier)+': fewer than 20 accepted history matches; limited evidence.')
            observed=dt.date.fromisoformat(prof['observed_on'])
            if (day-observed).days>60:warnings.append(prof.get('name',identifier)+': profile/ranking older than 60 days; provide a verified current rank if available.')
        pair=state.pairs.get('|'.join(sorted((a,b))),[])
        h2h={'completed_matches':len(pair),'a_wins':sum(r['winner']==a for r in pair),
             'b_wins':sum(r['winner']==b for r in pair),
             'same_surface_matches':sum(r['surface']==surface for r in pair),
             'used_by_model':any('h2h' in f for f in model['features']),
             'scope':('Accepted main-tour, Challenger main-draw and ATP-qualifying singles since 2010; excludes retirements, teams, ITF and Challenger qualifying.' if scope=='expanded_atp' else
                      'Accepted completed main-tour singles since 2010; excludes retirements and team events.')}
        def detail(identifier,rank):
            player=state.player(identifier);prof=player['profile']
            return {'id':identifier,'name':prof['name'],'rank':profiles[identifier]['rank'],
                    'rank_source':'caller' if rank is not None else 'latest accepted match profile',
                    'profile_observed_on':prof['observed_on'],'history_matches':player['n'],
                    'elo':round(player['elo'],2),'surface_matches':player['surfaces'].get(surface,{}).get('n',0)}
        cfg=(self.count_config or {}).get('tours',{}).get(tour,{})
        matched=cfg.get('by_best_of',{}).get(str(best_of),{}).get('moneyline') if self.count_config and self.count_config.get('base_model_sha256')==self.snapshot_sha256 else None
        test_metrics=matched['model'] if matched else model['test_metrics']
        return {'tour':tour,'market':'match_winner','date':date,'surface':surface,'indoor':indoor,'best_of':best_of,
                'a':detail(a,rank_a),'b':detail(b,rank_b),'probability_a':round(p,8),'probability_b':round(1-p,8),
                'h2h':h2h,'model':model['selected_group'],'model_scope':scope,'history_as_of':model['as_of'],
                'data':model['data'],'test_metrics':{k:test_metrics[k] for k in ('n','accuracy','log_loss','brier')},
                'test_metrics_best_of':best_of if matched else None,
                'test_metrics_scope':'format_matched_retrospective' if matched else 'mixed_formats_legacy_summary',
                'top_logit_contributions':dict(sorted(contributions.items(),key=lambda kv:abs(kv[1]),reverse=True)[:8]),
                'warnings':warnings}

    def health(self):
        today=dt.datetime.now(dt.timezone.utc)
        age=(today.date()-dt.date.fromisoformat(self.snapshot['as_of'])).days
        source_age=max((today-dt.datetime.fromisoformat(m['data']['checked_at'])).total_seconds()/86400
                       for m in self.snapshot['tours'].values())
        active=self.count_config or self.score_config
        configs_valid=active is None or active.get('base_model_sha256')==self.snapshot_sha256
        completion_age=(today.date()-dt.date.fromisoformat(self.completion_config['as_of'])).days if self.completion_config else None
        return {'status':'ok' if age<=3 and source_age<=3 and configs_valid and (completion_age is None or completion_age<=3) else 'degraded','snapshot_age_days':age,
                'score_configs_match_snapshot':configs_valid,
                'score_model_kind':next(iter(self.count_config['tours'].values())).get('model_kind','unknown') if self.count_config else 'stationary_point_model',
                'score_model_kinds_by_tour':{t:c.get('model_kind','unknown') for t,c in self.count_config['tours'].items()} if self.count_config else {},
                'completion_baseline':{'as_of':self.completion_config['as_of'],'age_days':completion_age,
                                       'n':self.completion_config['global']['n']} if self.completion_config else None,
                'source_check_age_days':round(source_age,2),'history_as_of':self.snapshot['as_of'],'tours':{
            t:{'players':len(self.states[t].players),'data':m['data'],'coefficient_fit_through':m['coefficient_fit_through'],
               'model':m['selected_group']} for t,m in self.snapshot['tours'].items()}}

    def score_distribution(self,tour,a,b,surface,best_of=3,date=None,rank_a=None,rank_b=None,
                           indoor=False,final_tiebreak_points=None):
        from .scoring import distribution,serve_parameters
        if final_tiebreak_points is None:raise ValueError('Explicit verified final_tiebreak_points (7 or 10) required; nonstandard formats unsupported')
        base=self.predict(tour,a,b,surface,best_of,date,rank_a,rank_b,indoor)
        pa,pb,evidence=serve_parameters(self.states[tour],base['a']['id'],base['b']['id'],base['surface'],dt.date.fromisoformat(base['date']).toordinal())
        offset=0.;validation=None;learned=False
        if self.score_config and not self.count_config:
            config=self.score_config
            if config.get('base_model_sha256')!=self.snapshot_sha256:
                raise ValueError('Score calibration does not match winner snapshot; rerun backtest_score.py')
            offset=config['tours'][tour]['serve_logit_offset'];validation=config['tours'][tour]['test']
        if self.count_config:
            if self.count_config.get('base_model_sha256')!=self.snapshot_sha256:raise ValueError('Count model does not match winner snapshot; rerun train_counts.py')
            from .counts import predict as predict_counts
            state=self.states[tour];profiles={}
            for side in ('a','b'):
                player=base[side];identifier=player['id'];profiles[identifier]=dict(state.player(identifier)['profile'])
                if player['rank_source']=='caller':profiles[identifier].update(rank=player['rank'],points=None)
            vector=state.features(base['a']['id'],base['b']['id'],base['surface'],base['best_of'],
                                  dt.date.fromisoformat(base['date']).toordinal(),profiles,indoor)
            count_model=self.count_config['tours'][tour]
            dist=predict_counts(count_model,vector,pa,pb,base['surface'],base['best_of'],base['probability_a'],final_tiebreak_points)
            validation=count_model['test'];learned=True;offset=0.
        else:
            def shift(p):return 1/(1+math.exp(-(math.log(p/(1-p))+offset)))
            dist=distribution(shift(pa),shift(pb),base['probability_a'],base['best_of'],final_tiebreak_points)
        scope=self.model(tour).get('scope','main_tour')
        context={'base':base,'serve_evidence':evidence,'serve_logit_offset':offset,
                 'score_model_status':'experimental' if validation else 'unvalidated','score_validation':validation,
                 'score_model_kind':count_model.get('model_kind','learned_length_and_empirical_set_scores') if learned else 'stationary_point_model',
                 'limitations':[('Adult ATP standard singles: main tour, Challenger main draw and ATP qualifying; no Challenger qualifying, ITF, doubles, juniors or live state.' if scope=='expanded_atp' else
                                 'Adult main-tour standard singles only; no doubles, ITF, Challenger, qualifying, juniors or live state.'),
                                'All score probabilities conditional on normal completion; retirement/void settlement probabilities are not applied.',
                                ('Learned completed length and empirical set scores; no injury/medical/weather or live information. Retrospective test period needs forward confirmation.' if learned else
                                 'Stationary serve-point approximation; first server averaged 50/50. No injury/medical/weather information.')]}
        return dist,context

    def predict_market(self,tour,a,b,surface,sports_market_type='moneyline',line=None,set_number=None,
                       selection='a',score=None,final_tiebreak_points=None,**kwargs):
        if sports_market_type=='tennis_completed_match':return self.predict_completion(tour,date=kwargs.get('date'))
        if sports_market_type=='tennis_exact_score' and score in ('Not Completed','not_completed'):
            from .completion import not_completed_quote
            completion=self.predict_completion(tour,date=kwargs.get('date'))
            return not_completed_quote(completion)
        dist,context=self.score_distribution(tour,a,b,surface,final_tiebreak_points=final_tiebreak_points,**kwargs)
        result=self.quote_market(dist,tour,sports_market_type,line,set_number,selection,score)
        if sports_market_type=='tennis_exact_score' and self.completion_config:
            completion=self.predict_completion(tour,date=kwargs.get('date'));p=completion['probabilities'][0]*result['probabilities'][0]
            result.update(probabilities_including_noncompletion=[p,1-p],completion_baseline=completion)
        return {**result,**context}

    def predict_completion(self,tour=None,competition=None,date=None,rule_version=None):
        from .completion import estimate
        return estimate(self.completion_config,tour,competition,date,rule_version)

    def quote_market(self,dist,tour,sports_market_type,line=None,set_number=None,selection='a',score=None,competition=None):
        """Quote another line from the same joint distribution without recomputing it."""
        from .scoring import quote
        result=quote(dist,sports_market_type,line,set_number,selection,score)
        from .validation import market_key
        parameters={}
        if result['line'] is not None:parameters['line']=result['line']
        if sports_market_type in ('tennis_set_winner','tennis_set_games_totals'):parameters['set_number']=result['set_number']
        if 'handicap' in sports_market_type or sports_market_type=='match_winner_and_game_margin':parameters['selection']=selection
        key=market_key(sports_market_type,parameters,score)
        config=(self.count_config or self.score_config or {}).get('tours',{}).get(tour,{})
        bo=str(dist['best_of'])
        validations=config.get('by_best_of',{}).get(bo,{})
        if competition:
            validations=config.get('by_competition_best_of',{}).get(competition+'/'+bo,{})
        validation=validations.get(key)
        result['market_validation']=validation
        result['validation_cohort']=competition or ('mixed_expanded_atp' if self.model(tour).get('scope')=='expanded_atp' else 'main_tour')
        result['validation_best_of']=dist['best_of']
        result['validation_protocol']='retrospective_requires_forward_validation'
        result['validation_gate']=('research_only_single_class_test_sample' if validation and not validation.get('test_contains_both_outcomes',True) else
                                   'research_only_no_baseline_sample' if validation and not validation.get('baseline_minimum_sample_n',1) else
                                   'research_only_below_frequency_baseline' if validation and validation['model']['log_loss']>=validation['2024_empirical_baseline']['log_loss'] else
                                   'research_only_no_parameter_test' if validation is None else 'research_only_better_than_frequency_baseline')
        result['retrospective_accuracy_above_baseline']=bool(validation and validation['model']['accuracy']>validation['2024_empirical_baseline']['accuracy']
                                                       and validation.get('test_contains_both_outcomes',True))
        if sports_market_type=='tennis_exact_score':
            group=f'competition-format/{competition}/{bo}' if competition else 'format/'+bo
            result['exact_score_top_pick_validation']=config.get('exact_score_top_pick',{}).get(group)
        return result

    def predict_markets(self,payload):
        from .markets import predict_markets
        return predict_markets(self,payload)

    def predict_poly_event(self,payload):
        from .markets import predict_poly_event
        return predict_poly_event(self,payload)

    def predict_tournament(self,payload):
        from .tournament import knockout
        if not isinstance(payload,dict) or payload.get('format')!='main_tour_singles_knockout' or payload.get('draw_verified') is not True:
            raise ValueError('Explicit format=main_tour_singles_knockout and draw_verified=true required; source verification is caller responsibility')
        if not isinstance(payload.get('source'),str) or not payload['source'].strip():raise ValueError('Draw source/provenance required')
        tour=payload['tour'];self.model(tour);slots=payload['draw']
        if not isinstance(slots,list):raise ValueError('draw must be array')
        resolved=[]
        for p in slots:
            if p is None:resolved.append(None);continue
            if not isinstance(p,dict) or 'id' not in p:raise ValueError('Draw slots must contain explicit player IDs')
            resolved.append({**p,'id':self.resolve(tour,p['id'])})
        def probability(a,b):return self.predict(tour,a,b,payload['surface'],payload['best_of'],payload.get('date'),indoor=payload.get('indoor',False))['probability_a']
        targets=payload.get('any_win_targets')
        if targets is not None:
            if not isinstance(targets,list):raise ValueError('any_win_targets must be array')
            targets=[self.resolve(tour,x) for x in targets]
        result=knockout(resolved,probability,targets,payload.get('top_seed_max',10))
        return {**result,'tour':tour,'surface':payload['surface'],'best_of':payload['best_of'],
                'source':payload['source'],'source_verification':'caller_asserted','history_as_of':self.model(tour)['as_of'],
                'players':resolved}

    def predict_tournament_market(self,payload):
        """Binary named draw events, conditional on caller-verified singles draw."""
        if not isinstance(payload,dict):raise ValueError('JSON object required')
        kind=payload.get('market_type')
        if kind not in ('tournament_winner','reach_round','finalist_pair','qualifier_reach_round',
                        'wildcard_reach_round','top_seed_first_round_exit','nationality_champion','defeat_top_seed','any_match_win'):
            raise ValueError('Unsupported supplied-draw market type')
        if kind in ('tournament_winner','reach_round','defeat_top_seed') and 'player' not in payload:
            raise ValueError('Selected player required for this draw market')
        if kind=='any_match_win' and not payload.get('any_win_targets'):raise ValueError('any_win_targets required')
        result=self.predict_tournament(payload);tour=payload['tour']
        player=self.resolve(tour,payload['player']) if 'player' in payload else None
        stage=str(payload.get('remaining_slots',''))
        if kind in ('reach_round','qualifier_reach_round','wildcard_reach_round'):
            stages=(next(iter(result['reach_round_probabilities'].values())) if kind=='reach_round' else
                    result['any_qualifier_or_wildcard_reaches_round'])
            if stage not in stages:
                raise ValueError('remaining_slots must be a stage in the verified draw')
        if player is not None and player not in result['winner_probabilities']:raise ValueError('Selected player not in draw')
        if kind=='tournament_winner':p=result['winner_probabilities'][player]
        elif kind=='reach_round':p=result['reach_round_probabilities'][player][stage]
        elif kind=='defeat_top_seed':p=result['defeat_top_seed_probabilities'][player]
        elif kind=='any_match_win':p=result['any_selected_player_wins_a_played_match_probability']
        elif kind in ('qualifier_reach_round','wildcard_reach_round'):
            p=result['any_qualifier_or_wildcard_reaches_round'][stage]['Q' if kind=='qualifier_reach_round' else 'WC']
        elif kind=='top_seed_first_round_exit':p=result['any_top10_seed_loses_opening_round_probability']
        elif kind=='nationality_champion':
            if not isinstance(payload.get('country'),str) or not payload['country']:raise ValueError('country required')
            if result['winner_country_probabilities'] is None:raise ValueError('Complete verified country metadata required')
            p=result['winner_country_probabilities'].get(payload['country'],0.)
        elif kind=='finalist_pair':
            ids=payload.get('pair')
            if not isinstance(ids,list) or len(ids)!=2:raise ValueError('Explicit pair of two players required')
            ids=[self.resolve(tour,x) for x in ids]
            if len(set(ids))!=2 or not set(ids)<=set(result['winner_probabilities']):raise ValueError('Distinct draw players required')
            p=sum(x['probability'] for x in result['finalist_pair_probabilities'] if {x['a'],x['b']}==set(ids))
        else:raise ValueError('Unsupported supplied-draw market type')
        if p is None:raise ValueError('Missing verified metadata for selected draw event')
        return {'sports_market_type':kind,'selection_order':['yes','no'],'probabilities':[p,1-p],
                'condition':result['condition'],'contract_ready':False,'status':'experimental_supplied_draw',
                'source':result['source'],'history_as_of':result['history_as_of'],'player':player,'remaining_slots':stage or None,
                'market_validation':None,'validation_gate':'research_only_no_historical_draw_backtest',
                'limitations':result['limitations']}
