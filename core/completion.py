"""Historical Polymarket completion base rates, never a player injury model."""
import datetime as dt
import math
import re


def rule_days(text):
    found=re.search(r'\((\d+) days after the scheduled start\)|delayed beyond (\d+) days from the scheduled date',text,re.I)
    return int(next(x for x in found.groups() if x is not None)) if found else None


def timestamp(value):
    if not isinstance(value,str):raise ValueError('Timestamp required')
    value=value.replace('Z','+00:00')
    if value.endswith('+00'):value+=':00'
    # Gamma emits variable precision; Python 3.9/3.10 only accept 3 or 6 digits.
    value=re.sub(r'(\d{2}:\d{2}:\d{2})\.(\d+)',lambda m:m[1]+'.'+(m[2]+'000000')[:6],value)
    out=dt.datetime.fromisoformat(value)
    if out.utcoffset() is None:raise ValueError('Timezone required')
    return out.astimezone(dt.timezone.utc)


def cohort(event):
    meta=event.get('eventMetadata') or {};source=str(meta.get('tennisFixtureSource','')).lower()
    title=event.get('title','').lower();sport=event.get('sport') or {}
    sport=sport.get('sport','') if isinstance(sport,dict) else sport
    if not sport:
        leagues={t.get('league') for t in event.get('teams') or []}
        if len(leagues)==1:sport=next(iter(leagues))
    tour='wta' if sport in ('wta','itf-women') or 'women' in source or 'women' in title else 'atp' if sport in ('atp','itf-men') else 'unknown'
    competition=('challenger_qualifying' if 'challenger' in source and 'qual' in source else
                 'challenger_main_draw' if 'challenger' in source else
                 'itf' if 'itf' in source or 'itf' in title or str(sport).startswith('itf') else
                 'atp_qualifying' if 'qual' in source and tour=='atp' else
                 'wta_qualifying' if 'qual' in source and tour=='wta' else 'main_tour' if tour!='unknown' else 'unknown')
    return tour,competition


def wilson(success,n):
    if not n:return [0.,1.]
    z=1.95996398454;p=success/n;den=1+z*z/n
    mid=(p+z*z/(2*n))/den;delta=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0.,mid-delta),min(1.,mid+delta)]


def estimate(config,tour=None,competition=None,date=None,rule_version=None):
    if not config:raise ValueError('Build completion baseline with train_completion.py first')
    if tour not in (None,'atp','wta','unknown'):raise ValueError('tour must be atp, wta or unknown')
    if rule_version is not None and (isinstance(rule_version,bool) or rule_version not in (7,14)):raise ValueError('Supported completion deadlines: 7 or 14 days')
    day=dt.date.fromisoformat(date) if date else dt.datetime.now(dt.timezone.utc).date()
    if day<dt.date.fromisoformat(config['as_of']):raise ValueError('Historical completion inference requires an archived baseline')
    if day>dt.datetime.now(dt.timezone.utc).date()+dt.timedelta(days=14):raise ValueError('Completion prediction must be within 14 days')
    requested='|'.join([tour or '*',competition or '*',str(rule_version or '*')])
    group=config['groups'].get(requested)
    fallback=group is None or group['n']<config['minimum_group_n']
    global_selected=config.get('selected_method')=='global_frequency'
    if fallback or global_selected:group=config['global']
    base=config['global']['probability'];strength=config['prior_strength']
    p=group['probability'] if fallback or global_selected else (group['yes']+strength*base)/(group['n']+strength)
    warnings=['Historical market-wide base rate; no player-specific health or injury inputs.',
              'Labels require closed AND UMA-resolved AND exact binary settlement; source is an archived Gamma snapshot, not independently replayed on-chain.',
              'Resolved-market selection and reporting delays can affect the estimate; unresolved or ambiguous records are excluded.',
              'Wilson interval assumes independent labels; common tournament/weather shocks and population drift can produce wider uncertainty.']
    specific=bool(tour or competition or rule_version)
    if global_selected and specific:warnings.append('Validation preferred the global base rate to cohort adjustments; this is a population estimate, not a validated cohort-specific rate.')
    elif fallback and specific:warnings.append('Insufficient matching cohort: uses global tennis baseline; this is an unvalidated transfer to the requested cohort.')
    age=(day-dt.date.fromisoformat(config['as_of'])).days
    if age>3:warnings.append('Completion baseline older than 3 days; refresh labels before operational use.')
    return {'sports_market_type':'tennis_completed_match','selection_order':['yes','no'],
            'probabilities':[p,1-p],'condition':'Historical Poly Completed Match resolution base rate, including resolved No outcomes',
            'period_reached_probability':1.,'period_not_reached_probability':0.,'probabilities_given_period_reached':[p,1-p],
            'line':None,'set_number':None,'score':None,'status':'historical_baseline','contract_ready':False,
            'requested_cohort':requested,'used_global_fallback':specific and (fallback or global_selected),'baseline_method':config.get('selected_method'),
            'sample':{k:group[k] for k in ('n','yes','no')},'raw_frequency':group['yes']/group['n'],
            'raw_frequency_95pct_wilson':wilson(group['yes'],group['n']),
            'baseline_as_of':config['as_of'],'source_checked_at':config['source_checked_at'],
            'validation':config['test'],'warnings':warnings,
            'note':'Confidence interval describes the recorded population rate, not individual-match certainty or missing-label bias.'}


def not_completed_quote(completion):
    p=completion['probabilities'][1]
    return {'sports_market_type':'tennis_exact_score','score':'Not Completed','selection_order':['yes','no'],
            'probabilities':[p,1-p],'probabilities_given_period_reached':[p,1-p],
            'period_reached_probability':1.,'period_not_reached_probability':0.,'line':None,'set_number':None,
            'status':'historical_baseline','contract_ready':False,
            'condition':'Historical unconditional Poly noncompletion base rate; not an individual injury forecast',
            'completion_baseline':completion}
