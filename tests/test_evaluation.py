import unittest
from core.evaluation import MarketEvaluation
from backtest_score import observed,outcomes
from core.scoring import distribution


class EvaluationTests(unittest.TestCase):
    def test_formats_cohorts_and_baselines_do_not_mix(self):
        e=MarketEvaluation();scores={'2-0':.6,'0-2':.4}
        for year in (2024,2025):
            for bo,competition,y in [(3,'main_tour',0),(5,'main_tour',1),(3,'atp_qualifying',1)]:
                e.add(year,competition,bo,[('total',y,.7)],scores,'2-0')
        d=e.summary()
        self.assertEqual(d['by_best_of']['3']['total']['model']['n'],2)
        self.assertEqual(d['by_best_of']['5']['total']['model']['n'],1)
        q=d['by_competition_best_of']['atp_qualifying/3']['total']
        self.assertEqual(q['model']['accuracy'],1)
        self.assertAlmostEqual(q['2024_empirical_baseline']['brier'],1/9)
        self.assertEqual(q['classification_strategy'],'single_outcome_choice')
        self.assertEqual(d['exact_score_top_pick']['all']['accuracy'],1)
        with self.assertRaises(ValueError):e.add(2024,'main_tour',3,[],scores,'2-0')

    def test_each_handicap_side_and_sign_has_its_own_outcome(self):
        d=distribution(.63,.59,.7)
        actual={'sets':[(6,4),(3,6),(6,4)],'score':'2-1','games':29,'margin':1}
        rows={k:(y,p) for k,y,p in outcomes(d,actual,3)}
        a=rows['tennis_set_handicap:{"line": -1.5}']
        b=rows['tennis_set_handicap:{"line": -1.5, "selection": "b"}']
        self.assertEqual((a[0],b[0]),(0,0))
        for kind in ('tennis_game_handicap','tennis_set_handicap'):
            a=rows[kind+':{"line": 1.5}']
            b=rows[kind+':{"line": -1.5, "selection": "b"}']
            self.assertEqual(a[0]+b[0],1)
            self.assertAlmostEqual(a[1]+b[1],1)
