# €7,000 crypto challenger upgrade and rollback

This is a Stage A release for the existing crypto development branch. Any subsequent Stage B requires explicit human approval of the full SHA and artifacts. The one-time V4.9.3 authorization applies to its own release. The approved target for any future crypto rehearsal must be confirmed in that approval. The existing Aruba staging scope in the repository is `/opt/personal-plan/staging`, Compose project `autotrader-aruba-test`, and existing loopback ports 18000 and 13000. The old production project is excluded. Use the existing staging configuration and access controls. Keep real trading disabled.

## 1. Prepare the exact source locally

From a clean checkout of the approved crypto commit, the first command is

```sh
python3 deploy/release.py prepare --ref HEAD --output deploy/releases/crypto-7000
```

Record the full commit, returned source fingerprint, source archive hash and manifest hash. If the exact archive already exists, use the existing immutable copy and verify it. Do not overwrite it. Verify an extracted copy and build locally with exact revision labels.

```sh
CRYPTO_COMMIT="$(git rev-parse HEAD)"
CRYPTO_SOURCE="$(mktemp -d)"
CRYPTO_VERSION="$(python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
CRYPTO_SHORT="$(printf "%.12s" "$CRYPTO_COMMIT")"
CRYPTO_ARCHIVE="deploy/releases/crypto-7000/autotrader-$CRYPTO_VERSION-$CRYPTO_SHORT.tar.gz"
test -f "$CRYPTO_ARCHIVE" && tar -xzf "$CRYPTO_ARCHIVE" -C "$CRYPTO_SOURCE"
python3 deploy/release.py verify --root "$CRYPTO_SOURCE" \
  --manifest "$CRYPTO_SOURCE/release-manifest.json" --commit "$CRYPTO_COMMIT"
docker build --platform linux/amd64 --build-arg RELEASE_COMMIT="$CRYPTO_COMMIT" \
  -f "$CRYPTO_SOURCE/Dockerfile.backend" -t "autotrader-app:$CRYPTO_COMMIT" "$CRYPTO_SOURCE"
docker build --platform linux/amd64 --build-arg RELEASE_COMMIT="$CRYPTO_COMMIT" \
  -t "autotrader-frontend:$CRYPTO_COMMIT" "$CRYPTO_SOURCE/frontend"
docker save "autotrader-app:$CRYPTO_COMMIT" "autotrader-frontend:$CRYPTO_COMMIT" | \
  gzip > "deploy/releases/crypto-7000/images-$CRYPTO_COMMIT.tar.gz"
```

Run each step with failure checking. Verify archive hashes, image platform, revision label, and the canonical image config digests before approving a transfer. Use the source manifest, build/test evidence and a release-bound staging activation helper reviewed for the exact candidate. The existing `deploy/operate_v496.py` and `deploy/staging_v496.py` encode a different release. A release-bound activator for this candidate must be supplied and verified before a VPS cutover. `deploy/vps.py` rejects V4.9 production activation.

## 2. Record the current profile and prove recovery

After approval, identify the exact primary database through the existing staging registry. Use the authorized read-only view at `/api/personal-paper` through existing dashboard authentication. Record `manifest`, `runtime_matches`, portfolio cash/reserves/equity, open positions and outstanding intents, the reconciled journal, and the backend source identity. Store the records privately. Keep the origin and active profile hashes distinct.

The candidate leaves the fetched branch's primary runtime fingerprint at `8568cac192b61bec09e6c67716d82eb04a16ebea236d3ed11a78ed8ddd096e4d`. It introduces no database schema migration or primary profile revision. Compare this fingerprint with the active staged manifest. A staged account can be on an older profile even when the repository branch is current. If they differ, keep the existing worker protecting positions and defer the worker replacement. A dashboard-only upgrade may be rehearsed separately against the deployed API contract. Never edit the active or origin manifest to resolve a mismatch.

After approval and once the candidate image is verified locally and loaded on the approved host, the existing staging backup utility supports the following commands from an extracted verified release. Inspect the capacity report and require all retained databases to reconcile in an isolated restore.

```sh
CRYPTO_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "autotrader-app:$CRYPTO_COMMIT")"
python3 deploy/staging_backup.py --capacity-only \
  --image-bytes "$CRYPTO_IMAGE_BYTES_PENDING" --transfer-bytes "$CRYPTO_TRANSFER_BYTES_PENDING"
python3 deploy/staging_backup.py --restore-test --candidate-image "$CRYPTO_IMAGE_ID"
```

Use zero for either pending byte budget only when those bytes are already on disk. Where staging capacity requires the supported off-host rehearsal, use `--plan-offhost-restore`, transfer the exact protected backup set to the approved isolated restore host, verify its hash, and run `--restore-from` with `--manifest-sha256`, `--candidate-image` and `--restore-evidence`. Require evidence covering the old image, candidate image, immutable database identity and profile, one original €7,000 funding event, per-table financial seals, and all retained account ownership. Keep the backup manifest and dump files private.

Pause new primary entries through the existing control after recording its prior state. Let existing positions and pending orders reconcile through their incumbent monitor and stored exit plans. Defer full replacement until exposure is flat and no orders, reservations or exit intents are pending in the affected scope. Capture the final backup/seal in that quiescent state. An emergency flatten is a separate order action and requires its own instruction. Preserve the original and active manifest records, position plans, database identity marker, volumes, rollback images, Nginx, TLS and private access.

## 3. Replace the application and verify

Only a reviewed, exact-commit staging operation may replace application images. Bind the source archive and image configuration IDs to the approved SHA. Scope the Compose operation to the approved services and keep database/cache volumes and unrelated applications intact. The candidate needs no Alembic action or active profile pointer update. Preserve the pre-cutover entry control state until verification and operator review.

Require `/readyz` to confirm paper-only authority and dependency health. Check the expected full release SHA from health/provenance and the running image IDs from the approved scope. Compare primary manifest hash, account ID, cash, reserves, position and order counts, equity and realized P&L against the quiescent seal. Verify one funding event, all historical fills and journal rows, no reattribution in storage, healthy protective heartbeat, and empty reconciliation errors. Check all affected official and shadow accounts for unchanged authority and isolation. Test authenticated dashboard reads and the challenger endpoint. Any financial or health failure stops cutover before entry controls are restored.

## 4. Run the forward challenger independently

Use a separate unprivileged process with public HTTP access, private output storage, and no database or exchange credentials. Prefer an isolated research host with its own public request budget. The collector issues at most one ticker scan, two benchmark details, and two extra market details, and up to two candle-only outcome refreshes per five-minute cycle after cache warm-up. It uses Revolut X public per-endpoint pacing. Keep the primary feed's protective priority and capacity isolated. Monitor public 429s, missed cycles, market validation errors and free disk. The report exposes censored paths and incomplete market coverage. [Revolut X REST API](https://developer.revolut.com/docs/api/revolut-x-crypto-exchange)

Choose future UTC boundaries and budget enough time for at least 30 independent observation days in each later interval. On the research host, use the candidate wheel or the verified source on `PYTHONPATH`.

```sh
PYTHONPATH=src python3 -m autotrader.crypto_research register "$CRYPTO_RESEARCH_DIR" \
  --start "$CRYPTO_START_UTC" --development-end "$CRYPTO_DEV_END_UTC" \
  --holdout-end "$CRYPTO_HOLDOUT_END_UTC" --shadow-end "$CRYPTO_SHADOW_END_UTC"
PYTHONPATH=src python3 -m autotrader.crypto_research collect "$CRYPTO_RESEARCH_DIR"
PYTHONPATH=src python3 -m autotrader.crypto_research report "$CRYPTO_RESEARCH_DIR" \
  --output "$CRYPTO_RESEARCH_DIR/report.json"
```

Run `collect` under the research host's process supervisor, once per registered directory. `--once` supports a scheduled one-cycle invocation. The collector refuses an overlapping writer, registers prior to the first window, and preserves every successfully captured bucket with write-once creation. Retain the source release, registration and captures. A changed rule needs a new registration and fresh holdout. Publish only the generated report through the already-approved research volume writer to `$RESEARCH_ROOT/crypto-7000/report.json`, atomically and with readable permissions for the backend account. Keep raw captures off the app and avoid any setup that needs staging trading credentials. The authenticated route `/api/personal-paper/challenger` exposes the report read-only. An absent report produces `INSUFFICIENT_EVIDENCE`.

## 5. Review and approve a future strategy transition

Use the ledger to review incumbent realized net performance and trade ownership. Use the prospective report to review discovery breadth, data coverage, outcome counts, bootstrap interval, drawdown, normal versus stressed costs, and whether results persist across the untouched holdout and subsequent forward window. Public-book entry projections and candle exits are proxies. A transition also needs matched incumbent/challenger evidence from a separately approved executable-depth research method, including adverse depth scenarios and stale/outage handling. Require reproducible data and recipe hashes, per-regime trade counts, independent risk review, and explicit human authorization for the new exact strategy release.

Implement any proposed authority change locally as a new immutable version and profile revision using `PersonalPaperService.create_runtime_revision` after reviewing its prerequisites. Verify the expected parent profile hash and paused control before pointer changes. Rehearse against a verified isolated restore and compare the old and new profile identities, funding, balances, positions, fills, orders, exit plans, reservations and journal. Adopt the new profile only after protection and reconciliation pass. A report, UI status, or local recipe cannot activate or approve a strategy.

## 6. Roll back

Stop a failed cutover while preserving diagnostics and newly recorded evidence. Keep the appropriate incumbent protective worker running if exposure exists. Roll back to the retained, verified prior application images and configuration with the same scoped Compose project and existing volumes. This release changes no schema or profile, so rollback requires no profile rewrite or financial restore. Recheck runtime fingerprint, reconciliation, active control state, pending orders, exit-plan ownership, service health and private access. If a later deployment has advanced the profile or posted financial activity, reconcile against the latest durable records before any database recovery. Never overwrite new transactions from a stale dump. Preserve all backups, release manifests, research reports and required rollback images. Use only scoped cleanup.
