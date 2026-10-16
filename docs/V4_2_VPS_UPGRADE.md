# V4.2 VPS upgrade: executed historical operation

This report records the operation already in flight when the later local-first approval gate arrived. It is not authorization for another deployment. The application source was authored locally, but the operation preceded the final Git release commit/tag; do not claim that the final Git release is already deployed.

At2026-10-16T11:28:41.288284Z, `autotrader-v41` in `/home/ubuntu/autotrader` ran version 4.2.0, source 072c258fa3820975e493643da00dca779ff43446869c6a5ce268dd054b07d704, schema0011_v42_shadow_isolation. Backend/frontend/worker were healthy, PostgreSQL and Redis OK, public-feed observations3/3, financial reconciliation empty. Official cash/equityEUR 500, no orders/positions, RESEARCH_ONLY, live trading disabled. The loopback ports13000/18000 and URL were preserved.

## Executed gate sequence

Locally authored staging/release scripts ran scoped Docker builds and tests.178 tests passed on UbuntuAMD64. All four exact core AMD64 images passed high/critical scans. The first rollout stopped before backup/migration because host Python lacked httpx. Previous V4.1 writers were restored; a private deployment virtual environment supplied the dependency. The retry stopped only owned writers and performed:

```sh
# Executed on the VPS under the locally authored release wrapper, tag4.2.0:
.tools/deploy-venv/bin/python deploy/vps.py backup --project autotrader-v41 --env-file .env
.tools/deploy-venv/bin/python deploy/vps.py restore --project autotrader-v41 --env-file .env --backup /home/ubuntu/autotrader/.tools/deployments/autotrader-v41/20261016T112748Z-aa22e9.dump
# Candidate ran deploy/verify_clone.py on the new restore DB with migrate=True.
# It verified0010→0011→0010→0011 and unchanged15 table seals before production.
AUTOTRADER_IMAGE_TAG=4.2.0 docker compose -p autotrader-v41 --env-file .env run --rm --no-deps migrate
AUTOTRADER_IMAGE_TAG=4.2.0 docker compose -p autotrader-v41 --env-file .env up -d --wait --no-build --no-deps backend worker frontend
.tools/deploy-venv/bin/python deploy/vps.py verify --project autotrader-v41 --env-file .env
```

Fresh backup SHA2562233c17298a8ae6fa5d24839b1db0f84c57ed53241e0024e90e690840ed82003, verified mode0600 custom archive. Full restoreDBautotrader_restore_c0e9c0d441fb was read-only financially; staged downgrade/reupgrade passed and every15 table seal matched. Production migration left those same financial seals unchanged. Dumps and prior images/source were retained; no volume was deleted. Only the image-tag environment entry changed; other secrets were verified unchanged and stayed on the server.

[evidence/v4_2-vps-deployment.json](evidence/v4_2-vps-deployment.json), [migration gates](evidence/v4_2-vps-migration-gates.json), [migration result](evidence/v4_2-vps-migration-result.json) identify exact images, containers, backups and health. Nginx hashes and protected container IDs/start times matched, including DWRS/REX/SMARTI and owned PostgreSQL/Redis.

## Work stopped at the new instruction

No later production action is claimed: no canonical new research publication to its data volume, no prospective shadow activation, no final public authenticated V4.2 browser acceptance, no deployment of the final commit/tag and no cleanup. The existing frontend was recreated and healthy on loopback, but final public end-to-end verification remains Stage B work. The next approved deployment must verify the current production state afresh rather than assume this snapshot remains current.
