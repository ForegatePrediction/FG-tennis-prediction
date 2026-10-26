from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core.bundle import publish,replace_file
from refresh import refresh


class BundleTests(unittest.TestCase):
    def test_publish_failure_restores_old_bundle_and_removes_new_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'live';stage=Path(directory)/'stage'
            for base,text in ((root,'old'),(stage,'new')):
                (base/'models').mkdir(parents=True)
                for name in ('current.json','count-config.json'):(base/'models'/name).write_text(text)
            (stage/'data').mkdir();(stage/'data/new.json').write_text('new')
            calls=[]
            def fail_once(source,target):
                calls.append(str(target))
                if len(calls)==3:raise OSError('simulated disk write failure')
                replace_file(source,target)
            with patch('core.bundle.replace_file',side_effect=fail_once):
                with self.assertRaises(OSError):publish(stage,root)
            for name in ('current.json','count-config.json'):self.assertEqual((root/'models'/name).read_text(),'old')
            self.assertFalse((root/'data/new.json').exists())

    def test_failed_training_does_not_touch_live_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'models').mkdir();live=root/'models/current.json';live.write_text('old')
            def fail(as_of,root):
                (root/'models').mkdir(exist_ok=True);(root/'models/current.json').write_text('unfinished')
                raise ValueError('score fitting failed')
            with patch('refresh.main',side_effect=fail),patch('refresh.fetch') as network:
                with self.assertRaises(ValueError):refresh(root,as_of='2026-10-24',offline=True)
                network.assert_not_called()
            self.assertEqual(live.read_text(),'old')
            self.assertFalse(list(root.glob('.refresh-*')))
