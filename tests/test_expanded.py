import copy
import datetime as dt
import json
import unittest
from core.data import ROOT
from core.inference import Engine


class ExpandedResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=ROOT/'models/expanded/current.json'
        if not path.exists() or not (path.parent/'score-config.json').exists():raise unittest.SkipTest('Build and backtest separate expanded snapshot first')
        cls.engine=Engine(path)

    def match(self):
        return {'tour':'atp','a':'L0I5','b':'S0JV','surface':'Hard','best_of':3,'final_tiebreak_points':7,
                'format':'expanded_atp_singles','competition':'challenger_main_draw'}

    def test_players_are_resolved_and_low_sample_evidence_is_visible(self):
        result=self.engine.predict_markets(self.match())
        self.assertEqual(result['summary']['predicted'],16)
        self.assertEqual(result['base']['model_scope'],'expanded_atp')
        self.assertTrue(any('limited evidence' in x for x in result['base']['warnings']))
        self.assertEqual(self.engine.score_config['base_model_sha256'],self.engine.snapshot_sha256)

    def test_validation_gate_uses_competition_not_mixed_sample(self):
        result=self.engine.predict_markets({**self.match(),'markets':[{'market_type':'tennis_match_totals','line':22.5}]})
        row=result['markets'][0]
        validation=self.engine.count_config['tours']['atp']['by_competition_best_of']['challenger_main_draw/3']['tennis_match_totals:{"line": 22.5}']
        self.assertEqual(row['market_validation'],validation)
        self.assertEqual(row['validation_cohort'],'challenger_main_draw')
        self.assertEqual(row['validation_best_of'],3)
        self.assertEqual(row['validation_gate'],'research_only_better_than_frequency_baseline')

    def hypothetical(self,source,competition):
        event=json.loads((ROOT/'tests/fixtures/poly-screenshot-event.json').read_text())
        event.update(id='hypothetical-expanded-test',title='Hypothetical: Mitsuki Wei Kang Leong vs Qian Sun',closed=False,
                     startTime=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=1)).isoformat(),eventMetadata={'tennisFixtureSource':source})
        return {'event':event,'match':{**self.match(),'competition':competition},'mapping_verified':True,'source':'Synthetic test only, not an actual event',
                'player_mapping':{'a':{'poly_name':'Mitsuki Wei Kang Leong'},'b':{'poly_name':'Qian Sun'}}}

    def test_challenger_main_draw_hypothetical_can_compute_but_qualifying_cannot(self):
        a=self.engine.predict_poly_event(self.hypothetical('optic-challenger','challenger_main_draw'))
        b=self.engine.predict_poly_event(self.hypothetical('optic-challenger-qualifying','challenger_qualifying'))
        self.assertEqual(a['summary']['predicted'],16)
        self.assertEqual(b['summary']['predicted'],1)
        self.assertEqual(b['summary']['mapped'],16)

    def test_scope_cannot_be_overridden_by_forged_competition(self):
        result=self.engine.predict_poly_event(self.hypothetical('optic-challenger-qualifying','challenger_main_draw'))
        self.assertEqual(result['summary']['predicted'],1)
        self.assertTrue(any('contradicts' in x for x in result['blockers']))
