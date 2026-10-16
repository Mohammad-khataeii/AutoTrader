import importlib.util
import json
import subprocess
import tarfile
from pathlib import Path

import pytest


def release_module():
    spec = importlib.util.spec_from_file_location('release_helper', Path('deploy/release.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def committed_fixture(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    files = {'pyproject.toml': '[project]\nname="fixture"\nversion="4.2.0"\n',
             'docker-compose.yml': 'services: {}\n', 'Dockerfile.backend': 'FROM scratch\n',
             'deploy/vps.py': '# fixture\n', 'src/autotrader/__init__.py': '__version__="4.2.0"\n',
             '.env': 'PRIVATE_RUNTIME_ONLY=never-in-release\n', 'autotrader.db': 'private runtime',
             '.env.example': 'DASHBOARD_PASSWORD=REPLACE_ME\n'}
    for name, content in files.items():
        p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()
    git('init'); git('config', 'user.name', 'Release Fixture'); git('config', 'user.email', 'test@example.invalid')
    git('add', '.'); git('commit', '-m', 'fixture')
    return root, git('rev-parse', 'HEAD')


def test_immutable_release_excludes_runtime_and_verifies_extracted_commit(tmp_path):
    module = release_module(); root, commit = committed_fixture(tmp_path)
    result = module.prepare(commit, tmp_path / 'out', root=root)
    extracted = tmp_path / 'extracted'; extracted.mkdir()
    with tarfile.open(result['archive']) as archive:
        names = archive.getnames()
        assert '.env' not in names and 'autotrader.db' not in names and '.env.example' in names
        archive.extractall(extracted, filter='data')
    check = module.verify_source_release(extracted, extracted / 'release-manifest.json', commit)
    assert check['commit'] == commit and check['version'] == '4.2.0'
    assert check['source_fingerprint'] == result['source_fingerprint']


def test_release_rejects_dirty_tree_and_refuses_overwriting_archive(tmp_path):
    module = release_module(); root, commit = committed_fixture(tmp_path)
    module.prepare(commit, tmp_path / 'out', root=root)
    with pytest.raises(FileExistsError):
        module.prepare(commit, tmp_path / 'out', root=root)
    (root / 'src/autotrader/__init__.py').write_text('changed')
    with pytest.raises(ValueError, match='working tree must be clean'):
        module.prepare(commit, tmp_path / 'out', root=root)


def test_release_refuses_changed_unknown_source_and_wrong_commit(tmp_path):
    module = release_module(); root, commit = committed_fixture(tmp_path)
    result = module.prepare(commit, tmp_path / 'out', root=root)
    manifest = Path(result['manifest'])
    with pytest.raises(ValueError, match='full immutable'):
        module.verify_source_release(root, manifest, 'HEAD')
    with pytest.raises(ValueError, match='identity'):
        module.verify_source_release(root, manifest, '0' * 40)
    (root / 'src/autotrader/extra.py').write_text('unexpected')
    with pytest.raises(ValueError, match='Unexpected'):
        module.verify_source_release(root, manifest, commit)
    (root / 'src/autotrader/extra.py').unlink()
    (root / 'Dockerfile.backend').write_text('FROM other')
    with pytest.raises(ValueError, match='hash mismatch'):
        module.verify_source_release(root, manifest, commit)


def test_release_refuses_path_traversal_and_source_symlinks(tmp_path):
    module = release_module(); root, commit = committed_fixture(tmp_path)
    result = module.prepare(commit, tmp_path / 'out', root=root); manifest = Path(result['manifest'])
    record = json.loads(manifest.read_text()); record['files']['../outside'] = '0' * 64
    manifest.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='Unsafe'):
        module.verify_source_release(root, manifest, commit)
    del record['files']['../outside']; manifest.write_text(json.dumps(record))
    target = root / 'Dockerfile.backend'; target.unlink(); target.symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError, match='symlink'):
        module.verify_source_release(root, manifest, commit)


def test_production_source_operation_requires_immutable_release_before_secrets_or_docker():
    result = subprocess.run(['python3', 'deploy/vps.py', 'upgrade', '--project', 'autotrader-v41',
                             '--env-file', '/nonexistent/private.env'], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert 'require --release-commit and --release-manifest' in result.stderr
    assert 'FileNotFoundError' not in result.stderr
