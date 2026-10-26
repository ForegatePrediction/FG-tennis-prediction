#!/usr/bin/env python3
"""Local HTTP adapter. Restarts are required after replacing the JSON snapshot."""
import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from core.inference import Engine
from core.foregate import ForegateService


def handler(engine,foregate=None,demo=False):
    foregate=foregate or ForegateService(engine,index=os.environ.get('FG_TENNIS_FIXTURES',str(Path(__file__).parent/'data/foregate-fixtures.json')))
    class Handler(BaseHTTPRequestHandler):
        def respond(self,status,value):
            raw=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin','*')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin','*')
            self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers','Content-Type')
            self.end_headers()
        def do_GET(self):
            parsed=urlparse(self.path);params={k:v[-1] for k,v in parse_qs(parsed.query).items()}
            try:
                if len(self.path)>32000:raise ValueError('Query exceeds 32000 characters')
                if demo and parsed.path in ('/demo','/demo.js'):
                    filename='tennis.html' if parsed.path=='/demo' else 'tennis.js'
                    raw=(Path(__file__).parent/'demo'/filename).read_bytes()
                    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8' if filename.endswith('.html') else 'text/javascript; charset=utf-8')
                    self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
                if parsed.path in ('/health','/ping'):result={**engine.health(),'foregate':foregate.health()}
                elif parsed.path=='/players':result=engine.players(params.get('tour','atp'),params.get('q',''),int(params.get('limit',30)))
                elif parsed.path=='/predict':
                    if params.get('type')=='tennis' or params.get('view')=='foregate' or 'eventSlug' in params:
                        result=foregate.predict(params);self.respond(200,result);return
                    required=('tour','a','b','surface')
                    if any(k not in params for k in required):raise ValueError('Required: tour, a, b, surface')
                    if params.get('indoor','false') not in ('true','false'):raise ValueError('indoor must be true or false')
                    result=engine.predict(params['tour'],params['a'],params['b'],params['surface'],
                        int(params.get('best_of',3)),params.get('date'),params.get('rank_a'),params.get('rank_b'),params.get('indoor','false')=='true')
                elif parsed.path=='/predict/market':
                    if any(k not in params for k in ('tour','a','b','surface','market_type','best_of','final_tiebreak_points')):
                        raise ValueError('Required: tour,a,b,surface,market_type,best_of,final_tiebreak_points')
                    if params.get('format')!='main_tour_singles':raise ValueError('Explicit format=main_tour_singles required; other competition formats unsupported')
                    if params.get('indoor','false') not in ('true','false'):raise ValueError('indoor must be true or false')
                    result=engine.predict_market(params['tour'],params['a'],params['b'],params['surface'],params['market_type'],
                        float(params['line']) if 'line' in params else None,int(params['set_number']) if 'set_number' in params else None,
                        params.get('selection','a'),params.get('score'),int(params['final_tiebreak_points']),
                        best_of=int(params['best_of']),date=params.get('date'),rank_a=params.get('rank_a'),rank_b=params.get('rank_b'),indoor=params.get('indoor','false')=='true')
                elif parsed.path=='/predict/completion':
                    result=engine.predict_completion(params.get('tour'),params.get('competition'),params.get('date'),
                                                     int(params['rule_days']) if 'rule_days' in params else None)
                elif parsed.path=='/coverage':
                    from core.coverage import coverage
                    result=coverage('expanded_atp' if any(m.get('scope')=='expanded_atp' for m in engine.snapshot['tours'].values()) else 'main_tour')
                else:self.respond(404,{'error':'Supported routes: /health, /players, /predict, /predict/market, /coverage; POST /predict/tournament, /predict/markets, /predict/poly-event'});return
                self.respond(200,result)
            except (ValueError,TypeError,KeyError) as exc:self.respond(400,{'error':str(exc)})
        def do_POST(self):
            route=urlparse(self.path).path
            if route not in ('/predict/tournament','/predict/tournament/market','/predict/markets','/predict/poly-event'):
                self.respond(404,{'error':'Supported POST routes: /predict/tournament, /predict/markets, /predict/poly-event'});return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=1000000:raise ValueError('JSON body required, max 1000000 bytes')
                payload=json.loads(self.rfile.read(size))
                if not isinstance(payload,dict):raise ValueError('JSON object required')
                method={'/predict/tournament':engine.predict_tournament,'/predict/markets':engine.predict_markets,
                        '/predict/poly-event':engine.predict_poly_event,'/predict/tournament/market':engine.predict_tournament_market}[route]
                self.respond(200,method(payload))
            except (ValueError,TypeError,KeyError) as exc:self.respond(400,{'error':str(exc)})
    return Handler


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=int(os.environ.get('PORT',8105)));parser.add_argument('--model',default=os.environ.get('FG_TENNIS_MODEL'))
    parser.add_argument('--expanded-model',default=os.environ.get('FG_TENNIS_EXPANDED_MODEL'))
    parser.add_argument('--fixtures',default=os.environ.get('FG_TENNIS_FIXTURES',str(Path(__file__).parent/'data/foregate-fixtures.json')))
    parser.add_argument('--demo',action='store_true',help='Enable explicitly synthetic ATP/WTA fixtures and /demo; local use only')
    args=parser.parse_args()
    if args.demo and args.host not in ('127.0.0.1','localhost','::1'):parser.error('Demo must bind to loopback')
    engine=Engine(args.model);expanded=Engine(args.expanded_model) if args.expanded_model else None
    service=ForegateService(engine,expanded,args.fixtures,demo=args.demo)
    print(f'ForeGate Tennis on http://{args.host}:{args.port}',flush=True)
    ThreadingHTTPServer((args.host,args.port),handler(engine,service,demo=args.demo)).serve_forever()
