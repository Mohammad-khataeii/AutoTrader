# V4.2 local baseline and workflow transition

Local repository `/Users/mohammadkhataei/Desktop/AutoTrader`; existing origin `https://github.com/Mohammad-khataeii/AutoTrader.git`. Starting commit94ab72138c0793b521a2a6851c67793a2344ff7d on `v4-execution-research` was V4.1. Work was preserved and moved to the requested `feature/autotrader-v4.2`; no repository was reinitialized, force-pushed or reset.

Original package fingerprint e0140ff18c36d86ac4c676e07aa650c2d93bac3fcfa6b708e0025f6573d66c5e; schema0010_v41_ai_quotas. Baseline148 tests passed without failures/skips against real local PostgreSQL. Original research833 positions/2,204 fills and all 12 simulations are frozen and reproduced exactly. See V4_2_BASELINE_AUDIT.md and its artifact hashes.

## Production-only differences reconciled

The preserved production V4.1 source is an extracted tree, without Git metadata; no production Git revision can honestly be asserted. A necessary read-only comparison of the pre-upgrade source backup excluded `.env`, credentials, database files and logs. [Hashes](evidence/v4_2-production-source-comparison.json) show pyproject, Compose, authentication code and deployment helper matched local V4.1. Dockerfile.backend contained an extra `RUN chmod -R a+rX /app` repair. V4.2 incorporates its purpose with narrower allowlisted0644files/0755directories before package installation, root ownership and UID10001 read-only verification. The global chmod is not blindly copied over secrets.

The V4.1 fresh-install ordering defect was present in the matching source helper despite successful manual production initialization. V4.2 now probes actual schema/financial state, migrates before fresh funding, and requires verified backup/restore plus cloned migration for populated upgrades. Existing dashboard Basic-authentication code matched; no production credential was copied or reset. The environment generator was outside the preserved source archive and was not compared; no unsupported absence claim is made.

## Workflow transition and actual production state

Before the later local-first instruction arrived, the user had explicitly authorized the V4.2 VPS upgrade. That in-flight operation completed at2026-10-16T11:28:41.288284Z: application4.2.0, schema0011, official EUR 500, zero orders/positions, RESEARCH_ONLY, live=false, healthy worker/PostgreSQL/Redis and empty reconciliation. All15 financial table seals matched across migration. Nginx and protected container IDs/start times were unchanged. Source was locally authored but not yet a committed release. This deployment must not be represented as deployment of the later approved Git release.

When the new instruction was read, further production changes stopped. No prospective production shadow experiments were activated, no release data was subsequently seeded, no remote cleanup was performed, and no later local source/release changes were sent. Verification records were retrieved read-only. Current Stage A prepares an immutable tested Git release; any further deployment or shadow activation requires explicit user approval. Existing active V4.2 therefore differs in deployment tooling/documentation from the final Stage A release; exact commit equivalence is unverified until approved redeployment.

Local Mac / Docker architecture is ARM64; VPS is Linux AMD64. Both native local Docker builds and actual AMD64 candidate builds were tested previously. The new workflow forbids additional remote builds/tests during Stage A. Compatibility risks: schema0011 downgrade refuses nonempty shadow history; restore clones cannot follow production shadow pointers; existing immutable research files must never be overwritten; source mismatch blocks shadow entries while protection continues; no validated strategy exists.
