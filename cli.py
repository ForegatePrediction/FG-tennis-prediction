#!/usr/bin/env python3
import argparse
import json
from core.inference import Engine


def main():
    parser=argparse.ArgumentParser(description='ForeGate free-data ATP/WTA match-winner model')
    parser.add_argument('--model',help='Combined JSON snapshot path')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('health')
    for command in ('markets','poly-event'):
        batch=sub.add_parser(command,help='Predict all requested markets from a local JSON request')
        batch.add_argument('--request',required=True)
    players=sub.add_parser('players');players.add_argument('--tour',required=True,choices=['atp','wta']);players.add_argument('--query',default='')
    pred=sub.add_parser('predict');pred.add_argument('--tour',required=True,choices=['atp','wta'])
    pred.add_argument('--a',required=True);pred.add_argument('--b',required=True)
    pred.add_argument('--surface',required=True,choices=['Hard','Clay','Grass','Carpet'])
    pred.add_argument('--best-of',type=int,default=3);pred.add_argument('--date')
    pred.add_argument('--rank-a',type=int);pred.add_argument('--rank-b',type=int)
    pred.add_argument('--indoor',action='store_true')
    args=parser.parse_args();engine=Engine(args.model)
    try:
        if args.command in ('markets','poly-event'):
            from pathlib import Path
            payload=json.loads(Path(args.request).read_text())
            result=engine.predict_markets(payload) if args.command=='markets' else engine.predict_poly_event(payload)
        elif args.command=='predict':result=engine.predict(args.tour,args.a,args.b,args.surface,args.best_of,args.date,args.rank_a,args.rank_b,args.indoor)
        elif args.command=='players':result=engine.players(args.tour,args.query)
        else:result=engine.health()
    except ValueError as exc:parser.error(str(exc))
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=='__main__':main()
