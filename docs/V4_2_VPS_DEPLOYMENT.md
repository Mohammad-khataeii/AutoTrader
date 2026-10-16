# V4.2 controlled deployment runbook

Stage A is local only. Stop after the release commit/tag and report READY_FOR_VPS_DEPLOYMENT. The user must explicitly approve that exact release before any Stage B SSH mutation, migration, container restart, data publication, shadow activation or cleanup. AGENTS.md preserves this workflow. An earlier in-flight rollout is documented separately in V4_2_VPS_UPGRADE.md and does not satisfy the approval gate for this final release.

## Stage A: immutable source

```sh
# After all work is committed, tested, pushed and tagged locally:
python3 deploy/release.py prepare --ref v4.2.0 --output .tools/releases/v4.2.0
# Save the emitted full 40-character commit and archive SHA256.
# Verify the published branch and peeled tag with git ls-remote origin.
```

The package is generated from committed Git blobs, not a floating working tree. It includes source/tests/docs and an embedded release-manifest.json; it excludes `.env`, `.tools`, runtime databases/dumps, datasets, node_modules and SSH material. Research-data publication is separate: preserve every existing immutable dataset/run, verify canonical hashes, and publish only the experimental pointer after approval. Do not replace the original historical pointer merely to make a gate pass.

## Stage B: only after explicit approval

Connect with `ssh -o BatchMode=yes autotrader-vps`; check hostname,whoami,uname-m,dockerps, exact application path/project, disk, current source/image identities, schema, health and financial reconciliation. Read-only source comparison excludes credentials/runtime data. Investigate unexplained production-only changes before replacing anything. Keep production `.env` and secrets on the VPS. Preserve source backups and existing Nginx/TLS hashes.

Transfer the approved immutable archive, verify its emitted SHA256, safely extract a release tree and verify:

```sh
python3 deploy/release.py verify --root /path/to/extracted-release --manifest /path/to/extracted-release/release-manifest.json --commit FULL_APPROVED_COMMIT
```

Back up the existing source excluding credentials/runtime volumes. Install only verified release source into the existing project directory, preserving `.env`, `.data`, `.tools`, named volumes, Nginx and TLS. Do not use git reset--hard. The existing tree has noGit, so a verified immutable archive is the supported source identity. Reverify its manifest after copying. Provision a private host deployment venv if needed; the helper requires httpx0.28.1, available in the locked application dependencies. Do not alter system Python.

```sh
# From /home/ubuntu/autotrader, after release verification and explicit approval:
.tools/deploy-venv/bin/python deploy/vps.py upgrade --project autotrader-v41 --env-file .env --release-commit FULL_APPROVED_COMMIT --release-manifest /path/to/verified/release-manifest.json
```

Upgrade builds backend/frontend for the native LinuxAMD64 target while the old runtime serves, stops only owned writers, takes a fresh parsed/checksummed mode0600 PostgreSQL backup outside build directories, fully restores it and each registered shadow domain into new read-only verification clones, reconciles, stages migration and safe rollback where supported, and only then migrates production. Any gate failure stops deployment. Core starts with--no-deps; PostgreSQL/Redis containers and volumes are preserved. Keep old images for rollback. Never use down-v or global prune. Verify actual chosen image IDs against security scans; rebuilds require fresh scan bindings.

For an explicit target build outside the native VPS, use `docker buildx build --platform linux/amd64 ...`; ARM64 local image tests do not establish AMD64 compatibility. The existing Dockerfiles support both; prior native AMD64 candidate evidence is retained, but final local release-tool changes have not been applied remotely under Stage A.

Verify public HTTPS root/assets and authenticated APIs, application4.2, worker heartbeat/scan, PostgreSQL/Redis, fresh genuine Revolut observations, original financial history, officialEUR 500 continuity, RESEARCH_ONLY, failed-strategy rejection, mockAI quotas/livefalse, market health, Nginx hashes and all protected container IDs/start times. No production official BUY should be created for testing.

Only after verified approved release health, start manageable original-B and B2 shadow experiments through authenticated API/dashboard, with frozen source/default parameters and LIVE_MARKET_SHADOW labels. These defaults differ from the historical selected1.5ATR grid. Each gets separate EUR 500; never combine its equity or reset losses. RecordUTCfreeze,30-daydue and coverage; extend sparse runs. Verify their real worker observations/leases and journal reconciliation. Never force an entry, infer a live fill from synthetic tests or auto-promote.

Back up all newly registered domains after activation, verify restores without activating clone workers, retain financial history, and perform scoped cleanup of identified AutoTrader-only temporary artifacts after confirmation. Preserve active/rollback images, all financial backups/volumes, `.env`, Nginx/TLS and every unrelated app. Cleanup has not been performed during the paused Stage A transition.
