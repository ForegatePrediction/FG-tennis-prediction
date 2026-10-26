"""Foregate's existing GET /predict + per-market AI sheet contract.

Fixture context is loaded from a reviewed local index, never guessed from ATP/WTA.
No external network calls are made while answering a prediction request.
"""
import copy
import datetime as dt
import json
from pathlib import Path

from .completion import timestamp
from .inference import normalize
from .validation import market_key

UTC=dt.timezone.utc
KINDS=('moneyline','tennis_set_winner','tennis_set_totals','tennis_set_handicap',
       'tennis_set_games_totals','tennis_match_totals','tennis_game_handicap',
       'tennis_first_set_winner','tennis_first_set_totals','tennis_exact_score','tennis_completed_match')


def default_markets(best_of):
    """A documented reference grid; actual fixture specs take precedence."""
    rows=[{'market_type':'moneyline'},{'market_type':'tennis_completed_match'}]
    for n in range(1,best_of+1):
        rows.append({'market_type':'tennis_first_set_winner' if n==1 else 'tennis_set_winner','set_number':n})
        for line in (8.5,9.5,10.5):
            rows.append({'market_type':'tennis_first_set_totals' if n==1 else 'tennis_set_games_totals',
                         'set_number':n,'line':line})
    rows.extend({'market_type':'tennis_match_totals','line':line}
                for line in ((20.5,21.5,22.5,23.5,24.5) if best_of==3 else (36.5,38.5,40.5,42.5)))
    rows.extend({'market_type':'tennis_set_totals','line':line} for line in ((2.5,) if best_of==3 else (3.5,4.5)))
    for kind,lines in (('tennis_set_handicap',(1.5,) if best_of==3 else (1.5,2.5)),
                       ('tennis_game_handicap',(1.5,2.5,3.5,4.5))):
        for side in ('a','b'):
            rows.extend({'market_type':kind,'line':-line,'selection':side} for line in lines)
    target=best_of//2+1
    for loser in range(target):
        for score in (f'{target}-{loser}',f'{loser}-{target}'):
            rows.append({'market_type':'tennis_exact_score','score':score})
    rows.append({'market_type':'tennis_exact_score','score':'Not Completed'})
    return rows


def identity(spec):
    kind=spec['market_type'];params={k:spec[k] for k in ('line','selection') if k in spec}
    if kind in ('tennis_set_winner','tennis_set_games_totals'):params['set_number']=spec['set_number']
    return market_key(kind,params,spec.get('score'))


def demo_fixtures():
    """Explicitly synthetic matchups, never masquerading as a live Poly event."""
    now=dt.datetime.now(UTC);fixtures={}
    for tour,a,b in (('atp','Jannik Sinner','Carlos Alcaraz'),('wta','Aryna Sabalenka','Iga Swiatek')):
        fixtures['demo-'+tour]={'eventSlug':'demo-'+tour,'tour':tour,'a':a,'b':b,
            'startTime':(now+dt.timedelta(days=1)).isoformat(),'checked_at':now.isoformat(),
            'source':'Synthetic UI verification; not a scheduled match','verified':True,'demo_only':True,
            'context':{'surface':'Hard','best_of':3,'final_tiebreak_points':7,'indoor':False,
                       'competition':'main_tour','format':'main_tour_singles'}}
    return fixtures


class ForegateService:
    def __init__(self,engine,expanded=None,index=None,demo=False):
        self.engine=engine;self.expanded=expanded;self.index=Path(index) if index else None
        self.demo=demo

    def catalog(self):
        value={'schema':1,'fixtures':{},'categories':{}}
        if self.index and self.index.exists():
            value=json.loads(self.index.read_text(encoding='utf-8'))
            if value.get('schema')!=1 or not isinstance(value.get('fixtures'),dict):
                raise ValueError('Invalid Foregate fixture index')
        if self.demo:value={**value,'fixtures':{**value['fixtures'],**demo_fixtures()}}
        return value

    def health(self):
        try:
            records=self.catalog()['fixtures']
            status='demo' if self.demo else 'available' if records else 'not_configured'
            return {'status':status,'fixtures':len(records),'automatic_collection':False,
                    'expanded_model_loaded':self.expanded is not None,'contract_ready':False}
        except (ValueError,TypeError,KeyError,OSError):return {'status':'invalid_index','contract_ready':False}

    def predict(self,params):
        if params.get('type') not in (None,'tennis'):raise ValueError('type must be tennis')
        lang=params.get('lang','zh')
        if lang not in ('zh','en','vi'):raise ValueError('lang must be zh, en or vi')
        slug=params.get('eventSlug');a=params.get('a');b=params.get('b')
        if not slug or not a or not b:raise ValueError('Required: eventSlug, a, b')
        out={'type':'tennis','eventSlug':slug,'marketId':params.get('marketId'),
             'A':a,'B':b,'matched_exact':False,'ready':False,'platform_markets':{},
             'market_results':[],'reasons':{},'unavailable':[],'contract_ready':False}
        try:
            catalog=self.catalog();record=copy.deepcopy(catalog['fixtures'].get(slug))
            if not record:raise ValueError('No reviewed fixture context for eventSlug')
            if record.get('eventSlug')!=slug or record.get('verified') is not True or not record.get('source'):
                raise ValueError('Reviewed fixture identity and provenance required')
            tour=record.get('tour');categories=catalog.get('categories',{})
            requested=params.get('tour')
            if params.get('categoryId'):
                category_tour=categories.get(params['categoryId'])
                if not category_tour:raise ValueError('Unknown categoryId; use verified ATP/WTA mapping')
                if requested and requested!=category_tour:raise ValueError('categoryId contradicts tour')
                requested=category_tour
            if tour not in ('atp','wta') or requested and requested!=tour:raise ValueError('Fixture tour mismatch')
            out['tour']=tour
            now=dt.datetime.now(UTC);start=timestamp(record['startTime']);checked=timestamp(record['checked_at'])
            age=(now-checked).total_seconds()
            if not -300<=age<=48*3600:raise ValueError('Fixture metadata missing a recent check (48 hours)')
            if start<=now or record.get('status','NOT_STARTED')!='NOT_STARTED':
                raise ValueError('Match already started or no longer confirmed pre-match')
            if start>now+dt.timedelta(days=14):raise ValueError('Fixture outside 14-day prediction window')
            context=record.get('context')
            required=('surface','best_of','final_tiebreak_points','competition','format','indoor')
            if not isinstance(context,dict) or any(k not in context for k in required):
                raise ValueError('Missing reviewed surface, format or competition context')
            if type(context['best_of']) is not int or context['best_of'] not in (3,5):raise ValueError('Invalid fixture best_of')
            if type(context['final_tiebreak_points']) is not int or context['final_tiebreak_points'] not in (7,10):raise ValueError('Invalid fixture tiebreak')
            if type(context['indoor']) is not bool:raise ValueError('Invalid fixture indoor flag')
            for key in required:
                if key in params and str(params[key]).lower()!=str(context[key]).lower():
                    raise ValueError('Query contradicts reviewed fixture '+key)
            competition=context['competition']
            if competition not in ('main_tour','challenger_main_draw','atp_qualifying'):
                raise ValueError('Competition outside validated model scope: '+str(competition))
            if competition!='main_tour' and tour!='atp':raise ValueError('Expanded qualifying/Challenger scope is ATP only')
            expected='main_tour_singles' if competition=='main_tour' else 'expanded_atp_singles'
            if context['format']!=expected:raise ValueError('Competition and format contradict')
            engine=self.engine if competition=='main_tour' else self.expanded
            if engine is None:raise ValueError('Separate expanded ATP snapshot is not loaded')
            original=[engine.resolve(tour,record[k]) for k in ('a','b')]
            actual=[engine.resolve(tour,x) for x in (a,b)]
            if actual==original:swapped=False
            elif actual==original[::-1]:swapped=True
            else:raise ValueError('Players do not match the indexed fixture')
            if actual[0]==actual[1]:raise ValueError('Players must differ')
            if params.get('date') and params['date']!=start.date().isoformat():raise ValueError('Date contradicts fixture start')
            specs=json.loads(params['markets']) if 'markets' in params else record.get('markets')
            origin='query' if 'markets' in params else 'fixture' if specs is not None else 'reference_grid'
            if specs is None:specs=default_markets(context['best_of'])
            if not isinstance(specs,list) or not 1<=len(specs)<=200 or not all(isinstance(s,dict) for s in specs):
                raise ValueError('markets must contain 1..200 objects')
            specs=copy.deepcopy(specs)
            if swapped and origin=='fixture':
                for spec in specs:
                    if 'selection' in spec:spec['selection']='b' if spec['selection']=='a' else 'a'
                    if spec.get('score') not in (None,'Not Completed','Other'):
                        spec['score']='-'.join(spec['score'].split('-')[::-1])
            result=engine.predict_markets({**context,'tour':tour,'a':actual[0],'b':actual[1],
                'date':start.date().isoformat(),'markets':specs})
            out.update(matched_exact=True,model_revision=engine.snapshot_sha256,history_as_of=engine.snapshot['as_of'],
                       matchStartTime=start.isoformat(),fixture_checked_at=record['checked_at'],fixture_source=record['source'],
                       context=context,market_specs_origin=origin,demo_only=record.get('demo_only',False),
                       warnings=result.get('base',{}).get('warnings',[]))
            names=[engine.states[tour].player(i)['profile']['name'] for i in actual]
            out.update(A=names[0],B=names[1])
            import_issues={x['outcomeId']:x['reason'] for x in record.get('import_issues',[])}
            for spec,row in zip(specs,result['markets']):
                if row['status']=='unavailable':
                    if origin=='fixture' and str(spec.get('id')) in import_issues:
                        row={**row,'reason':import_issues[str(spec['id'])]}
                    out['unavailable'].append(row);continue
                kind=row['sports_market_type'];key=identity(spec)
                labels=self.labels(row,names,lang)
                entry={**row,'key':key,'pairs':list(zip(labels,row['probabilities']))}
                if kind=='moneyline':entry.update(home=row['probabilities'][0],away=row['probabilities'][1])
                reason=self.reason(row,names,lang,result.get('base',{}))
                out['reasons'][key]=reason
                out['reasons'].setdefault(kind,reason)
                if kind=='moneyline':out['platform_markets'][kind]=entry
                else:out['platform_markets'].setdefault(kind,[]).append(entry)
                binding=record.get('bindings',{}).get(str(spec.get('id'))) if origin=='fixture' else None
                if binding:
                    order=binding['order']
                    if swapped and kind in ('moneyline','tennis_first_set_winner','tennis_set_winner'):order=[1-i for i in order]
                    entry['foregate_outcomes']=[{**option,'probability':row['probabilities'][i]}
                                               for option,i in zip(binding['options'],order)]
                out['market_results'].append(entry)
            out['ready']=bool(out['market_results']);out['summary']=result['summary']
        except (ValueError,TypeError,KeyError,OSError) as exc:
            out.update(ready=False,platform_markets={},market_results=[],reasons={})
            out['unavailable'].append({'reason':str(exc)})
        out['status']='ready' if out['ready'] and not out['unavailable'] else 'partial' if out['ready'] else 'unavailable'
        return out

    @staticmethod
    def labels(row,names,lang):
        words={'zh':('大','小','是','否'),'en':('Over','Under','Yes','No'),'vi':('Tài','Xỉu','Có','Không')}[lang]
        selection=row['selection_order'];line=row.get('line')
        if selection==['a','b']:return names
        if selection==['over','under']:return [f'{words[0]} {line:g}',f'{words[1]} {line:g}']
        if selection==['yes','no']:return list(words[2:])
        side=0 if row.get('handicap_selection')=='a' else 1
        return [f'{names[side]} {line:+g}',f'{names[1-side]} {-line:+g}']

    @staticmethod
    def reason(row,names,lang,base=None):
        baseline=row['status']=='historical_baseline'
        text={'zh':('根据历史完赛合约估算的整体概率，不是该球员的伤病预测。',
                    '根据赛前球员历史和同一比分分布计算；以标准比赛正常完赛为条件。',
                    '回测结果为回顾性验证，尚需前向验证。'),
              'en':('Historical population completion rate; not a player injury forecast.',
                    'Computed from pre-match player history and one joint score distribution, conditional on normal completion.',
                    'Backtests are retrospective; forward validation remains necessary.'),
              'vi':('Tỷ lệ hoàn tất chung trong lịch sử; không dự báo chấn thương cá nhân.',
                    'Tính từ lịch sử trước trận và cùng phân phối tỷ số, với điều kiện trận đấu hoàn tất bình thường.',
                    'Kiểm định hồi cứu; vẫn cần kiểm định tương lai.')}[lang]
        reasons=[text[0] if baseline else text[1]]
        base=base or {}
        if not baseline and 'a' in base and 'b' in base:
            a,b=base['a'],base['b']
            reasons.append({'zh':f"歷史評級：{a['name']} {a['elo']:.0f}，{b['name']} {b['elo']:.0f}；歷史截至 {base['history_as_of']}。",
                            'en':f"Historical ratings: {a['name']} {a['elo']:.0f}, {b['name']} {b['elo']:.0f}; history through {base['history_as_of']}.",
                            'vi':f"Điểm lịch sử: {a['name']} {a['elo']:.0f}, {b['name']} {b['elo']:.0f}; dữ liệu đến {base['history_as_of']}."}[lang])
        validation=row.get('market_validation')
        if validation:
            n=validation['model']['n'];acc=validation['model']['accuracy'];baseline_acc=validation['2024_empirical_baseline']['accuracy']
            reasons.append({'zh':f'此參數回顧性回測 {n:,} 場，命中率 {acc:.1%}；歷史頻率基線 {baseline_acc:.1%}。',
                            'en':f'This parameter: {n:,} retrospective test matches, accuracy {acc:.1%}; frequency baseline {baseline_acc:.1%}.',
                            'vi':f'Tham số này: {n:,} trận kiểm định hồi cứu, độ chính xác {acc:.1%}; mức cơ sở {baseline_acc:.1%}.'}[lang])
        reasons.append(text[2])
        reach=row.get('period_not_reached_probability',0)
        if reach:
            reasons.append({'zh':f'未进行到该盘的概率：{reach:.1%}，不计作任一方输。',
                            'en':f'Period not reached: {reach:.1%}; this is not a loss for either selection.',
                            'vi':f'Không diễn ra set này: {reach:.1%}; không tính là thua cho bên nào.'}[lang])
        return reasons
