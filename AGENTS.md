# AutoTrader development and deployment

All application, strategy, frontend, migration, Docker and deployment-script changes originate in this local repository. Preserve existing uncommitted work and financial/research history. Never develop or patch application source directly on the VPS.

The release workflow is: local implementation → local tests and builds → commit → push to the existing GitHub remote → immutable release package/tag → user approval → VPS backup/restore verification → scoped deployment of that exact commit → verification → scoped cleanup.

Complete Stage A and report the exact commit, push, tests, results and limitations. Stop before Stage B until the user explicitly approves that release. Prior deployment approval does not authorize deployment of a newly changed release under this workflow.

## One-time V4.9.3 task authorization

The human request of 30 October 2026, "AutoTrader V4.9.3 — Intelligent Trading Improvements, ML Repair, Continuous Learning and Automatic Aruba Deployment", explicitly authorizes one unattended release produced by this task. Its request SHA256 is `576553e6385141538e3a85a9fa0e0e4e91ff60013050d1d88d3be97f893144ae`; the starting commit is `1c1b758f80deac18725167c234469cc0895a0120`. The scope and required checks are committed in `deploy/authorizations/v493-once.json`.

For this task alone, continue from successful local implementation, tests, Linux/AMD64 builds, commit/push and immutable release preparation into deployment without another routine human approval. Before any activation, record the full resulting Git SHA, source manifest/archive hashes, image archive hash, canonical image configuration IDs, engineering/financial verification hashes and this task identifier. The versioned V4.9.3 helper must verify that binding and claim a single durable authorization record on Aruba. A different commit or artifact set cannot reuse a claimed authorization. Same-byte healthy verification and a protected same-release resume are permitted; this exception never grants future or arbitrary deployments.

Only SSH alias `aruba-vps`, directory `/opt/personal-plan/staging`, Compose project `autotrader-aruba-test`, ports `127.0.0.1:18000` and `127.0.0.1:13000`, and paper-only execution are authorized. The old `autotrader-v41` production project remains excluded. All other financial-preservation, flat-exposure/deferred-cutover, backup/isolated-restore, source/image identity, runtime-health, rollback, credential and scoped-cleanup requirements remain mandatory. No primary ML weight promotion or unvalidated strategy change is authorized. If identity, scope, authorization, backup, reconciliation or verification cannot be established, stop safely and preserve diagnostics. Candidate corrections must originate locally and receive new immutable identities; a different release after a claimed authorization requires new human authorization.

During Stage A, do not restart production containers, migrate databases, change production configuration or create remote files. Necessary production diagnostics must be read-only and identified. Production credentials and `.env` remain on the VPS. Never open, display, copy or transmit SSH private keys.

Keep `main` untouched. Use the single existing development branch `feature/autotrader-v46-intelligent-opportunity-engine` for all ongoing work; do not create a new branch for each release or task. Consolidate fully incorporated development branches without discarding unique history. For this release, create `v4.6.0-rc.2` only after its verification gates pass. Do not force-push, overwrite an existing tag, or replace production branches. `deploy/release.py` packages committed source and verifies the full commit and file hashes. Production source operations in `deploy/vps.py` require its manifest and the approved full commit.

Keep the Compose project `autotrader-v41`, production URL and existing loopback ports. Preserve PostgreSQL/Redis volumes, all financial history, source/financial backups, required rollback images, Nginx and TLS. Do not touch DWRS, REX Builder, SMARTI or unrelated containers. Never run global prune or `down -v`.

If deployment fails, stop, preserve diagnostics, recover safely if necessary, and fix/test/commit/push the correction locally before a separately approved redeployment. Do not blindly restore over newer financial transactions. Stop deployment on failed backup, migration or reconciliation verification.

Keep real-money trading disabled, use no real exchange orders, preserve official strategy approval gates, keep shadow domains isolated, and never represent historical proxies or synthetic acceptance as prospective market performance. No profitability or completed 30-day claim follows from engineering acceptance.
