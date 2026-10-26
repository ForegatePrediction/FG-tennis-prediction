"""Completed standard-singles joint score model; no market prices as inputs.

IID service-point baseline, then a minimum-KL tilt on the match winner to
preserve the existing calibrated match probability. This is a new experimental
score distribution, not independently calibrated derivative-market odds.
"""
from collections import defaultdict
from functools import lru_cache
import math


def hold(p):
    if not math.isfinite(p) or not 0 < p < 1: raise ValueError('Point probability must be between 0 and 1')
    q = 1-p
    return p**4*(1+4*q+10*q*q) + 20*p**3*q**3*p*p/(p*p+q*q)


def tiebreak(pa, pb, first, target=7):
    """A wins a win-by-two tiebreak; analytic tail at (target-1)-all."""
    @lru_cache(None)
    def win(a, b):
        if max(a, b) >= target and abs(a-b) >= 2: return float(a > b)
        if a == b == target-1:
            return pa*(1-pb)/(pa*(1-pb)+(1-pa)*pb)
        server = first ^ (((a+b+1)//2) % 2)
        p = pa if server == 0 else 1-pb
        return p*win(a+1, b)+(1-p)*win(a, b+1)
    return win(0, 0)


def set_kernel(pa, pb, first, target=7):
    """(A games, B games, next set's first server) -> probability."""
    ha, hb = hold(pa), hold(pb); states = {(0, 0): 1.}; out = defaultdict(float)
    for _ in range(13):
        following = defaultdict(float)
        for (a, b), mass in states.items():
            if max(a, b) >= 6 and abs(a-b) >= 2:
                out[a, b, first ^ ((a+b) % 2)] += mass; continue
            if a == b == 6:
                p = tiebreak(pa, pb, first, target)
                out[7, 6, first ^ 1] += mass*p
                out[6, 7, first ^ 1] += mass*(1-p); continue
            server = first ^ ((a+b) % 2); p = ha if server == 0 else 1-hb
            following[a+1, b] += mass*p; following[a, b+1] += mass*(1-p)
        states = following
    if states: raise ArithmeticError('Set recursion did not terminate')
    return dict(out)


def serve_parameters(state, a, b, surface, day):
    sr = .63 if state.tour == 'atp' else .57
    sa = state.summary(a, surface, day); sb = state.summary(b, surface, day)
    def logit(p): return math.log(p/(1-p))
    def estimate(server, receiver):
        x = logit(server['serve'])+logit(1-receiver['return'])-logit(sr)
        return max(.4, min(.8, 1/(1+math.exp(-x))))
    return estimate(sa, sb), estimate(sb, sa), {'a_recent_stats_fraction': sa['stats_sample'],
                                               'b_recent_stats_fraction': sb['stats_sample']}


def distribution(pa, pb, match_probability_a, best_of=3, final_tiebreak_points=7,score_probabilities=None,set_outcomes=None,set_outcomes_by_period=None):
    if best_of not in (3, 5): raise ValueError('Only standard best-of-3/5 singles supported')
    if final_tiebreak_points not in (7, 10): raise ValueError('Final-set tiebreak target must be explicitly 7 or 10')
    if not math.isfinite(match_probability_a) or not 0 < match_probability_a < 1:
        raise ValueError('Match probability must be strictly between zero and one')
    target = best_of//2+1
    kernels = {(first, points): set_kernel(pa, pb, first, points)
               for first in (0, 1) for points in {7, final_tiebreak_points}}
    def empirical_kernel(outcomes):
        if not outcomes or any(not math.isfinite(p) or p<0 for p in outcomes.values()) or abs(sum(outcomes.values())-1)>1e-8:
            raise ValueError('Normalized finite set-outcome probabilities required')
        for (a,b) in outcomes:
            if not (max(a,b)==6 and min(a,b)<=4 or max(a,b)==7 and min(a,b) in (5,6)):raise ValueError('Nonstandard empirical set score')
        return {(first,points):{(a,b,first^((a+b)%2)):p for (a,b),p in outcomes.items()}
                for first in (0,1) for points in {7,final_tiebreak_points}}
    if set_outcomes is not None:kernels=empirical_kernel(set_outcomes)
    period_kernels={}
    if set_outcomes_by_period is not None:
        if set(set_outcomes_by_period)!=set(range(1,best_of+1)):
            raise ValueError('Empirical kernels required for every period in the match format')
        period_kernels={i:empirical_kernel(values) for i,values in set_outcomes_by_period.items()}
    def kernel(a, b, server):
        return period_kernels.get(a+b+1,kernels)[server, final_tiebreak_points if a == b == target-1 else 7]
    @lru_cache(None)
    def eventual(a, b, server):
        if a == target or b == target: return float(a == target)
        return sum(mass*eventual(a+(ga > gb), b+(gb > ga), nxt)
                   for (ga, gb, nxt), mass in kernel(a, b, server).items())
    raw_p = (eventual(0, 0, 0)+eventual(0, 0, 1))/2
    weights = (match_probability_a/raw_p, (1-match_probability_a)/(1-raw_p))
    if score_probabilities is not None:
        raw_scores=defaultdict(float);pending={(0,0,0):.5,(0,0,1):.5}
        for _ in range(best_of+1):
            following=defaultdict(float)
            for (a,b,server),mass in pending.items():
                if max(a,b)==target:raw_scores[f'{a}-{b}']+=mass;continue
                for (ga,gb,nxt),p in kernel(a,b,server).items():following[a+(ga>gb),b+(gb>ga),nxt]+=mass*p
            pending=following
        if set(raw_scores)!=set(score_probabilities) or any(not math.isfinite(p) or p<0 for p in score_probabilities.values()):raise ValueError('Complete valid terminal score probabilities required')
        if abs(sum(score_probabilities.values())-1)>1e-8 or abs(sum(p for s,p in score_probabilities.items() if int(s.split('-')[0])==target)-match_probability_a)>1e-8:
            raise ValueError('Terminal score probabilities must preserve match winner')
        terminal_weights={s:score_probabilities[s]/p for s,p in raw_scores.items()}
    else:terminal_weights=None
    @lru_cache(None)
    def tilt(a, b, server):
        if terminal_weights is None:
            p=eventual(a,b,server);return p*weights[0]+(1-p)*weights[1]
        if max(a,b)==target:return terminal_weights[f'{a}-{b}']
        return sum(p*tilt(a+(ga>gb),b+(gb>ga),nxt) for (ga,gb,nxt),p in kernel(a,b,server).items())
    # Period marginals jointly weighted by the eventual match winner.
    periods = {i: {'a': 0., 'b': 0., 'games': defaultdict(float)} for i in range(1, best_of+1)}
    states = {(0, 0, 0): .5, (0, 0, 1): .5}; scores = defaultdict(float)
    for depth in range(best_of+1):
        following = defaultdict(float)
        for (a, b, server), mass in states.items():
            if a == target or b == target:
                scores[f'{a}-{b}'] += mass*tilt(a, b, server); continue
            for (ga, gb, nxt), probability in kernel(a, b, server).items():
                aa, bb = a+(ga > gb), b+(gb > ga); unweighted = mass*probability
                weighted = unweighted*tilt(aa, bb, nxt)
                period = periods[depth+1]
                period['a' if ga > gb else 'b'] += weighted
                period['games'][ga+gb] += weighted
                following[aa, bb, nxt] += unweighted
        states = following
    # Separate count convolutions retain dependence on final winner without
    # a huge joint games-by-margin state table.
    def counts(margin):
        current = {(0, 0, 0, 0): .5, (0, 0, 1, 0): .5}; terminal = defaultdict(float)
        for _ in range(best_of+1):
            following = defaultdict(float)
            for (a, b, server, value), mass in current.items():
                if a == target or b == target:
                    terminal[value, a == target] += mass*tilt(a, b, server); continue
                for (ga, gb, nxt), probability in kernel(a, b, server).items():
                    following[a+(ga > gb), b+(gb > ga), nxt, value+(ga-gb if margin else ga+gb)] += mass*probability
            current = following
        return dict(terminal)
    return {'scores': dict(scores), 'totals': counts(False), 'margins': counts(True),
            'periods': periods, 'raw_match_probability_a': raw_p,
            'match_probability_a': match_probability_a, 'serve_point_probability_a': pa,
            'serve_point_probability_b': pb, 'best_of': best_of,
            'final_tiebreak_points': final_tiebreak_points}


SCORE_TYPES = ('moneyline', 'tennis_first_set_winner', 'tennis_set_winner',
               'tennis_first_set_totals', 'tennis_set_games_totals', 'tennis_match_totals',
               'tennis_set_totals', 'tennis_game_handicap', 'tennis_set_handicap',
               'tennis_exact_score', 'match_winner_and_game_margin')


def quote(dist, kind, line=None, set_number=None, selection='a', score=None):
    """Semantic selections, never inferred Poly outcome/token order.

    All probabilities conditional on normal match completion. Period markets
    expose non-reach separately; it must not be silently normalized away.
    """
    if kind not in SCORE_TYPES: raise ValueError('Market requires a separate model: '+kind)
    if selection not in ('a', 'b'): raise ValueError('selection must be a or b')
    if kind in ('tennis_first_set_winner', 'tennis_first_set_totals'):
        if set_number not in (None,1):raise ValueError('First-set markets cannot refer to another set')
        set_number = 1
    period = None
    if kind in ('tennis_first_set_winner', 'tennis_set_winner', 'tennis_first_set_totals', 'tennis_set_games_totals'):
        if isinstance(set_number, bool) or not isinstance(set_number,int) or set_number not in dist['periods']: raise ValueError('Explicit integer set_number must be within match format')
        period = dist['periods'][set_number]
    needs_line = kind in ('tennis_first_set_totals', 'tennis_set_games_totals', 'tennis_match_totals', 'tennis_set_totals',
                          'tennis_game_handicap', 'tennis_set_handicap', 'match_winner_and_game_margin')
    if needs_line:
        if line is None or isinstance(line, bool) or not math.isfinite(float(line)) or abs(float(line)) > 100:
            raise ValueError('Explicit finite line required, magnitude <=100')
        line = float(line)
        if line*2 != round(line*2) or line.is_integer(): raise ValueError('Only half-integer lines supported; integer push rules require explicit settlement support')
    if kind == 'moneyline': p = dist['match_probability_a']; reach = 1.; labels = ['a', 'b']
    elif kind in ('tennis_first_set_winner', 'tennis_set_winner'):
        p = period['a']; reach = period['a']+period['b']; labels = ['a', 'b']
    elif kind in ('tennis_first_set_totals', 'tennis_set_games_totals'):
        p = sum(v for games, v in period['games'].items() if games > line)
        reach = period['a']+period['b']; labels = ['over', 'under']
    elif kind == 'tennis_match_totals':
        p = sum(v for (games, _), v in dist['totals'].items() if games > line); reach = 1.; labels = ['over', 'under']
    elif kind == 'tennis_set_totals':
        p = sum(v for score, v in dist['scores'].items() if sum(map(int, score.split('-'))) > line)
        reach = 1.; labels = ['over', 'under']
    elif kind in ('tennis_game_handicap', 'match_winner_and_game_margin'):
        sign = 1 if selection == 'a' else -1
        p = sum(v for (margin, a_won), v in dist['margins'].items()
                if sign*margin+line > 0 and (kind != 'match_winner_and_game_margin' or a_won == (selection == 'a')))
        reach = 1.; labels = [selection+'_covers' if kind == 'tennis_game_handicap' else selection+'_wins_and_covers', 'complement']
    elif kind == 'tennis_set_handicap':
        sign = 1 if selection == 'a' else -1
        p = sum(v for score, v in dist['scores'].items() if sign*(int(score[0])-int(score[2]))+line > 0)
        reach = 1.; labels = [selection+'_covers', 'complement']
    else:
        if score not in dist['scores']: raise ValueError('Explicit A-B completed set score required; Not Completed needs completion-risk model')
        p = dist['scores'][score]; reach = 1.; labels = ['yes', 'no']
    # Rounding guards, not renormalization of missing periods.
    reach = max(0., min(1., reach)); p = max(0., min(reach, p))
    return {'sports_market_type': kind, 'selection_order': labels,
            'probabilities': [p, max(0., reach-p)], 'period_reached_probability': reach,
            'period_not_reached_probability': 1-reach,
            'probabilities_given_period_reached': [p/reach, 1-p/reach] if reach else None,
            'line': line, 'set_number': set_number, 'handicap_selection': selection if 'handicap' in kind or kind == 'match_winner_and_game_margin' else None,
            'score': score, 'condition': 'normal_completed_standard_singles_match',
            'contract_ready': False, 'status': 'experimental',
            'note': 'Semantic probabilities only. Bind verified Poly selections and retirement/void rules separately; no unconditional tradable price is asserted.'}
