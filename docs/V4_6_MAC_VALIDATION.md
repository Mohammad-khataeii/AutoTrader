# Personal Plan — Mac hosting and validation (October 26, 2026)

**Operating status: RUNNING — PARTIALLY VERIFIED.** The persistent local application and simulated accounting passed verification and remain running. Another physical LAN device and a whole Docker Desktop/Mac restart were not available for testing. Public-provider rate limits and occasional incomplete completed-candle coverage remain explicit data limitations. No VPS access or changes occurred.

## A. Mac environment

macOS 26.6.2 (25G83), Apple M4 ARM64, 10 CPU cores, 16 GiB RAM. Docker Desktop 4.96.2 / Engine 29.9.2 / Compose 5.6.1, with 10 CPUs and about 7.75 GiB assigned to its native ARM64 VM. Host test tools: Python 3.12.0 and Node 22.13.0; application image Python 3.12.15. Free host disk was about 30 GiB at inspection and 17 GiB near completion; no broad cleanup was used. System power, firewall, DNS, security and login settings were not changed.

Repository: `/Users/mohammadkhataei/Desktop/AutoTrader`. Runtime: existing Docker Compose stack plus the local-only `docker-compose.mac.yml`, project `autotrader-v46-mac`. New project volumes preserve PostgreSQL, Redis, research and reports independently of all prior projects. PostgreSQL/Redis financial data was initialized fresh; no old account records were imported. Existing immutable research was seeded separately for historical inspection.

## B. Running services

| Service | State | Docker health | Host ports |
|---|---|---|---|
| backend | running | healthy | 127.0.0.1:8000 |
| frontend | running | healthy | 127.0.0.1:3000; 10.0.0.183:3000 |
| postgres | running | healthy | None |
| redis | running | healthy | None |
| research-worker | running | not configured | None |
| worker | running | healthy | None |

All six services use native ARM64 images and `restart: unless-stopped`. The research worker is running/idle and has no Docker healthcheck; its job workflow passed in the separate disposable environment. PostgreSQL and Redis have no host port publication. Schema initialization reached `0011_v42_shadow_isolation` using the supported Alembic path. The completed migration container exits successfully and is not a long-running service.

Actual final [`docker compose ps`](evidence/v4_6_mac_20261026/compose-ps.txt) and [image/service identities](evidence/v4_6_mac_20261026/native-services.json) are retained.

## C. Access information

- Frontend: <http://localhost:3000>.
- LAN frontend: <http://10.0.0.183:3000>. Authenticated access was verified from this Mac; another physical device is unverified.
- Backend: <http://localhost:8000>, loopback only.
- Authentication: HTTP Basic through the frontend API proxy. Username `admin`; find `DASHBOARD_PASSWORD` in the private mode-0600 `.env.local` in this repository. Passwords were not printed or committed. The generated `.env-dashboard-password` is also private/ignored.

Nginx permits private network clients and forwards API authentication. The frontend binds only localhost and the selected private interface. No public forwarding, external domain or tunnel was configured. DHCP changes require updating the private `MAC_LAN_IP` and recreating only the frontend. [Operating commands and sleep/Docker limitations](V4_6_MAC_SERVER.md) explain normal starts; do not use the fresh-deployment helper to reset or restart this populated account.

## D. Test results

| Verification | Result |
|---|---|
| Final backend suite, actual disposable PostgreSQL | 275 passed; one Starlette/AnyIO deprecation warning |
| Focused read-model/health/accounting regression | 25 passed, included in full suite |
| Ruff / Mypy | PASS / 95 source files |
| Frontend unit / TypeScript / production build | 14 passed / PASS / PASS |
| Existing desktop/mobile/error/control browser suite | 30 passed in disposable environment |
| Actual persistent-server review, seven areas, zero API mutations | 2 passed, desktop 1440px and mobile 375px |
| Compiled React/API/worker lifecycle and kill/restart checks | 3 passed in disposable environments |
| Actual ARM64 candidate lifecycles | 15 passed in internal-only disposable cluster |
| Persistent account PostgreSQL/Redis/application restart | PASS; ledger seals unchanged, one funding, EUR500 |

Financial acceptance includes actual simulated orders/fills, partial targets, protective stops, closure, duplicate prevention, reservations, restart recovery, reconciliation, official/shadow isolation and unchanged frozen V4.2/V4.4 files. These are synthetic test outcomes, not public-market returns. No financial controls or fabricated fills were applied to the persistent account. Local backup sets were checksummed and parsed, retained privately, and used to compare ledger seals across restarts. No database was restored over current records. Operational marks/snapshots can advance normally.

The opt-in live browser cases are skipped in the disposable suite and run separately against localhost; they signed in, reviewed all seven navigation areas, exercised read-only paging/comparison, captured screenshots and signed out. Source-bound [verification](evidence/v4_6_mac_20261026/verification.json), [restart proof](evidence/v4_6_mac_20261026/restart-persistence.json) and [ARM64 lifecycles](evidence/v4_6_mac_20261026/container-lifecycles-final.json) retain details.

## E. Actual market observations

Captured 111 read-only samples across 7 distinct five-minute observations, from 11:02:29 to 11:30:10 UTC (12:02:29–12:30:10 CET). Each cycle evaluated nine EUR markets across A3/B3/E3: 27 strategy/market observations per cycle, 189 total. Repeated snapshots are deduplicated by bucket; these are not 189 independent investment opportunities.

| Observation UTC | Technical | Economic | Data exceptions |
|---|---:|---:|---|
| 11:02:29 | 0 | 0 | None |
| 11:05:28 | 0 | 0 | None |
| 11:10:39 | 0 | 0 | None |
| 11:16:03 | 0 | 0 | None |
| 11:21:02 | 0 | 0 | None |
| 11:25:09 | 1 | 0 | SOL-EUR: latest_completed_candle_missing |
| 11:30:10 | 1 | 0 | ETH-EUR: latest_completed_candle_missing |

The baseline scanner covered BTC/ETH/SOL; bounded discovery screened 61 supported EUR markets and added six detailed checks per observed cycle. ADA, BCH, ENA, INJ, PEPE and XRP appeared alongside baseline markets, with selection changing over time. Rejections mainly involved absent breakout/retest confirmation, pullback invalidation, recovery/volume conditions and insufficient persistent relative strength.

The 11:25 observation contained an ADA-EUR A3 technical candidate at EUR75 research size: modeled round-trip cost EUR0.318652, first-target net scenario EUR0.406131, modeled stop loss EUR0.629859 and net reward/risk 0.644797, below the unchanged 1.2 minimum. The 11:30 observation contained a PEPE-EUR A3 technical candidate: cost EUR0.344036 and net reward/risk 1.195527, still below 1.2. Neither qualified economically. These two events are different market observations, not executed positions. Prices, stops, targets and costs remain conditional estimates, not observed future fills or calibrated expected returns.

At final financial capture the official account had 123 persisted WAIT decisions: 35 for `strategy_not_approved_and_validated`; 88 for `Entry conditions not met.`. Orders, fills, open/closed positions and realized/unrealized/net P&L remained zero; equity and available balance remained EUR500; funding count was exactly one. Research approval gates blocked unvalidated official entries.

8 public 429 responses were recorded among 286 requests at the final market-counter capture, with 278 successes, 81 candle refreshes, 96 candle-cache hits and 7407 downloaded candles. Actual public books, spreads and depth were used. Two captured observations explicitly marked missing latest completed candles (SOL, then ETH) as partial; later baseline acquisition continued. Such unavailable observations were not converted into qualifying signals. Full-cycle and raw-capture hashes are in [public observations](evidence/v4_6_mac_20261026/public-observations-summary.json).

Research snapshots remained current at ages above 90 seconds while their quote observations correctly became stale; every order still requires fresh executable data and account admission. Following PID-1 container restarts, prior research displayed RECOVERING and returned to HEALTHY on the next completed observation. No sustained profitability or 30-day performance claim is made.

## F. Problems and fixes

1. Worker freshness incorrectly aged a startup marker instead of periodic heartbeats. The newest persisted heartbeat now drives health; a newer startup timestamp detects restarts even when the container reuses PID 1. Future operation timestamps cannot override valid timing checks.
2. Overview expected available/reserved cash, exposure and realized/unrealized P&L that its compact API omitted. The same repeatable-read financial snapshot now includes those fields, with realized P&L from the journal. Regression compares real partial-exit accounting, proves no new equity snapshots are written by the read model, and preserves unknown valuation for stale marks.
3. Monitoring tested all retained discovery caches, so old unused symbols produced a false global stale status. It now requires complete fresh coverage for every active scanner symbol; stale/missing active caches still fail. Retained historical-cache counts are explicit, and opportunity freshness remains independent.
4. Compact Overview reported a hardcoded V4.5 version; it now reports the running API version.
5. Two-decimal account formatting made distinct sub-cent entry/stop/target prices appear identical. Opportunity prices now preserve sub-cent precision, with account amounts still in cents; reward/risk uses four decimals and shows the actual minimum so 1.1955 is not presented as a passing 1.20.
6. The lifecycle launcher previously hardcoded AMD64. It accepts an explicit ARM64 platform and verifies the actual architecture while retaining all financial assertions. Local Compose publishes only the intended local/LAN frontend and uses native PostgreSQL 16 without changing the VPS configuration.

No strategy conditions, fees, sizing constraints, approval requirements, risk caps or execution-quality checks were relaxed.

## G. Performance

Five local verification samples (concurrent disposable tests were running) gave these API measurements through the frontend proxy:

| Endpoint | Median ms | Maximum ms | Last bytes |
|---|---:|---:|---:|
| `/api/overview/summary` | 16.82 | 23.3 | 1070 |
| `/api/opportunities?limit=12` | 8.9 | 11.54 | 50200 |
| `/api/monitoring/summary` | 29.82 | 33.4 | 5823 |
| `/api/strategies/comparison` | 9.29 | 12.9 | 20104 |

Observed container memory totaled approximately 305 MiB in the last sampled set: backend about 91 MiB, worker 82 MiB, research worker 54 MiB, PostgreSQL 59 MiB, Redis 10 MiB and frontend 9 MiB. CPU sample maxima were backend 16.51%, worker 8.70%, PostgreSQL 1.63%, Redis 1.31% and frontend 1.07% (Docker per-core percentages, not whole-Mac percentages). The idle research worker sampled 0%. Short observations do not establish long-term memory stability.

Observer durations were 6.02–7.99 seconds across the seven captured cycles. The final measured baseline scan is recorded in the state artifact; the sampled scan took 3.40 seconds with zero schedule overrun; protective monitoring continued on its separate approximately five-second cadence. Database SELECT-1 probes took 76–107 ms including Docker exec/Compose startup overhead; this is not pure database execution latency.

Final frontend main JavaScript was approximately 176.44 kB uncompressed; largest deferred chart chunk 372.04 kB, with no >500 kB advisory. Actual local browser loading timings and transferred scripts are retained per viewport; they are cold-context localhost measurements, not remote-device benchmarks. [Performance samples](evidence/v4_6_mac_20261026/performance-summary.json) retain measured values. No unmeasured sustained throughput, false-positive improvement or heavy-research protection guarantee is claimed.

## H. Screenshots

These are the running persistent Personal Plan server with actual public observations; separate synthetic acceptance screenshots are labeled by their evidence files.

[Overview desktop](evidence/v4_6_mac_20261026/mac-live-overview-1440.png) · [Opportunities mobile](evidence/v4_6_mac_20261026/mac-live-opportunities-375.png) · [Cost-constrained detail](evidence/v4_6_mac_20261026/mac-live-cost-constrained-1440.png). All seven areas have desktop/mobile captures in the dated evidence directory.

## I. Git and data preservation

Base RC2 commit: `ed0b53ec5be82d50eb03aa52d0a8ba16ec18d84c`. Changes stay on `feature/autotrader-v46-intelligent-opportunity-engine`; final delivery identifies the exact correction commit after testing. No new release tag/package is created, `v4.6.0-rc.2` is unchanged, and main remains untouched. Only local hosting, read models, financial presentation, tests and dated evidence changed. Old release evidence, frozen runners, existing research/financial data, other project resources and required images/backups are preserved.

Running backend application fingerprint: `a8056c98601d5ce10e4169cf0643cb8b9fec9a5cd9d335cac88a98999ded853e`; execution fingerprint `5a1c7388e5278287b88071ad9f2ce5059069f470610e4350f5d5ae092fc04150`. All 243 Python files match the native image. Original 71 V4.2 and 76 V4.4 files verify unchanged. Credentials, raw high-frequency captures, private local backups and test runtime files remain ignored under `.tools`/private environment files. Only owned disposable acceptance resources are cleaned up; the six persistent Mac services remain running.

## J. Final operating status

**RUNNING — PARTIALLY VERIFIED.** Local infrastructure, public acquisition, accounting, restarts and desktop/mobile UI passed. LAN reachability from another physical device and whole Docker Desktop/host reboot remain unverified. Public data can be rate limited or late; the application records that explicitly and rejects unavailable or uneconomic entries. Docker Desktop must run and the Mac must remain awake and connected. Existing power settings were left intact. The short observation window does not validate strategy profitability. Production/VPS deployment remains outside this task and its existing approval/readiness block is unchanged.
