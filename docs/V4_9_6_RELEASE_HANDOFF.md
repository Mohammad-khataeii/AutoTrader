# V4.9.6 · Aruba staging handoff

The candidate is paper-only and **activation is blocked**. No tests were run by request. No tag or prior unattended authorization applies to this release. The helper requires passing reviewed evidence bound to the exact commit and source fingerprint, plus explicit approval of that commit. Do not use a direct Compose replacement to bypass these gates.

### Prepare immutable artifacts locally

Run from this repository on the existing development branch. Use the full SHA reported with the handoff.

```bash
commit=$(git rev-parse HEAD)
out="$PWD/deploy/releases/$commit"
python3 deploy/release.py prepare --ref "$commit" --output "$out"
archive="$out/autotrader-4.9.6rc1-${commit:0:12}.tar.gz"
mkdir -p "$out/source"
tar -xzf "$archive" -C "$out/source"
python3 deploy/release.py verify --root "$out/source" --manifest "$out/source/release-manifest.json" --commit "$commit"

docker buildx build --platform linux/amd64 --provenance=false --load --build-arg RELEASE_COMMIT="$commit" \
  -f "$out/source/Dockerfile.backend" -t "autotrader-app:$commit" "$out/source"
docker buildx build --platform linux/amd64 --provenance=false --load --build-arg RELEASE_COMMIT="$commit" \
  -t "autotrader-frontend:$commit" "$out/source/frontend"
docker save "autotrader-app:$commit" "autotrader-frontend:$commit" | gzip -n > "$out/images.tar.gz"
cp "$archive" "$out/source.tar.gz"
python3 - "$out" "$commit" <<'PY'
import hashlib, json, pathlib, sys, tarfile
out, commit = pathlib.Path(sys.argv[1]), sys.argv[2]
def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()
with tarfile.open(out/'images.tar.gz', 'r:gz') as archive:
    manifest = json.load(archive.extractfile('manifest.json'))
    def image(name):
        tag = 'autotrader-' + name + ':' + commit
        row, = (r for r in manifest if tag in (r['RepoTags'] or []))
        config = archive.extractfile(row['Config']).read()
        data = json.loads(config)
        assert (data['os'], data['architecture'], data['config']['Labels']['org.opencontainers.image.revision']) == ('linux', 'amd64', commit)
        return 'sha256:' + hashlib.sha256(config).hexdigest()
    binding = dict(commit=commit, app=image('app'), frontend=image('frontend'),
                   manifest_sha256=sha(out/'source/release-manifest.json'),
                   source_sha256=sha(out/'source.tar.gz'), images_sha256=sha(out/'images.tar.gz'))
(out/'binding.json').write_text(json.dumps(binding, indent=2)+'\n')
PY
(cd "$out" && shasum -a 256 source.tar.gz images.tar.gz binding.json > SHA256SUMS)
```

### Replace the existing staging app after the gates pass

The following commands are for the operator **after tests, evidence review, and explicit approval of this commit**. The reviewed directory must contain `staging-readiness.json` and the passing reports named in `deploy/staging_v496.py`. The reports must bind status, full commit, and source fingerprint; the readiness record must include their SHA-256 hashes. No such evidence was generated for this handoff.

1. Record which spot accounts were running. Pause new entries for the official, personal, and active shadow accounts in the existing dashboard. Leave the worker running to protect existing exposure. Wait until all positions, reservations, and pending orders are zero. If they do not flatten or health fails, defer replacement.
2. Transfer only the approved immutable artifacts and evidence:

```bash
remote=/opt/personal-plan/staging
ssh aruba-vps "umask 077; mkdir '$remote/incoming/$commit' '$remote/releases/$commit'"
scp "$out/source.tar.gz" "$out/images.tar.gz" "$out/binding.json" "$out/SHA256SUMS" \
  "aruba-vps:$remote/incoming/$commit/"
scp -r "$out/reviewed" "aruba-vps:$remote/incoming/$commit/"
ssh aruba-vps "set -eu
  cd '$remote/incoming/$commit'
  sha256sum -c SHA256SUMS
  tar -xzf source.tar.gz -C '$remote/releases/$commit'
  docker load -i images.tar.gz
  python3 '$remote/releases/$commit/deploy/staging_v496.py' preflight --commit '$commit'
  python3 '$remote/releases/$commit/deploy/staging_v496.py' activate --commit '$commit' --approved-commit '$commit'
  python3 '$remote/releases/$commit/deploy/staging_v496.py' verify --commit '$commit'"
```

3. The helper verifies the previous controls, restores all 17 backups in isolation, checks the flat cutover and retained volumes/images, then replaces backend, frontend, spot worker and research worker and starts the independent perpetuals worker. It verifies the second restore, the unchanged spot financial seals, lab tables and feed freshness. It leaves all entries paused. Resume only the spot accounts that were running before maintenance. When ready to start the experiment, open **Perpetuals** and select **Enable paper entries**.
4. If any command fails, leave entries paused and retain `/opt/personal-plan/staging/evidence/v496-<short SHA>` and the backups. The saved previous Compose and backup wrappers and image IDs are the recovery inputs. Verify current exposure is flat before stopping any protective worker. The lab migration leaves the old spot schema revision alone, so verified image recovery can use the previous wrapper without restoring over financial history. If exposure is unknown or open, keep protection and investigate. Do not replay an old authorization, overwrite a release, or restart unrelated services.

Do not run global prune or remove volumes, dumps, source releases, active images, or the previous rollback images. A future scoped server cleanup should name the specific disposable tags and confirm no running or stopped container uses their image IDs. This handoff targets only the Aruba staging project and its existing loopback ports.
