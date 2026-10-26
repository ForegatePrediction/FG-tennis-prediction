#!/usr/bin/env python3
"""Build free data and all dependent models in isolation before publication."""
import argparse
import datetime as dt
from pathlib import Path
import shutil
import tempfile
from core.data import ROOT
from core.bundle import publish
from fetch import fetch
from train import main
from backtest_score import evaluate
from train_counts import main as train_counts


def refresh(root=ROOT,force_history=False,as_of=None,offline=False):
    root=Path(root)
    now=dt.datetime.now(dt.timezone.utc)
    as_of=as_of or (now.date()-dt.timedelta(days=1)).isoformat()
    with tempfile.TemporaryDirectory(dir=root,prefix='.refresh-') as directory:
        stage=Path(directory)
        # Copy only the small training corpus, never the large Poly archive.
        for relative in ('data/raw','data/source-manifest.json','models/completion.json'):
            source=root/relative;target=stage/relative
            if source.is_dir():shutil.copytree(source,target)
            elif source.is_file():target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        if not offline:fetch(start=2010,end=now.year,force=force_history,root=stage)
        main(as_of,root=stage)
        evaluate(root=stage)
        train_counts(root=stage)
        from core.inference import Engine
        engine=Engine(stage/'models/current.json')
        if not engine.health()['score_configs_match_snapshot']:raise ValueError('Refuse mismatched refresh bundle')
        if set(engine.snapshot['tours'])!={'atp','wta'}:raise ValueError('Both tours required')
        for tour in engine.snapshot['tours']:
            config=engine.count_config['tours'][tour]
            if config.get('validation_schema')!=2 or not config.get('by_best_of'):
                raise ValueError('Format-specific market validation required')
        from audit_market_accuracy import save_from_reports
        save_from_reports(stage)
        publish(stage,root)
    return {'as_of':as_of,'offline':offline,'status':'published_local_bundle'}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--force-history',action='store_true');parser.add_argument('--as-of')
    parser.add_argument('--offline',action='store_true',help='Use cached source files; no network requests')
    args=parser.parse_args()
    print(refresh(force_history=args.force_history,as_of=args.as_of,offline=args.offline))
