"""The refresh stage must never train against an unrelated live corpus."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backtest_score import evaluate
from train_counts import main as train_counts


class RefreshPathTests(unittest.TestCase):
    def test_score_builders_load_the_requested_staging_corpus(self):
        for module,builder in (('backtest_score',evaluate),('train_counts',train_counts)):
            for expanded in (False,True):
                with self.subTest(module=module,expanded=expanded),tempfile.TemporaryDirectory() as directory:
                    root=Path(directory)
                    source={'files':[]}
                    fingerprint=hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()
                    data={'manifest_sha256':fingerprint,'expanded_manifest_sha256':fingerprint}
                    snapshot={'as_of':'2026-10-24','tours':{'atp':{'data':data}}}
                    relative='models/expanded/current.json' if expanded else 'models/current.json'
                    for name,value in ((relative,snapshot),('data/source-manifest.json',source),
                                       ('data/expanded/source-manifest.json',source)):
                        target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                        target.write_text(json.dumps(value))
                    with patch(module+'.load_tour',side_effect=RuntimeError('training boundary')) as load:
                        with self.assertRaisesRegex(RuntimeError,'training boundary'):
                            builder(expanded=expanded,root=root)
                    load.assert_called_once_with('atp','2026-10-24',root=root,
                                                 scope='expanded_atp' if expanded else 'main_tour')
