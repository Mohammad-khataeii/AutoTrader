# V4 verified checkpoint and exact continuation

Branch: codex/v4-execution-research. Current implementation source commit: ee272db. Source fingerprint: b31992258941962d61ee8bfaa7b38ea882a7f5449099ff78fb0045fc15e4966d. Subsequent commits contain deployment/security builds, documentation and evidence.

Status: PARTIALLY_COMPLETE_WITH_BLOCKERS. The connected V4 application and research pipeline are implemented. Security clearance is blocked by PostgreSQL libxml2 and Grafana bundled dependencies. No strategy passed validation, so approved strategy IDs remain empty and the bot holds cash. This is a legitimate research outcome.

## Verified

- Unchanged baseline80passed; execution/data regression98passed.
- Final native Windows118passed/516.60s and installed-Linux118passed/445.74s, zero failures/skips. See V4_TEST_EVIDENCE.md and the release JUnit artifacts.
- Actual worker/API lifecycle: cost rejection, valid entry, TP1, partial TP2, killed interpreter/restart, protective exit and exact reconciliation.
- Genuine Coinbase direct-EUR48datasets/76606bar records; eight assets, six TF. Full final-source study research-20261015T205023, six strategies on daily/4h, all fail validation.623fills/4260curve rows exported.
- Browser15pages, actual queued research worker job, plots, historical LIMIT replay and persisted controls pass. Ruff/mypy/TypeScript/Vitest pass.
- Rebuilt/deployed core and research worker; restart preserves51journal events, reconciliation empty. Isolated binary backup/restore passes.
- Backend/frontend all-severity, Redis high/critical, pip/npm audits clear.
- Patched Prometheus reproducible build/scan/UI/query/authenticated scrape verified; Compose selects it. Official old findings are retained as superseded evidence.
- Original user SQLite blob b2b81065cd9f90c2d2f728cb3e5c8a7d6e424c31 unchanged. Existing user data/volumes not reset.

## Current local deployment

Project autotrader-v34-acceptance retains its existing volumes. Core services and research worker run. Dashboard http://127.0.0.1:13000; API http://127.0.0.1:18000. Credentials remain only in ignored .tools/v34-test.env and its private secret files; never print/commit them. Optional monitoring containers remain stopped. Do not enable Grafana until remediation/rescan/functional verification.

## Exact mandatory remaining work

1. Remediate PostgreSQL16 image libxml2 2.13.9-r2 CVE-2026-86140 using a verified fixed compatible package/build. The selected Alpine branch did not supply a fix after --pull/--no-cache rebuild. Preserve SQL/XML capability and PG16 volume/extension compatibility, then exercise XML behavior, populated-volume restart and isolated restore. Internal DB/unused application XML reduces exposure but is not a patch.
2. Obtain/rebuild Grafana13.2.4 bundled Go plugins with patched Go/x/net/x/crypto/grpc dependencies. Raw scan2critical/14high unique CVEs; exact affected versions/binaries and13unresolved CVEs are retained in evidence/v4-security-assessment.json. Windows-only and current-no-Tempo-server exclusions are scoped, not removed. Verify login, persistent dashboards, provisioning and Prometheus queries after replacements.
3. Rescan exact selected image IDs, rerun scripts/assess_v4_security.py, update V4_SECURITY_REMEDIATION.md and reconsider completion only after required security checks pass. Keep optional monitoring stopped while unresolved.

Research advancement is separate: no strategy is approved. A daily/4h study cannot approve production5m; promotion requires explicit approval, matching source, actual timeframe and exact frozen runtime parameters. More suitable history and prospective validation are needed before any claim of predictive edge.

Before reporting a future nonempty optimized ensemble, replace its current runtime-default simulation parameters with per-member frozen parameters and verify the combined replay. Only the empty cash ensemble has been demonstrated; no optimized-ensemble return is claimed.

## Commands

Exact tested deployment/Linux commands: V4_DEPLOYMENT.md. Final results: V4_BACKTEST_RESULTS.md. Scope/assumptions: V4_KNOWN_LIMITATIONS.md. Requirement status: V4_COMPLETION_MATRIX.md. Do not restart PostgreSQL while either full suite is running. Never use down -v as an upgrade. Any Python source change invalidates the source fingerprint and requires a matching new research run; do not relabel old reports as current.

No live trading, paid AI request, external message or remote VPS deployment was performed.
