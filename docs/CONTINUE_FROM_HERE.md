# V3.4 verified checkpoint and exact continuation

Branch:codex/v3.4-reconstruction. Earlier P0 commit:5b900db. The final implementation commit is recorded below after committing this checkpoint; Git HEAD identifies any subsequent documentation-only update. Original tracked autotrader.db and existing user volumes were not reset or migrated during isolated acceptance.

Status:PARTIALLY_COMPLETE_WITH_BLOCKERS. No failing backend/frontend tests remain. The full-stack image security gate fails; functional success is not security clearance.

## Verified work

- Windows complete-regression.xml:80passed/no failures/no skips in407.24s.
- Linux linux-regression.xml:80passed/no failures/no skips in341.53s, using the actual installed Alpine runtime and password-authenticated PostgreSQL.
- Linux proof A actual worker81->84, B98->101, C184->193/API183. C completed4fills, TP3zero, independent replay[]. Earlier Windows launcher-only restart claims are invalid.
- Ruff clean; Mypy37files clean; frontend TypeScript/Vitest/build passed; final Playwright passed all12pages, five persistent controls, actual balance/chart, completed LIMIT historical report and logout.
- Populated/fresh migrations, rollback/retry and immutable-history quarantine passed at head0009_legacy_quarantine.
- Reviewed correction API passed authentication, stale-plan, source refusal and concurrent idempotency; no new economics are invented.
- Latest Compose restart/restore preserved51journal events,19fills,6positions, cash499.110340421159 and schema0009, with replay[].
- Public smoke and multi-asset/OOS replay passed engineering checks; actual replay lost money.
- Backend/frontend all-severity image scans clear; Redis high/critical clear; source secret/method/network review passed.

## Current deployment and private state

Selected test project:autotrader-v34-acceptance. Core PostgreSQL/Redis/backend/worker/frontend remain running. Dashboard http://127.0.0.1:13000, API http://127.0.0.1:18000, both loopback. Credentials are only in ignored .tools/v34-test.env and .tools secrets; never print or commit them. Prometheus/Grafana functional checks passed, then optional monitoring containers were stopped pending their security remediation; their volumes remain. Separate restored databases and private dumps remain for inspection.

The isolated Windows PG test container is autotrader-v34-test-pg on127.0.0.1:55434. The Linux harness creates disposable databases inside the selected deployment; it never substitutes SQLite for PG concurrency proof. First Linux attempt failed because libpq omitted passwords; tests/conftest.py now preserves explicitly supplied credentials. Corrected targeted7and full80runs passed.

## Exact unresolved requirements / next implementation actions

REQ-15, REQ-23 and total acceptance security clearance remain IN_PROGRESS:

1. PostgreSQL libxml2 2.13.9-r2:resolve CVE-2026-86140. Scanner lists no fixed Alpine package. Modify Dockerfile.postgres to a verified fixed XML library/server build while preserving PostgreSQL16 data and extension compatibility; exercise XML regression and populated-volume restart/restore. Do not remove XML support silently or reset volumes.
2. Prometheus v3.15.0:provide a verified rebuilt/patched binary with Go>=1.27.2 and x/net>=0.60.0 (or independently verified fixed equivalents). Verify the Prometheus pseudo-version advisory against actual source commits. Add a reproducible build Dockerfile and update docker-compose.yml, then test authenticated scraping. Current scan:2CRITICAL/9HIGH unique CVEs.
3. Grafana13.2.4:rebuild/obtain verified fixed server/plugin binaries covering Go1.26.6/1.26.7/1.27.1, x/net0.58/0.59, x/crypto0.55, grpc1.83.0 and Tempo pseudo-version findings. Current scan:2CRITICAL/14HIGH. Dockerfile.grafana already upgrades OS packages; that does not replace embedded Go dependencies. Test persistent dashboard/login/provisioning after replacing binaries.
4. Rerun all image scans and scripts/summarize_security.py. Review exact CVEs, binary paths and scanner-provided fixes in docs/evidence/stack-security.json. No silent exceptions or unsupported exploitability assertions.
5. After changes, run the commands below, update the29requirement/44contract tracker and commit. Only then reconsider final completion status.

No paid OpenAI call, external news feed, Telegram message or remote VPS deployment occurred. Mock/off operation is explicitly allowed. Actual legacy attribution requires trusted historical evidence; the repair tool deliberately cannot guess it.

## Resume commands (PowerShell)

```powershell
$env:AUTOTRADER_TEST_PG_ADMIN_URL='postgresql://postgres@127.0.0.1:55434/postgres'
.\.venv\Scripts\python -m pytest -q -s --junitxml=docs/evidence/complete-regression.xml
.\.venv\Scripts\python -m ruff check src tests scripts alembic
.\.venv\Scripts\python -m mypy src/autotrader
docker compose -p autotrader-v34-acceptance --env-file .tools/v34-test.env --profile monitoring up --build -d
.\.venv\Scripts\python scripts/verify_deployment.py --env-file .tools/v34-test.env --project autotrader-v34-acceptance --restart
.\.venv\Scripts\python scripts/verify_restore.py --env-file .tools/v34-test.env --project autotrader-v34-acceptance
docker build -f Dockerfile.tests --build-arg RUNTIME_IMAGE=autotrader-v34-acceptance-backend -t autotrader-v34-verification .
docker run --rm --name autotrader-v34-linux-verification --network autotrader-v34-acceptance_data --env-file .tools/v34-test.env -e ENVIRONMENT=test -v C:/Users/moha/Downloads/AutoTrader:/verification autotrader-v34-verification
npm.cmd run typecheck --prefix frontend
npm.cmd run test --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run test:e2e --prefix frontend
.\.venv\Scripts\python scripts/summarize_security.py
.\.venv\Scripts\python scripts/verify_security.py
```

Do not stop/recreate PostgreSQL while either test suite is running. Changes to the schema or process harness require fresh migration/restart proof; a prior passing run does not validate new code. Never use down -v as an upgrade procedure.
