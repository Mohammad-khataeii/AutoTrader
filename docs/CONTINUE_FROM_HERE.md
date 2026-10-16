# V4.1 verified checkpoint and continuation

Status: PARTIALLY_COMPLETE_WITH_BLOCKERS. Branch: `codex/v4-execution-research`.
Baseline commit: `2033c7b6cf2f8f327913deb2d92e3343ded370b9`.
Integrated V4.1 source: `d2e9e8b`; deployment/security follow-up: `387fec0`; operational verifier: `c14beff`.
Package fingerprint (62 Python files):
`e0140ff18c36d86ac4c676e07aa650c2d93bac3fcfa6b708e0025f6573d66c5e`.
Later commits contain evidence/reports; inspect Git before continuing.

## Verified current scope

- Native final regression: 148 passed on disposable PostgreSQL16 databases. Final
  installed-Linux regression: 148 passed against the selected backported PostgreSQL16
  image, 414.98s. See V4_1_TEST_EVIDENCE.md and final JUnit artifacts.
  Prior failures remain as development evidence, not final acceptance.
- Six existing strategies×5m/15m, exact matching source, frozen member parameters,
  causal liquidity, chronological selection/walk-forward/cost stresses are complete.
  Run `research-20261016T044934`: **NO STRATEGY PASSED VALIDATION**. Approval set empty.
-48 genuine Coinbase direct-EUR datasets,351788observations; BTC/ETH180days5m,
  others90days5m, all source gaps retained. Bulk cache is ignored `.data/research`;
  exported results/trades/curves/diagnostics/checksums are tracked under docs/evidence.
- Durable30/day,6/rolling-hour,USD10/month quotas with real PostgreSQL account locking,
  restart/concurrency/calendar/unknown-billing tests. Mock runtime; no paid call.
- Exact worker/API paper lifecycle, partial target/kill/restart/protective exit,
  risk losses, financial concurrency and reconciliation pass. Existing user DB unchanged.
-16-page real browser workflow passes: queued research, LIMIT replay, controls,
  genuine5m evidence, quota views, local prospective pilot observation/JSON/CSV.
- Backup/restore, upgrade, same-schema image rollback, full-volume restart, Redis
  outage and PostgreSQL outage/recovery executed in the isolated local project.
- PostgreSQL16 CVE-2026-86140 is now backported from the upstream GNOME fix into
  local Alpine2.13.9-r3, preserving ABI/SQL/XML and existing distro patches. Upstream
  checks plus the actual-function bounds regression and vulnerable negative control
  pass. XML/extensions, restored-data restart and reconciliation pass. Do not repeat
  the old V4 conclusion that no compatible fix was implemented.
- Core high/critical scans are clear in recorded local scope. Disabled Grafana still
  has21distinct CVEs (2critical/19high),53package occurrences. Whole-stack security is
  not cleared. Raw scans/provenance/bounds/functional records are retained.

## Local deployment

Project `autotrader-v41-acceptance`; core + research worker running. UI
http://127.0.0.1:13000; API http://127.0.0.1:18000. Private generated credentials only
in ignored `.tools/v41-test.env` and associated secret files; never print/commit.
Selected PostgreSQL tag: `autotrader-v41-postgres:16-backported`. Actual image IDs,
current application tag, health and reconciliation are in the final deployment/core
scan evidence. Named volumes are preserved. Grafana/Prometheus remain stopped.
No unrelated workload/image/volume was removed. No remote VPS was accessed.

A local RESEARCH_ONLY pilot started2026-10-16T05:39:21Z, planned end
2026-11-15T05:39:21Z, from the actual public-data worker. It has acceptance restart/
outage gaps and is not the user's VPS experiment. Thirty days have NOT elapsed.

## Exact remaining work

1. Rebuild/replace Grafana's affected bundled Go/plugin dependencies with verified
   fixed versions. Rescan actual selected image IDs, then verify authenticated login,
   persistent dashboards, provisioning and Prometheus queries before enabling its
   quarantined profile. Full CVE/package list: V4_1_SECURITY_REMEDIATION.md.
2. Maintain the local libxml2 backport until a verified compatible official package
   replaces it. Dockerfile refuses application to a base library other than
  2.13.9-r2 after upgrade. Review/rebase new distro patches; preserve SQL/XML,
   PostgreSQL16 volumes/extensions, upstream+bounds checks, restore/restart and exact
   destination-architecture scan. APKBUILD provenance records a post-build whitespace
   normalization only; source/commands/checksums are unchanged.
3. Obtain the actual Ubuntu host/access and inventory existing workloads. Follow
   V4_1_VPS_DEPLOYMENT.md with a unique project, private secrets/loopback ports,
   destination build/scan, scoped migration/backup/restore/health checks, host restart,
   firewall/TLS or SSH tunnel, disk monitoring and secure off-host backups. No remote
   verification claim can be made without doing those steps there.
4. Freeze and explicitly start the intended prospective pilot after configuration
   is settled. Collect genuine observations/daily reports for30days, disclose gaps,
   compare costs/benchmarks/rejections and do not present elapsed time alone as edge.
   Do not weaken historical validation or force entries to create activity.

## Reproduction

Read V4_1_FINAL_REPORT.md, V4_1_TEST_EVIDENCE.md and the completion matrix first.
`python3 -m autotrader.research.cli research evaluate --root .data/research --timeframes 5m 15m`
replays the completed study; exported reports disclose reused historical dates.
Any package Python change invalidates its fingerprint and requires matching new
research. Do not relabel old reports. `deploy/vps.py sync-research` verifies all
hashes/source identity and gives new pointers to UID10001. Selected browser jobs
change latest-run; restore the complete study with the verified synchronization.

Use the scoped deploy script for inventory/build/up/verify/backup/restore/upgrade/
rollback. Never remove project volumes or perform global pruning. Full Linux tests
use the installed runtime with disposable PostgreSQL databases; do not restart
PostgreSQL while that suite runs. No live trading or real-money orders are available
through ordinary application paths. No external message was sent.
