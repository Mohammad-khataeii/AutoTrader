# V3.4 executed test evidence

Authoritative application status is PARTIALLY_COMPLETE_WITH_BLOCKERS because full-stack security clearance has unresolved findings. Financial/runtime proofs and image security have separate outcomes.

## Evidence correction

The first Windows subprocess harness killed the venv launcher instead of its child interpreter. Earlier restart claims, including the initial13-case and68-case reports, are INVALID as actual worker-restart evidence. They are superseded by logged interpreter PID discovery, persisted worker_instance matching, owned process-tree termination and kernel termination verification. No repository reopen is counted as a process restart.

Baseline27812aa: archived original suite30passed/4PostgreSQL skips after installing missing dependencies. Current PG fixtures fail when PostgreSQL is absent. No skips are accepted as concurrency evidence.

## Final commands and outcomes

Use the repository virtualenv for Python commands below. The Windows admin URL selects only the isolated loopback PostgreSQL test container.

```powershell
$env:AUTOTRADER_TEST_PG_ADMIN_URL='postgresql://postgres@127.0.0.1:55434/postgres'
.\.venv\Scripts\python -m pytest -q -s --junitxml=docs/evidence/complete-regression.xml
.\.venv\Scripts\python -m ruff check src tests scripts alembic
.\.venv\Scripts\python -m mypy src/autotrader
npm.cmd run typecheck --prefix frontend
npm.cmd run test --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run test:e2e --prefix frontend
npm.cmd audit --prefix frontend --json
.\.venv\Scripts\python -m pip_audit -f json -o docs/evidence/pip-audit-fixed.json
.\.venv\Scripts\python -m pip check
```

| Gate | Classification | Actual result / retained evidence |
|---|---|---|
| Complete Windows backend suite | PASSED |80passed,0failed,0skipped in407.24s; complete-regression.xml |
| Corrected actual process A/B/C | PASSED |Windows A28656->20656; B24100->24316; C10652->29844, API4408; four lifecycle fills, TP3zero, replay[] |
| Additional worker protective/limiter/confirmation cases | PASSED |6passed in22.44s; extended-worker-suite.xml; included in broader regression |
| Audited projection correction | PASSED |4passed in14.59s; actual API authentication, stale fingerprint, concurrent idempotency and source-history refusal |
| Migration plus correction regression | PASSED |6passed in28.66s; corrections-migration.xml |
| Historical limit IOC replay | PASSED |2backtest cases passed in104.94s; market fills vs zero-fill limit; included in80-case regression |
| Ruff | PASSED |No findings in src/tests/scripts/alembic |
| Mypy | PASSED |No issues in37source files |
| TypeScript / Vitest / production build | PASSED |Typecheck clean;1Vitest test; production bundle built. Non-fatal523KB bundle advisory remains |
| Playwright | PASSED |All12pages, real backend balance, five persistent controls, visible equity path, login/logout, completed stored LIMIT replay; playwright.json |
| Public Revolut X read-only connectivity | PASSED |379markets,61EUR pairs, book/tickers and240closed candles; live-public-smoke.json |
| Public historical multi-asset/OOS replay | PASSED |480BTC/ETH observations; net-EUR1.511679218185;5closed trades and1open; both OOS windows negative; research-replay.json |
| Compose migration/readiness/worker/scanner/auth | PASSED |Real running Linux services; deployment-verification.json |
| Compose persistent restart | PASSED |51journal events retained, pause persisted, replay[]; deployment-verification.json |
| Binary backup/separate-database restore | PASSED |51journal events/19fills/6positions, identical cash/schema0009, replay[]; backup-restore.json |
| Prometheus/Grafana functional health | PASSED |Authenticated target up, Grafana database ok; monitoring-health.json. Containers subsequently stopped pending security remediation |
| Python/npm dependency audit | PASSED |No known Python distribution vulnerabilities; npm0vulnerabilities; pip check clean |
| Source secrets / paper-only methods / network bindings | PASSED |No configured-secret/key findings; exchange GETonly; public bindings loopback, database/cache internal; source-security.json |
| Application backend/frontend image scan | PASSED |Final Alpine images:zero known vulnerabilities; container-release-cves.sarif/frontend-container-cves.sarif |
| Full-stack high/critical image clearance | FAILED |PostgreSQL1HIGH; Prometheus2CRITICAL/9HIGH unique CVEs; Grafana2CRITICAL/14HIGH; Redis clear. Exact packages/paths/fixes:stack-security.json |
| Actual paid OpenAI call/invoice comparison | NOT_RUN |No credentials/purchase required or used; provider boundary/budget tests passed |
| Remote VPS deployment | NOT_RUN |No VPS supplied; Linux containers actually deployed locally, defaults loopback/internal |

Linux image regression uses the deployed runtime package with test tools added only in a separate verification image:

```powershell
docker build -f Dockerfile.tests --build-arg RUNTIME_IMAGE=autotrader-v34-acceptance-backend -t autotrader-v34-verification .
docker run --rm --name autotrader-v34-linux-verification --network autotrader-v34-acceptance_data --env-file .tools/v34-test.env -e ENVIRONMENT=test -v C:/Users/moha/Downloads/AutoTrader:/verification autotrader-v34-verification
```

First Linux attempt:33passed/47setup errors because libpq connection info omits passwords. The fixture was repaired to preserve explicitly supplied credentials for child URLs. Corrected Linux targeted proof C+migrations+corrections:7passed in31.63s; API9, worker10->19,4fills,replay[]. Full corrected Linux regression:80passed,0failed,0skipped in341.53s. Proof A actual PID81->84; B98->101; C184->193/API183. Four autonomous lifecycle fills, TP3zero, replay[]. Evidence:linux-regression.xml.

Deployment and restore commands (no volumes deleted):

```powershell
docker compose -p autotrader-v34-acceptance --env-file .tools/v34-test.env --profile monitoring up --build -d
.\.venv\Scripts\python scripts/verify_deployment.py --env-file .tools/v34-test.env --project autotrader-v34-acceptance --restart
.\.venv\Scripts\python scripts/verify_restore.py --env-file .tools/v34-test.env --project autotrader-v34-acceptance
.\.venv\Scripts\python scripts/verify_security.py
.\.venv\Scripts\python scripts/summarize_security.py
```

Scanner commands for images use `docker scout cves IMAGE --format sarif --output FILE`; support-service scans add `--only-severity critical,high`. All captured reports are summarized without equating successful scanning with security clearance. Windows Scout reported temporary-archive cleanup warnings but emitted completed reports. Earlier Debian/backend and stock frontend findings were remediated by upgraded Alpine runtime packages and unused tooling/module removal. PostgreSQL retains server16/data compatibility and replaces the obsolete Go privilege helper with the C su-exec interface; the final filesystem does not ship the removed binary in lower layers.

Local .log files preserve command output; committed XML/JSON/SARIF, proof excerpts and screenshots preserve reviewable evidence. No test count is an assertion counter; repeated runs are not added together to imply additional distinct coverage. Existing autotrader.db and user volumes remain unchanged.
