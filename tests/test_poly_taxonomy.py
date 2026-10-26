import unittest
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from audit_poly_taxonomy import build, classify, registry


def fixture():
    return {'id': '1', 'title': 'Tournament: A Player vs B Player', 'sport': {'id': 45, 'sport': 'atp'},
            'series': [{'id': '12012', 'slug': 'wimbledon', 'title': 'Wimbledon'}],
            'eventMetadata': {'league': 'Tournament'},
            'teams': [{'id': 10, 'name': 'A Player', 'ordering': 'away'}, {'id': 11, 'name': 'B Player', 'ordering': 'home'}],
            'markets': [{'sportsMarketType': 'moneyline', 'outcomes': '["B Player", "A Player"]',
                         'description': 'A match.\n\nRetirement, default or disqualification.'}]}


class PolyTaxonomyTests(unittest.TestCase):
    def test_event_sport_and_series_remain_independent(self):
        d = classify(fixture())
        self.assertEqual(d['poly_sport'], 'atp')
        self.assertEqual(d['poly_series'][0]['id'], '12012')
        self.assertEqual(d['level_hint'], 'unverified')

    def test_qualifying_and_challenger_from_fixture_source(self):
        e = fixture(); e['eventMetadata']['tennisFixtureSource'] = 'optic-challenger-qualifying'
        d = classify(e)
        self.assertEqual(d['draw_stage_hint'], 'qualifying')
        self.assertEqual(d['level_hint'], 'challenger')
        self.assertEqual(classify(fixture())['draw_stage_hint'], 'not_marked_qualifying')

    def test_format_conflict_is_not_silently_routed_as_singles(self):
        e = fixture(); e['sport']['sport'] = 'atp-doubles'; e['eventMetadata']['format'] = 'singles'
        d = classify(e)
        self.assertEqual(d['discipline_hint'], 'unknown')
        self.assertIn('conflicting_format', d['issues'])

    def test_junior_not_inferred_adult_from_atp(self):
        e = fixture(); e['title'] = 'Wimbledon Juniors, Boys: A Player vs B Player'
        self.assertEqual(classify(e)['age_group_hint'], 'junior')
        self.assertEqual(classify(e)['level_hint'], 'junior')

    def test_player_junior_name_does_not_change_competition_age_group(self):
        e = fixture(); e['title'] = 'M15 Example: A Player vs Glauco Pinheiro da Cruz Junior'
        e['eventMetadata']['league'] = 'M15 Example'
        self.assertEqual(classify(e)['age_group_hint'], 'not_marked_junior')

    def test_poly_explicit_alias_handles_pair_order_without_fuzzy_matching(self):
        e = fixture(); e['teams'][0]['name'] = 'Player, A'; e['teams'][0]['alias'] = 'A Player'
        d = classify(e)
        self.assertEqual(d['moneyline_outcome_map'][1]['poly_participant_id'], '10')
        self.assertEqual(d['moneyline_outcome_map'][1]['match_basis'], 'explicit_poly_alias')
        e['teams'][1]['alias'] = 'A Player'
        self.assertIn('outcome_identity_unresolved', classify(e)['issues'])

    def test_itf_men_and_women_share_category(self):
        e = fixture(); e['sport']['sport'] = 'itf'
        for league, gender in [('M25 Example', 'male'), ('W15 Example', 'female'), ('Example', 'unknown')]:
            e['eventMetadata']['league'] = league
            self.assertEqual(classify(e)['gender_hint'], gender)

    def test_outcome_order_not_team_array_or_home_order(self):
        e = fixture(); e['markets'][0].update({'id': '77', 'conditionId': 'condition', 'clobTokenIds': '["token-b","token-a"]'})
        d = classify(e)
        self.assertEqual([s['poly_participant_id'] for s in d['moneyline_outcome_map']], ['11', '10'])
        self.assertEqual(d['poly_markets'][0]['id'], '77')
        self.assertEqual(d['poly_markets'][0]['clobTokenIds'], '["token-b","token-a"]')
        e = fixture(); e['teams'].append({'id': 12, 'name': 'A Player'})
        self.assertIn('outcome_identity_unresolved', classify(e)['issues'])

    def test_names_or_provider_ids_do_not_merge_poly_entities(self):
        rows, collisions = registry([{'id': 1, 'name': 'Same Name', 'providerId': 77, 'league': 'atp'},
                                     {'id': 2, 'name': 'Same Name', 'providerId': 77, 'league': 'daviscup'}])
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(collisions), 1)
        self.assertTrue(all(r['canonical_player_id'] is None for r in rows))

    def test_pair_stays_pair_without_fabricated_individual_ids(self):
        rows, _ = registry([{'id': 1, 'name': 'A/B', 'league': 'atp-doubles'}])
        self.assertEqual(rows[0]['entity_hint'], 'pair')
        self.assertIsNone(rows[0]['canonical_player_id'])

    def test_binary_futures_not_single_match(self):
        e = fixture(); e['title'] = 'Will A Player finish number 1?'; e['markets'][0]['outcomes'] = '["Yes","No"]'
        self.assertEqual(classify(e)['event_kind'], 'other_contract')

    def test_legacy_major_without_sport_or_market_type_stays_in_review_inventory(self):
        e = {'id': '41151', 'title': 'US Open: Novak Djokovic vs Taylor Fritz',
             'markets': [{'outcomes': '["Djokovic","Fritz"]'}]}
        d = classify(e)
        self.assertEqual(d['event_kind'], 'legacy_match_candidate')
        self.assertEqual(d['legacy_candidate_outcomes'], [['Djokovic', 'Fritz']])
        self.assertIn('legacy_untyped_match_requires_review', d['issues'])

    def test_no_silent_defaults_for_surface_or_match_format(self):
        d = classify(fixture())
        self.assertIsNone(d['surface'])
        self.assertIsNone(d['best_of'])

    def test_relative_extra_history_and_latest_open_snapshot_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); scan = root / 'scan'; scan.mkdir()
            (scan / 'sports.json').write_text('[]')
            current = fixture(); current['closed'] = False
            old = fixture(); old['closed'] = True
            (scan / 'closed-000.json').write_text(json.dumps([old]))
            (scan / 'open-000.json').write_text(json.dumps([current]))
            old['id'] = '2'; history = root / 'wimbledon-history-000.json'; history.write_text(json.dumps([old]))
            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch('audit_poly_taxonomy.ROOT', root): result = build(scan, [Path(history.name)])
            finally: os.chdir(previous)
            self.assertEqual(result['sample_events'], 2)
            rows = json.loads((root / 'reports/poly-event-catalog.json').read_text())
            self.assertFalse(next(r for r in rows if r['poly_event_id'] == '1')['closed'])


if __name__ == '__main__': unittest.main()
