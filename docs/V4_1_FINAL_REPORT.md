# AutoTrader V4.1 final report

## 1. Overall status

**PARTIALLY_COMPLETE_WITH_BLOCKERS**

| Independent outcome | Finding |
|---|---|
| A. Engineering verification | Integrated application passes 148 native and 148 installed-Linux regression tests on real PostgreSQL 16, browser workflow and scoped deployment/recovery checks. Financial integrity is preserved. Scope and Linux results are in V4_1_TEST_EVIDENCE.md. |
| B. Research verification | Genuine 5m/15m evaluation completed for all six existing strategies with exact source/frozen parameters. **NO STRATEGY PASSED VALIDATION.** No strategy is approved. |
| C. Deployment verification | Isolated local Docker deployment, backup/restore, upgrade, rollback, restart and dependency recovery verified. No user's remote Ubuntu VPS was accessed or deployed. |

Whole-stack security clearance remains blocked by disabled Grafana dependencies. An actual 30-day period has not elapsed. Those limitations prevent COMPLETE_AND_VERIFIED; losing research is a valid result, not a reason to loosen gates.

## 2. Existing V4 components preserved

The existing FastAPI/React application, PostgreSQL account lock and immutable financial journal, EUR 500 virtual capital, bid/ask-aware paper broker, IOC/limit behavior, partial fills/targets, stop/trailing/time exits, allocation, three-position/EUR 100 position/EUR 350 exposure/EUR 150 reserve limits, 5 EUR planned loss, 15 EUR daily/EUR 35 weekly triggers and six-entry/day cap remain. No leverage, shorts, capital reset/increase or live exchange order path was introduced.

Six strategy hypotheses and two defensive filters are retained; their mathematical strategy version stays 4.0.0 while the application is 4.1.0. Integration fixes freeze each ensemble member's selected parameters, align signal/risk/exit sizing, and remove current-bar volume lookahead. Research promotion now has durable candidate/approval/suspension states checked again under the accounting lock. New PostgreSQL coordinator leases fence stale workers. Durable AI usage is extended by migration 0010 rather than replacing the ledger. Daily/hourly limits, shared login throttling, explicit operation states, persistent pilot reports and dashboard views are integrated.

Starting commit `2033c7b6cf2f8f327913deb2d92e3343ded370b9` was clean. Final package source fingerprint: `e0140ff18c36d86ac4c676e07aa650c2d93bac3fcfa6b708e0025f6573d66c5e`. The original tracked SQLite SHA256 remains `5f966b0fa48e8d3d82f6634cba1052593cf70f3cb3fae162b84cc70420afd326`. Existing user financial data was not reset.

## 3. Historical datasets

Newly acquired public Coinbase Exchange direct-EUR OHLCV: **48 datasets, 351, 788 observations, 8 assets, 6 timeframes, 0 acquisition failures**. Products were verified through the provider listing. Timeframes: 1m, 5m, 15m, 1h, 4h, 1d. 4h is aggregated only from four contiguous completed 1h candles. Sources, exact 48-row counts/start/end dates/gaps, immutable versions, SHA256s, raw request pages and provenance are in [V4_1_INTRADAY_DATA.md](V4_1_INTRADAY_DATA.md) and [dataset evidence](evidence/v4_1-datasets.json).

|5m symbol|Completed observations|Missing requested bars|Requested UTC interval, end exclusive|
|---|---:|---:|---|
|BTC-EUR|51,747|93|2026-04-19 to 2026-10-16|
|ETH-EUR|51,724|116|2026-04-19 to 2026-10-16|
|SOL-EUR|25,894|26|2026-07-18 to 2026-10-16|
|XRP-EUR|25,127|793|2026-07-18 to 2026-10-16|
|ADA-EUR|19,916|6,004|2026-07-18 to 2026-10-16|
|LINK-EUR|18,709|7,211|2026-07-18 to 2026-10-16|
|AVAX-EUR|13,719|12,201|2026-07-18 to 2026-10-16|
|DOT-EUR|10,884|15,036|2026-07-18 to 2026-10-16|

Other requested windows: 15m 90 days; 1h/4h 180 days; 1m 2 days; daily from 2020-01-01. Actual endpoints/counts are authoritative and can begin after requested dates. Missing listing/no-tick intervals remain absent. No synthetic gap fill, FX conversion or fabricated L2 is used. Incremental coverage, atomic writes, content hashes and raw-page crash recovery were tested. No data cache was supplied at baseline.

Coinbase is a proxy for Revolut X; prices, liquidity and precision schedules can differ. Runtime uses actual public Revolut quotes/metadata. The public smoke check read 379 pairs, 61 EUR pairs plus BTC book/candles/ticker without placing orders. Historical volume is not an executable order book.

## 4. Five-minute strategy results

Run `research-20261016T044934`, exact final package fingerprint. Strict historical test 2026-09-10T01:20Z through 2026-10-16T00:00Z exclusive. Parameters selected on training and frozen; validation, purging/embargo, walk-forward, multiple-testing/block intervals and cost/parameter stresses are retained. Historical dates were replayed during engineering and are not described as newly untouched.

|Strategy|Net EUR|Closed trades|Max drawdown|Profit factor|Fee stress net EUR|Wider spread/slippage net EUR|Validation|
|---|---:|---:|---:|---:|---:|---:|---|
|A_TREND_PULLBACK|-24.1342|126|5.8851%|0.3895|-27.2028|-28.2535|FAIL|
|B_COMPRESSION_BREAKOUT|-11.7928|77|2.8146%|0.5338|-9.2855|-8.0434|FAIL|
|C_BREAKOUT_RETEST|-18.4963|67|3.8708%|0.2170|-13.2940|-9.3456|FAIL|
|D_VOLUME_ACCUMULATION|-33.3256|129|6.9025%|0.3084|-30.1809|-30.2796|FAIL|
|E_RELATIVE_STRENGTH|-6.1916|17|1.4539%|0.2765|-7.4705|-8.0651|FAIL|
|F_MEAN_REVERSION|-18.8279|79|3.7804%|0.0723|-10.3224|-7.5753|FAIL|

All six 15m strategies also lose. Costs:10 bps per-side fee, 10 bps full spread, 8 bps per-side slippage; fee stress 20 bps; friction stress 25 bps spread/20 bps slippage. Shared modeled depth is 1% of prior completed volume. Stress can change entries/exits and is not a fixed-trade arithmetic adjustment. Residual positions are marked, not force-liquidated.

Common EUR 500 references:5m cash EUR 0; BTC buy/hold+41.8939; ETH+10.7318; equal-weight current universe+49.9088; legacy signals-50.4310; V4 runtime-default parameters-28.2552; independently frozen V4.1 members-26.7101; empty validated ensemble EUR 0. Passive references carry different exposure and are not recommendations.15m equivalents and all assumptions are in the complete backtest report.

Exports contain 2, 204 modeled fills, 833 closedpositions, 72474 equity/drawdown rows, 135 asset/regime detail rows and 24 monthly period rows. Trade details, parameter/source hashes, holding times, fees/spread/slippage, wins/losses, exposure/turnover, sensitivity and gate failures are reproducible. Unsupported subgroup confidence intervals stay null. Group curves are portfolio contributions on common EUR 500, not standalone allocations. See [backtests](V4_1_FIVE_MINUTE_BACKTESTS.md), [validation](V4_1_STRATEGY_VALIDATION.md), [regimes](V4_1_MARKET_REGIME_RESULTS.md) and [export checksums](evidence/v4_1-export-manifest.json).

## 5. Approved strategies

**NO STRATEGY PASSED VALIDATION.** Approved production-paper member set: **empty**. The scanner continues reading genuine data, computing signals and recording policy rejections in RESEARCH_ONLY mode. Financial entries remain blocked. Explicit approval cannot rescue failed/stale/mismatched research. Synthetic acceptance trades use separate databases and are excluded from forward performance.

## 6. AI quotas

Persistent maxima:30 paid analyses per UTC day, 6 per rolling 60 minutes, USD 10 per calendar month. PostgreSQL account locking and database time serialize reservation/submission, including concurrent workers and restarts. The executed suite verifies 30 accepted/31st rejected, 6 accepted/7th rejected, exact rolling expiry, daily/month/leap-year boundaries, simultaneous claims, monthly reservations, unknown-billing holds, duplicate material-event suppression, audited reconciliation and cost-bound fail-closed behavior. Portfolio-risk capacity is reserved within total quotas.

Final regression includes all quota tests; initial 17-case quota evidence and 19-case safety/migration evidence are retained. AI defaults to mock, shows 0 paid calls in local runtime, and has no real paid provider verification. Estimated token cost is distinct from confirmed billing. Unknown outcomes keep holds; provider/pricing overages block later paid requests and require evidence-based reconciliation. These internal guards cannot guarantee external billing never exceedsUSD 10 if the provider violates configured bounds. Details: [AI quotas](V4_1_AI_QUOTAS.md).

## 7. Financial integrity

Final native and installed-Linux suites each pass all 148 tests on real PostgreSQL 16; the Linux suite uses the selected backported database image. Actual worker/API processes demonstrated cost-based rejection, valid paper entry, TP1, partial TP2, killed worker/restart, remaining target/protective exit, five unique fills, zero stranded reserve and empty reconciliation. Other process tests cover simultaneous orders/stops/targets, duplicate economic messages, deadlocks, connection loss after commit, reservation cancellation, marked exposure, daily/weekly unrealized loss, stale/missing marks and durable risk halts. Financial limits were not weakened.

V4→V4.1 migration preserves existing AI holds and journal history. Local backup/restore/upgrade/rollback/full restart preserve funding and controls. PostgreSQL outage returns readiness HTTP 503 and cannot acquire an account transaction/lease; after recovery, the original journal remains and reconciliation is empty. Redis is optional to financial correctness. All synthetic financial acceptance records remain separate from genuine historical research and the local prospective pilot. See [test evidence](V4_1_TEST_EVIDENCE.md).

## 8. Security

The selected PostgreSQL 16 image now includes a real upstream backport of CVE-2026-86140 while preserving its libxml2 ABI and SQL/XML. Bounds regression, vulnerable negative control, upstream checks, extensions, restored database, restart and financial reconciliation pass. Backend/frontend/Redis/selected PostgreSQL have zero high/critical findings in recorded scans. Locked pip/npm audits have no known findings. This is a scoped local result, not all-severity or remote security clearance.

**Remaining:** quarantined Grafana 13.2.4 has 21 distinct CVEs (2 critical/19 high; 53 package occurrences). It is stopped and absent from the default core profile. The exact CVE/package list and raw SARIF remain in [security disposition](V4_1_SECURITY_REMEDIATION.md). Do not enable it before patch/rebuild/rescan and functional verification. The local libxml2 backport must be maintained until a compatible official fixed package is verified. No exchange private key or real paid API call was used; public exchange HTTP operations are GET-only.

## 9. VPS deployment

Actual environment: a separate Docker Desktop Linux/aarch64 project on this Mac, **not a remote VPS**. Core services plus research worker were healthy with PostgreSQL 16.15, Redis, loopback UI/API, private DB/cache ports, readiness true, RESEARCH_ONLY and empty reconciliation. PostgreSQL image backport was selected through a backup/restore-verified upgrade on the existing volume. Binary backups are private/checksummed and restored into newly named databases; no original database overwrite. Upgrade/rollback and full project restart were executed. Final exact container IDs/health and scans are retained in evidence.

Remaining remote work: obtain intended Ubuntu host access; inventory existing workloads/resources; choose unique project/loopback ports; generate private secrets; securely transfer exact source/research; build/scan destination-architecture images; perform scoped startup, backup/restore, health/financial verification; verify host restart, SSH tunnel or TLS proxy, firewall, disk alerts and off-host backup. Exact commands and limits: [deployment guide](V4_1_VPS_DEPLOYMENT.md). No remote deployment claim is made.

## 10. Remaining limitations

Grafana remediation, actual remote deployment and elapsed 30-day observations remain incomplete. The browser started a local prospective RESEARCH_ONLY pilot at 2026-10-16T05:39:21Z, planned end 2026-11-15T05:39:21Z. It has real short-lived observations, including intentional acceptance restart/outage gaps; this is not the user's VPS experiment. No completed month or profitable forward result exists.

Provider proxies/gaps, modeled costs/depth, reused historical intervals, approximate independent-date/block statistics, changing cross-sectional history, no historical Revolut L2, no independent host supervisor, no external paging, manual retention/off-host backup and unverified real paid model access remain material limitations. All required 14 V4.1 documents and continuation are present; statuses are itemized in [completion matrix](V4_1_COMPLETION_MATRIX.md) and [limitations](V4_1_KNOWN_LIMITATIONS.md).

## 11. Next engineering action

Patch or rebuild Grafana's affected bundled Go/plugin dependencies, rescan the exact selected images and verify authenticated login, persistent dashboards, provisioning and Prometheus queries before enabling monitoring. Maintain the tested libxml2 backport until an official compatible fixed package replaces it. Remote deployment requires the actual Ubuntu host; scientific advancement requires new frozen prospective observations, not retuning the already examined historical test.
