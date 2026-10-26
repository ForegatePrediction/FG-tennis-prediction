"""Training-only market evaluation, with frozen baselines per format/cohort."""
import collections
import math
import numpy as np
from .linear import metrics


class MarketEvaluation:
    def __init__(self):
        self.priors = collections.defaultdict(lambda: [0, 0])
        self.score_priors = collections.defaultdict(collections.Counter)
        self.rows = collections.defaultdict(lambda: collections.defaultdict(list))
        self.exact = collections.defaultdict(list)
        self.baseline_frozen = False

    def add(self, year, competition, best_of, values, scores, actual_score):
        if year < 2024:return
        if year == 2024 and self.baseline_frozen:raise ValueError('Calibration rows must precede test rows')
        if year > 2024:self.baseline_frozen = True
        groups = [('all', ('all', best_of)), (f'format/{best_of}', ('all', best_of)),
                  (f'competition/{competition}', (competition, best_of)),
                  (f'competition-format/{competition}/{best_of}', (competition, best_of))]
        for key, y, p in values:
            if not math.isfinite(p) or not 0 <= p <= 1 or y not in (0, 1):
                raise ValueError('Finite probabilities and binary labels required')
            if year == 2024:
                for cohort in ('all', competition):
                    prior = self.priors[cohort, best_of, key];prior[0] += y;prior[1] += 1
            else:
                for label, (cohort, bo) in groups:
                    yes, n = self.priors[cohort, bo, key]
                    self.rows[label][key].append((y, p, (yes + 1) / (n + 2), n))
        if year == 2024:
            for cohort in ('all', competition):self.score_priors[cohort, best_of][actual_score] += 1
        else:
            picked = max(scores, key=scores.get)
            for label, (cohort, bo) in groups:
                counts = self.score_priors[cohort, bo]
                baseline_pick = counts.most_common(1)[0][0] if counts else None
                self.exact[label].append((int(picked == actual_score), int(baseline_pick == actual_score),
                                          -math.log(max(1e-9, scores[actual_score]))))

    def summary(self):
        tables = {}
        for label, values in self.rows.items():
            table = {}
            for key, rows in values.items():
                data = np.asarray(rows);y, p, b = data[:, 0], data[:, 1], data[:, 2]
                model, baseline = metrics(y, p), metrics(y, b)
                table[key] = {'model': model, '2024_empirical_baseline': baseline,
                              'baseline_minimum_sample_n': int(data[:, 3].min()),
                              'model_positive_prediction_rate': float(np.mean(p >= .5)),
                              'observed_positive_rate': float(y.mean()),
                              'accuracy_gain_over_baseline': model['accuracy'] - baseline['accuracy'],
                              'log_loss_gain_over_baseline': baseline['log_loss'] - model['log_loss'],
                              'brier_gain_over_baseline': baseline['brier'] - model['brier'],
                              'test_contains_both_outcomes': bool(y.min() != y.max()),
                              'classification_strategy': 'single_outcome_choice' if np.all(p >= .5) or np.all(p < .5) else 'match_dependent_choices',
                              'evaluation_status': 'retrospective_requires_forward_validation'}
            tables[label] = table
        exact = {label: {'n': len(rows), 'accuracy': float(np.mean([r[0] for r in rows])),
                         '2024_most_common_score_accuracy': float(np.mean([r[1] for r in rows])),
                         'multiclass_log_loss': float(np.mean([r[2] for r in rows]))}
                 for label, rows in self.exact.items()}
        def split(prefix):return {k[len(prefix):]: v for k, v in tables.items() if k.startswith(prefix)}
        return {'markets': tables['all'], 'by_best_of': split('format/'),
                'by_competition': split('competition/'),
                'by_competition_best_of': split('competition-format/'),
                'exact_score_top_pick': exact}
