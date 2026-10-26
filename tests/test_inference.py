import datetime as dt
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from core.data import ROOT
from core.features import FEATURES
from core.inference import Engine
from core.validation import market_key
from server import handler


class InferenceTests(unittest.TestCase):
    def test_fractional_or_boolean_match_format_is_rejected(self):
        for value in (3.9,True,False,5.1):
            with self.assertRaises(ValueError):self.engine.predict('atp','S0AG','A0E2','Hard',best_of=value)

    def test_format_and_handicap_side_have_matching_backtests(self):
        report=json.loads((ROOT/'reports/atp-counts-backtest.json').read_text())
        winner=json.loads((ROOT/'reports/atp-backtest.json').read_text())
        counts=[]
        for bo in (3,5):
            expected=report['by_best_of'][str(bo)][market_key('tennis_set_handicap',{'line':-1.5,'selection':'b'})]
            n=expected['model']['n'];counts.append(n)
            q=self.engine.predict_market('atp','S0AG','A0E2','Hard','tennis_set_handicap',-1.5,
                                         selection='b',final_tiebreak_points=7,best_of=bo)
            self.assertEqual(q['validation_best_of'],bo)
            self.assertEqual(q['market_validation'],expected)
            self.assertEqual(q['market_validation']['model']['n'],n)
            self.assertEqual(q['base']['test_metrics']['n'],winner['by_best_of'][str(bo)]['n'])
        self.assertEqual(sum(counts),report['test_matches'])
        q=self.engine.predict_market('atp','S0AG','A0E2','Hard','tennis_set_totals',2.5,final_tiebreak_points=7)
        expected=report['by_best_of']['3'][market_key('tennis_set_totals',{'line':2.5})]
        self.assertEqual(q['market_validation'],expected)
        self.assertEqual(q['retrospective_accuracy_above_baseline'],
                         expected['model']['accuracy']>expected['2024_empirical_baseline']['accuracy']
                         and expected['test_contains_both_outcomes'])

    def test_missing_format_validation_never_uses_mixed_summary(self):
        cfg=self.engine.count_config['tours']['atp']
        with patch.dict(cfg,{'by_best_of':{}}):
            q=self.engine.predict_market('atp','S0AG','A0E2','Hard','tennis_match_totals',22.5,final_tiebreak_points=7)
            self.assertIsNone(q['market_validation'])
            self.assertEqual(q['validation_gate'],'research_only_no_parameter_test')

    def test_draw_inputs_are_explicit_and_historical_accuracy_is_not_invented(self):
        payload={'format':'main_tour_singles_knockout','draw_verified':True,'source':'Synthetic test draw',
                 'tour':'atp','surface':'Hard','best_of':3,'market_type':'tournament_winner',
                 'draw':[{'id':i,'entry':'DA'} for i in ['S0AG','A0E2','Z355','D643']]}
        with self.assertRaisesRegex(ValueError,'player required'):self.engine.predict_tournament_market(payload)
        q=self.engine.predict_tournament_market({**payload,'player':'S0AG'})
        self.assertIsNone(q['market_validation'])
        self.assertEqual(q['validation_gate'],'research_only_no_historical_draw_backtest')
        with self.assertRaisesRegex(ValueError,'remaining_slots'):
            self.engine.predict_tournament_market({**payload,'market_type':'reach_round','player':'S0AG','remaining_slots':64})

    @classmethod
    def setUpClass(cls):
        if not (ROOT/'models/current.json').exists():raise unittest.SkipTest('Build snapshot with train.py first')
        cls.engine=Engine()

    def test_swap_symmetry(self):
        for tour,a,b in [('atp','Jannik Sinner','Carlos Alcaraz'),('wta','Aryna Sabalenka','Iga Swiatek')]:
            p=self.engine.predict(tour,a,b,'Clay');q=self.engine.predict(tour,b,a,'Clay')
            self.assertAlmostEqual(p['probability_a']+q['probability_a'],1.,7)
            self.assertEqual(p['h2h']['a_wins'],q['h2h']['b_wins'])

    def test_invalid_or_ambiguous_players_fail(self):
        for a,b in [('Sinner','Carlos Alcaraz'),('Jannik Sinner','Jannik Sinner'),('not-a-player','Carlos Alcaraz')]:
            with self.assertRaises(ValueError):self.engine.predict('atp',a,b,'Hard')
        with self.assertRaises(ValueError):self.engine.predict('wta','Aryna Sabalenka','Iga Swiatek','Hard',5)

    def test_historical_snapshot_guard_and_rank_validation(self):
        with self.assertRaises(ValueError):self.engine.predict('atp','S0AG','A0E2','Hard',date='2020-01-01')
        for rank in (0,-1,1.5,float('nan')):
            with self.assertRaises(ValueError):self.engine.predict('atp','S0AG','A0E2','Hard',rank_a=rank)

    def test_runtime_matches_numpy_training_formula(self):
        try:
            import numpy as np
            from core.linear import probabilities
        except ImportError:self.skipTest('NumPy optional at runtime')
        tour='atp';m=self.engine.model(tour);day=dt.datetime.now(dt.timezone.utc).date()
        vector=self.engine.states[tour].features('S0AG','A0E2','Grass',5,day.toordinal())
        x=np.asarray([[vector[FEATURES.index(k)] for k in m['features']]])
        actual=self.engine.predict(tour,'S0AG','A0E2','Grass',5)['probability_a']
        self.assertAlmostEqual(actual,float(probabilities(x,m)[0]),7)

    def test_http_contract(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.engine));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        local=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            for path in ('/health','/players?tour=atp&q=Sinner','/predict?tour=atp&a=S0AG&b=A0E2&surface=Hard','/coverage','/predict/completion?tour=atp&rule_days=14',
                         '/predict/market?tour=atp&a=S0AG&b=A0E2&surface=Hard&market_type=tennis_set_handicap&line=-1.5&best_of=3&final_tiebreak_points=7&format=main_tour_singles'):
                with local.open(base+path,timeout=5) as response:
                    self.assertEqual(response.status,200);json.load(response)
            with self.assertRaises(urllib.error.HTTPError) as context:local.open(base+'/predict?tour=atp',timeout=5)
            self.assertEqual(context.exception.code,400)
            payload={'tour':'atp','surface':'Hard','best_of':3,'format':'main_tour_singles_knockout',
                     'draw_verified':True,'source':'Hypothetical two-player test draw, not an actual event',
                     'draw':[{'id':'S0AG','entry':'DA','seed':1,'country':'ITA'},
                             {'id':'A0E2','entry':'DA','seed':2,'country':'ESP'}]}
            request=urllib.request.Request(base+'/predict/tournament',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with local.open(request,timeout=5) as response:
                result=json.load(response);self.assertAlmostEqual(sum(result['winner_probabilities'].values()),1.)
                self.assertFalse(result['contract_ready'])
            payload.update(market_type='defeat_top_seed',player='S0AG',top_seed_max=2)
            request=urllib.request.Request(base+'/predict/tournament/market',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with local.open(request,timeout=5) as response:
                result=json.load(response);self.assertAlmostEqual(sum(result['probabilities']),1.)
            payload={'tour':'atp','a':'S0AG','b':'A0E2','surface':'Hard','best_of':3,'final_tiebreak_points':7,'format':'main_tour_singles'}
            request=urllib.request.Request(base+'/predict/markets',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with local.open(request,timeout=5) as response:
                result=json.load(response);self.assertEqual(result['summary'],{'requested':16,'predicted':16,'unavailable':0})
            payload['markets']=[{'market_type':'tennis_exact_score','score':x} for x in ('2-0','2-1','0-2','1-2','Not Completed')]
            request=urllib.request.Request(base+'/predict/markets',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with local.open(request,timeout=5) as response:
                result=json.load(response);rows=result['markets']
                total=sum(r['probabilities_including_noncompletion'][0] if 'probabilities_including_noncompletion' in r else r['probabilities'][0] for r in rows)
                self.assertAlmostEqual(total,1.)
                self.assertEqual(rows[-1]['probabilities'],rows[-1]['probabilities_given_period_reached'])
            event=json.loads((ROOT/'tests/fixtures/poly-screenshot-event.json').read_text())
            payload={'event':event,'match':{**payload,'a':'L0I5','b':'S0JV'},'mapping_verified':True,'source':'Archived Gamma event, local test only',
                     'player_mapping':{'a':{'poly_name':'Mitsuki Wei Kang Leong'},'b':{'poly_name':'Qian Sun'}}}
            request=urllib.request.Request(base+'/predict/poly-event',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with local.open(request,timeout=5) as response:
                result=json.load(response);self.assertEqual(result['summary']['mapped'],16)
                self.assertEqual(result['summary']['predicted'],0)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
