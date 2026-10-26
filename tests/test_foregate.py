import copy
import datetime as dt
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlencode
import urllib.request
from unittest.mock import patch

from core.data import ROOT
from core.foregate import ForegateService,default_markets,demo_fixtures,KINDS
from core.foregate_detail import detail_event,fixture_record
from core.inference import Engine
from core.markets import compile_market
from import_foregate_fixtures import build
from server import handler


class DetailMappingTests(unittest.TestCase):
    def setUp(self):
        self.detail=json.loads((ROOT/'tests/fixtures/foregate-ningbo-detail.json').read_text())

    def test_actual_foregate_ids_names_and_match_time_are_preserved(self):
        e=detail_event(self.detail);m=e['markets'][0]
        self.assertEqual(e['startTime'],'2026-10-26T02:00:00+00:00')
        self.assertEqual(m['id'],'472025364885938119')
        self.assertEqual(m['_foregate_options'][0]['optionId'],'472025364890129210')
        self.assertEqual(m['outcomes'],['Khumoyun Sultanov','Naoya Honda'])
        self.assertEqual(m['clobTokenIds'][0],self.detail['outcomes'][0]['yesAssetId'])
        self.assertNotIn('chance',m)

    def review(self,competition='challenger_qualifying'):
        e=detail_event(self.detail)
        return {'verified':True,'source':'Reviewed test metadata, not a production fixture',
                'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),
                'a':e['a'],'b':e['b'],'tour':'atp',
                'context':{'surface':'Hard','best_of':3,'final_tiebreak_points':7,'indoor':False,
                           'format':'expanded_atp_singles','competition':competition}}

    def test_qualifying_cannot_silently_become_a_main_draw(self):
        with self.assertRaisesRegex(ValueError,'Qualifying'):
            fixture_record(self.detail,self.review('main_tour'),True)
        record=fixture_record(self.detail,self.review(),True)
        self.assertEqual(record['context']['competition'],'challenger_qualifying')
        self.assertEqual(record['markets'][0]['market_type'],'moneyline')

    def test_category_type_aliases_are_accepted_and_conflicts_rejected(self):
        row=self.detail['outcomes'][0];row['marketSportsType']=row.pop('sportsMarketType')
        self.assertEqual(detail_event(self.detail)['markets'][0]['sportsMarketType'],'moneyline')
        row['sportsMarketType']='tennis_set_totals'
        with self.assertRaisesRegex(ValueError,'Conflicting'):detail_event(self.detail)

    def test_numeric_asset_ids_and_conflicting_start_fields_fail(self):
        self.detail['outcomes'][0]['yesAssetId']=123456
        with self.assertRaises(ValueError):detail_event(self.detail)
        self.setUp();self.detail['matchStartTime']='1792990800000'
        with self.assertRaisesRegex(ValueError,'Conflicting'):detail_event(self.detail)

    def test_import_reports_missing_context_instead_of_guessing(self):
        result=build([self.detail],{'fixtures':{}})
        self.assertFalse(result['fixtures']);self.assertEqual(len(result['import_errors']),1)


class ExactScoreMappingTests(unittest.TestCase):
    def setUp(self):
        self.mapping={'a':{'poly_name':'Jannik Sinner'},'b':{'poly_name':'Carlos Alcaraz'}}
        self.market={'sportsMarketType':'tennis_exact_score','outcomes':['No','Yes'],
                     'clobTokenIds':['12','13'],'question':'Will Carlos Alcaraz win 2-0?',
                     'description':'Explicit binary final set score contract, synthetic test.'}

    def test_named_score_is_oriented_to_a_and_yes_no_order_preserved(self):
        result=compile_market(self.market,self.mapping)
        self.assertEqual(result['spec']['score'],'0-2');self.assertEqual(result['order'],[1,0])

    def test_other_and_ambiguous_scores_are_not_guessed(self):
        for title in ('Final score 2-0','Other'):
            with self.assertRaises(ValueError):compile_market({**self.market,'question':title},self.mapping)

    def test_not_completed_branch_is_explicit(self):
        result=compile_market({**self.market,'question':'Not Completed'},self.mapping)
        self.assertEqual(result['spec']['score'],'Not Completed')


class ForegateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.engine=Engine()

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'fixtures.json'
        self.records=demo_fixtures()
        self.service=ForegateService(self.engine,index=self.path)
        self.save()

    def save(self):
        self.path.write_text(json.dumps({'schema':1,'fixtures':self.records,'categories':{'30157':'atp','test-wta':'wta'}}))

    def params(self,tour='atp',**extra):
        r=self.records['demo-'+tour]
        return {'type':'tennis','tour':tour,'eventSlug':'demo-'+tour,'a':r['a'],'b':r['b'],**extra}

    def test_both_tours_return_every_platform_family_from_one_distribution(self):
        for tour in ('atp','wta'):
            with patch.object(self.engine,'score_distribution',wraps=self.engine.score_distribution) as calculate:
                result=self.service.predict(self.params(tour))
            self.assertTrue(result['ready']);self.assertFalse(result['contract_ready'])
            self.assertEqual(set(result['platform_markets']),set(KINDS));self.assertEqual(calculate.call_count,1)
            self.assertAlmostEqual(result['platform_markets']['moneyline']['home']+result['platform_markets']['moneyline']['away'],1)

    def test_exact_lines_periods_and_unreached_mass_are_not_collapsed(self):
        r=self.service.predict(self.params())
        rows=r['platform_markets']['tennis_match_totals']
        self.assertEqual([x['line'] for x in rows],[20.5,21.5,22.5,23.5,24.5])
        self.assertGreater(rows[0]['probabilities'][0],rows[-1]['probabilities'][0])
        later=next(x for x in r['platform_markets']['tennis_set_winner'] if x['set_number']==3)
        self.assertGreater(later['period_not_reached_probability'],0)
        self.assertAlmostEqual(sum(p for _,p in later['pairs'])+later['period_not_reached_probability'],1)

    def test_missing_stale_started_or_unknown_context_never_returns_guessed_odds(self):
        for change in ({'context':None},{'checked_at':'2000-01-01T00:00:00Z'},
                       {'startTime':'2000-01-01T00:00:00Z'},{'status':'LIVE'},
                       {'context':{**self.records['demo-atp']['context'],'competition':'challenger_qualifying'}}):
            old=copy.deepcopy(self.records['demo-atp']);self.records['demo-atp'].update(change);self.save()
            r=self.service.predict(self.params());self.assertFalse(r['ready']);self.assertEqual(r['platform_markets'],{})
            self.records['demo-atp']=old
        self.save();r=self.service.predict(self.params(eventSlug='unknown',mode='fixture'))
        self.assertFalse(r['ready'])

    def test_wrong_players_tour_category_or_context_cannot_override_index(self):
        for change in ({'a':'Novak Djokovic'},{'tour':'wta'},{'categoryId':'test-wta'},
                       {'surface':'Clay'},{'best_of':'5'},{'categoryId':'unverified'}):
            result=self.service.predict({**self.params(),**change});self.assertFalse(result['ready'])

    def test_reverse_players_preserve_binding_to_foregate_option_ids(self):
        record=self.records['demo-atp'];record['markets']=[{'id':'987','market_type':'moneyline'}]
        record['bindings']={'987':{'order':[0,1],'options':[{'optionId':'11','title':record['a'],'assetId':'123'},
                                                          {'optionId':'12','title':record['b'],'assetId':'456'}]}}
        self.save();first=self.service.predict(self.params());reverse=self.service.predict(self.params(a=record['b'],b=record['a']))
        self.assertTrue(reverse['ready'])
        for a,b in zip(first['market_results'][0]['foregate_outcomes'],reverse['market_results'][0]['foregate_outcomes']):
            self.assertEqual(a['optionId'],b['optionId']);self.assertAlmostEqual(a['probability'],b['probability'],7)

    def test_requested_lines_do_not_inherit_unrelated_fixture_option_bindings(self):
        r=self.records['demo-atp'];r['markets']=[{'id':'1','market_type':'tennis_match_totals','line':21.5}]
        r['bindings']={'1':{'order':[0,1],'options':[{'optionId':'12'},{'optionId':'13'}]}};self.save()
        q=self.service.predict(self.params(markets=json.dumps([{'id':'1','market_type':'tennis_match_totals','line':22.5}])))
        self.assertEqual(q['market_results'][0]['line'],22.5)
        self.assertNotIn('foregate_outcomes',q['market_results'][0])

    def test_partial_result_preserves_the_exact_import_failure(self):
        r=self.records['demo-atp'];r['markets']=[{'id':'1','market_type':'moneyline'},
                                               {'id':'2','market_type':'unmapped_contract'}]
        r['import_issues']=[{'outcomeId':'2','reason':'Missing explicit set number'}];self.save()
        result=self.service.predict(self.params())
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['unavailable'][0]['request_id'],'2')
        self.assertEqual(result['unavailable'][0]['reason'],'Missing explicit set number')

    def test_languages_and_missing_expanded_snapshot(self):
        texts=[]
        for lang in ('zh','en','vi'):
            r=self.service.predict(self.params(lang=lang));self.assertTrue(r['ready']);texts.append(r['reasons']['moneyline'][0])
        self.assertEqual(len(set(texts)),3)
        self.records['demo-atp']['context'].update(competition='atp_qualifying',format='expanded_atp_singles');self.save()
        r=self.service.predict(self.params());self.assertFalse(r['ready']);self.assertIn('expanded',r['unavailable'][0]['reason'])

    def test_only_reviewed_player_aliases_can_resolve_to_existing_ids(self):
        self.assertEqual(self.engine.resolve('atp','Dominic Stephan Stricker'),'S0LA')
        self.assertEqual(self.engine.resolve('atp','Daniel Merida Aguilar'),'M0N7')
        self.assertEqual(self.engine.resolve('atp','Tomas Etcheverry'),'EA24')
        with self.assertRaises(ValueError):self.engine.resolve('atp','Etcheverry')

    def test_http_get_cors_demo_and_legacy_predict(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.engine,self.service,demo=True))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        local=urllib.request.build_opener(urllib.request.ProxyHandler({}));base=f'http://127.0.0.1:{server.server_port}'
        try:
            for route in ('/predict?'+urlencode(self.params()),'/predict?tour=atp&a=S0AG&b=A0E2&surface=Hard'):
                with local.open(base+route) as response:
                    self.assertEqual(response.headers['Access-Control-Allow-Origin'],'*');r=json.load(response)
                    self.assertTrue(r.get('ready',False) or 'probability_a' in r)
            with local.open(base+'/demo') as response:self.assertIn(b'Tennis',response.read())
            with local.open(urllib.request.Request(base+'/predict',method='OPTIONS')) as response:self.assertEqual(response.status,204)
        finally:server.shutdown();server.server_close();thread.join()
