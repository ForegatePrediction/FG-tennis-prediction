import unittest
from core.counts import predict,features
from core.features import FEATURES
from core.scoring import distribution,quote


class LearnedCountsTests(unittest.TestCase):
    def test_period_kernels_change_period_totals_without_breaking_joint_mass(self):
        kernels={1:{(6,0):.5,(0,6):.5},2:{(6,4):.5,(4,6):.5},3:{(7,6):.5,(6,7):.5}}
        d=distribution(.63,.63,.5,3,7,{'2-0':.25,'2-1':.25,'0-2':.25,'1-2':.25},
                       set_outcomes_by_period=kernels)
        self.assertAlmostEqual(quote(d,'tennis_first_set_totals',8.5)['probabilities'][0],0)
        self.assertAlmostEqual(quote(d,'tennis_set_games_totals',8.5,2)['probabilities'][0],1)
        self.assertAlmostEqual(quote(d,'tennis_set_games_totals',8.5,3)['period_reached_probability'],.5)
        for name in ('totals','margins'):
            self.assertAlmostEqual(sum(d[name].values()),1)
            self.assertAlmostEqual(sum(p for (_,winner),p in d[name].items() if winner),.5)
        with self.assertRaises(ValueError):distribution(.63,.63,.5,set_outcomes_by_period={1:kernels[1]})

    def test_terminal_tilt_preserves_all_mass_and_match_probability(self):
        scores={'2-0':.5,'2-1':.2,'0-2':.1,'1-2':.2}
        d=distribution(.65,.6,.7,3,7,score_probabilities=scores)
        for key,p in scores.items():self.assertAlmostEqual(d['scores'][key],p)
        self.assertAlmostEqual(quote(d,'tennis_set_totals',2.5)['probabilities'][0],.4)
        self.assertAlmostEqual(d['periods'][3]['a']+d['periods'][3]['b'],.4)
        for table in ('totals','margins'):
            self.assertAlmostEqual(sum(d[table].values()),1)
            self.assertAlmostEqual(sum(p for (_,won),p in d[table].items() if won),.7)

    def test_supplied_terminal_scores_must_match_winner_and_normalize(self):
        for scores in ({'2-0':1.},{'2-0':.1,'2-1':.1,'0-2':.4,'1-2':.4}):
            with self.assertRaises(ValueError):distribution(.6,.6,.7,score_probabilities=scores)

    def test_empirical_kernel_and_length_model_exchange_symmetry(self):
        v=[0.]*len(FEATURES);v[FEATURES.index('elo')]=.3;v[FEATURES.index('rank')]=.2
        width=len(features(v,.65,.61,'Hard'))
        model={'scale':[1.]*width,'weights':[.2,.3]+[0.]*(width-2),'temperature':1.}
        config={'length_models':{'3':{'3':model}},'kernel_global':[10,20,30,50,60,50,40],
                'kernel_surfaces':{},'kernel_cells':{},'kernel_prior_strength':100}
        a=predict(config,v,.65,.61,'Hard',3,.72,7)
        b=predict(config,[-x for x in v],.61,.65,'Hard',3,.28,7)
        for score,p in a['scores'].items():self.assertAlmostEqual(p,b['scores'][score[::-1]])
        for (margin,won),p in a['margins'].items():self.assertAlmostEqual(p,b['margins'][-margin,not won])
        qs=[quote(a,'tennis_match_totals',line)['probabilities'][0] for line in (19.5,20.5,21.5,22.5,23.5)]
        self.assertEqual(qs,sorted(qs,reverse=True))
