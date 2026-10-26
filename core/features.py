"""Causal, swap-antisymmetric tennis features; no third-party runtime packages."""
import collections
import datetime as dt
import heapq
import math
from .data import number

BASE = ['elo', 'surface_elo', 'rank', 'points', 'rank_available', 'points_available']
EXTRA = ['experience', 'surface_experience', 'career_winrate', 'surface_winrate',
         'form', 'form_residual', 'surface_form', 'h2h_residual', 'surface_h2h_residual',
         'serve', 'return', 'ace_rate', 'double_fault_rate', 'first_serve_in',
         'first_serve_won', 'second_serve_won', 'break_saved', 'hold_rate',
         'break_rate', 'stats_sample', 'age', 'height', 'left_handed',
         'recent_load', 'recent_minutes', 'rest_days', 'precise_history', 'versus_hand']
INTERACTIONS = ['elo_bo5', 'surface_elo_bo5', 'elo_clay', 'elo_grass', 'elo_indoor',
                'serve_bo5', 'h2h_clay']
FEATURES = BASE + EXTRA + INTERACTIONS
GROUPS = {'ranking': ['rank', 'points', 'rank_available', 'points_available'],
          'elo': ['elo'], 'surface_elo': ['elo', 'surface_elo'],
          'core': BASE + ['elo_bo5', 'surface_elo_bo5', 'elo_clay', 'elo_grass'],
          'enhanced_no_h2h': [k for k in FEATURES if 'h2h' not in k],
          'enhanced': FEATURES}


def expect(a, b):
    return 1 / (1 + 10 ** (max(-6, min(6, (b-a)/400))))


def profile(row, player):
    prefix = 'winner' if player == row['winner_id'] else 'loser'
    return {'name': row[prefix+'_name'], 'rank': number(row.get(prefix+'_rank')),
            'points': number(row.get(prefix+'_rank_points')), 'age': number(row.get(prefix+'_age')),
            'height': number(row.get(prefix+'_ht')), 'hand': row.get(prefix+'_hand', '')}


def fresh_player():
    return {'elo': 1500., 'n': 0, 'wins': 0, 'surfaces': {}, 'history': [], 'profile': {}}


def surface_player(player, surface):
    return player['surfaces'].get(surface, {'elo': 1500., 'n': 0, 'wins': 0})


class State:
    def __init__(self, tour, value=None):
        self.tour = tour
        self.players = (value or {}).get('players', {})
        self.pairs = (value or {}).get('pairs', {})

    def export(self):
        return {'players': self.players, 'pairs': self.pairs}

    def player(self, identifier):
        return self.players.get(identifier, fresh_player())

    def summary(self, identifier, surface, day, current_profile=None, opposite_hand=''):
        player = self.player(identifier)
        surf = surface_player(player, surface)
        prof = current_profile if current_profile is not None else player['profile']
        history = [h for h in player['history'] if h['available'] <= day]
        recent = history[-30:]
        same = [h for h in history if h['surface'] == surface][-30:]
        def mean(rows, key, prior, weight=5):
            valid = [(r[key], math.exp(-math.log(2)*max(0, day-r['available'])/180))
                     for r in rows if r.get(key) is not None]
            return (prior*weight + sum(v*w for v,w in valid))/(weight+sum(w for _,w in valid))
        stats = [h['stats'] for h in recent if h.get('stats')]
        def ratio(num, den, prior, pseudo=100):
            usable = [s for s in stats if s.get(num) is not None and s.get(den) is not None and s[den] > 0]
            return (pseudo*prior+sum(s[num] for s in usable))/(pseudo+sum(s[den] for s in usable))
        sr = .63 if self.tour == 'atp' else .57
        last = history[-1] if history else None
        load = [h for h in history if 0 <= day-h['available'] <= 14]
        precise = bool(last and last['precision'] == 'day')
        rank, points = prof.get('rank'), prof.get('points')
        return {'elo': player['elo']/400, 'surface_elo': (player['elo'] +
                    (surf['elo']-player['elo'])*surf['n']/(surf['n']+15))/400,
                'rank': -math.log(max(1,rank or 1000))/3,
                'points': math.log(1+max(0,points or 0))/3,
                'rank_available': float(bool(rank)), 'points_available': float(bool(points)),
                'experience': math.log1p(player['n'])/5, 'surface_experience': math.log1p(surf['n'])/5,
                'career_winrate': (player['wins']+5)/(player['n']+10),
                'surface_winrate': (surf['wins']+5)/(surf['n']+10),
                'form': mean(recent[-10:], 'win', .5),
                'form_residual': mean(recent[-10:], 'residual', 0.),
                'surface_form': mean(same, 'win', .5),
                'serve': ratio('spw','sp',sr), 'return': ratio('rpw','rp',1-sr),
                'ace_rate': ratio('ace','sp',.06), 'double_fault_rate': ratio('df','sp',.04),
                'first_serve_in': ratio('first_in','sp',.62),
                'first_serve_won': ratio('first_won','first_in',.70),
                'second_serve_won': ratio('second_won','second_pts',.50),
                'break_saved': ratio('bp_saved','bp_faced',.60,20),
                'hold_rate': ratio('held','sg',.78 if self.tour=='atp' else .65,20),
                'break_rate': ratio('broken','rg',.22 if self.tour=='atp' else .35,20),
                'stats_sample': len(stats)/30, 'age': min(45,max(14,prof.get('age') or 26))/10,
                'height': min(220,max(140,prof.get('height') or 180))/20,
                'left_handed': float(prof.get('hand')=='L'),
                'recent_load': len(load)/5,
                'recent_minutes': sum(h.get('minutes') or 0 for h in load)/600,
                'rest_days': min(60,day-last['source_day'])/30 if precise else 0.,
                'precise_history': float(precise),
                'versus_hand': mean([h for h in recent if h.get('opponent_hand')==opposite_hand], 'residual',0.,10)}

    def features(self, a, b, surface, best_of, day, profiles=None, indoor=False):
        profiles = profiles or {}
        pa = profiles.get(a, self.player(a)['profile'])
        pb = profiles.get(b, self.player(b)['profile'])
        sa = self.summary(a,surface,day,pa,pb.get('hand',''))
        sb = self.summary(b,surface,day,pb,pa.get('hand',''))
        values = {key:sa[key]-sb[key] for key in BASE+EXTRA if 'h2h' not in key}
        ids = sorted((a,b)); sign = 1 if a == ids[0] else -1
        pairs = self.pairs.get('|'.join(ids), [])
        for key, rows in [('h2h_residual',pairs), ('surface_h2h_residual',[p for p in pairs if p['surface']==surface])]:
            weights=[math.exp(-math.log(2)*max(0,day-p['available'])/365) for p in rows if p['available']<=day]
            past=[p for p in rows if p['available']<=day]
            values[key]=sign*sum(w*p['residual'] for w,p in zip(weights,past))/(5+sum(weights))
        values.update(elo_bo5=values['elo']*(best_of==5), surface_elo_bo5=values['surface_elo']*(best_of==5),
                      elo_clay=values['elo']*(surface=='Clay'), elo_grass=values['elo']*(surface=='Grass'),
                      elo_indoor=values['elo']*bool(indoor), serve_bo5=values['serve']*(best_of==5),
                      h2h_clay=values['h2h_residual']*(surface=='Clay'))
        return [values[key] for key in FEATURES]

    def update(self, match):
        a,b=match['a'],match['b']; y=match['y']; row=match['raw'];surface=match['surface']
        for identifier in (a,b):
            if identifier not in self.players:self.players[identifier]=fresh_player()
        pa,pb=self.players[a],self.players[b]
        p=expect(pa['elo'],pb['elo'])
        for identifier,win,opponent in [(a,y,b),(b,1-y,a)]:
            player=self.players[identifier]
            surf=player['surfaces'].setdefault(surface,{'elo':1500.,'n':0,'wins':0})
            opp=surface_player(self.players[opponent],surface)
            # Freeze both pre-match surface expectations below, before any update.
        psa=surface_player(pa,surface)['elo'];psb=surface_player(pb,surface)['elo']
        ps=expect(psa,psb)
        for identifier,win,opponent,prob,probs in [(a,y,b,p,ps),(b,1-y,a,1-p,1-ps)]:
            player=self.players[identifier];surf=player['surfaces'][surface]
            k=250/(player['n']+5)**.4
            ks=200/(surf['n']+5)**.4
            player['elo']+=k*(win-prob);surf['elo']+=ks*(win-probs)
            player['n']+=1;player['wins']+=win;surf['n']+=1;surf['wins']+=win
            observed=dt.date.fromordinal(match['source_day']).isoformat()
            if observed>=player['profile'].get('observed_on',''):
                player['profile']=profile(row,identifier)
                player['profile']['observed_on']=observed
            prefix='w_' if identifier==row['winner_id'] else 'l_';other='l_' if prefix=='w_' else 'w_'
            def n(key):return number(row.get(prefix+key))
            def o(key):return number(row.get(other+key))
            sp,fw,sw=n('svpt'),n('1stWon'),n('2ndWon');rp,ofw,osw=o('svpt'),o('1stWon'),o('2ndWon')
            stats=None
            if all(v is not None for v in (sp,fw,sw,rp,ofw,osw)) and sp>0 and rp>0 and 0<=fw+sw<=sp and 0<=ofw+osw<=rp:
                sg,rg=n('SvGms'),o('SvGms');bp,bps=n('bpFaced'),n('bpSaved');obp,obps=o('bpFaced'),o('bpSaved')
                stats={'sp':sp,'spw':fw+sw,'rp':rp,'rpw':rp-ofw-osw,
                       'ace':n('ace'),'df':n('df'),'first_in':n('1stIn'),'first_won':fw,'second_won':sw,
                       'second_pts':sp-n('1stIn') if n('1stIn') is not None else None,
                       'bp_saved':bps,'bp_faced':bp,'sg':sg,'rg':rg,
                       'held':sg-(bp-bps) if None not in (sg,bp,bps) else None,
                       'broken':obp-obps if None not in (obp,obps) else None}
                if any(v is not None and v<0 for v in stats.values()):stats=None
                if stats and any(stats[num] is not None and stats[den] is not None and stats[num]>stats[den]
                                 for num,den in [('ace','sp'),('df','sp'),('first_in','sp'),('first_won','first_in'),
                                                 ('second_won','second_pts'),('bp_saved','bp_faced'),('held','sg'),('broken','rg')]):
                    stats=None
            record={'available':match['available'],'source_day':match['source_day'], 'precision':match['date_precision'],
                    'surface':surface,'win':win,'residual':win-prob,'stats':stats,
                    'minutes':number(row.get('minutes')),'opponent_hand':profile(row,opponent)['hand']}
            player['history'].append(record)
            # Enough past observations for rolling statistics, all pair history retained separately.
            player['history']=player['history'][-120:]
        key='|'.join(sorted((a,b)))
        self.pairs.setdefault(key,[]).append({'available':match['available'],'surface':surface,'residual':y-p,'winner':row['winner_id']})


def build_features(tour,matches,as_of,include_score_context=False):
    state=State(tour);pending=[];vectors=[];metadata=[];counter=0
    for start,group in __import__('itertools').groupby(matches,key=lambda m:m['start']):
        while pending and pending[0][0]<=start:
            _,_,m=heapq.heappop(pending);state.update(m)
        block=list(group)
        event_profiles={}
        for m in block:
            for identifier in (m['a'],m['b']):
                event_profiles.setdefault((m['event'],identifier),profile(m['raw'],identifier))
        for m in block:
            row=m['raw'];profiles={i:event_profiles[(m['event'],i)] for i in (m['a'],m['b'])}
            vectors.append(state.features(m['a'],m['b'],m['surface'],m['best_of'],start,profiles,row.get('indoor')=='I'))
            item={k:m[k] for k in ('id','event','start','available','surface','best_of','y','a','b')}
            if include_score_context:
                from .scoring import serve_parameters
                item['serve_context']=serve_parameters(state,m['a'],m['b'],m['surface'],start)
            metadata.append(item)
        for m in block:
            counter+=1;heapq.heappush(pending,(m['available'],counter,m))
    cutoff=dt.date.fromisoformat(as_of).toordinal()
    while pending and pending[0][0]<=cutoff:
        _,_,m=heapq.heappop(pending);state.update(m)
    return vectors,metadata,state
