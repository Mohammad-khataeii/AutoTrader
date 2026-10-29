# V4.9.1 staging release handoff

This is a primary-only paper admission update for the existing Aruba staging deployment, Compose project `autotrader-aruba-test`. The old production server and real exchange execution are excluded. The release preserves seventeen databases, the original €7,000 account funding, all fills and financial history, seven original forward controls, eight archived controls, private Tailscale access, loopback ports, database volumes and rollback images.

## Stage A release identity

The immutable source archive's `release-manifest.json` provides the full commit, version, source fingerprint and every packaged file hash. `deploy/release.py verify` checks that exact identity. The matching Git tag is `v4.9.1-rc.1`; an existing tag must never be overwritten. Application source fingerprint is `308e8e1ea0e1dd904c38ed6e4abb16214bc156e7d68a732db6ac27d42bb2b48b` (280 Python files), primary runtime fingerprint `bddd32eae4c72058c583cd55684622b86a12527067b7c6b8941613207c49535c`, and unchanged shadow execution fingerprint `44264f01586fedbd62e949f142c8240bb2dd9bae86c454fb17d388e2f5d9559c`.

Source-bound gates and their hashes are in `docs/evidence/v4_9_1/staging-readiness.json`. The native full run initially passed 445 cases and exposed one legacy diagnostic exception compatibility mismatch. That script-only correction passed a six-case focused recheck. The installed Linux run independently covers all non-host cases; host Docker lifecycle and memory-cap cases are verified natively. Detailed original results and the correction are retained in the backend gate rather than hidden. No application change occurred after the source freeze.

The local financial rehearsal restored all seventeen current exports into a network-isolated PostgreSQL instance with no host ports. It upgraded only the primary profile to `4.9.1-paper.1`, preserved €6,961.614219600281 cash and sixteen lifetime fills, retained all original financial-table hashes, and left all fifteen shadow manifests unchanged. The installed product API started, rejected unauthenticated access, reconciled the upgraded clone and exposed the historical entry concerns and detailed exit condition. These are local engineering checks; current VPS feed/worker/UI verification remains a Stage B gate.

## Exact release approval and Stage B

The full pushed commit must be explicitly approved after the completed Stage A report, as required by `AGENTS.md`. Until then, no release upload, remote configuration change, migration or restart is authorized under this workflow. Read-only diagnostics are allowed and do not constitute deployment.

After exact approval:

1. Verify the local source archive, image archive hashes and canonical Linux AMD64 image binding. Desktop Docker can report an OCI index ID where the VPS reports the platform config ID: derive both from the same saved archive, verify config/layer/revision hashes, and use the canonical config ID for the VPS. Never substitute an arbitrary image or retag changed bytes.
2. Transfer only the immutable artifacts to staging, verify hashes, extract beneath `/opt/personal-plan/staging/releases/<full-commit>`, and load the exact images. Keep credentials and `.env.staging` on the VPS.
3. Execute that release's `deploy/staging_v491.py activate` with `--commit <full-commit>`, the same `--approved-commit`, the canonical image binding, and a bounded `--wait-flat-seconds` (up to 21600 seconds). Capture its evidence and exit status. Do not use the older V4.9 provisioning helper for this upgrade.
4. The helper validates all gates and source/image identities; preserves Tailscale configuration; pauses new entries; retains existing protection while waiting for **every** retained ledger to become flat; performs a fresh seventeen-database backup, isolated restore and candidate-profile rehearsal; then cuts over the exact source/images without changing PostgreSQL/Redis volumes or images.
5. Before resuming entries, it verifies all fifteen retained control manifests, performs another seventeen-database backup/restore, checks new primary context observations and fresh worker monitoring, and resumes the same seven original compatible controls and the primary. No artificial order is forced merely to demonstrate a fill.
6. Verify the private dashboard, genuine market feeds, all control states, paper execution policy, fills/order reconciliation, source/image identity and logs. Compare original financial history, funding counts, PostgreSQL/Redis volumes and Tailscale Serve hash to the preflight. Preserve source/financial backups and rollback images. Cleanup may remove only uniquely owned successful disposable verification resources.

On a failed backup, restore, reconciliation or activation check, stop. Preserve evidence and existing position protection. Never blindly restore a database over newer transactions. Image-only rollback is permitted by the helper only while all ledgers are known flat; the previous image remains in monitoring mode with entries paused. Any correction originates locally and requires its own tested, committed, pushed and separately approved release.

## Performance limits

This is a cautious engineering and policy correction, not a validated profitable model. Known losing entries are development cases. Two previously blocked A3 proposals pass the new guard, so filtered known losses cannot be treated as upgraded-strategy returns. Forward comparisons retain their original hypotheses and different sizing policies. No 30-day, positive-expectancy, independent-win-rate or real-money claim follows from this release.
