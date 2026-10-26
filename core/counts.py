"""Learned match lengths and empirical set-score kernels.

Score-terminal reweighting preserves the existing match-winner probability and
keeps total sets, total games, per-set markets and margins on one distribution.
"""
import math
from .features import FEATURES
from .scoring import distribution


def features(vector,pa,pb,surface,sign=1):
    values=dict(zip(FEATURES,vector))
    signed=[values[k]*sign for k in ('elo','surface_elo','rank','points','experience')]
    return [1.]+signed+[abs(values['elo']),abs(values['surface_elo']),
                        (pa+pb-1.2)*5,(pa-pb)*sign*10,
                        float(surface=='Clay'),float(surface=='Grass'),float(surface=='Carpet')]


def linear_probability(vector,model):
    z=sum(max(-8,min(8,v/s))*w for v,s,w in zip(vector,model['scale'],model['weights']))/model.get('temperature',1.)
    return 1/(1+math.exp(-max(-35,min(35,z))))


def kernel_key(vector,pa,pb,surface,sign=1):
    values=dict(zip(FEATURES,vector));strength=sign*(values['elo']+values['surface_elo'])/2
    bucket=sum(strength>x for x in (-1.,-.5,-.15,.15,.5,1.))
    serve=sum((pa+pb)/2>x for x in (.56,.60,.64,.68))
    return surface+'|'+str(bucket)+'|'+str(serve)


def loser_score_probabilities(config,vector,pa,pb,surface,sign,period=None,best_of=None):
    global_counts=config['kernel_global'];surface_counts=config['kernel_surfaces'].get(surface,global_counts)
    alpha=config['kernel_prior_strength']
    prior=[(n+alpha*(g+1)/(sum(global_counts)+7))/(sum(surface_counts)+alpha) for n,g in zip(surface_counts,global_counts)]
    cell=config['kernel_cells'].get(kernel_key(vector,pa,pb,surface,sign),[0]*7)
    pooled=[(n+alpha*p)/(sum(cell)+alpha) for n,p in zip(cell,prior)]
    if config.get('kernel_period_strength') is None or period is None:return pooled
    # Format-specific hierarchical shrinkage keeps sparse deciding-set cells
    # close to the shared model, without borrowing labels from the test period.
    strength=config['kernel_period_strength'];prefix=f'{best_of}:{period}'
    counts=config.get('kernel_period_global',{}).get(prefix,[0]*7)
    overall=config.get('kernel_format_global',{}).get(str(best_of),global_counts)
    overall_prob=[(n+1)/(sum(overall)+7) for n in overall]
    # A period changes the pooled shape by a learned likelihood ratio; it must
    # not erase strength/surface information by replacing it with a global rate.
    ratio=[((n+strength*g)/(sum(counts)+strength))/g for n,g in zip(counts,overall_prob)]
    weights=[p*r for p,r in zip(pooled,ratio)]
    prior=[p/sum(weights) for p in weights]
    counts=config.get('kernel_period_cells',{}).get(prefix+'|'+kernel_key(vector,pa,pb,surface,sign),[0]*7)
    return [(n+strength*p)/(sum(counts)+strength) for n,p in zip(counts,prior)]


def predict(config,vector,pa,pb,surface,best_of,match_p,final_tiebreak_points):
    target=best_of//2+1;scores={};models=config['length_models'][str(best_of)]
    for side,sign,mass in (('a',1,match_p),('b',-1,1-match_p)):
        xx=features(vector,pa,pb,surface,sign)
        if best_of==3:
            long=linear_probability(xx,models['3']);lengths={2:1-long,3:long}
        else:
            four=linear_probability(xx,models['4']);five=linear_probability(xx,models['5'])
            lengths={3:1-four,4:four*(1-five),5:four*five}
        for n,p in lengths.items():
            a,b=(target,n-target) if side=='a' else (n-target,target)
            scores[f'{a}-{b}']=mass*p
    # Per-set winner prior only; the terminal tilt enforces calibrated match and
    # learned score probabilities. No live score, serve order or market odds.
    def match_win(p):return sum(math.comb(target-1+k,k)*p**target*(1-p)**k for k in range(target))
    lo,hi=1e-5,1-1e-5
    for _ in range(40):
        mid=(lo+hi)/2
        if match_win(mid)<match_p:lo=mid
        else:hi=mid
    set_p=(lo+hi)/2
    def kernel(period=None):
        result={}
        for sign,mass in ((1,set_p),(-1,1-set_p)):
            for loser,p in enumerate(loser_score_probabilities(config,vector,pa,pb,surface,sign,period,best_of)):
                winner=7 if loser in (5,6) else 6
                pair=(winner,loser) if sign==1 else (loser,winner);result[pair]=mass*p
        return result
    periods={i:kernel(i) for i in range(1,best_of+1)} if config.get('kernel_period_strength') is not None else None
    return distribution(pa,pb,match_p,best_of,final_tiebreak_points,scores,kernel(),periods)
