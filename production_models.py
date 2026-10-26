#!/usr/bin/env python3
"""Publish and verify immutable, public model bundles without copying GitHub credentials."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request
from core.data import ROOT
from core.inference import Engine

REPO='ForegatePrediction/FG-tennis-prediction'
FILES=('current.json','count-config.json','score-config.json','completion.json')


def validate(directory):
    engine=Engine(Path(directory)/'current.json');health=engine.health()
    if health['status']!='ok' or set(engine.states)!={'atp','wta'}:raise ValueError('Model bundle is incomplete or stale')
    for config in (engine.count_config,engine.score_config):
        if not config or config.get('base_model_sha256')!=engine.snapshot_sha256:raise ValueError('Mismatched model configuration')
    if not engine.completion_config:raise ValueError('Missing completion baseline')
    return health


def build(destination,root=ROOT):
    root=Path(root);destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    validate(root/'models')
    bundle=destination/'tennis-model.tar.gz'
    with tarfile.open(bundle,'w:gz') as archive:
        for name in FILES:archive.add(root/'models'/name,arcname=name)
    digest=hashlib.sha256(bundle.read_bytes()).hexdigest()
    (destination/'tennis-model.sha256').write_text(digest+'\n')
    shutil.copyfile(root/'data/completion-checkpoint.json.gz',destination/'completion-checkpoint.json.gz')
    return {'sha256':digest,'bytes':bundle.stat().st_size}


def fetch(url,maximum):
    request=urllib.request.Request(url,headers={'User-Agent':'ForegateTennis/1.0 model-deployment'})
    with urllib.request.urlopen(request,timeout=60) as response:raw=response.read(maximum+1)
    if len(raw)>maximum:raise ValueError('Release asset exceeds size limit')
    return raw


def unpack(raw,destination):
    destination=Path(destination)
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
        members=archive.getmembers()
        if len(members)!=len(FILES) or {m.name for m in members}!=set(FILES):raise ValueError('Unexpected model archive members')
        for member in members:
            if not member.isfile() or member.size>100*1024*1024:raise ValueError('Invalid model archive member')
            with archive.extractfile(member) as source,(destination/member.name).open('wb') as target:shutil.copyfileobj(source,target)


def pull(store):
    store=Path(store);store.mkdir(parents=True,exist_ok=True)
    release=json.loads(fetch('https://api.github.com/repos/'+REPO+'/releases/latest',1024*1024))
    if release.get('draft') or release.get('prerelease'):raise ValueError('Only stable published bundles are deployable')
    assets={x['name']:x['browser_download_url'] for x in release['assets']}
    for name in ('tennis-model.tar.gz','tennis-model.sha256'):
        if not assets[name].startswith('https://github.com/'+REPO+'/releases/download/'):raise ValueError('Unexpected release asset origin')
    digest=fetch(assets['tennis-model.sha256'],128).decode().strip()
    if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('Invalid bundle digest')
    current=store/'current';old=os.readlink(current) if current.is_symlink() else None
    target=store/digest
    if old==digest:return {'changed':False,'generation':digest}
    raw=fetch(assets['tennis-model.tar.gz'],30*1024*1024)
    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Release checksum mismatch')
    if not target.exists():
        with tempfile.TemporaryDirectory(dir=store,prefix='.staging-') as tmp:
            unpack(raw,tmp);health=validate(tmp)
            (Path(tmp)/'release.json').write_text(json.dumps({'release':release['html_url'],'sha256':digest,'health':health}))
            os.rename(tmp,target)
    else:validate(target)
    temporary=store/'current.next';temporary.unlink(missing_ok=True);temporary.symlink_to(digest);os.replace(temporary,current)
    return {'changed':True,'previous':old,'generation':digest,'release':release['html_url']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--build',type=Path);mode.add_argument('--pull',type=Path)
    args=parser.parse_args();print(json.dumps(build(args.build) if args.build else pull(args.pull)))
