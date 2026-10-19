# AutoTrader development and deployment

All application, strategy, frontend, migration, Docker and deployment-script changes originate in this local repository. Preserve existing uncommitted work and financial/research history. Never develop or patch application source directly on the VPS.

The release workflow is: local implementation → local tests and builds → commit → push to the existing GitHub remote → immutable release package/tag → user approval → VPS backup/restore verification → scoped deployment of that exact commit → verification → scoped cleanup.

Complete Stage A and report the exact commit, push, tests, results and limitations. Stop before Stage B until the user explicitly approves that release. Prior deployment approval does not authorize deployment of a newly changed release under this workflow.

During Stage A, do not restart production containers, migrate databases, change production configuration or create remote files. Necessary production diagnostics must be read-only and identified. Production credentials and `.env` remain on the VPS. Never open, display, copy or transmit SSH private keys.

Keep `main` untouched. Use the single existing development branch `feature/autotrader-v46-intelligent-opportunity-engine` for all ongoing work; do not create a new branch for each release or task. Consolidate fully incorporated development branches without discarding unique history. For this release, create `v4.6.0-rc.1` only after its verification gates pass. Do not force-push, overwrite an existing tag, or replace production branches. `deploy/release.py` packages committed source and verifies the full commit and file hashes. Production source operations in `deploy/vps.py` require its manifest and the approved full commit.

Keep the Compose project `autotrader-v41`, production URL and existing loopback ports. Preserve PostgreSQL/Redis volumes, all financial history, source/financial backups, required rollback images, Nginx and TLS. Do not touch DWRS, REX Builder, SMARTI or unrelated containers. Never run global prune or `down -v`.

If deployment fails, stop, preserve diagnostics, recover safely if necessary, and fix/test/commit/push the correction locally before a separately approved redeployment. Do not blindly restore over newer financial transactions. Stop deployment on failed backup, migration or reconciliation verification.

Keep real-money trading disabled, use no real exchange orders, preserve official strategy approval gates, keep shadow domains isolated, and never represent historical proxies or synthetic acceptance as prospective market performance. No profitability or completed 30-day claim follows from engineering acceptance.
