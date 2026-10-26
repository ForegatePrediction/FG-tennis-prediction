import copy
import datetime as dt
import json
from unittest import TestCase
from unittest.mock import patch
from core.data import ROOT
from core.inference import Engine
from core.markets import compile_market,screenshot_markets
from core.scoring import SCORE_TYPES


class BatchMarketTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=Engine()
        cls.event=json.loads((ROOT/'tests/fixtures/poly-screenshot-event.json').read_text())
        cls.mapping={'a':{'poly_name':'Mitsuki Wei Kang Leong'},'b':{'poly_name':'Qian Sun'}}

    def match(self):
        return {'tour':'atp','a':'S0AG','b':'A0E2','surface':'Hard','best_of':3,
                'final_tiebreak_points':7,'format':'main_tour_singles','competition':'main_tour'}

    def hypothetical(self):
        text=json.dumps(self.event).replace('Mitsuki Wei Kang Leong','Jannik Sinner').replace('Qian Sun','Carlos Alcaraz')
        event=json.loads(text)
        event.update(id='hypothetical-test',title='Hypothetical: Jannik Sinner vs Carlos Alcaraz',closed=False,live=False,ended=False,
                     startTime=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=1)).isoformat(),eventMetadata={})
        return {'event':event,'match':self.match(),'mapping_verified':True,'source':'Synthetic test only; not an actual event',
                'player_mapping':{'a':{'poly_name':'Jannik Sinner'},'b':{'poly_name':'Carlos Alcaraz'}}}

    def test_all_screenshot_lines_and_sides_share_one_distribution(self):
        with patch.object(self.engine,'score_distribution',wraps=self.engine.score_distribution) as calculate:
            result=self.engine.predict_markets(self.match())
            self.assertEqual(calculate.call_count,1)
        self.assertEqual(result['summary'],{'requested':16,'predicted':16,'unavailable':0})
        self.assertFalse(result['contract_ready'])
        rows=result['markets'];money=next(r for r in rows if r['sports_market_type']=='moneyline')
        self.assertEqual(money['probabilities'][0],result['base']['probability_a'])
        totals=[r for r in rows if r['sports_market_type']=='tennis_match_totals']
        self.assertGreater(totals[0]['probabilities'][0],totals[1]['probabilities'][0])
        self.assertGreater(totals[1]['probabilities'][0],totals[2]['probabilities'][0])

    def test_all_eleven_score_families_can_be_requested(self):
        specs=[{'market_type':kind,'line':2.5,'set_number':1,'selection':'a','score':'2-0'} for kind in SCORE_TYPES]
        result=self.engine.predict_markets({**self.match(),'markets':specs})
        self.assertEqual(result['summary']['predicted'],11)

    def test_bad_market_does_not_discard_valid_siblings(self):
        specs=[{'market_type':'tennis_match_totals','line':22}, {'market_type':'moneyline'},
               {'market_type':'unknown'}, {'market_type':'tennis_set_winner','set_number':3}]
        result=self.engine.predict_markets({**self.match(),'markets':specs})
        self.assertEqual(result['summary']['predicted'],2)
        late=result['markets'][-1]
        self.assertAlmostEqual(sum(late['probabilities'])+late['period_not_reached_probability'],1)

    def test_actual_sixteen_contracts_map_without_guessing(self):
        bound=[compile_market(m,self.mapping) for m in self.event['markets']]
        self.assertEqual(len(bound),16)
        self.assertEqual(bound[-1]['spec']['selection'],'b')
        self.assertEqual(bound[-1]['spec']['line'],-1.5)
        self.assertEqual(bound[-2]['spec']['selection'],'a')

    def test_reverse_handicap_outcome_and_token_binding(self):
        payload=self.hypothetical();result=self.engine.predict_poly_event(payload)
        self.assertEqual(result['summary'],{'requested':16,'mapped':16,'predicted':16,'unavailable':0})
        b=result['markets'][-1]
        self.assertEqual(b['outcome_predictions'][0]['outcome'],'Carlos Alcaraz')
        self.assertEqual(b['outcome_predictions'][0]['token_id'],json.loads(payload['event']['markets'][-1]['clobTokenIds'])[0])
        q=self.engine.predict_market('atp','S0AG','A0E2','Hard','tennis_set_handicap',-1.5,selection='b',final_tiebreak_points=7,
                                     date=result['context']['base']['date'])
        self.assertEqual(b['outcome_predictions'][0]['conditional_probability'],q['probabilities'][0])
        self.assertFalse(b['contract_ready'])

    def test_under_first_and_prices_are_not_model_inputs(self):
        payload=self.hypothetical();market=next(m for m in payload['event']['markets'] if m['sportsMarketType']=='tennis_match_totals')
        market['outcomes']='["Under", "Over"]';market['clobTokenIds']='["12", "13"]'
        first=self.engine.predict_poly_event(payload)
        for m in payload['event']['markets']:m['outcomePrices']='not even JSON'
        second=self.engine.predict_poly_event(payload)
        self.assertEqual(first,second)
        row=next(m for m in first['markets'] if m['market_id']==str(market['id']))
        self.assertEqual(row['outcome_predictions'][0]['conditional_probability'],row['probabilities'][1])

    def test_bad_contract_mapping_isolated_from_siblings(self):
        payload=self.hypothetical();payload['event']['markets'][-1]['clobTokenIds']='["12"]'
        result=self.engine.predict_poly_event(payload)
        self.assertEqual(result['summary']['predicted'],15)
        self.assertEqual(result['summary']['mapped'],15)
        self.assertIsNone(result['markets'][-1]['outcome_predictions'])

    def test_missing_players_and_challenger_scope_do_not_receive_fake_odds(self):
        payload={'event':self.event,'player_mapping':self.mapping,'mapping_verified':True,'source':'Archived Gamma event',
                 'match':{**self.match(),'a':'L0I5','b':'S0JV'}}
        result=self.engine.predict_poly_event(payload)
        self.assertEqual(result['summary']['predicted'],0)
        self.assertTrue(any('outside validated' in s for s in result['blockers']))
        self.assertTrue(any('Missing internal' in s for s in result['blockers']))
        self.assertTrue(any('already started' in s for s in result['blockers']))

    def test_cannot_override_event_scope_with_main_tour_string(self):
        payload=self.hypothetical();payload['event']['eventMetadata']={'tennisFixtureSource':'optic-challenger-qualifying'}
        result=self.engine.predict_poly_event(payload)
        self.assertEqual(result['summary']['predicted'],1)
        self.assertTrue(all(r['sports_market_type']=='tennis_completed_match' or r['status']=='unavailable' for r in result['markets']))

    def test_identity_aliases_must_include_internal_name(self):
        payload=self.hypothetical();payload['match']['a']='F324'
        result=self.engine.predict_poly_event(payload)
        self.assertEqual(result['summary']['predicted'],1)
        self.assertTrue(all(r['sports_market_type']=='tennis_completed_match' or r['status']=='unavailable' for r in result['markets']))

    def test_conflicting_lines_sets_names_and_tokens_rejected(self):
        base=next(m for m in self.event['markets'] if m['sportsMarketType']=='tennis_match_totals')
        for change in ({'line':77.5},{'clobTokenIds':'["12","12"]'},{'description':''}):
            with self.assertRaises(ValueError):compile_market({**base,**change},self.mapping)
        base=next(m for m in self.event['markets'] if m['sportsMarketType']=='tennis_set_winner')
        with self.assertRaises(ValueError):compile_market({**base,'line':3},self.mapping)
        mapping=copy.deepcopy(self.mapping);mapping['b']['aliases']=['Mitsuki Wei Kang Leong']
        with self.assertRaises(ValueError):compile_market(base,mapping)

    def test_outright_binary_contract_cannot_be_match_winner(self):
        m=copy.deepcopy(self.event['markets'][0]);m['outcomes']='["Yes","No"]'
        with self.assertRaises(ValueError):compile_market(m,self.mapping)
