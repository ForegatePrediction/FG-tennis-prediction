import unittest

from audit_polymarket import describe, sport_of, tennis_sports


def fixture():
    return {'id':'123','title':'European Open: A Player vs B Player','slug':'atp-a-b-2026-10-25',
            'sport':{'sport':'atp'},'eventMetadata':{'league':'European Open'},'series':[{'id':'10365','slug':'atp'}],
            'startDate':'2026-10-18T00:00:00Z','endDate':'2026-11-01T00:00:00Z',
            'markets':[{'sportsMarketType':'moneyline','active':True,'closed':False,'acceptingOrders':True,
                        'outcomes':'["A Player","B Player"]','gameStartTime':'2026-10-25T12:00:00Z',
                        'description':'This match is in the European Open.\n\nRetirement, default, or disqualification.'}]}


class MarketAuditTests(unittest.TestCase):
    def test_exact_tag_excludes_table_tennis(self):
        rows=[{'tags':'1, 864,100639'},{'tags':'1,8640'},{'tags':'1,100639'}]
        self.assertEqual(tennis_sports(rows),rows[:1])

    def test_disqualification_does_not_mean_qualifying(self):
        self.assertFalse(describe(fixture())['qualifying'])

    def test_qualification_can_be_only_in_description(self):
        e=fixture();e['markets'][0]['description']='Match in Seoul, Qualifying, originally scheduled for tomorrow.\n\nRules'
        self.assertTrue(describe(e)['qualifying'])

    def test_doubles_are_not_inferred_from_shared_atp_tag(self):
        e=fixture();e['sport']={'sport':'atp-doubles'};e['series']=[{'id':'11632','slug':'atp-doubles'}]
        d=describe(e);self.assertTrue(d['doubles']);self.assertEqual(d['series_ids'],['11632'])

    def test_actual_start_not_creation_or_expiry(self):
        self.assertEqual(describe(fixture())['game_start'],'2026-10-25T12:00:00Z')

    def test_closed_or_non_accepting_moneyline_is_not_tradable(self):
        for field,value in [('closed',True),('acceptingOrders',False),('active',False)]:
            e=fixture();e['markets'][0][field]=value
            self.assertFalse(describe(e)['tradable_match_moneyline'])

    def test_futures_moneyline_not_match_coverage(self):
        e=fixture();e['title']='ATP Tennis: Event Winner';e['markets'][0]['outcomes']='["Yes","No"]'
        self.assertFalse(describe(e)['is_match'])
        self.assertFalse(describe(e)['tradable_match_moneyline'])

    def test_nullable_metadata(self):
        e=fixture();e['sport']=None;e['series']=None;e['eventMetadata']=None
        self.assertEqual(sport_of(e),'outright_or_other')
        self.assertEqual(describe(e)['league'],'European Open')

    def test_junior_is_not_adult_tour_just_because_sport_atp(self):
        e=fixture();e['title']='Wimbledon Juniors, Boys: A Player vs B Player'
        self.assertTrue(describe(e)['junior'])

    def test_player_name_junior_is_not_a_junior_tournament(self):
        e=fixture();e['title']='M15 Example: A Player vs Glauco Pinheiro da Cruz Junior'
        e['eventMetadata']['league']='M15 Example'
        self.assertFalse(describe(e)['junior'])


if __name__=='__main__':unittest.main()
