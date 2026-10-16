# V4.1 isolated deployment and recovery

Actual tested environment: Docker Desktop Linux/aarch64 containers on macOS, Compose project `autotrader-v41-acceptance`. This is not a user's Ubuntu VPS deployment. Backend, worker, frontend, PostgreSQL 16, Redis and the dedicated research worker were exercised with real public Revolut data. Optional monitoring stayed stopped. No unrelated project/container/image/volume was removed. The original tracked SQLite database was not migrated or reset.

Application UI/API publish only `127.0.0.1:13000` / `127.0.0.1:18000` in local acceptance. PostgreSQL and Redis have no host ports. Separate project networks, named data/research/report volumes, CPU/memory limits, bounded logs, unprivileged read-only application containers and restart policies are configured. The bootstrap initializer alone owns its project's volume permissions. Grafana requires the deliberately quarantined profile and must remain disabled pending remediation.

## Start a new isolated installation

From the repository root, inspect existing workloads/ports first. Choose a unique `autotrader-*` project name and free loopback ports. Generate secrets on that host; never copy acceptance secrets into a public configuration:

```sh
python3 scripts/generate_env.py --output .env
python3 deploy/vps.py inventory --project autotrader-v41 --env-file .env
python3 deploy/vps.py build --project autotrader-v41 --env-file .env
python3 deploy/vps.py up --project autotrader-v41 --env-file .env
python3 deploy/vps.py verify --project autotrader-v41 --env-file .env
```

The generator refuses overwrites and uses private file permissions. Set unique API_PORT/FRONTEND_PORT in the private environment if defaults collide. AI remains mock, paper capital EUR 500, live execution false, approved strategies empty. Do not enable paid mode without verified pricing/access and persistent budget checks. `.env.example` documents the quota/price fields.

Research data must exist on the destination host. Acquire/verify genuine data and evaluate the exact installed source, or securely transfer the verified content-addressed cache and complete run directory before bootstrap:

```sh
python3 -m autotrader.research.cli research download --root .data/research --start 2020-01-01 --end 2026-10-16
python3 -m autotrader.research.cli research availability --root .data/research
python3 -m autotrader.research.cli research evaluate --root .data/research --timeframes 5m 15m
python3 deploy/vps.py sync-research --project autotrader-v41 --env-file .env
```

Use new completed dates when extending history. `sync-research` checks source identity and every dataset checksum before publishing pointers; both pointers are owned by UID10001. A browser failure exposed and verified the repair of root-owned pointer files. Seed never deletes old immutable versions. Enable the dedicated research worker only when needed with `docker compose -p autotrader-v41 --env-file .env --profile research up -d research-worker`. It shares this project's volumes/database, not financial execution authority.

## Backup, upgrade, rollback

```sh
python3 deploy/vps.py backup --project autotrader-v41 --env-file .env
python3 deploy/vps.py restore --project autotrader-v41 --env-file .env --backup /ABSOLUTE/PRIVATE/BACKUP.dump
python3 deploy/vps.py upgrade --project autotrader-v41 --env-file .env
python3 deploy/vps.py rollback --project autotrader-v41 --env-file .env --release /ABSOLUTE/PRIVATE/release.json
```

Backups are mode600 in a private project directory; metadata includes checksum and schema. Archives are parsed and restored into a newly named independent database with financial reconciliation before migrations. Existing production data is never overwritten by the restore command. Upgrade builds before stopping application processes, verifies the backup/restore, migrates, starts core services and retains prior image IDs. Rollback verifies the project and unchanged schema, reinstates retained images and persists the selected tag. It refuses an automatic schema downgrade; review a separately restored database when schema compatibility differs. No `down -v`, global prune or deletion of another project's resources is used. Backups contain financial history and must stay private; secure off-host backup is an operator responsibility.

Executed local evidence: `v4_1-backup-restore.json`, `v4_1-upgrade.json`, `v4_1-rollback.json`, `v4_1-deployment-restart.json`, `v4_1-dependency-recovery.json`. The upgrade includes a complete restore and empty reconciliation. Full project restart preserved the original funding journal and persisted pause state. Redis outage was reported unavailable while the API/database remained ready. PostgreSQL outage returned readiness503, blocked transactional/lease execution, and recovery returned RESEARCH_ONLY with one initial funding event and empty reconciliation. These acceptance outages appear in the local pilot; no uninterrupted availability claim is made.

## Remaining remote steps

No SSH host/access was supplied. On the intended Ubuntu host: inventory workloads and resource capacity; install/verify supported Docker/Compose; select private secrets and unused loopback ports; securely copy the repository and verified research; take a recoverable backup before touching existing data; build/scan exact destination-architecture images; run the scoped startup and verification commands; verify remote host restart, disk alerts and off-host restores. Access the loopback UI through an SSH tunnel (for example local13000 to host3000) or a separately reviewed TLS/authenticated reverse proxy. Check actual firewall rules; never publish database/cache ports.

Security disposition in V4_1_SECURITY_REMEDIATION.md governs image release readiness. A current high/critical scan of the actual destination architecture remains required. A 30-day pilot starts explicitly after deployment/configuration freeze; local acceptance is not remote approval or a completed month.
