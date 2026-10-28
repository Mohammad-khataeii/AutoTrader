"""Disk-backed isolated restore prevents data growth exhausting the memory cap."""
import ast
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def backup():
    spec=importlib.util.spec_from_file_location('backup_test',Path('deploy/staging_backup.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('scenario',['success','disk_full','restore_error','verification_failed'])
def test_restore_uses_scoped_disk_volume_and_preserves_failed_diagnostics(backup,monkeypatch,tmp_path,scenario):
    records=[{'database':'autotrader_aruba_staging','file':'one.dump','sha256':__import__('hashlib').sha256(b'dump').hexdigest(),'bytes':4,'database_size_bytes':700*1024**2}]
    (tmp_path/'one.dump').write_bytes(b'dump');manifest=tmp_path/'backup-set.json';manifest.write_text('{}')
    calls=[]
    def run(args,data=None):
        calls.append(args)
        if '/restore-space:ro' in ' '.join(args):return str(1 if scenario=='disk_full' else 10*1024**3).encode()
        if 'pg_restore' in args and scenario=='restore_error':raise RuntimeError('isolated_copy_failed')
        if '/verify.py' in args:return json.dumps({'status':'FAIL' if scenario=='verification_failed' else 'PASS','accounts':[{}]}).encode()
        return b''
    monkeypatch.setattr(backup,'run',run)
    monkeypatch.setattr(backup.subprocess,'run',lambda *a,**kw:type('Ready',(),{'returncode':0})())
    result={}
    if scenario=='success':
        backup.restore_clone(tmp_path,records,'sha256:'+'a'*64,manifest,result)
        assert result['restore_test'] and result['restore_storage']=='ISOLATED_NAMED_VOLUME'
        assert result['isolated_restore_resources_removed'] and result['disk_capacity']['required_bytes']>1024**3
    else:
        with pytest.raises((RuntimeError,ValueError)):backup.restore_clone(tmp_path,records,'sha256:'+'a'*64,manifest,result)
        assert not result.get('restore_test')
    starts=[a for a in calls if a[:3]==['docker','run','-d']]
    if scenario=='disk_full':assert starts==[]
    else:
        start=starts[0];assert '--tmpfs' not in start and start[start.index('--memory')+1]=='512m'
        mount=start[start.index('-v')+1];assert mount.startswith('autotrader-aruba-restore-') and mount.endswith('-data:/var/lib/postgresql/data')
        assert not any(a in start for a in ['-p','--publish','--network=host'])
    removals=[a for a in calls if a[:3]==['docker','volume','rm']]
    assert bool(removals)==(scenario in ['success','disk_full'])
    assert (tmp_path/'restore-attempt.json').is_file()


def test_all_embedded_remote_programs_compile(backup):
    for name in ['DISCOVER','OWNER','VERIFY','REHEARSE']:compile(getattr(backup,name),name,'exec')
    ast.parse(Path(backup.__file__).read_text())
