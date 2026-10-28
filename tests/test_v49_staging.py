"""Release regressions for retained identities and fail-closed activation ordering."""
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def staging(monkeypatch):
    monkeypatch.syspath_prepend(str(Path('deploy').resolve()))
    spec = importlib.util.spec_from_file_location('staging_test', Path('deploy/staging_v49.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ledger(identity, strategy, compatible=True, control='PAUSED'):
    return {'experiment_id': identity, 'strategy_id': strategy,
            'portfolio': {'control': control, 'positions': '0', 'pending_orders': '0',
                          'reserved_cash': '0'},
            'runtime_compatibility': {'compatible': compatible}, 'reconciliation': []}


def retained_and_selected():
    selected = {f'new-{i}': f'strategy-{i}' for i in range(7)}
    rows = [ledger('old-1', 'old-strategy', False), ledger('old-2', 'old-strategy', False)]
    rows += [ledger(identity, strategy) for identity, strategy in selected.items()]
    return rows, selected


def test_two_retained_incompatible_ledgers_do_not_authorize_or_block_seven_new_ledgers(staging):
    rows, selected = retained_and_selected()
    result = staging.validate_ledgers(rows, selected, maintenance=True)
    assert result['retained_incompatible_paused'] == ['old-1', 'old-2']
    for row in rows[2:]:
        row['portfolio']['control'] = 'RUNNING'
    staging.validate_ledgers(rows, selected, running=True)
    assert [r['portfolio']['control'] for r in rows[:2]] == ['PAUSED', 'PAUSED']


@pytest.mark.parametrize(('field', 'value'), [('positions', '1'), ('pending_orders', '1'),
                                            ('reserved_cash', '2.5'), ('control', 'RUNNING')])
def test_unknown_retained_runtime_cannot_have_exposure_or_run(staging, field, value):
    rows, selected = retained_and_selected()
    rows[0]['portfolio'][field] = value
    with pytest.raises(ValueError, match='retained_unknown_runtime'):
        staging.validate_ledgers(rows, selected)


@pytest.mark.parametrize('problem', ['missing', 'duplicate', 'wrong_strategy', 'incompatible',
                                     'not_running', 'reconciliation', 'unknown_reconciliation'])
def test_selected_seven_require_exact_identity_runtime_and_financial_health(staging, problem):
    rows, selected = retained_and_selected()
    for row in rows[2:]:
        row['portfolio']['control'] = 'RUNNING'
    if problem == 'missing': rows.pop()
    elif problem == 'duplicate': rows.append(copy.deepcopy(rows[-1]))
    elif problem == 'wrong_strategy': rows[-1]['strategy_id'] = 'other'
    elif problem == 'incompatible': rows[-1]['runtime_compatibility']['compatible'] = False
    elif problem == 'not_running': rows[-1]['portfolio']['control'] = 'PAUSED'
    elif problem == 'reconciliation': rows[0]['reconciliation'] = ['funding_mismatch']
    else: rows[0]['reconciliation'] = None
    with pytest.raises(ValueError):
        staging.validate_ledgers(rows, selected, running=True)


def test_maintenance_rejects_even_compatible_exposure_before_stopping_worker(staging):
    rows, selected = retained_and_selected()
    rows[-1]['portfolio']['positions'] = '1'
    with pytest.raises(ValueError, match='maintenance_requires_all_retained'):
        staging.validate_ledgers(rows, selected, maintenance=True)


@pytest.mark.parametrize('scenario', ['success', 'all_restore_failure', 'pre_restore_failure', 'pre_invalid_result'])
def test_activation_reuses_seven_existing_ledgers_and_requires_all_database_restore_before_resume(
        staging, monkeypatch, tmp_path, scenario):
    restore_passes = scenario == 'success'
    commit = 'a' * 40
    base = tmp_path / 'staging'
    root = base / 'releases' / commit
    evidence = root / 'docs/evidence/v4_9'
    evidence.mkdir(parents=True)
    (base / 'ops').mkdir()
    (base / 'ops/compose').write_text('# previous wrapper\n')
    (base / 'evidence').mkdir()
    gates = {}
    for name in ['backend-tests.json', 'frontend-tests.json', 'browser-tests.json',
                 'linux-tests.json', 'research-summary.json', 'financial-restore.json', 'runtime-compatibility.json', 'restart-recovery.json']:
        data = b'{"status":"PASS"}'
        (evidence / name).write_bytes(data)
        gates[name] = hashlib.sha256(data).hexdigest()
    (evidence / 'staging-readiness.json').write_text(json.dumps(
        {'status': 'PASS', 'source_fingerprint': 'source', 'gates': gates}))
    manifest = {'version': '4.9.0.dev1', 'source_fingerprint': 'source',
                'files': {'src/autotrader/__init__.py': 'file-hash'}}
    (root / 'release-manifest.json').write_text(json.dumps(manifest))
    binding = base / 'images.json'
    images = {'app': 'sha256:' + 'b' * 64, 'frontend': 'sha256:' + 'c' * 64}
    binding.write_text(json.dumps({'commit': commit, **images}))
    rows, selected = retained_and_selected()
    events = []
    primary = {'portfolio': {'risk_state': 'HEALTHY', 'control': 'RUNNING', 'positions': '0',
                            'pending_orders': '0', 'reserved_cash': '0'},
               'performance': {'open_positions': 0}, 'manifest': {'version': '4.9.0-paper.1'},
               'reconciliation': [], 'orders': []}
    backup = {'restore_test': True, 'restore': {'status': 'PASS'}, 'manifest': '/retained/backup.json',
              'candidate_profile_rehearsal': {'status': 'PASS'}}
    monkeypatch.setattr(staging, 'BASE', base)
    monkeypatch.setattr(staging, 'ROOT', root)
    monkeypatch.setattr(staging, 'verify_source_release', lambda *a: None)
    monkeypatch.setattr(staging, 'check_config', lambda *a: None)
    monkeypatch.setattr(staging, 'inventory', lambda: {'services': {
        s: {'image': s, 'volumes': [s + '-retained']} for s in ['postgres', 'redis']}})
    monkeypatch.setattr(staging, 'api', lambda path: copy.deepcopy(
        {'experiments': rows} if path.endswith('/competition') else primary))
    monkeypatch.setattr(staging, 'verify_private_access', lambda: {'status':'PASS'})
    monkeypatch.setattr(staging, 'verify_runtime', lambda *a, **kw: {'status': 'PASS'})

    def run(args, data=None):
        if args[:3] == ['docker', 'image', 'inspect']:
            return json.dumps([{'Architecture': 'amd64', 'Os': 'linux',
                                'Config': {'Labels': {'org.opencontainers.image.revision': commit}}}]).encode()
        if args[:2] == ['docker', 'run']:
            return json.dumps({'__init__.py': 'file-hash'}).encode()
        if staging.LEDGER_INVENTORY in args:
            return json.dumps(rows).encode()
        if str(root / 'deploy/staging_backup.py') in args:
            if '--rehearse-profile' in args:
                events.append('pre_cutover_restore')
                if scenario=='pre_restore_failure':raise RuntimeError('isolated_restore_OOM')
                if scenario=='pre_invalid_result':return b'{"restore_test":false}'
                return json.dumps(backup).encode()
            events.append('all_ledger_restore')
            result = copy.deepcopy(backup)
            result['restore_test'] = restore_passes
            return json.dumps(result).encode()
        if 'up' in args:
            events.append('start_worker' if args[-1] == 'worker' else 'start_services')
        return b'{}'

    def dc(*args):
        if args[0]=='stop':events.append('stop_previous_runtime')
        if staging.RETIRE in args:
            events.append('retire_flat_retained')
            return b'{"status":"PASS"}'
        if staging.SHADOWS in args:
            events.append('reuse_paused_seven')
            return json.dumps({'independent_ledgers': [
                {'experiment_id': identity, 'strategy_id': strategy}
                for identity, strategy in selected.items()]}).encode()
        if staging.SHADOW_RESUME in args:
            assert json.loads(args[-1]) == selected
            events.append('resume_selected_seven')
            for row in rows[2:]: row['portfolio']['control'] = 'RUNNING'
            return json.dumps({'status': 'PASS', 'resumed_experiment_ids': list(selected)}).encode()
        if staging.CONTROL in args:
            action = args[-1]
            events.append(action)
            primary['portfolio']['control'] = 'RUNNING' if action == 'resume' else 'PAUSED'
            if action == 'pause_all':
                for row in rows: row['portfolio']['control'] = 'PAUSED'
        return b'{}'

    monkeypatch.setattr(staging, 'run', run)
    monkeypatch.setattr(staging, 'dc', dc)
    monkeypatch.setattr(sys, 'argv', ['staging.py', 'activate', '--commit', commit,
                                     '--approved-commit', commit, '--images', str(binding), '--wait-flat-seconds', '0'])
    if restore_passes:
        staging.main()
        assert events.index('pre_cutover_restore') < events.index('retire_flat_retained') < events.index('reuse_paused_seven')
        assert events.index('all_ledger_restore') < events.index('start_worker')
        assert events.index('start_worker') < events.index('resume_selected_seven') < events.index('resume')
        assert [r['portfolio']['control'] for r in rows[:2]] == ['PAUSED', 'PAUSED']
    elif scenario.startswith('pre_'):
        expected=RuntimeError if scenario=='pre_restore_failure' else ValueError
        with pytest.raises(expected):staging.main()
        failure=json.loads((base/'evidence'/('v49-'+commit[:12])/'activation-failed.json').read_text())
        assert failure['phase']=='PRE_CUTOVER_BACKUP_RESTORE' and failure['previous_protection_retained']
        assert failure['new_release_activated'] is False and 'stop_previous_runtime' not in events
        assert 'resume' not in events and primary['portfolio']['control']=='PAUSED'
        assert (base/'ops/compose').read_text()=='# previous wrapper\n'
        with pytest.raises(ValueError,match='failed_release_requires_new_verified'):staging.main()
        assert events.count('pre_cutover_restore')==1
    else:
        with pytest.raises(ValueError, match='all_ledger_backup_restore_required'):
            staging.main()
        assert 'resume_selected_seven' not in events and 'resume' not in events
        assert primary['portfolio']['control'] == 'PAUSED'
        assert all(r['portfolio']['control'] == 'PAUSED' for r in rows)
