"""Exact fixed-strength knockout-draw probabilities, conditional on completion."""
import math


def knockout(slots, probability,any_win_targets=None,top_seed_max=10):
    """Slots are unique player dictionaries or explicit byes (None)."""
    size=len(slots)
    if size<2 or size>128 or size&(size-1):raise ValueError('Draw must contain 2..128 power-of-two slots, with explicit byes')
    players=[p for p in slots if p is not None]
    if len(players)<2:raise ValueError('At least two players required')
    if any(slots[i] is None and slots[i+1] is None for i in range(0,size,2)):raise ValueError('Two opposing byes are not a valid complete main draw')
    ids=[p['id'] for p in players]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate draw player')
    if isinstance(top_seed_max,bool) or not isinstance(top_seed_max,int) or not 1<=top_seed_max<=128:raise ValueError('top_seed_max must be integer 1..128')
    if any_win_targets is not None and (not isinstance(any_win_targets,list) or not any_win_targets or len(set(any_win_targets))!=len(any_win_targets) or not set(any_win_targets)<=set(ids)):
        raise ValueError('any_win_targets must be unique draw player IDs')
    for p in players:
        seed=p.get('seed')
        if seed is not None and (isinstance(seed,bool) or not isinstance(seed,int) or not 1<=seed<=128):raise ValueError('Seed must be integer 1..128 or null')
        if p.get('entry') not in ('DA','Q','LL','WC','unknown'):raise ValueError('Explicit entry required: DA/Q/LL/WC/unknown')
    seeds=[p['seed'] for p in players if p.get('seed') is not None]
    if len(seeds)!=len(set(seeds)):raise ValueError('Duplicate seed')
    nodes=[{p['id']:1.} if p else {} for p in slots]
    # Joint probability that the advancing player has already beaten a high seed.
    flagged=[{i:0. for i in node} for node in nodes];ever_seed={i:0. for i in ids}
    # Separate sub-probability DP for no selected player having won any played
    # match. A bye advances the player without triggering a win event.
    no_target=[dict(node) for node in nodes];target_ids=set(any_win_targets or [])
    reaches={i:{str(size):1.} for i in ids};stage_any={};no_seed_loss=1.;cache={}
    def win(a,b):
        key=tuple(sorted((a,b)))
        if key not in cache:
            p=float(probability(*key))
            if not math.isfinite(p) or not 0<=p<=1:raise ValueError('Invalid matchup probability')
            cache[key]=p
        return cache[key] if a==key[0] else 1-cache[key]
    by_id={p['id']:p for p in players}
    entry_known=all(p['entry']!='unknown' for p in players)
    while len(nodes)>1:
        if len(nodes)==2:
            finalist_pairs=[{'a':a,'b':b,'probability':pa*pb} for a,pa in nodes[0].items() for b,pb in nodes[1].items()]
        following=[];next_flagged=[];next_no_target=[]
        for index in range(0,len(nodes),2):
            left,right=nodes[index:index+2];merged={}
            flags={};no_wins={}
            if not left or not right:
                merged=dict(left or right);chosen=index if left else index+1
                flags=dict(flagged[chosen]);no_wins=dict(no_target[chosen])
            else:
                for a,pa in left.items():
                    for b,pb in right.items():
                        p=win(a,b);merged[a]=merged.get(a,0.)+pa*pb*p;merged[b]=merged.get(b,0.)+pa*pb*(1-p)
                        eligible_a=by_id[a].get('seed') is not None and by_id[a]['seed']<=top_seed_max
                        eligible_b=by_id[b].get('seed') is not None and by_id[b]['seed']<=top_seed_max
                        fa,fb=flagged[index].get(a,0.),flagged[index+1].get(b,0.)
                        new_a=max(0.,pa-fa)*pb*p*eligible_b;new_b=pa*max(0.,pb-fb)*(1-p)*eligible_a
                        ever_seed[a]+=new_a;ever_seed[b]+=new_b
                        flags[a]=flags.get(a,0.)+fa*pb*p+new_a
                        flags[b]=flags.get(b,0.)+pa*fb*(1-p)+new_b
                        q=no_target[index].get(a,0.)*no_target[index+1].get(b,0.)
                        if a not in target_ids:no_wins[a]=no_wins.get(a,0.)+q*p
                        if b not in target_ids:no_wins[b]=no_wins.get(b,0.)+q*(1-p)
            if len(nodes)==size:
                eligible=[i for i in list(left)+list(right) if by_id[i].get('seed') is not None and by_id[i]['seed']<=10]
                if len(eligible)==2:no_seed_loss=0.
                elif len(eligible)==1:no_seed_loss*=merged[eligible[0]]
            following.append(merged)
            next_flagged.append(flags);next_no_target.append(no_wins)
        nodes=following;flagged=next_flagged;no_target=next_no_target;remaining=len(nodes)
        for node in nodes:
            for i,p in node.items():reaches[i][str(remaining)]=p
        stage_any[str(remaining)]={}
        for entry in ('Q','WC'):
            stage_any[str(remaining)][entry]=(1-math.prod(1-sum(p for i,p in node.items() if by_id[i]['entry']==entry) for node in nodes)) if entry_known else None
    countries={}
    if all(p.get('country') for p in players):
        for i,p in nodes[0].items():
            country=by_id[i]['country'];countries[country]=countries.get(country,0.)+p
    return {'winner_probabilities':nodes[0],'reach_round_probabilities':reaches,
            'defeat_top_seed_probabilities':ever_seed,'opponent_seed_max':top_seed_max,
            'any_selected_player_wins_a_played_match_probability':1-sum(no_target[0].values()) if any_win_targets is not None else None,
            'any_win_targets':any_win_targets,
            'finalist_pair_probabilities':finalist_pairs,'any_qualifier_or_wildcard_reaches_round':stage_any,
            'any_top10_seed_loses_opening_round_probability':1-no_seed_loss,
            'winner_country_probabilities':countries or None,'matchups_evaluated':len(cache),
            'condition':'All listed matches complete normally; static strengths; exact supplied knockout draw.',
            'status':'experimental','contract_ready':False,
            'limitations':['No withdrawals, replacements, injury or strength evolution simulated.',
                           'Reach-round keys are remaining draw slots (16 = round of 16; 1 = champion).',
                           'Qualifiers exclude lucky losers; missing entry/country metadata yields unavailable aggregates.',
                           'Country probabilities cover this draw only, not a combined ATP/WTA contract.']}
