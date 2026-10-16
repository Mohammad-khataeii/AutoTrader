# V4.2 recovery and rollback

Rollback is an approved production operation, not a Stage A development step. Diagnose first, stop further rollout changes, preserve logs/current journals/backups, and classify app-only versus schema failure. Keep unrelated containers, Nginx/TLS and all volumes untouched. Corrections originate locally, are tested/committed/pushed and receive approval before redeployment.

Before migration, a failed backup/restore/safety gate must prevent schema changes. If owned writers were stopped, recover the previously working compatible images using a scoped Compose override with immutable previous IDs and--no-build--no-deps. The actual first attempt did exactly this after a missing host dependency; no migration had run. Never hide that failure as a clean first attempt.

Schema0011 adds shadow registry/identity metadata and preserves all 15existing financial tables. Empty-domain0010→0011→0010→0011 was tested on local realPostgreSQL, an actual oldDockerDB clone and the real production backup clone. Forced PostgreSQLDDL failure rolled back transactionally. These tests do not authorize a blind production downgrade.

Once any shadow registry/identity exists, downgrade intentionally refuses deletion. Do not disable this guard, delete the registry or drop shadow databases to make V4.1 start. The helper's rollback action refuses schema mismatch against the backup revision. Prefer a corrected compatible V4.2 release with current financial data.

```sh
# Inspect a previously verified release record; only when current schema is compatible:
.tools/deploy-venv/bin/python deploy/vps.py rollback --project autotrader-v41 --env-file .env --release /path/to/verified/release.json
# A restore is always a new verification DB; never the active production DB:
.tools/deploy-venv/bin/python deploy/vps.py restore --project autotrader-v41 --env-file .env --backup /path/to/verified.dump
```

Archivechecksum, complete restore, exact account/domain identity and EUR 500journal reconciliation must pass. Never overwrite newer trades with an earlier dump, and never restore while live writers still target the database. Full multi-domain recovery is verified in an isolated new PostgreSQL cluster with original logical DB names; restored original/shadow/second-shadow journals remain independent. A restore-to-new-name registry is deliberately unable to follow original production shadow pointers. Same-cluster remapping requires an explicit reviewed mapping/reconciliation procedure.

Retain V4.1 source/image backups, all final-release image identities, every financial dump, new journals and named volumes. No destructive database restore, global prune, volume removal or unrelated restart is part of ordinary rollback.
