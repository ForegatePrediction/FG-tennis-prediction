import copy
import json
import math
import unittest
from core.coverage import coverage
from core.data import ROOT
from core.inference import Engine
from core.scoring import distribution,hold,quote,set_kernel,tiebreak
from core.tournament import knockout
from backtest_score import observed


class ScoreTests(unittest.TestCase):
    def test_fair_analytic_case_and_terminal_conservation(self):
        self.assertAlmostEqual(hold(.5),.5)
        for target in (7,10):
            self.assertAlmostEqual(tiebreak(.5,.5,0,target),.5)
            self.assertAlmostEqual(sum(set_kernel(.65,.6,0,target).values()),1)
        d=distribution(.5,.5,.5,5,10)
        expected={'3-0':.125,'3-1':.1875,'3-2':.1875,'0-3':.125,'1-3':.1875,'2-3':.1875}
        for score,p in expected.items():self.assertAlmostEqual(d['scores'][score],p)

    def test_swapping_players_reverses_joint_scores_and_margins(self):
        a=distribution(.67,.59,.79,5,10);b=distribution(.59,.67,.21,5,10)
        for score,p in a['scores'].items():self.assertAlmostEqual(p,b['scores'][score[::-1]])
        for (margin,won),p in a['margins'].items():self.assertAlmostEqual(p,b['margins'][-margin,not won])
        for games in range(1,70):
            self.assertAlmostEqual(sum(p for (g,_),p in a['totals'].items() if g==games),sum(p for (g,_),p in b['totals'].items() if g==games))

    def test_all_marginals_share_calibrated_winner(self):
        d=distribution(.68,.57,.82,3,7)
        self.assertAlmostEqual(sum(v for k,v in d['scores'].items() if k[0]=='2'),.82)
        for name in ('totals','margins'):
            self.assertAlmostEqual(sum(d[name].values()),1)
            self.assertAlmostEqual(sum(v for (_,won),v in d[name].items() if won),.82)
        self.assertAlmostEqual(quote(d,'tennis_set_totals',2.5)['probabilities'][0],d['periods'][3]['a']+d['periods'][3]['b'])

    def test_unreached_period_not_losing_and_cannot_be_silently_dropped(self):
        d=distribution(.5,.5,.5,3,7);q=quote(d,'tennis_set_winner',set_number=3)
        self.assertAlmostEqual(q['period_not_reached_probability'],.5)
        self.assertAlmostEqual(sum(q['probabilities']),.5)
        self.assertEqual(q['probabilities_given_period_reached'],[.5,.5])
        self.assertFalse(q['contract_ready'])

    def test_score_parser_preserves_loser_first_set_and_rejects_early_end(self):
        m={'best_of':3,'y':0,'raw':{'score':'6-4 3-6 7-6(4)'}}
        actual=observed(m);self.assertEqual(actual['score'],'1-2');self.assertEqual(actual['sets'][0],(4,6))
        m['raw']['score']='6-0 6-0 0-6';self.assertIsNone(observed(m))

    def test_missing_or_unsupported_settlement_parameters_rejected(self):
        d=distribution(.63,.62,.55)
        for kind,kw in [('tennis_completed_match',{}),('tennis_exact_score',{'score':'Not Completed'}),
                        ('tennis_set_winner',{'set_number':4}),('tennis_game_handicap',{'line':3}),
                        ('tennis_match_totals',{'line':float('nan')})]:
            with self.assertRaises(ValueError):quote(d,kind,**kw)
        with self.assertRaises(ValueError):distribution(.6,.6,.5,3,12)

    def test_handicap_sign_is_for_selected_player(self):
        d=distribution(.67,.59,.79,3,7)
        a=quote(d,'tennis_game_handicap',-3.5,selection='a')
        b=quote(d,'tennis_game_handicap',3.5,selection='b')
        self.assertAlmostEqual(a['probabilities'][0]+b['probabilities'][0],1)


class TournamentTests(unittest.TestCase):
    def draw(self):return [{'id':str(i),'seed':i+1,'entry':'Q' if i==0 else 'WC' if i==1 else 'DA','country':'X' if i<2 else 'Y'} for i in range(4)]

    def test_exact_fair_draw_and_path_exclusivity(self):
        r=knockout(self.draw(),lambda a,b:.5)
        self.assertEqual(r['winner_probabilities'],dict.fromkeys(('0','1','2','3'),.25))
        self.assertAlmostEqual(sum(x['probability'] for x in r['finalist_pair_probabilities']),1)
        self.assertFalse(any({x['a'],x['b']}=={'0','1'} for x in r['finalist_pair_probabilities']))
        self.assertEqual(r['any_qualifier_or_wildcard_reaches_round']['2'],{'Q':.5,'WC':.5})
        self.assertEqual(r['any_top10_seed_loses_opening_round_probability'],1)
        self.assertEqual(r['winner_country_probabilities'],{'X':.5,'Y':.5})

    def test_bye_is_not_a_played_loss_and_missing_metadata_not_zero(self):
        d=self.draw();d[1]=None;d[0]['country']=None;d[0]['entry']='unknown';d[2]['seed']=None;d[3]['seed']=None
        r=knockout(d,lambda a,b:.5)
        self.assertAlmostEqual(r['winner_probabilities']['0'],.5)
        self.assertEqual(r['any_top10_seed_loses_opening_round_probability'],0)
        self.assertIsNone(r['winner_country_probabilities'])
        self.assertIsNone(r['any_qualifier_or_wildcard_reaches_round']['2']['Q'])

    def test_duplicate_player_seed_and_invalid_probability_rejected(self):
        for d in ([self.draw()[0]]*4,self.draw()[:3]):
            with self.assertRaises(ValueError):knockout(d,lambda a,b:.5)
        with self.assertRaises(ValueError):knockout(self.draw(),lambda a,b:float('nan'))

    def test_target_wins_and_seed_defeat_are_path_events_not_champion_probability(self):
        result=knockout(self.draw(),lambda a,b:.5,any_win_targets=['0','2'],top_seed_max=1)
        self.assertAlmostEqual(result['any_selected_player_wins_a_played_match_probability'],.75)
        self.assertAlmostEqual(result['defeat_top_seed_probabilities']['1'],.5)
        self.assertAlmostEqual(result['defeat_top_seed_probabilities']['2'],.125)
        self.assertEqual(result['defeat_top_seed_probabilities']['0'],0)
        same_pair=knockout(self.draw(),lambda a,b:.5,any_win_targets=['0','1'])
        self.assertEqual(same_pair['any_selected_player_wins_a_played_match_probability'],1)

    def test_bye_does_not_trigger_any_match_win(self):
        draw=self.draw();draw[1]=None
        result=knockout(draw,lambda a,b:.5,any_win_targets=['0'])
        self.assertAlmostEqual(result['any_selected_player_wins_a_played_match_probability'],.5)

    def test_matrix_covers_every_observed_family_once(self):
        c=coverage();names=[r['family'] for r in c['families']]
        self.assertEqual(len(names),len(set(names)));self.assertEqual(len(names),38)
        s=json.loads((ROOT/'reports/poly-tennis-market-types.json').read_text())
        self.assertEqual(set(names),set(s['research_family_counts']))
        self.assertEqual(c['score_families']+c['draw_families']+c.get('baseline_families',0)+c['unavailable_families'],38)


class ScoreInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.engine=Engine()

    def test_existing_winner_unchanged_and_probability_matches(self):
        e=self.engine;base=e.predict('atp','S0AG','A0E2','Hard')
        q=e.predict_market('atp','S0AG','A0E2','Hard','moneyline',final_tiebreak_points=7)
        self.assertAlmostEqual(q['probabilities'][0],base['probability_a'])
        with self.assertRaises(ValueError):e.score_distribution('atp','S0AG','A0E2','Hard')

    def test_snapshot_config_mismatch_fails_closed(self):
        engine=copy.copy(self.engine);engine.count_config={'base_model_sha256':'not-the-snapshot'}
        with self.assertRaisesRegex(ValueError,'does not match'):engine.score_distribution('atp','S0AG','A0E2','Hard',final_tiebreak_points=7)

    def test_unused_legacy_calibration_does_not_override_valid_count_model(self):
        engine=copy.copy(self.engine);engine.score_config={'base_model_sha256':'not-the-snapshot'}
        _,context=engine.score_distribution('atp','S0AG','A0E2','Hard',final_tiebreak_points=7)
        self.assertEqual(context['score_model_status'],'experimental')
        self.assertTrue(engine.health()['score_configs_match_snapshot'])


if __name__=='__main__':unittest.main()
