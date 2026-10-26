import unittest

from audit_poly_market_types import array, family, parameters


class MarketTypeTests(unittest.TestCase):
    def test_annual_comparison_is_not_match_moneyline(self):
        event = {'id': '139296', 'title': 'Will Alcaraz or Sinner win more Grand Slams in 2026?'}
        market = {'outcomes': '["Alcaraz", "Sinner"]'}
        self.assertEqual(family(event, market)[0], 'more_grand_slams')

    def test_native_enum_takes_precedence_over_legacy_label(self):
        event = {'id': '139296', 'title': 'Example'}
        self.assertEqual(family(event, {'sportsMarketType': 'future_tennis_type'})[0], 'future_tennis_type')

    def test_native_moneyline_can_mean_tournament_winner(self):
        event = {'id': '1144193', 'title': 'ATP Tennis: Shanghai, China Winner'}
        market = {'sportsMarketType': 'moneyline', 'outcomes': '["Yes", "No"]'}
        self.assertEqual(family(event, market)[0], 'tournament_winner')

    def test_finalist_pair_contract_is_not_a_match(self):
        self.assertEqual(family({'id': '40300', 'title': 'US Open Final: Sinner vs. Alcaraz?'}, {'outcomes': '["Yes", "No"]'})[0], 'finalist_pair')

    def test_legacy_score_group_other_branch_is_not_moneyline(self):
        event = {'id': '31546', 'title': 'Sinner vs Shelton: Final Score (Sets)'}
        market = {'question': 'Other', 'outcomes': '["Yes", "No"]', 'groupItemTitle': 'Other'}
        self.assertEqual(family(event, market)[0], 'tennis_exact_score')
        self.assertEqual(parameters(market, 'tennis_exact_score')['special_branch'], 'other')

    def test_retirement_completion_and_score_special_branch_are_distinct(self):
        market = {'question': 'Exact Score: Not Completed?', 'groupItemTitle': 'Not Completed'}
        self.assertEqual(parameters(market, 'tennis_exact_score')['special_branch'], 'not_completed')
        self.assertEqual(parameters(market, 'tennis_completed_match'), {})

    def test_line_is_set_number_only_for_set_winner(self):
        winner = parameters({'question': 'Set 3 Winner: A vs B', 'line': 3}, 'tennis_set_winner')
        games = parameters({'question': 'A vs B: Set 3 Games O/U 9.5', 'line': 9.5}, 'tennis_set_games_totals')
        sets = parameters({'question': 'Total Sets O/U 3.5', 'line': 3.5}, 'tennis_set_totals')
        self.assertEqual(winner, {'set_number': 3})
        self.assertEqual(games, {'set_number': 3, 'threshold': 9.5, 'unit': 'games'})
        self.assertEqual(sets, {'threshold': 3.5, 'unit': 'sets'})

    def test_handicap_direction_comes_from_named_contract_not_raw_positive_line(self):
        m = {'question': 'Set Handicap: Sinner (-1.5) vs Zverev (+1.5)', 'line': 1.5}
        parsed = parameters(m, 'tennis_set_handicap')['named_handicaps']
        self.assertEqual(parsed[0], {'selection': 'Sinner', 'handicap': -1.5})
        self.assertEqual(parsed[1], {'selection': 'Zverev', 'handicap': 1.5})

    def test_legacy_spread_title_still_uses_native_set_unit(self):
        parsed = parameters({'question': 'Spread: Shelton (-1.5) vs Auger-Aliassime (+1.5)', 'line': 1.5}, 'tennis_set_handicap')
        self.assertEqual(parsed['unit'], 'sets')
        self.assertEqual(parsed['named_handicaps'][0]['handicap'], -1.5)

    def test_legacy_compound_handicap_keeps_extra_match_win_condition(self):
        kind, _ = family({'id': '31905', 'title': 'Will Swiatek win by 4+ games?'}, {})
        self.assertEqual(kind, 'match_winner_and_game_margin')

    def test_unknown_question_is_not_silently_winner_and_outcomes_keep_order(self):
        self.assertEqual(family({'id': 'new', 'title': 'New tennis question'}, {})[0], 'unclassified')
        self.assertEqual(array('["No", "Yes"]'), ['No', 'Yes'])
        with self.assertRaises(ValueError): array('{"Yes": 1}')


if __name__ == '__main__': unittest.main()
