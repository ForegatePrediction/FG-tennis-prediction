#!/usr/bin/env python3
"""Build a separate ATP main/Challenger/ATP-qualifying research snapshot.

Never replaces models/current.json. No Challenger-qualifying test data exists
in these sources; that competition remains outside the validated scope.
"""
import argparse
import datetime as dt
from core.data import ROOT,atomic_json
from train import train_tour


def main(as_of=None):
    as_of=as_of or (dt.datetime.now(dt.timezone.utc).date()-dt.timedelta(days=1)).isoformat()
    model,report,audit=train_tour('atp',as_of,scope='expanded_atp')
    atomic_json(ROOT/'models/expanded/current.json',{'schema':1,'as_of':as_of,'tours':{'atp':model}})
    atomic_json(ROOT/'reports/atp-expanded-backtest.json',report)
    atomic_json(ROOT/'reports/atp-expanded-data-audit.json',audit)
    return model,report,audit


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--as-of');args=parser.parse_args();main(args.as_of)
