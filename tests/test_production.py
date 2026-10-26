import copy
import datetime as dt
import io
import json
from pathlib import Path
import tarfile
import tempfile
import hashlib
import unittest
from unittest.mock import patch
from production_models import unpack,pull,REPO
from refresh_fixtures import collect
from refresh_completion import merge_labels
from core.completion import timestamp


class FixtureRefreshTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,10,26,tzinfo=dt.timezone.utc)
        self.registry={'rules_source':'https://official.test/rules','competitions':[
            {'names':['Reviewed Cup'],'tour':'atp','from':'2026-10-26','through':'2026-11-01',
             'surface':'Hard','indoor':True,'best_of':3,'final_tiebreak_points':7,'source':'https://official.test/cup'}]}
        self.event={'id':'1','slug':'test','startTime':'2026-10-27T10:00:00Z','closed':False,
            'eventMetadata':{'league':'Reviewed Cup'},'teams':[{'name':'A','league':'atp'},{'name':'B','league':'atp'}],
            'markets':[{'id':'123','sportsMarketType':'moneyline','outcomes':['B','A'],
                        'clobTokenIds':['999999999999999999999999','888888888888888888888888'],
                        'description':'This market refers to the match between A and B.','question':'A vs B'}]}

    def test_exact_reviewed_competition_preserves_gamma_token_order(self):
        result=collect([([self.event],'https://gamma.test')],self.registry,self.now)
        row=result['fixtures']['test'];self.assertEqual((row['a'],row['b']),('B','A'))
        self.assertEqual(row['context']['indoor'],True)
        self.assertEqual(row['bindings']['123']['poly_options'][0]['title'],'B')
        self.assertEqual(row['bindings']['123']['poly_options'][0]['assetId'],'999999999999999999999999')

    def test_unreviewed_expired_qualifying_or_live_events_are_skipped(self):
        changes=[{'eventMetadata':{'league':'Unknown'}},{'startTime':'2026-11-02T10:00:00Z'},
                 {'eventMetadata':{'league':'Reviewed Cup','tennisFixtureSource':'optic-challenger-qualifying'}},
                 {'live':True},{'teams':[{'name':'A/B','league':'atp-doubles'},{'name':'C/D','league':'atp-doubles'}]}]
        for change in changes:
            result=collect([([{**self.event,**change}],'url')],self.registry,self.now)
            self.assertFalse(result['fixtures'])

    def test_repeated_feed_is_not_published_as_a_complete_scan(self):
        with self.assertRaises(ValueError):collect([([self.event,self.event],'url')],self.registry,self.now)


class ModelReleaseTests(unittest.TestCase):
    def test_archive_cannot_write_paths_links_or_extra_files(self):
        for name,kind in (('../current.json',tarfile.REGTYPE),('current.json',tarfile.SYMTYPE)):
            stream=io.BytesIO()
            with tarfile.open(fileobj=stream,mode='w:gz') as archive:
                item=tarfile.TarInfo(name);item.type=kind;archive.addfile(item)
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):unpack(stream.getvalue(),tmp)
                self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_bad_checksum_keeps_current_generation(self):
        base='https://github.com/'+REPO+'/releases/download/test/'
        release={'assets':[{'name':name,'browser_download_url':base+name} for name in ('tennis-model.tar.gz','tennis-model.sha256')]}
        with tempfile.TemporaryDirectory() as tmp:
            current=Path(tmp)/'current';current.symlink_to('previous')
            with patch('production_models.fetch',side_effect=[json.dumps(release).encode(),b'0'*64,b'bad bundle']):
                with self.assertRaisesRegex(ValueError,'checksum'):pull(tmp)
            self.assertEqual(current.readlink(),Path('previous'))

    def test_verified_bundle_switches_atomically_and_can_be_reused(self):
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w:gz') as archive:
            for name in ('current.json','count-config.json','score-config.json','completion.json'):
                item=tarfile.TarInfo(name);item.size=2;archive.addfile(item,io.BytesIO(b'{}'))
        raw=stream.getvalue();digest=hashlib.sha256(raw).hexdigest()
        base='https://github.com/'+REPO+'/releases/download/test/'
        release={'html_url':'https://github.com/'+REPO+'/releases/tag/test',
                 'assets':[{'name':name,'browser_download_url':base+name} for name in ('tennis-model.tar.gz','tennis-model.sha256')]}
        with tempfile.TemporaryDirectory() as tmp,patch('production_models.validate',return_value={'status':'ok'}):
            with patch('production_models.fetch',side_effect=[json.dumps(release).encode(),digest.encode(),raw]):result=pull(tmp)
            self.assertTrue(result['changed']);self.assertEqual((Path(tmp)/'current').readlink(),Path(digest))
            with patch('production_models.fetch',side_effect=[json.dumps(release).encode(),digest.encode()]):result=pull(tmp)
            self.assertFalse(result['changed'])


class CompletionIncrementTests(unittest.TestCase):
    def test_variable_fractional_seconds_are_supported_on_production_python(self):
        self.assertEqual(timestamp('2026-10-25T17:05:23.59083Z').microsecond,590830)
    def test_old_labels_are_preserved_and_conflicts_fail(self):
        now=dt.datetime(2026,10,26,tzinfo=dt.timezone.utc)
        seed={'checked_at':now.isoformat(),'labels':[{'market_id':str(i),'available':'2026-09-01','yes':1} for i in range(1000)]}
        event={'id':'1','createdAt':'2026-10-25T00:00:00Z','markets':[{'sportsMarketType':'tennis_completed_match'}]}
        new={'market_id':'1001','available':'2026-10-25','yes':0}
        with patch('refresh_completion.label',return_value=(new,None)):
            value=merge_labels(seed,[([event],'url')],now)
        self.assertEqual(len(value['labels']),1001);self.assertEqual(len(seed['labels']),1000)
        with patch('refresh_completion.label',return_value=({'market_id':'1','available':'2026-09-01','yes':0},None)):
            with self.assertRaisesRegex(ValueError,'Conflicting'):merge_labels(seed,[([event],'url')],now)
