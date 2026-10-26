#!/usr/bin/env python3
"""Reproduce the user's sixteen contracts and save explicit availability."""
import json
from core.data import ROOT,atomic_json
from core.inference import Engine


def main():
    engine=Engine()
    event=json.loads((ROOT/'tests/fixtures/poly-screenshot-event.json').read_text())
    request={'event':event,'mapping_verified':True,
             'source':'Gamma event 1247021 plus exact full-name match in TennisMyLife ATP IDs. Archived audit; surface/format not independently verified for forecast.',
             'match':{'tour':'atp','a':'L0I5','b':'S0JV','surface':'Hard','best_of':3,'final_tiebreak_points':7,
                      'format':'expanded_atp_singles','competition':'challenger_qualifying'},
             'player_mapping':{'a':{'poly_name':'Mitsuki Wei Kang Leong'},'b':{'poly_name':'Qian Sun'}}}
    snapshot=ROOT/'models/expanded/current.json'
    expanded=Engine(snapshot) if snapshot.exists() else None
    actual=(expanded or engine).predict_poly_event(request)
    atomic_json(ROOT/'examples/poly-screenshot-audit-request.json',request)
    atomic_json(ROOT/'reports/poly-screenshot-availability.json',actual)
    # A distinct hypothetical request proves computation using known players.
    # It is never relabelled as the actual Challenger-qualifying fixture.
    example={'tour':'atp','a':'S0AG','b':'A0E2','surface':'Hard','best_of':3,'final_tiebreak_points':7,
             'format':'main_tour_singles','competition':'main_tour'}
    atomic_json(ROOT/'examples/markets-request.json',example)
    hypothetical=engine.predict_markets(example)
    hypothetical['example_note']='Hypothetical Sinner/Alcaraz BO3 Hard matchup, not an actual scheduled event. Demonstrates the screenshot line set only.'
    atomic_json(ROOT/'reports/markets-response-example.json',hypothetical)
    players={side:(expanded.players('atp',request['match'][side]) if expanded else []) for side in ('a','b')}
    model_report=json.loads((ROOT/'reports/atp-expanded-backtest.json').read_text()) if expanded else None
    result={'actual_event':{'id':event['id'],'title':event['title'],'fixture_source':event['eventMetadata']['tennisFixtureSource'],
                            'url':'https://polymarket.com/event/'+event['slug'],'summary':actual['summary'],'blockers':actual['blockers']},
            'computable_line_template':hypothetical['summary'],'players_in_expanded_model':players,
            'expanded_winner_test':{name:{k:v['model'][k] for k in ('n','accuracy','log_loss')} for name,v in model_report['by_competition'].items()} if model_report else None,
            'status':'local experimental implementation; not deployed, no GitHub push; not all Poly competitions are forecastable'}
    atomic_json(ROOT/'reports/screenshot-delivery.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':main()
