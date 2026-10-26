import copy
import datetime as dt
import json
import unittest
from core.completion import estimate,rule_days,timestamp,wilson
from core.data import ROOT
from train_completion import label,split_rows


class CompletionTests(unittest.TestCase):
    def fixture(self):
        e=json.loads((ROOT/'tests/fixtures/poly-screenshot-event.json').read_text())
        m=copy.deepcopy(next(m for m in e['markets'] if m['sportsMarketType']=='tennis_completed_match'))
        m.update(closed=True,umaResolutionStatus='resolved',outcomePrices='["1","0"]',
                 createdAt='2026-10-23T06:00:00Z',closedTime='2026-10-25 09:00:00+00',umaEndDate='2026-10-25T09:00:00Z')
        return e,m

    def test_settlement_requires_resolved_closed_and_exact_binary_not_price_guess(self):
        e,m=self.fixture();r,reason=label(e,m);self.assertIsNone(reason);self.assertEqual(r['yes'],1)
        for change in ({'closed':False},{'umaResolutionStatus':'proposed'},{'outcomePrices':'["0.5","0.5"]'}, {'outcomePrices':'["0.999","0.001"]'}):
            r,_=label(e,{**m,**change});self.assertIsNone(r)

    def test_pre_start_cancellation_is_valid_no_label_and_outcome_order_is_explicit(self):
        e,m=self.fixture();m.update(outcomes='["No","Yes"]',outcomePrices='["1","0"]',closedTime='2026-10-24T09:00:00Z',umaEndDate='2026-10-24T09:00:00Z')
        r,why=label(e,m);self.assertIsNone(why);self.assertEqual(r['yes'],0)
        self.assertLess(timestamp(r['available']),timestamp(r['start']))

    def test_seven_and_fourteen_day_rule_versions_are_distinct(self):
        e,m=self.fixture();self.assertEqual(rule_days(m['description']),14)
        self.assertEqual(rule_days('or is delayed beyond 7 days from the scheduled date without a winner determined'),7)
        self.assertIsNone(rule_days('no known deadline'))

    def test_maturity_and_chronology_prevent_leakage_or_fast_yes_selection(self):
        rows=[]
        for mid,issued,start,available in [('fit','2026-08-01','2026-08-02','2026-08-03'),
                                          ('selection','2026-09-02','2026-09-03','2026-09-04'),
                                          ('test','2026-10-02','2026-10-03','2026-10-04'),
                                          ('too_recent','2026-10-20','2026-10-21','2026-10-22'),
                                          ('late_label','2026-09-02','2026-09-03','2026-10-02')]:
            rows.append({'market_id':mid,'issued_at':issued+'T00:00:00Z','start':start+'T00:00:00Z','available':available+'T00:00:00Z'})
        accepted,fit,selection,frozen,test,_,_=split_rows(rows,'2026-10-24')
        self.assertEqual([r['market_id'] for r in fit],['fit'])
        self.assertEqual([r['market_id'] for r in selection],['selection'])
        self.assertEqual([r['market_id'] for r in test],['test'])
        self.assertNotIn('too_recent',[r['market_id'] for r in accepted])
        self.assertNotIn('late_label',[r['market_id'] for r in frozen])

    def test_global_estimate_is_population_rate_with_uncertainty(self):
        today=dt.datetime.now(dt.timezone.utc).date().isoformat()
        config={'as_of':today,'source_checked_at':today,'selected_method':'global_frequency','groups':{},'minimum_group_n':50,
                'global':{'n':1000,'yes':940,'no':60,'probability':941/1002},'prior_strength':200,'test':{}}
        q=estimate(config);self.assertAlmostEqual(sum(q['probabilities']),1)
        self.assertFalse(q['used_global_fallback']);self.assertEqual(q['sample']['no'],60)
        lo,hi=q['raw_frequency_95pct_wilson'];self.assertLess(lo,.94);self.assertGreater(hi,.94)
        with self.assertRaises(ValueError):estimate(config,date='2000-01-01')
