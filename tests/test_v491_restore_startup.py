"""The temporary PostgreSQL bootstrap socket must never authorize restoration."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def backup():
    spec=importlib.util.spec_from_file_location('startup_backup',Path('deploy/staging_backup.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_restore_ignores_ready_bootstrap_socket_until_final_tcp_postmaster(backup,monkeypatch):
    calls=[];sleeps=[]
    def probe(args,**kwargs):
        calls.append(args)
        # Bootstrap's Unix socket is already ready; final TCP is not ready yet.
        ready=('-h' not in args) or len(calls)>=3
        return SimpleNamespace(returncode=0 if ready else 1)
    monkeypatch.setattr(backup.subprocess,'run',probe);monkeypatch.setattr(backup.time,'sleep',sleeps.append)
    backup.wait_restore_postgres('owned-isolated-restore')
    assert len(calls)==3 and sleeps==[.25,.25]
    assert all(a[a.index('-h')+1]=='127.0.0.1' and a[a.index('-d')+1]=='postgres' for a in calls)


def test_restore_readiness_timeout_stops_without_authorizing_database_creation(backup,monkeypatch):
    calls=[];sleeps=[]
    monkeypatch.setattr(backup.subprocess,'run',lambda args,**kwargs:(calls.append(args) or SimpleNamespace(returncode=1)))
    monkeypatch.setattr(backup.time,'sleep',sleeps.append)
    with pytest.raises(RuntimeError,match='restore_clone_unavailable'):backup.wait_restore_postgres('owned-isolated-restore')
    assert len(calls)==len(sleeps)==60
    assert not any('createdb' in a or 'pg_restore' in a for a in calls)
