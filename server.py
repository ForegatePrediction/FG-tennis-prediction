#!/usr/bin/env python3
"""Local HTTP adapter. Restarts are required after replacing the JSON snapshot."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs,urlparse
from core.inference import Engine


def handler(engine):
    class Handler(BaseHTTPRequestHandler):
        def respond(self,status,value):
            raw=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            parsed=urlparse(self.path);params={k:v[-1] for k,v in parse_qs(parsed.query).items()}
            try:
                if parsed.path in ('/health','/ping'):result=engine.health()
                elif parsed.path=='/players':result=engine.players(params.get('tour','atp'),params.get('q',''),int(params.get('limit',30)))
                elif parsed.path=='/predict':
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
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8105);parser.add_argument('--model')
    args=parser.parse_args();engine=Engine(args.model)
    print(f'ForeGate Tennis on http://{args.host}:{args.port}',flush=True)
    ThreadingHTTPServer((args.host,args.port),handler(engine)).serve_forever()
