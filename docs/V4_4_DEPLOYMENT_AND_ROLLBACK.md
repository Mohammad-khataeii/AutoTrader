# V4.4 approval-gated deployment and rollback

This is a plan, not a record of executed production operations. Stage A stops after local verification, commit, push and immutable packaging. Existing permission to deploy an older release does not authorize this commit. Approval must identify the full SHA in the V4.4 release manifest.

## Release identity and local compatibility

Use `feature/autotrader-v44-engine-and-ux` and a new immutable `v4.4.0` tag. Never overwrite `v4.2.0`, force-push, or replace a production branch. `deploy/release.py` packages committed source and hashes every released file. After approval, verify the archive checksum and extracted tree against the exact approved SHA:

```sh
python3 deploy/release.py verify --root "$RELEASE_DIR" \
  --manifest "$RELEASE_DIR/release-manifest.json" --commit "$APPROVED_FULL_SHA"
```

The [before](evidence/v4_4/local-compatibility-before.json) and [after](evidence/v4_4/local-compatibility-after.json) read-only reports cover four dedicated local PostgreSQL V4.2 accounts: three B2 and one A2, two active and two stopped. Every original manifest hash and the source `9f03f481049165cba9b54082d6f45f6e06e76d4b0a1625832b5f8434f8ace23a` remain. All four reconcile and select `verified-v42`; occupied slots remain four. Test account IDs are synthetic and are not production identities. The legacy lifecycle additionally proves an accepted original A2 BUY, five fills, partial-target crash recovery and zero official-account financial activity.

There is no V4.4 DDL migration. Schema must remain the existing V4.2 revision; any unexpected revision or financial-seal change blocks deployment. Original manifests do not gain V4.4 fields. No new experiment, archive or extra funding is created automatically.

## Approved Stage B sequence

1. Connect using the already configured SSH host alias only after approval. Keep all credentials and `.env` on the VPS; never open/copy private keys. Inventory the existing `autotrader-v41` Compose services, images, ports, Nginx/TLS and mounted research/financial volumes. Record unrelated-container identities so the final check can establish they were untouched. Preserve existing API/frontend loopback ports and production URL.
2. Capture authenticated health, full reconciliation and the exact four registry manifests/identity hashes without operator state changes. Record worker/protection heartbeats, open positions, outstanding orders, balances, latest journal keys and approval state. Stop on an unknown source/identity or inconsistent ledger. Verify no real-money capability is enabled.
3. Preserve rollback image IDs and the existing application source package. Build the exact approved source for Linux AMD64, scoped to backend/frontend. Do not rebuild/restart PostgreSQL, Redis or unrelated services. Local ARM64 build acceptance is not a substitute for this check.
4. Quiesce only AutoTrader's worker/backend/research-worker for a coordinated backup window. Account PAUSED/STOPPED states and frozen experiment manifests must not be changed to implement a deployment pause. With open positions, plan the brief monitoring interruption explicitly and recover with scoped images if the preflight fails.
5. Create a custom-format PostgreSQL backup of the official database **and every registered shadow database**, including archived domains. Parse each dump, verify checksums and restore into fresh isolated databases. The existing `deploy/vps.py backup`/`restore` path preserves original databases and verifies financial seals; its shadow registry must have no CREATING entries. Preserve all original dumps, volumes and rollback images. Never restore a dump over active financial data.
6. Validate candidate schema and rollback behavior against the restored domains. Do not start a worker against an official clone whose registry still names production shadow databases. Use a separate isolated PostgreSQL cluster with original database names, or a reviewed test mapping with external access to production domains denied. Verify all original manifest JSON and identity hashes, original source fingerprint, account identities, full ledger reconciliation, no duplicated funding and protective monitoring under `verified-v42`. Run `verify_legacy()` in the installed candidate wheel. Unknown runtime/tampering blocks release even if readiness is green.
7. Inspect actual research-volume paths and both original/experimental latest pointers. Verify immutable report hashes and all referenced datasets. The existing original-only sync command does not publish the experimental pointer. If publication is missing, prepare a separate hash-verified immutable publication and review the pointer update; preserve every existing valid report. A historical source mismatch never authorizes an official strategy or a synthetic prospective claim.
8. Once every prerequisite passes, run the manifest-gated scoped upgrade from the approved extraction. The existing command is below; it repeats coordinated backup/restore and migration checks. Its generic verification must be supplemented by the V4.4 frozen-runner checks above and the authenticated compatibility endpoint afterward. It is not sufficient by itself to establish legacy compatibility.

```sh
python3 deploy/vps.py upgrade --project autotrader-v41 \
  --env-file /home/ubuntu/autotrader/.env \
  --release-commit "$APPROVED_FULL_SHA" \
  --release-manifest "$RELEASE_DIR/release-manifest.json"
```

9. Verify backend and public frontend `/readyz` are JSON and real-money disabled; official equity/journal continuity; four original identities/manifests; `/api/release/compatibility` COMPATIBLE; original active/stopped states; exact legacy runner; worker and protection heartbeats; fresh completed scans; actual new shadow explanations; full reconciliation; authenticated exports; negative published research; public dashboard at mobile/desktop widths. Compare unrelated containers, ports, Nginx and TLS with the recorded inventory. Record the actual commit/image IDs, before/after financial seals and measurement windows.
10. Keep rollback images, backups and all volumes. Cleanup is scoped to this release's disposable clones and temporary files after verified success and reviewed retention; never run global prune, `down -v`, or remove shared/unrelated containers. A deployment failure stops the workflow, preserves diagnostics and requires a locally tested, committed, pushed correction and new approval.

## Rollback constraints

Prefer a scoped rollback to the recorded previous AutoTrader image IDs using the saved release record, without migrating or restoring over current transactions:

```sh
python3 deploy/vps.py rollback --project autotrader-v41 \
  --env-file /home/ubuntu/autotrader/.env --release "$VERIFIED_RELEASE_RECORD"
```

The existing helper refuses a schema mismatch and retains PostgreSQL/Redis volumes; it does not run a destructive downgrade. Reconcile after rollback. If a schema ever changes, restore a backup into a new isolated database for review; never blindly overwrite later financial transactions.

For the **original four V4.2 accounts before any V4.4-only account/archive action**, original source-pinned execution and repository semantics remain available. A regression test reads their upgraded additive observations with the original verified V4.2 repository, unchanged manifests, journal and reconciliation. New observation metadata is ignored by the old implementation. Existing migration tests also cover transactional injected failure, downgrade and re-upgrade with identical financial history.

Once V4.4 native accounts have been created, they require a runtime that supports their frozen execution fingerprint. A V4.2 image cannot authorize their BUYs under its original full-source check. Once archival has released a slot, the old registry lacks that membership concept: it will show archived STOPPED records and lifetime count rather than the new workspace count. Therefore rollback to V4.2 after either operation is **not an accepted routine recovery path**. Quiesce new entries, inventory and reconcile every retained domain, and choose a known-good V4.4 image supporting the same runner/archival architecture or prepare a separately reviewed compatibility correction. Do not delete accounts, unarchive histories, rewrite manifests or reset balances to make an old image fit.

Rollback cannot claim prospective strategy validity or profitability. No production backup, clone, deployment, rollback, publication or cleanup described here has been run during Stage A.
