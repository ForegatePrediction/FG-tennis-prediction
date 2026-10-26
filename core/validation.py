"""Shared parameter identity for training reports and runtime lookup."""
import json


def market_key(kind, params=None, score=None):
    if kind == 'tennis_exact_score':return kind + ':' + str(score)
    params = dict(params or {})
    if params.get('selection') == 'a':params.pop('selection')
    return kind + (':' + json.dumps(params, sort_keys=True) if params else '')
