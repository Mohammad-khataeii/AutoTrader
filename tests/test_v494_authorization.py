"""V4.9.4 Single-task authorization, immutable release, exclusive claim."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from deploy import task_authorization as auth


def inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, 'SCOPE', tmp_path)
    policy = json.loads(Path('deploy/authorizations/v494-once.json').read_text())
    policy['directory'] = str(tmp_path)
    archive = tmp_path / 'source.tar.gz'
    archive.write_bytes(b'actual immutable source archive v494')
    image = tmp_path / 'images.tar.gz'
    image.write_bytes(b'actual immutable image archive v494')
    manifest = {'commit': 'a' * 40, 'version': '4.9.4rc1', 'source_fingerprint': 'd' * 64}
    images = {'commit': 'a' * 40, 'source_fingerprint': 'd' * 64, 'app': 'sha256:' + 'b' * 64, 'frontend': 'sha256:' + 'c' * 64,
              'source_archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
              'image_archive_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
              'artifact_files': {'source': str(archive), 'images': str(image)}}
    return policy, manifest, images


def test_v494_single_task_claim_exact_resume_and_different_release_refusal(tmp_path, monkeypatch):
    p, m, i = inputs(tmp_path, monkeypatch)
    binding = auth.bind(p, m, i, tmp_path)
    assert binding['task_id'] == auth.TASK_V494
    assert binding['request_sha256'] == auth.REQUEST_V494
    path = tmp_path / 'claim.json'
    assert auth.claim(path, binding)['claim'] == 'CREATED_ONCE'
    original = path.read_bytes()
    assert auth.claim(path, binding)['claim'] == 'EXISTING_EXACT_IDENTITY'
    assert path.read_bytes() == original and path.stat().st_mode & 0o777 == 0o600
    changed = copy.deepcopy(binding)
    changed['commit'] = 'e' * 40
    with pytest.raises(ValueError, match='different_release'):
        auth.claim(path, changed)


@pytest.mark.parametrize('fault', ['scope', 'live', 'count', 'future', 'version', 'digest', 'archive', 'image', 'source', 'old_commit'])
def test_v494_authorization_fails_closed_before_any_claim(tmp_path, monkeypatch, fault):
    p, m, i = inputs(tmp_path, monkeypatch)
    if fault == 'scope': p['compose_project'] = 'autotrader-v41'
    if fault == 'live': p['live_trading_authorized'] = True
    if fault == 'count': p['maximum_distinct_releases'] = 2
    if fault == 'future': p['task_id'] = 'later-task'
    if fault == 'version': m['version'] = '4.9.3rc1'
    if fault == 'digest': i['image_archive_sha256'] = 'missing'
    if fault == 'archive': Path(i['artifact_files']['images']).write_bytes(b'changed')
    if fault == 'image': i['app'] = 'mutable:latest'
    if fault == 'source': i['source_fingerprint'] = 'e' * 64
    if fault == 'old_commit': m['commit'] = i['commit'] = auth.START_V494
    with pytest.raises(ValueError):
        auth.bind(p, m, i, tmp_path)
    assert not (tmp_path / 'claim.json').exists()
