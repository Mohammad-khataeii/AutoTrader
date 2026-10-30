"""Single-task immutable deployment binding, separate from engineering gates.

A durable exclusive claim binds the human's one-time authorization to one full
commit and its actual artifacts. It never fabricates an exact-commit approval.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

TASK='autotrader-v493-2026-10-30'
REQUEST='576553e6385141538e3a85a9fa0e0e4e91ff60013050d1d88d3be97f893144ae'
START='1c1b758f80deac18725167c234469cc0895a0120'
BRANCH='feature/autotrader-v46-intelligent-opportunity-engine'
SCOPE=Path('/opt/personal-plan/staging')


def canonical(value: Any) -> bytes:
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def bind(policy: dict[str,Any],manifest: dict[str,Any],images: dict[str,Any],base: Path,*,verify_archives: bool=True) -> dict[str,Any]:
    required={'task_id':TASK,'request_sha256':REQUEST,'starting_commit':START,'branch':BRANCH,
              'release_prefix':'4.9.3','maximum_distinct_releases':1,'host_alias':'aruba-vps',
              'directory':str(SCOPE),'compose_project':'autotrader-aruba-test',
              'backend_binding':'127.0.0.1:18000','frontend_binding':'127.0.0.1:13000',
              'paper_only':True,'live_trading_authorized':False,'automatic_primary_model_promotion':False,
              'requires_all_engineering_financial_restore_and_runtime_gates':True}
    if any(policy.get(k)!=v for k,v in required.items()) or base!=SCOPE:
        raise ValueError('task_authorization_scope_failed')
    commit=manifest.get('commit','')
    if not re.fullmatch('[a-f0-9]{40}',commit) or commit==START or images.get('commit')!=commit:
        raise ValueError('task_authorization_commit_failed')
    if not manifest.get('version','').startswith('4.9.3') or images.get('source_fingerprint')!=manifest.get('source_fingerprint'):
        raise ValueError('task_authorization_source_failed')
    hashes={key:images.get(key) for key in ('source_archive_sha256','image_archive_sha256')}
    hashes['source_fingerprint']=manifest.get('source_fingerprint')
    if any(not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v) for v in hashes.values()):
        raise ValueError('task_authorization_digest_required')
    for key in ('app','frontend'):
        if not re.fullmatch('sha256:[a-f0-9]{64}',images.get(key,'')):
            raise ValueError('task_authorization_image_required')
    if verify_archives:
        for role,key in [('source','source_archive_sha256'),('images','image_archive_sha256')]:
            path=Path(images.get('artifact_files',{}).get(role,''))
            if not path.is_absolute() or not path.resolve().is_relative_to(base.resolve()) or not path.is_file():
                raise ValueError('task_authorization_archive_scope_failed')
            with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=hashes[key]:raise ValueError('task_authorization_archive_hash_failed')
    return {'schema':'autotrader-task-claim/1','task_id':TASK,'request_sha256':REQUEST,
            'commit':commit,'version':manifest['version'],'artifacts':hashes,
            'images':{key:images[key] for key in ('app','frontend')},
            'scope':required,'authorization':'EXPLICIT_SINGLE_TASK_USER_AUTHORIZATION',
            'future_releases_authorized':False}


def claim(path: Path,binding: dict[str,Any]) -> dict[str,Any]:
    """Atomic create and fsync before any pause/activation; byte-identical resume.

    Caller owns the release lock. A torn or altered claim fails closed. Never
    replace it with a different commit, even after a failed deployment.
    """
    data=canonical(binding)+b'\n'
    try:
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        if path.read_bytes()!=data:raise ValueError('task_authorization_already_claimed_by_different_release')
        return {'status':'PASS','claim':'EXISTING_EXACT_IDENTITY','commit':binding['commit']}
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)
    return {'status':'PASS','claim':'CREATED_ONCE','commit':binding['commit']}
