import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from enumerate_poly_tennis import walk_dictionary, walk_events
from build_poly_enumeration import axes, build, competition, major_key, outside_root_decision


def event(identifier):
    return {'id': str(identifier), 'title': 'Example: A Player vs B Player', 'tags': [{'id': '864'}]}


class EnumerationTests(unittest.TestCase):
    def test_cursor_walk_has_no_status_filter_and_follows_cursor(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('enumerate_poly_tennis.page', side_effect=[{'events': [event(1)], 'next_cursor': 'cursor'}, {'events': [event(2)]}]) as get:
                result = walk_events(Path(folder))
            self.assertTrue(result['pagination_exhausted'])
            self.assertEqual(result['unique_events'], 2)
            queries = [parse_qs(urlsplit(c.args[0]).query) for c in get.call_args_list]
            self.assertEqual(queries[1]['after_cursor'], ['cursor'])
            for q in queries:
                self.assertFalse({'active', 'closed', 'archived', 'offset'} & q.keys())

    def test_repeated_cursor_and_wrong_filter_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('enumerate_poly_tennis.page', side_effect=[{'events': [event(1)], 'next_cursor': 'same'}, {'events': [event(2)], 'next_cursor': 'same'}]):
                with self.assertRaisesRegex(ValueError, 'Repeated cursor'): walk_events(Path(folder))
            with patch('enumerate_poly_tennis.page', return_value={'events': [{'id': '3', 'tags': []}]}):
                with self.assertRaisesRegex(ValueError, 'Tag filter mismatch'): walk_events(Path(folder))

    def test_page_budget_is_not_exhaustion(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('enumerate_poly_tennis.page', return_value={'events': [event(1)], 'next_cursor': 'more'}):
                result = walk_events(Path(folder), maximum=1)
            self.assertFalse(result['pagination_exhausted'])

    def test_dictionary_cap_does_not_terminate_before_empty_page(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('enumerate_poly_tennis.page', side_effect=[[{'id': '1'}], [{'id': '2'}], []]) as get:
                result = walk_dictionary(Path(folder), 'tags', size=100)
            self.assertEqual(result['records'], 2)
            self.assertTrue(result['pagination_exhausted'])
            self.assertEqual([parse_qs(urlsplit(c.args[0]).query)['offset'] for c in get.call_args_list], [['0'], ['1'], ['2']])

    def test_legacy_title_and_four_grand_slams_preserved(self):
        for name, expected in [('Australian Open', 'australian_open'), ('Roland Garros', 'roland_garros'), ('French Open', 'roland_garros'), ('Wimbledon', 'wimbledon'), ('US Open', 'us_open')]:
            e = {'title': name + ': A Player vs B Player'}
            self.assertEqual(competition(e), (name, 'title_prefix'))
            self.assertEqual(major_key(e), (expected, 'competition_name'))
        self.assertEqual(competition({'title': 'Will A Player win more Grand Slams?'}), (None, None))

    def test_player_name_junior_is_not_competition_age(self):
        e = {'title': 'M15 Example: A Player vs Glauco Junior', 'metadata': {'league': 'M15 Example'}, 'sport': {'sport': 'itf'}}
        self.assertFalse(axes(e)['junior'])
        self.assertEqual(axes(e)['itf_grade_prefix'], 'M15')

    def test_shared_grand_slam_and_us_open_do_not_turn_golf_into_tennis(self):
        for slug in ['grand-slam', 'us-open']:
            e = {'tags': [{'slug': slug}, {'slug': 'golf'}]}
            self.assertEqual(outside_root_decision(e), 'excluded_other_sport')
        self.assertEqual(outside_root_decision({'tags': [{'slug': 'wimbledon'}]}), 'confirmed_tennis')
        self.assertEqual(outside_root_decision({'tags': [{'slug': 'grand-slam'}]}), 'unresolved')
        self.assertEqual(outside_root_decision({'tags': [{'slug': 'tennis'}], 'sport': {'sport': 'cfb'}}), 'excluded_other_sport')
        self.assertEqual(outside_root_decision({'series': [{'slug': 'cfb-2025'}]}), 'excluded_other_sport')
        self.assertEqual(outside_root_decision({'tags': [{'slug': 'barcelona-open'}]}), 'confirmed_tennis')

    def test_report_build_requires_complete_evidence_and_retains_legacy_competition(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); scan = root / 'scan'
            for kind in ('tags', 'series', 'tennis-history'):
                (scan / kind).mkdir(parents=True)
                (scan / kind / 'status.json').write_text(json.dumps({'pagination_exhausted': True, 'pages': 1, 'records': 1, 'unique_events': 1}))
            (scan / 'cross-check-manifest.json').write_text(json.dumps({'all_pagination_exhausted': True, 'tag_seeds': [], 'series_seeds': [], 'queries': 0}))
            (scan / 'tags/dictionary.json').write_text(json.dumps([{'id': '864', 'label': 'Tennis', 'slug': 'tennis'}]))
            (scan / 'series/dictionary.json').write_text('[]')
            e = {'id': '1', 'title': 'Wimbledon: A Player vs B Player', 'createdAt': '2024-01-01', 'tags': [{'id': '864'}], 'market_types': ['unspecified']}
            (scan / 'tennis-history/events-compact.json').write_text(json.dumps([e]))
            (root / 'docs').mkdir()
            with patch('build_poly_enumeration.ROOT', root):
                result = build(scan)
                self.assertEqual(result['competition_labels_unique'], 1)
                self.assertEqual(next(m for m in result['majors'] if m['key'] == 'wimbledon')['events'], 1)
                (scan / 'tennis-history/status.json').write_text('{"pagination_exhausted":false}')
                with self.assertRaisesRegex(ValueError, 'Enumeration incomplete'): build(scan)


if __name__ == '__main__': unittest.main()
