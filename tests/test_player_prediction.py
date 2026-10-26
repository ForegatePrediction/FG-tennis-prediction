"""Player-only API compatibility and probability invariants, not accuracy claims."""
import copy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import urllib.request

from core.foregate import ForegateService, KINDS, demo_fixtures
from core.inference import Engine, normalize
from server import handler


class PlayerPredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=Engine()

    def setUp(self):
        self.service=ForegateService(self.engine)
        self.params={'type':'tennis','tour':'wta','a':'Qinwen Zheng','b':'Aryna Sabalenka'}

    def predict(self,**changes):
        return self.service.predict({**self.params,**changes})

    def test_two_players_without_event_or_court_return_all_reference_families(self):
        r=self.predict()
        self.assertTrue(r['ready']);self.assertEqual(r['status'],'ready')
        self.assertEqual(set(r['platform_markets']),set(KINDS))
        self.assertEqual(r['summary'],{'requested':35,'predicted':35,'unavailable':0})
        self.assertEqual(r['prediction_mode'],'player_baseline')
        self.assertFalse(r['fixture_matched']);self.assertFalse(r['context_verified'])
        self.assertFalse(r['contract_ready']);self.assertIsNone(r['matchStartTime'])
        self.assertEqual(r['context']['best_of'],3)
        self.assertEqual({s['surface'] for s in r['surface_scenarios']},{'Hard','Clay','Grass'})
        self.assertAlmostEqual(sum(s['weight'] for s in r['surface_scenarios']),1.)
        self.assertIn('surface',{a['field'] for a in r['assumptions']})

    def test_case_spacing_punctuation_accents_and_id_case_are_compatible(self):
        original=self.predict()
        for a,b in [(' QINWEN--ZHENG ',' ARYNA\u00a0 SABALENKA '),
                    ('Qinwen_Zheng','Aryna.Sabalenka'),('Ｑｉｎｗｅｎ Ｚｈｅｎｇ','Aryna’Sabalenka')]:
            r=self.predict(type=' TENNIS ',tour=' WTA ',lang=' ZH ',a=a,b=b)
            self.assertTrue(r['ready'],r['unavailable'])
            self.assertEqual(r['A'],'Qinwen Zheng');self.assertEqual(r['B'],'Aryna Sabalenka')
            self.assertEqual(r['platform_markets']['moneyline']['home'],original['platform_markets']['moneyline']['home'])
        self.assertEqual(self.engine.resolve('atp',' s0ag '),'S0AG')
        self.assertEqual(self.engine.resolve('atp','  Tómas--Etcheverry '),'EA24')
        self.assertEqual(normalize('Straße'),normalize('STRASSE'))

    def test_ambiguous_names_surnames_empty_names_and_same_player_are_rejected(self):
        for a in ('Zheng','---','not-a-player','Aryna SABALENKA'):
            r=self.predict(a=a);self.assertFalse(r['ready']);self.assertFalse(r['platform_markets'])
        state=self.engine.states['wta']
        collision=copy.deepcopy(next(iter(state.players.values())))
        collision['profile']['name']='Qinwen-Zheng'
        with patch.dict(state.players,{'collision-test-id':collision}):
            self.assertFalse(self.predict()['ready'])

    def test_tour_can_be_inferred_but_conflicting_category_is_rejected(self):
        r=self.service.predict({k:v for k,v in self.params.items() if k!='tour'})
        self.assertTrue(r['ready']);self.assertEqual(r['tour'],'wta')
        self.assertFalse(self.predict(categoryId='30157')['ready'])
        self.assertFalse(self.service.predict({'a':'unknown','b':'also unknown'})['ready'])
        with tempfile.TemporaryDirectory() as directory:
            index=Path(directory)/'fixtures.json'
            index.write_text(json.dumps({'schema':1,'fixtures':{},'categories':{'known-wta':'wta'}}))
            service=ForegateService(self.engine,index=index)
            r=service.predict({'a':'Qinwen Zheng','b':'Aryna Sabalenka','categoryId':'known-wta'})
            self.assertTrue(r['ready']);self.assertEqual(r['tour'],'wta')

    def test_missing_event_auto_falls_back_and_strict_fixture_mode_is_retained(self):
        r=self.predict(eventSlug='unknown-event',marketId='472025364873351967')
        self.assertTrue(r['ready']);self.assertFalse(r['fixture_matched'])
        self.assertEqual(r['marketId'],'472025364873351967')
        self.assertFalse(self.predict(eventSlug='unknown-event',mode='fixture')['ready'])
        self.assertFalse(self.predict(mode='fixture')['ready'])
        for row in r['market_results']:
            self.assertNotIn('foregate_outcomes',row);self.assertNotIn('poly_outcomes',row)

    def test_known_event_keeps_identity_and_time_guards_and_players_mode_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            index=Path(directory)/'fixtures.json';records=demo_fixtures()
            index.write_text(json.dumps({'schema':1,'fixtures':records,'categories':{}}))
            service=ForegateService(self.engine,index=index)
            params={'eventSlug':'demo-wta','a':records['demo-wta']['a'],'b':records['demo-wta']['b']}
            r=service.predict(params)
            self.assertTrue(r['ready']);self.assertEqual(r['prediction_mode'],'reviewed_fixture')
            self.assertTrue(r['context_verified']);self.assertTrue(r['fixture_matched'])
            self.assertFalse(service.predict({**params,'a':'Qinwen Zheng'})['ready'])
            r=service.predict({**params,'a':'Qinwen Zheng','mode':'players'})
            self.assertTrue(r['ready']);self.assertFalse(r['fixture_matched'])

    def test_surface_mixture_preserves_order_symmetry_and_period_probability_mass(self):
        r=self.predict();reverse=self.predict(a=self.params['b'],b=self.params['a'])
        self.assertEqual(r['surface_scenarios'],reverse['surface_scenarios'])
        self.assertAlmostEqual(r['platform_markets']['moneyline']['home'],reverse['platform_markets']['moneyline']['away'],7)
        expected=sum(s['weight']*self.predict(surface=s['surface'])['platform_markets']['moneyline']['home'] for s in r['surface_scenarios'])
        self.assertAlmostEqual(r['platform_markets']['moneyline']['home'],expected,12)
        for row in r['market_results']:
            if 'period_not_reached_probability' in row:
                self.assertAlmostEqual(sum(row['probabilities'])+row['period_not_reached_probability'],1.,10)
                if row['period_reached_probability']:
                    self.assertAlmostEqual(sum(row['probabilities_given_period_reached']),1.,10)

    def test_explicit_context_overrides_defaults_without_retraining_or_false_accuracy(self):
        r=self.predict(surface=' clay ',best_of='3',indoor=' TRUE ',final_tiebreak_points='10')
        self.assertTrue(r['ready']);self.assertEqual(r['surface_scenarios'],[{'surface':'Clay','weight':1.}])
        self.assertTrue(r['context']['indoor'])
        self.assertFalse({'surface','best_of','indoor','final_tiebreak_points'}&{a['field'] for a in r['assumptions']})
        direct=self.engine.predict('wta',self.params['a'],self.params['b'],'Clay',indoor=True)
        self.assertAlmostEqual(r['platform_markets']['moneyline']['home'],direct['probability_a'])
        self.assertNotIn('test_metrics',r['base'])
        for row in r['market_results']:
            if row['status']!='historical_baseline':
                self.assertIsNone(row['market_validation'])
                self.assertEqual(row['validation_protocol'],'player_scenarios_not_independently_backtested')

    def test_invalid_context_does_not_return_completion_only_as_player_success(self):
        for change in ({'surface':'unknown'},{'best_of':'5'},{'date':'2020-01-01'},
                       {'rank_a':'0'},{'indoor':'maybe'},{'competition':'challenger_main_draw'}):
            r=self.predict(**change)
            self.assertFalse(r['ready'],change);self.assertFalse(r['platform_markets'])

    def test_requested_lines_and_individual_failures_do_not_gain_market_bindings(self):
        specs=[{'id':'long-market-id','market_type':'tennis_match_totals','line':21.5},
               {'market_type':'tennis_set_games_totals','set_number':3,'line':9.5},
               {'market_type':'unknown_contract'}]
        r=self.predict(markets=json.dumps(specs))
        self.assertEqual(r['status'],'partial');self.assertEqual(r['summary']['predicted'],2)
        self.assertEqual(r['market_results'][0]['line'],21.5)
        self.assertEqual(r['market_results'][0]['request_id'],'long-market-id')
        self.assertNotIn('foregate_outcomes',r['market_results'][0])
        for invalid in ('{}','[]','null'):
            self.assertFalse(self.predict(markets=invalid)['ready'])

    def test_gateway_view_http_without_event_and_legacy_raw_response(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.engine,self.service))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        local=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            query={'view':'foregate','tour':' WTA ','a':'QINWEN-ZHENG','b':'ARYNA SABALENKA'}
            with local.open(base+'/predict?'+urlencode(query)) as response:
                r=json.load(response);self.assertTrue(r['ready'])
                self.assertEqual(response.headers['Access-Control-Allow-Origin'],'*')
            with local.open(base+'/predict?tour=atp&a=s0ag&b=a0e2&surface=hard') as response:
                r=json.load(response);self.assertIn('probability_a',r);self.assertNotIn('platform_markets',r)
            with local.open(base+'/health') as response:
                r=json.load(response);self.assertTrue(r['foregate']['player_prediction_available'])
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
