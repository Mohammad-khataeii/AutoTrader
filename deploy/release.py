"""Create an immutable release locally; verify it without Git on a deployment host."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

FORMAT = 'autotrader-release/v1'
ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {'src', 'alembic', 'frontend', 'deploy', 'scripts', 'tests', 'docs'}
ROOT_FILES = {'.dockerignore', '.env.example', '.gitignore', 'AGENTS.md', 'README.md',
              'pyproject.toml', 'requirements.lock', 'alembic.ini', 'docker-compose.yml', 'docker-compose.mac.yml'}


def allowed(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        return False
    if any(p in {'.git', '.tools', '.data', '.venv', 'node_modules', '__pycache__',
                 'dist', 'test-results', 'playwright-report'} for p in path.parts):
        return False
    if any(p.startswith('.env') for p in path.parts) and name != '.env.example':
        return False
    return (name in ROOT_FILES or (len(path.parts) == 1 and name.startswith('Dockerfile.'))
            or path.parts[0] in DIRECTORIES)


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def verify_release_preflight(root: Path) -> dict:
    """Production activation requires reviewed, source-bound engineering evidence."""
    import tomllib
    version_file = root / 'pyproject.toml'
    version = tomllib.loads(version_file.read_text()).get('project', {}).get('version', '') if version_file.exists() else ''
    if version.startswith('4.7.'):
        raise ValueError('V4.7 is a Mac-only paper development release; VPS deployment is not authorized')
    v46 = version.startswith('4.6.')
    folder = root / ('docs/evidence/v4_6_rc2' if 'rc2' in version else 'docs/evidence/v4_6' if v46 else 'docs/evidence/v4_5_rc2')
    readiness = json.loads((folder/'deployment-readiness.json').read_bytes())
    required = {'backend-tests.json', 'frontend-tests.json', 'amd64-container-tests.json',
                'eight-account-manifest-verification.json', 'v42-runtime-parity.json',
                'v44-runtime-parity.json', 'v45-runtime-identity.json', 'native-entry-acceptance.json',
                'financial-integrity.json', 'nine-database-backup-restore.json',
                'isolated-restart-recovery.json', 'rollback-readiness.json'}
    if v46:
        required = {'tests.json', 'runtime-compatibility.json', 'container-tests.json', 'financial-restore.json'}
    evidence = readiness.get('engineering_evidence', {})
    if readiness.get('recommendation') != 'READY' or not required.issubset(evidence):
        raise ValueError('Release engineering preflight is blocked or incomplete')
    for name, expected in evidence.items():
        if Path(name).name != name or digest((folder/name).read_bytes()) != expected:
            raise ValueError('Release evidence hash mismatch: '+name)
        report = json.loads((folder/name).read_bytes())
        if report.get('engineering_status', report.get('status')) != 'PASS':
            raise ValueError('Release engineering evidence did not pass: '+name)
    package = {str(p.relative_to(root/'src/autotrader')): digest(p.read_bytes())
               for p in sorted((root/'src/autotrader').rglob('*.py'))}
    if digest(canonical(package)) != readiness.get('application_source_fingerprint'):
        raise ValueError('Release evidence belongs to different application source')
    return {'status': 'PASS', 'evidence_files': len(evidence), 'deployment_authorized': False}


def verify_source_release(root: Path, manifest: Path, commit: str) -> dict:
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('A full immutable Git commit is required')
    record = json.loads(manifest.read_bytes())
    if record.get('format') != FORMAT or record.get('commit') != commit:
        raise ValueError('Release manifest identity does not match approved commit')
    files = record.get('files', {})
    required = {'pyproject.toml', 'docker-compose.yml', 'deploy/vps.py',
                'Dockerfile.backend', 'src/autotrader/__init__.py'}
    if not required.issubset(files):
        raise ValueError('Incomplete release manifest')
    for name, expected in files.items():
        if not allowed(name) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Unsafe release manifest entry')
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Release source symlink/outside root refused')
        if not path.is_file() or digest(path.read_bytes()) != expected:
            raise ValueError('Release source hash mismatch: ' + name)
    package = {str(p.relative_to(root / 'src/autotrader')).replace('\\', '/'): digest(p.read_bytes())
               for p in sorted((root / 'src/autotrader').rglob('*.py'))}
    expected_package = {n.removeprefix('src/autotrader/'): h for n, h in files.items()
                        if n.startswith('src/autotrader/') and n.endswith('.py')}
    if package != expected_package or digest(canonical(package)) != record['source_fingerprint']:
        raise ValueError('Unexpected or modified application source')
    return {'commit': commit, 'source_fingerprint': record['source_fingerprint'],
            'files_verified': len(files), 'version': record['version']}


def prepare(ref: str, output: Path, *, root: Path = ROOT) -> dict:
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args])
    if git('status', '--porcelain', '--untracked-files=normal').strip():
        raise ValueError('Commit all local release work before packaging; working tree must be clean')
    commit = git('rev-parse', '--verify', ref + '^{commit}').decode().strip()
    output.mkdir(parents=True, exist_ok=True)
    names = git('ls-tree', '-rz', '--name-only', commit).decode().split('\0')
    blobs = {n: git('show', commit + ':' + n) for n in names if n and allowed(n)}
    # Private credentials and runtime state are never part of a release payload.
    for name, blob in blobs.items():
        if re.search(rb'-----BEGIN (?:OPENSSH|RSA|EC|DSA|ENCRYPTED) PRIVATE KEY-----', blob):
            raise ValueError('Private key material in release entry: ' + name)
    package = {n.removeprefix('src/autotrader/'): digest(b) for n, b in blobs.items()
               if n.startswith('src/autotrader/') and n.endswith('.py')}
    import tomllib
    version = tomllib.loads(blobs['pyproject.toml'].decode())['project']['version']
    record = {'format': FORMAT, 'commit': commit, 'version': version,
              'source_fingerprint': digest(canonical(package)),
              'files': {n: digest(b) for n, b in sorted(blobs.items())}}
    manifest_bytes = json.dumps(record, indent=2, sort_keys=True).encode() + b'\n'
    archive = output / ('autotrader-' + version + '-' + commit[:12] + '.tar.gz')
    if archive.exists():
        raise FileExistsError('Immutable release archive already exists: ' + str(archive))
    with (archive.open('xb') as stream,
          gzip.GzipFile(fileobj=stream, mode='wb', mtime=0) as compressed,
          tarfile.open(fileobj=compressed, mode='w') as tar):
        for name, data in [*sorted(blobs.items()), ('release-manifest.json', manifest_bytes)]:
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o644; info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    manifest = output / (archive.name.removesuffix('.tar.gz') + '.manifest.json')
    manifest.write_bytes(manifest_bytes)
    result = {'commit': commit, 'version': version, 'source_fingerprint': record['source_fingerprint'],
              'files': len(blobs), 'archive': str(archive.resolve()),
              'archive_sha256': digest(archive.read_bytes()), 'manifest': str(manifest.resolve())}
    archive.with_suffix('.sha256').write_text(result['archive_sha256'] + '  ' + archive.name + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    pack = commands.add_parser('prepare'); pack.add_argument('--ref', required=True)
    pack.add_argument('--output', type=Path, required=True)
    check = commands.add_parser('verify'); check.add_argument('--root', type=Path, default=ROOT)
    check.add_argument('--manifest', type=Path, required=True); check.add_argument('--commit', required=True)
    args = parser.parse_args()
    value = prepare(args.ref, args.output) if args.action == 'prepare' else verify_source_release(args.root, args.manifest, args.commit)
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    main()
