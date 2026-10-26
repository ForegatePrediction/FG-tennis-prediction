import copy
import csv
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path
from core.data import load_tour, read_csv, regular_score
from core.features import State, FEATURES, build_features


def row(event='2025-one',day='20250106',winner='a',loser='b',num='1'):
    return {'tourney_id':event,'tourney_name':'Demo','tourney_date':day,'surface':'Hard',
            'tourney_level':'250','best_of':'3','match_num':num,'score':'6-4 6-4','round':'R32',
            'winner_id':winner,'winner_name':winner.upper(),'winner_rank':'10','winner_rank_points':'3000','winner_hand':'R',
            'loser_id':loser,'loser_name':loser.upper(),'loser_rank':'20','loser_rank_points':'2000','loser_hand':'L',
            'w_svpt':'60','w_1stIn':'40','w_1stWon':'30','w_2ndWon':'10','l_svpt':'60','l_1stIn':'40','l_1stWon':'25','l_2ndWon':'8'}


class CausalityTests(unittest.TestCase):
    def load(self,rows,as_of='2025-02-01'):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'data/raw/atp/test.csv';p.parent.mkdir(parents=True)
            with p.open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys() for r in rows))));writer.writeheader();writer.writerows(rows)
            return load_tour('atp',as_of,root)

    def test_nonstandard_scores(self):
        for score in ('6-4 6-4 RET','W/O','4-1 4-2 4-2','6-4','6-4 4-6 [10-8]','6-5 6-3'):
            self.assertFalse(regular_score(dict(row(),score=score)))
        self.assertTrue(regular_score(dict(row(),score='7-6(5) 6-7(3) 8-6')))

    def test_html_and_empty_source_fail_closed(self):
        with self.assertRaises(ValueError):read_csv(b'<html>upstream error</html>')
        with self.assertRaises(ValueError):read_csv(b'tourney_id\n')

    def test_only_validated_ongoing_files_may_be_empty(self):
        header=(','.join(row())+'\n').encode()
        with self.assertRaises(ValueError):read_csv(header)
        with self.assertRaises(ValueError):read_csv(b'<html>error</html>',allow_empty=True)
        self.assertEqual(read_csv(header,allow_empty=True),[])
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'data/raw/atp/ongoing_tourneys.csv';path.parent.mkdir(parents=True)
            path.write_bytes(header)
            record=row()
            with (path.parent/'2025.csv').open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(record));writer.writeheader();writer.writerow(record)
            rows,_=load_tour('atp','2025-02-01',root)
            self.assertEqual(len(rows),1)
            (path.parent/'2024.csv').write_bytes(header)
            with self.assertRaises(ValueError):load_tour('atp','2025-02-01',root)

    def test_same_event_results_do_not_enter_features(self):
        first=row();second=row(winner='a',loser='c',num='2')
        rows,_=self.load([first,second]);x,_,state=build_features('atp',rows,'2025-02-01')
        changed=dict(first)
        for key in first:
            if key.startswith('winner_'):
                opposite=key.replace('winner_','loser_',1)
                changed[key],changed[opposite]=first[opposite],first[key]
        alt,_=self.load([changed,second]);xx,_,_=build_features('atp',alt,'2025-02-01')
        self.assertEqual(x[1],xx[1]);self.assertEqual(state.player('a')['n'],2)

    def test_future_and_mixed_dates_are_conservative(self):
        with self.assertRaises(ValueError):self.load([row()],as_of='2025-01-12')
        rows,_=self.load([row(),row(day='20250112',winner='a',loser='c',num='2')],as_of='2025-01-13')
        self.assertTrue(all(m['available']==dt.date(2025,1,13).toordinal() for m in rows))
        self.assertTrue(all(m['date_precision']=='tournament' for m in rows))

    def test_two_week_events_cannot_use_one_week_release(self):
        for level,as_of in [('1000','2025-01-15'),('G','2025-01-20')]:
            with self.assertRaises(ValueError):self.load([dict(row(),tourney_level=level)],as_of=as_of)

    def test_conflicting_duplicates_rejected(self):
        with self.assertRaises(ValueError):self.load([row(),dict(row(),score='6-2 6-2')])

    def test_expanded_scope_keeps_qualifying_and_main_draw_rematch(self):
        with tempfile.TemporaryDirectory() as root:
            main=Path(root)/'data/raw/atp/2018.csv';quali=Path(root)/'data/expanded/atp_quali/2018_atp_quali.csv'
            for path,record in [(main,row()),(quali,dict(row(),round='Q2',score='6-3 7-6(2)'))]:
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('w',newline='') as f:
                    writer=csv.DictWriter(f,fieldnames=list(record));writer.writeheader();writer.writerow(record)
            baseline,_=load_tour('atp','2025-02-01',root)
            expanded,audit=load_tour('atp','2025-02-01',root,scope='expanded_atp')
            self.assertEqual(len(baseline),1);self.assertEqual(len(expanded),2)
            self.assertNotEqual(expanded[0]['id'],expanded[1]['id'])
            self.assertEqual(audit['competition_counts'],{'atp_qualifying':1,'main_tour':1})
            _,_,state=build_features('atp',expanded,'2025-02-01')
            self.assertEqual(state.player('a')['n'],2)

    def test_expanded_scope_does_not_ingest_challenger_into_main_model(self):
        with tempfile.TemporaryDirectory() as root:
            for name,record in [('data/raw/atp/2025.csv',row()),('data/expanded/2025_challenger.csv',dict(row(event='2025-c'),tourney_level='C'))]:
                path=Path(root)/name;path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('w',newline='') as f:
                    writer=csv.DictWriter(f,fieldnames=list(record));writer.writeheader();writer.writerow(record)
            baseline,_=load_tour('atp','2025-02-01',root)
            expanded,_=load_tour('atp','2025-02-01',root,scope='expanded_atp')
            self.assertEqual(len(baseline),1);self.assertEqual(len(expanded),2)

    def test_antisymmetric_after_history_and_h2h_shrinkage(self):
        matches,_=self.load([row()]);state=State('atp');state.update(matches[0]);day=dt.date(2025,2,1).toordinal()
        a=state.features('a','b','Hard',3,day);b=state.features('b','a','Hard',3,day)
        for x,y in zip(a,b):self.assertAlmostEqual(x,-y,12)
        self.assertLess(abs(a[FEATURES.index('h2h_residual')]),.1)
        self.assertEqual(state.player('a')['history'][0]['stats']['spw'],40)

    def test_future_result_does_not_change_earlier_features(self):
        r=[row(),row('2025-two','20250120','a','c','2'),row('2025-three','20250127','b','c','3')]
        ms,_=self.load(r,as_of='2025-02-10');x,_,_=build_features('atp',ms,'2025-02-10')
        r[-1].update(winner_id='c',loser_id='b',winner_name='C',loser_name='B')
        ms,_=self.load(r,as_of='2025-02-10');xx,_,_=build_features('atp',ms,'2025-02-10')
        self.assertEqual(x[:2],xx[:2])

    def test_match_statistics_not_used_to_predict_that_match(self):
        source=row();ms,_=self.load([source]);x,_,_=build_features('atp',ms,'2025-02-01')
        source['w_1stWon']='1';ms,_=self.load([source]);xx,_,_=build_features('atp',ms,'2025-02-01')
        self.assertEqual(x,xx)


if __name__=='__main__':unittest.main()
