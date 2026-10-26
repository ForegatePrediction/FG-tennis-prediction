#!/usr/bin/env python3
"""Re-score frozen V2 models by format; never fit or change a model."""
import collections
import argparse
import datetime as dt
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

from backtest_score import observed, outcomes
from core.counts import predict
from core.data import ROOT, atomic_json, load_tour
from core.features import FEATURES, build_features
from core.linear import metrics


def evaluate(expanded=False):
    path = ROOT / ('models/expanded/current.json' if expanded else 'models/current.json')
    snapshot = json.loads(path.read_text())
    bundle = json.loads((path.parent / 'count-config.json').read_text())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if bundle['base_model_sha256'] != digest:
        raise ValueError('Count model and winner snapshot differ')
    source = json.loads((ROOT / 'data/source-manifest.json').read_text())
    manifests = [(source, ROOT / 'data/raw', False)]
    if expanded:
        extra = json.loads((ROOT / 'data/expanded/source-manifest.json').read_text())
        manifests.append((extra, ROOT / 'data/expanded', True))
    result = {}
    for tour, model in snapshot['tours'].items():
        print(tour, 'expanded' if expanded else 'main', 'replaying frozen model', flush=True)
        for manifest, folder, is_extra in manifests:
            key = 'expanded_manifest_sha256' if is_extra else 'manifest_sha256'
            if model['data'][key] != hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest():
                raise ValueError('Source manifest differs from model')
            for item in manifest['files']:
                if not is_extra and item['tour'] != tour:
                    continue
                filename = folder / item['name'] if is_extra else folder / tour / item['name']
                if hashlib.sha256(filename.read_bytes()).hexdigest() != item['sha256']:
                    raise ValueError('Source file differs from manifest')
        matches, _ = load_tour(tour, snapshot['as_of'], scope='expanded_atp' if expanded else 'main_tour')
        vectors, meta, _ = build_features(tour, matches, snapshot['as_of'], include_score_context=True)
        config = bundle['tours'][tour]
        cols = [FEATURES.index(k) for k in model['features']]
        priors = collections.defaultdict(list)
        score_priors = collections.defaultdict(collections.Counter)
        groups = collections.defaultdict(lambda: collections.defaultdict(lambda: [[], [], []]))
        exact = collections.defaultdict(list)
        for m, v, c in zip(matches, vectors, meta):
            year = dt.date.fromordinal(m['start']).year
            if year < 2024 or (year == 2024 and dt.date.fromordinal(m['available']).year != 2024):
                continue
            actual = observed(m)
            if actual is None:
                continue
            bo = m['best_of']
            pa, pb, _ = c['serve_context']
            logit = sum(max(-8, min(8, v[i] / s)) * w / model['temperature']
                        for i, s, w in zip(cols, model['scale'], model['weights']))
            p = 1 / (1 + math.exp(-max(-35, min(35, logit))))
            dist = predict(config, v, pa, pb, m['surface'], bo, p, 10 if bo == 5 else 7)
            labels = ['all', f'best_of_{bo}', f"{m['raw']['_competition']}:best_of_{bo}"]
            for key, y, pred in outcomes(dist, actual, bo):
                if year == 2024:
                    priors[bo, key].append(y)
                else:
                    previous = priors[bo, key]
                    baseline = (sum(previous) + 1) / (len(previous) + 2)
                    for label in labels:
                        row = groups[label][key]
                        row[0].append(y); row[1].append(pred); row[2].append(baseline)
            if year == 2024:
                score_priors[bo][actual['score']] += 1
            else:
                picked = max(dist['scores'], key=dist['scores'].get)
                base_pick = score_priors[bo].most_common(1)[0][0]
                for label in labels:
                    exact[label].append((int(picked == actual['score']), int(base_pick == actual['score']),
                                         -math.log(max(1e-9, dist['scores'][actual['score']]))))
        report = {}
        for label, values in groups.items():
            report[label] = {
                'markets': {key: {'model': metrics(np.asarray(y), np.asarray(p)),
                                  '2024_frequency_baseline': metrics(np.asarray(y), np.asarray(b))}
                            for key, (y, p, b) in values.items()},
                'exact_score_top_pick': {
                    'n': len(exact[label]),
                    'accuracy': float(np.mean([r[0] for r in exact[label]])),
                    '2024_most_common_score_accuracy': float(np.mean([r[1] for r in exact[label]])),
                    'multiclass_log_loss': float(np.mean([r[2] for r in exact[label]]))}}
        old = json.loads((ROOT / f'reports/{tour}{"-expanded" if expanded else ""}-counts-backtest.json').read_text())
        for key, row in report['all']['markets'].items():
            for metric in ('n', 'accuracy', 'log_loss', 'brier'):
                if abs(row['model'][metric] - old['markets'][key]['model'][metric]) > 1e-10:
                    raise ValueError('Replay disagrees with existing backtest: ' + key)
        result[tour] = {'as_of': snapshot['as_of'], 'snapshot_sha256': digest, 'groups': report}
        print(tour, 'replay matches existing report; format splits and multiclass accuracy complete', flush=True)
    return result


def export_reports(root=ROOT,expanded=False):
    """Export the same grouping from reports already produced by a full replay."""
    root=Path(root)
    path=root/('models/expanded/current.json' if expanded else 'models/current.json')
    snapshot=json.loads(path.read_text());config=json.loads((path.parent/'count-config.json').read_text())
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if config['base_model_sha256']!=digest:raise ValueError('Validation config differs from winner snapshot')
    result={}
    for tour,cfg in config['tours'].items():
        report=json.loads((root/f'reports/{tour}{"-expanded" if expanded else ""}-counts-backtest.json').read_text())
        for config_key,report_key in [('market_validation','markets'),('by_best_of','by_best_of'),
                                      ('by_competition_best_of','by_competition_best_of')]:
            if cfg.get(config_key)!=report.get(report_key):raise ValueError('Report and active validation differ')
        tables={'all':(cfg['market_validation'],'all')}
        tables.update({f'best_of_{bo}':(values,'format/'+bo) for bo,values in cfg['by_best_of'].items()})
        tables.update({f'{key.split("/")[0]}:best_of_{key.split("/")[1]}':(values,'competition-format/'+key)
                       for key,values in cfg['by_competition_best_of'].items()})
        groups={}
        for name,(values,exact_key) in tables.items():
            groups[name]={'markets':{k:{'2024_frequency_baseline' if field=='2024_empirical_baseline' else field:value
                                       for field,value in row.items()} for k,row in values.items()},
                          'exact_score_top_pick':cfg['exact_score_top_pick'][exact_key]}
        result[tour]={'as_of':snapshot['as_of'],'snapshot_sha256':digest,'groups':groups,
                      'model_kind':cfg['model_kind'],'period_kernel_selection':report['period_kernel_selection']}
    return result


def save_from_reports(root=ROOT):
    root=Path(root)
    result={'protocol':'Already replayed frozen models; report/config/hash agreement checked. '
            'Reused 2025+ retrospective data; no independent forward or trading validation. '
            'Frequency baselines split by format, parameter, selection and competition.',
            'main':export_reports(root),'expanded':{},
            'draw_validation':{'status':'not_historically_backtested','accuracy':None}}
    if (root/'models/expanded/current.json').exists():result['expanded']=export_reports(root,True)
    if (root/'models/completion.json').exists():
        c=json.loads((root/'models/completion.json').read_text())
        result['completion']={'global':c['global'],'test':c['test'],
                              'classification_strategy':'always_predict_complete; no individual retirement detection'}
    atomic_json(root/'reports/market-accuracy-by-format.json',result)
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--from-reports',action='store_true')
    if parser.parse_args().from_reports:
        save_from_reports();print('Exported hash-checked active reports');raise SystemExit(0)
    started = time.time()
    result = {'protocol': 'Frozen V2 re-evaluation on reused 2025+ retrospective data; not a fresh holdout. '
              'Completed standard singles only; period metrics conditional on reaching that period. '
              'Binary accuracy uses p>=0.5; exact-score accuracy selects one full-match score. '
              'Baseline is frozen 2024 frequency per best_of and market parameter, including in competition slices.',
              'main': evaluate(), 'expanded': evaluate(True)}
    result['runtime_seconds'] = round(time.time() - started, 2)
    atomic_json(ROOT / 'reports/market-accuracy-by-format.json', result)
    print('Saved reports/market-accuracy-by-format.json', flush=True)
