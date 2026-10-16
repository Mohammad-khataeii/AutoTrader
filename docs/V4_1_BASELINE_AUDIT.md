# V4.1 baseline audit

Starting Git commit: `2033c7b6cf2f8f327913deb2d92e3343ded370b9` (clean checkout).
Python source fingerprint: `6bf034790fe7300a4a05db8b78d5f3ff21db2d77ef8f8c8dbc7c4c072117ff74`.
Tracked SQLite SHA256: `5f966b0fa48e8d3d82f6634cba1052593cf70f3cb3fae162b84cc70420afd326`.
See `evidence/v4_1-baseline-source.json` for individual source hashes.

The requested V4 documents and execution, research, persistence, worker, AI,
configuration and Compose implementations were inspected. This is the existing
FastAPI/React/PostgreSQL/Redis paper application, not a new financial engine.
Six registry entry strategies, two filters, real PostgreSQL account locking,
side-aware IOC simulation, protective exits, partial target quantities, immutable
journal, recovery, source/timeframe/parameter research gates and Alembic exist.

Reproduced limitations:

- No `.data/research` directory was supplied with this checkout. The 48 datasets,
  76,606 bars and 118 passing tests in V4 documentation are prior-machine claims,
  not new local evidence. The tracked V4 source fingerprint differs from the
  prior evidence. Previous performance cannot authorize this checkout.
- CLI full research defaults to 1d/4h; intraday download defaults to two days.
- `workflow.run_full` ensembles omit independently selected parameters.
- AI account-locked reservations enforce monthly dollars, with no daily/hourly
  count. Usage lacks event/provider identity and explicit billing-state detail.
- Promotion is a persistent global policy snapshot plus environment approval IDs;
  there is no explicit durable per-candidate approval/suspension lifecycle.
- Login throttling is per process. Worker scan exceptions other than market errors
  can terminate the coordinator; no coordinator ownership fence exists.
- Optional Grafana shares the monitoring profile; V4 security findings cannot be
  cleared from old scans. PostgreSQL remains version 16 in Compose.
- README identifies V3.4, while package/API identify V4.0.

Environment: macOS, Python 3.12.0, local PostgreSQL 15.13, Docker 29.8.2.
Docker initially had no daemon socket; starting the installed Docker app restored
access. Inventory found no running containers, with unrelated DWRS/REX images
present; those images are preserved. No remote VPS access was provided or used.
No existing financial database was migrated or reset.

An initial pytest invocation without `AUTOTRADER_TEST_PG_ADMIN_URL` produced
55 passed / 63 setup errors (29.55s), as intended by the no-SQLite-fallback fixture.
The real-PostgreSQL baseline rerun uses disposable databases via
`AUTOTRADER_TEST_PG_ADMIN_URL='dbname=postgres host=localhost' python3 -m pytest -q --junitxml=docs/evidence/v4_1-baseline.xml`.
Its result is recorded below when complete. No source edits preceded that run.

Public source probe: Coinbase `/products` listed all eight direct EUR products;
a GET for BTC-EUR five-minute bars on 2026-04-19 returned HTTP 200 and genuine
OHLCV. The official candle endpoint limits pages to 300, supports 60/300/900/3600/
21600/86400 seconds, and explicitly warns that no-tick intervals can be absent.
4h must therefore remain an aggregation of complete contiguous 1h observations.

Baseline completed: **118 passed, zero failed/skipped**, 147.35 seconds, real
PostgreSQL 15.13, JUnit `evidence/v4_1-baseline.xml`. Ruff passes. TypeScript
checking, Vitest (one case), production frontend build pass; existing 535kB
bundle warning persists. A separate PostgreSQL 16 Docker verification instance
was then created on loopback port 55441 with a dedicated named volume.
