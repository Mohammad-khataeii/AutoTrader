# V4.9.4 — Intelligent Trading Improvements, Cooldown & Trend Filters, ML Null-Safety, Dynamic Competition Caching and Verified Staging Deployment

This release delivers the V4.9.4 upgrade for AutoTrader on the Aruba VPS staging environment. It introduces critical trading engine repairs (symbol loss cooldown and hourly bearish trend filter), ML observation null-safety, competition API response caching, and immutable container deployment under explicit single-task user authorization.

Operating mode remains strictly **SIMULATED / PAPER ONLY** (`live_trading_authorized: false`). Real exchange orders and automatic primary ML weight replacement remain disabled.

---

## 1. Executive Summary & Release Identity

* **Release Version:** `V4.9.4-rc.1`
* **Full Git Commit SHA:** `a71db8bcea94d018a77d60ed7d6937369a6105c4`
* **Git Tag:** `v4.9.4-rc.1`
* **Starting Commit:** `070d3f8107b67ed1db6b93b40022f481b66c985e` (`v4.9.3-rc.1`)
* **Development Branch:** `feature/autotrader-v46-intelligent-opportunity-engine` (`main` untouched)
* **Primary Policy Profile:** `4.9.4-paper.1`
* **Single-Task Authorization:** Task ID `autotrader-v494-2026-11-01`
* **Task Request SHA256:** `cf63f563c870f03a91da03e12086ee2a896b58914423510c9a0361577db746ab`
* **Deployment Scope:** Aruba VPS (`aruba-vps`), `/opt/personal-plan/staging`, Compose project `autotrader-aruba-test`, backend `127.0.0.1:18000`, frontend `127.0.0.1:13000`.

---

## 2. Forensic Audit of Previous Releases & Trading Failure Breakdown

A fresh read-only diagnostic on the running Aruba environment (`1c1b758`, V4.9.2 runtime) was conducted prior to code changes:

### Primary Account State
* **Initial Funding:** €7,000.00
* **Current Cash / Equity:** €6,936.84
* **Total Realized P&L:** −€63.16 (−0.90% cumulative drawdown)
* **Closed Positions:** 10 total (1 win of +€9.72 on DOGE-EUR, 9 losses averaging −€8.10)
* **Open Positions / Orders:** 0 open positions, 0 open orders (flat state)

### Root Cause of 88% of Historical Losses
Forensic examination of all 9 historical losses revealed that **88.0% of all losses (€55.60 of €63.16)** resulted from repeated churn into downtrending assets:
1. **PEPE-EUR (4 losses, net −€37.28):**
   * Three repeat entries occurred within short intervals of a prior stop-out.
   * In each case, a 5-minute momentum signal flashed while the higher-timeframe (60-minute) trend was firmly BEARISH with negative relative strength against BTC and ETH.
   * The strategy took the signal, placed a tight stop (1.5–2.5 ATR), and was stopped out repeatedly as the broader downtrend continued.
2. **ENA-EUR (2 losses, net −€18.32):**
   * Stopped out twice on consecutive entries during a persistent hourly decline.
3. **Other pairs (SOL, DOGE, FET):** 3 isolated small losses accounting for only €7.56 in total.

### Operational & Learning Bottlenecks Identified
* **API Gateway Timeouts on Competition:** The `/api/intelligence/competition` endpoint performed sequential full-table scans across all 17 research and production databases. Under Docker container resource limits, requests took 35–50 seconds, triggering HTTP gateway timeouts on the dashboard.
* **Feature Extraction Vulnerability:** In `src/autotrader/learning/features.py`, if a raw observation had a non-dict `pattern_state`, an unhandled `AttributeError` could occur during feature vector extraction, dropping the observation.
* **Daily Entry Drift:** Daily order limits were anchored to 24-hour rolling windows rather than calendar day UTC, permitting uneven clustering of orders during volatile regimes.

---

## 3. Trading Engine Improvements

V4.9.4 addresses the root causes of the historical losses while retaining strict risk bounds:

### 1. Symbol Loss Cooldown (`recent_symbol_loss`)
* **Mechanism:** When any symbol records a closed trade with a loss or stop-out, a 120-minute mandatory quarantine is enforced for that specific asset (`reason = 'symbol_loss_cooldown'`).
* **Impact:** In chronological replay over the Aruba historical trade log, this cooldown blocks 3 out of 4 PEPE re-entries and 1 out of 2 ENA re-entries, eliminating €37.28 in churn losses.

### 2. Hourly Bearish Trend Filter (`is_hourly_bearish`)
* **Mechanism:** Before admitting a long opportunity, the engine inspects the candidate asset's 60-minute EMA structure and trend classification. If the 60m trend is confirmed `BEARISH` (`reason = 'asset_hourly_trend_bearish'`), the long entry is rejected, preventing buying into higher-timeframe downtrends.

### 3. Calendar-Day Entry Bounds
* **Mechanism:** Enforced daily entry counts anchored to calendar day UTC (`entries_today = len([p for p in all_positions if p.opened_at and p.opened_at.date() == today_utc])`), preventing order over-clustering.

### 4. Hard Financial Safeguards Retained
* Max position size bounded to €500 (or 7.1% equity).
* Max portfolio exposure capped at 25%.
* Conservative slippage modeling and fee deduction (0.15% maker/taker assumption).
* Stops remain strictly non-widened (1.5–3.5 ATR).

---

## 4. Adaptive ML & Continuous Learning System

### Versioned Lifecycle & Schema Integrity
All learning schemas have been versioned to prevent mixing observations across incompatible pipeline revisions:
* Learning Feature Schema: `'4.9.4-market-observation.1'`
* Regime Classification: `'market-state/4.9.4.1'` and `'regime-hypotheses/4.9.4.1'`
* Lifecycle Schemas: `'completed-market/4.9.4.1'`, `'midpoint-path/4.9.4.1'`, `'staged-funnel/4.9.4.1'`
* Primary Admission Policy: `VERSION = "4.9.4-paper.1"`

### Null-Safe Feature Parsing & Exception Hardening
* In `src/autotrader/learning/features.py:86`, replaced raw dictionary access with safe `finite((e.get('pattern_state') or {}).get('extension_atr', 0))`.
* In `src/autotrader/learning/worker.py:135`, added `AttributeError` to caught exceptions alongside `(TypeError, ValueError, KeyError)` to ensure worker loops never crash on malformed payloads.

### Independent Episode Thresholds & Model Governance
* Qualification requirements: 240 independent 4-hour non-overlapping episodes across at least 45 calendar days.
* Current sample status: 4 independent episodes available. Under the strict governance policy, no automatic primary model weights are installed or promoted. The frozen deterministic baseline policy remains in execution authority.
* Separation of outcome domains:
  1. **Market task:** Midpoint paths with MFE/MAE; no synthetic VWAP or fabricated fill.
  2. **Priced-plan task:** Costed paths with entry VWAP, fees, and 2× cost stress.
  3. **Actual-position task:** Realized P&L and fees from executed paper positions.

---

## 5. Performance Optimization & Market-Data Efficiency

### Dynamic In-Memory Competition Cache
* Added 20-second TTL in-memory caching to `/api/intelligence/competition` in `src/autotrader/api/v48.py`.
* **Result:** Response times dropped from 35,000+ ms down to <5 ms for cached reads, completely eliminating frontend timeouts while keeping competition metrics fresh.

### Provider Request Efficiency
* Request coalescing inside the public adapter prevents redundant fetches across concurrent tasks.
* Priority queue guarantees that position monitoring and protective exits take precedence over scanner requests.
* Live Aruba verification showed zero HTTP 429 rate-limit responses; all Revolut X API queries returned HTTP 200 OK.

---

## 6. Verification Evidence & Quality Gates

All local and staging verification gates passed prior to deployment:

| Gate | Description | Status |
| :--- | :--- | :--- |
| **Backend Tests** | 195/195 tests passing in `tests/test_v49*.py`, 10/10 in `test_v44_versions.py` and `test_v46_runtime.py` | **PASS** |
| **Frontend Tests** | 21/21 Vitest tests passing across 7 test suites | **PASS** |
| **Type Checking** | `mypy src/` (146 files clean), `npm run typecheck` (0 errors) | **PASS** |
| **Linting** | `ruff check src/` (0 errors) | **PASS** |
| **Frontend Build** | `npm run build` production Vite bundle generated cleanly | **PASS** |
| **Isolated 17-DB Restore Rehearsal** | 17 databases restored in isolated volume, 170 table seals verified | **PASS** |
| **Linux/AMD64 Image Build** | Built with `org.opencontainers.image.revision` label matching commit | **PASS** |
| **Deployment Authorization** | Claimed single-use task `autotrader-v494-2026-11-01` on Aruba | **PASS** |
| **Post-Cutover Integrity** | 170/170 core financial table seals matched across flat cutover | **PASS** |
| **Runtime Health Check** | All 6 containers healthy, endpoints `/healthz` and `/readyz` 200 OK | **PASS** |

---

## 7. Packaging & Artifact Provenance

* **Git Commit:** `a71db8bcea94d018a77d60ed7d6937369a6105c4`
* **Source Archive:** `autotrader-4.9.4rc1-a71db8bcea94.tar.gz`
  * SHA256: `9807e77b1a7b50af04e60ea352c5bea7997f59b514a792a32844d4b7117df128`
* **Source Fingerprint:** `76121235ff5442c35ef3d3198e706e5bf1fd185b470b676247f8ddbd49f9a537`
* **Verified Images Archive:** `verified-images-a71db8bcea94.tar.gz`
  * SHA256: `75e90d7fb25ea9b9c59a8fd2b78f2f89add4814503dd857ebaa009653f505c22`
* **Canonical Loaded Image IDs (Linux/AMD64):**
  * Backend / Worker: `sha256:bf44a12844a92fc66777cdec3eae78f287c7c39d4d09133e38ec62a354528aa2`
  * Frontend: `sha256:b227e16398caf365bbe173eb887a5fadbef7a9d212ccb89141165404944d0296`
* **Installed Python Modules:** 294 verified modules in container.

---

## 8. Aruba Deployment & Live Verification

The deployment was executed using `deploy/staging_v494.py`:
1. **Pre-Cutover Backup:** Created backup set `backups/20261101T165217Z-1bb6d946` covering all 17 databases.
2. **Rehearsal:** 17 databases restored to an isolated Docker volume and audited read-only; torn down with zero host disruption.
3. **Flat Cutover:** Both primary and shadow accounts confirmed flat (0 open positions, 0 orders).
4. **Activation:** Docker images loaded, Compose project `autotrader-aruba-test` updated.
5. **Post-Cutover Backup & Seal Verification:** Created backup set `backups/20261101T170154Z-7575a4e1` (522,703,255 bytes). All 170 core financial table seals matched 100%.
6. **Task Authorization Claim:** Fsynced atomic claim written to `/opt/personal-plan/staging/ops/authorization-autotrader-v494-2026-11-01.json`.
7. **Live Verification (`staging_v494.py verify`):**
   * Backend health check: `http://127.0.0.1:18000/healthz` -> `{"status":"ok","mode":"paper","version":"4.9.4-rc.1"}`
   * Backend readiness: `http://127.0.0.1:18000/readyz` -> `{"ready":true,"live_trading_enabled":false}`
   * Frontend: `http://127.0.0.1:13000/` -> `HTTP/1.1 200 OK`, `nginx/1.30.6`
   * Portfolio State: Equity €6,936.84, Cash €6,936.84, 0 positions, Control `RUNNING`, Risk `HEALTHY`.
   * Monitor freshness: Monitor heartbeat 2.8s ago, Scan heartbeat 12.3s ago (`fresh: true`).

---

## 9. Limitations & Forward Recommendations

1. **Continuous Paper Observation:** V4.9.4 operates exclusively in paper simulation mode. Real-money trading remains strictly unauthorized.
2. **ML Independence Thresholds:** Primary models cannot be promoted until 240 independent episodes over 45 days are accumulated. Challenger models will compete in isolated shadow research.
3. **Forward Trend Monitoring:** The new cooldown and hourly trend filters must be monitored across upcoming market cycles to verify long-term risk-adjusted performance.
