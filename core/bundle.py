"""Shared read/publish locks and rollback for a completed refresh on POSIX."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import shutil
import tempfile


@contextmanager
def bundle_lock(directory, exclusive=False):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/'.bundle.lock'
    try:handle=path.open('a+b') if exclusive else path.open('rb')
    except FileNotFoundError:
        try:handle=path.open('a+b')
        except PermissionError:
            # Read-only packaged snapshots cannot be concurrently published.
            if exclusive:raise
            yield;return
    with handle as lock:
        fcntl.flock(lock,fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


def replace_file(source,target):
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_name(target.name+'.publish.tmp')
    try:
        shutil.copyfile(source,temporary)
        os.replace(temporary,target)
    finally:
        temporary.unlink(missing_ok=True)


def publish(stage,root):
    """Shared lock prevents readers loading mixed generations; failures roll back.

    This is not a durable journal against power loss. Hash checks remain active.
    """
    stage,root=Path(stage),Path(root)
    files=sorted(p.relative_to(stage) for directory in ('models','reports','data')
                 for p in (stage/directory).rglob('*') if p.is_file() and not p.name.startswith('.'))
    if not files:raise ValueError('Empty refresh stage')
    with bundle_lock(root/'models',True), tempfile.TemporaryDirectory(dir=stage,prefix='rollback-') as backup:
        backup=Path(backup);previous={}
        for relative in files:
            target=root/relative;previous[relative]=target.exists()
            if target.exists():
                saved=backup/relative;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(target,saved)
        attempted=[]
        try:
            for relative in files:
                attempted.append(relative);replace_file(stage/relative,root/relative)
        except BaseException:
            for relative in reversed(attempted):
                if previous[relative]:replace_file(backup/relative,root/relative)
                else:(root/relative).unlink(missing_ok=True)
            raise
