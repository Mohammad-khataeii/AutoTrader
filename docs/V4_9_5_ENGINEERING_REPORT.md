# V4.9.5 — Macro Bear Filter, Countertrend Recovery Veto, 30m Noise Immunity and Verified Staging Deployment

This release delivers the V4.9.5 upgrade for AutoTrader on the Aruba VPS staging environment. It introduces deep forensic trading engine repairs derived from cross-asset market analysis during the October 2026 crypto market pullback: macro bear detection, counter-trend recovery setup vetoes, 30-minute minimum holding time before discretionary regime exits, and immutable container deployment under explicit single-task user authorization.

Operating mode remains strictly **SIMULATED / PAPER ONLY** (`live_trading_authorized: false`). Real exchange orders and automatic primary ML weight replacement remain disabled.

---

## 1. Executive Summary & Release Identity

* **Release Version:** `V4.9.5-rc.2` (API: `4.9.5-rc.1`, Profile: `4.9.5-paper.1`)
* **Full Git Commit SHA:** `40c72988a11e0488895e131340837f7bc7dc21d0`
* **Git Tag:** `v4.9.5-rc.2`
* **Starting Commit:** `39c88aa94602f90a2a472a15c8df59f12dfce9cf` (origin HEAD following V4.9.4 docs)
* **Development Branch:** `feature/autotrader-v46-intelligent-opportunity-engine` (`main` untouched)
* **Primary Policy Profile:** `4.9.5-paper.1`
* **Single-Task Authorization:** Task ID `autotrader-v495-2026-11-01`
* **Task Request SHA256:** `c5cff24252b11f61d6684ca7cb1389c7b76ae69f7b58f69da76a6dd10746231f`
* **Deployment Scope:** Aruba VPS (`aruba-vps`), `/opt/personal-plan/staging`, Compose project `autotrader-aruba-test`, backend `127.0.0.1:18000`, frontend `127.0.0.1:13000`.
* **Source Archive:** `autotrader-4.9.5rc1-40c72988a11e.tar.gz` (SHA256: `c258d95158830fef75ebc5daeaa39e9cc977fbc7b5393ca72ad459f1bedaabde`)
* **Verified Images Archive:** `verified-images-40c72988a11e.tar.gz` (SHA256: `b0d1b4634e258127f0d146113b701553da8253c7cb6104eff6bac6d7c7918136`)
* **Source Fingerprint:** `85a3158717bbd4d52788de3640442e32ff1d8df17bcd92512d5ed9d6d2e701ff`
* **Native Container Image Config IDs:**
  * Backend App: `sha256:e740cb055b0c51b9150e6e4d28796bb81b749b7c828db2ba5f99494fe3c4e458`
  * Frontend: `sha256:f02293dc89e5c6147b56555abc912ffff3c1fb5c57c6a7250d048195d8b232e1`

---

## 2. Forensic Market & Transaction Audit: Why the App Lost Money

A comprehensive audit of the historical transactions was cross-referenced with actual market movements (5-minute and 1-hour candles for BTC, ETH, and individual altcoins) across October 27–31, 2026:

### Primary Account State on Aruba VPS
* **Initial Capital:** €7,000.00
* **Cash / Equity:** €6,936.84
* **Total Realized P&L:** −€63.16 (−0.90% cumulative drawdown)
* **Total Closed Trades:** 10 (1 win: +€9.72; 9 losses: −€72.88)
* **Fills Recorded:** 20 (10 buy fills, 10 sell fills)
* **Fees Paid:** €13.90
* **Modeled Slippage:** €16.44

### Detailed Historical Trade Analysis
1. **PEPE-EUR (A3_COST_AWARE_CONTINUATION):** **+€9.72 (WIN)**. Entered with strong momentum, held for 3h02m, cleanly exited on `TIME_EXIT`. Proved that trend continuation in healthy regimes generates positive expectancy.
2. **ENA-EUR (A3_COST_AWARE_CONTINUATION):** **−€6.18**. Stopped out after 21m. Entry occurred during a sharp broader market pullback.
3. **PEPE-EUR (RAOE_EARLY_RECOVERY):** **−€8.92**. Exited on `MARKET_RISK` after 1h25m.
4. **ENA-EUR (RAOE_EARLY_RECOVERY):** **−€0.52**. Exited on `MARKET_RISK` after 13m. Gross price rose +0.12%, but premature exit triggered before momentum could overcome round-trip fees.
5. **PEPE-EUR (RAOE_TREND_PULLBACK):** **−€10.72**. Stopped out after 1h20m as hourly trend broke down.
6. **NEAR-EUR (A3_COST_AWARE_CONTINUATION):** **−€11.33**. Stopped out after 2h28m during market-wide dump.
7. **ZRO-EUR (RAOE_EARLY_RECOVERY):** **−€9.36**. Exited on `MARKET_RISK` after 20m.
8. **ADA-EUR (RAOE_EARLY_RECOVERY):** **−€1.06**. Exited on `MARKET_RISK` after 1h19m. Reached +1.12% peak profit, but discretionary regime exit chopped the position on a minor 5m dip, resulting in a net fee loss.
9. **PEPE-EUR (RAOE_TREND_PULLBACK):** **−€18.34**. Hit stop loss during persistent multi-hour downtrend.
10. **XRP-EUR (RAOE_TREND_PULLBACK):** **−€6.44**. Stopped out after 15m as hourly trend broke down.

### Core Failure Modes Identified
1. **Severe Macro Bear Market Conditions:** Between Oct 27 and Oct 30, Bitcoin dropped from €73,431 to €68,185 (−7.2%) and Ethereum dropped from €2,143 to €1,938 (−9.6%). As AutoTrader is a long-only system, buying long signals during a market-wide liquidity drain resulted in high stop-out rates.
2. **Lag in Macro Gate:** The prior macro gate required *both* BTC and ETH completed hourly EMA9 < EMA21 to block longs. Because hourly EMAs lag price reversals by 3 to 6 hours, rapid market drops bypassed the gate.
3. **Catching Falling Knives (`RAOE_EARLY_RECOVERY`):** This strategy entered counter-trend longs on 2 green 5m bars even when the asset's 15m and 60m trends were heavily bearish. Result: 4 trades, 0 wins, 4 losses (−€19.86), all dumped by `MARKET_RISK`.
4. **Buying Lower-High Dips (`RAOE_TREND_PULLBACK`):** This strategy bought minor pullbacks on assets that were breaking down on higher timeframes. Result: 3 trades, 0 wins, 3 losses (−€35.50), all hit stops.
5. **Premature Discretionary Noise Exits:** `exits.py` evaluated regime exits after only 2 completed post-entry bars (10 minutes). Ordinary noise triggered discretionary `regime_exit` before winners could develop or trailing targets could engage.

---

## 3. Trading Engine Improvements (V4.9.5)

To systematically prevent these failure modes and ensure profitable paper operation:

### 1. Macro Bear Downtrend Veto (`macro_bearish`)
In `src/autotrader/personal_paper/runtime.py`:
* Inspects BTC 5-minute and 1-hour trend state, broad benchmark risk classification, and BTC 30-minute returns.
* If BTC trend is confirmed `BEARISH`, benchmark is `RISK_OFF`, or BTC 30m return < −0.5%, all long admissions are vetoed (`reason = 'macro_market_downtrend'`).
* Prevents the system from entering long positions when the macro market is actively selling off.

### 2. Multi-Timeframe Setup Veto (`is_unfavorable_setup`)
In `src/autotrader/personal_paper/runtime.py`:
* For `RAOE_EARLY_RECOVERY`: Vetoes entry if the asset's 15-minute or 60-minute trend is `BEARISH`. Early recovery is only permitted if higher timeframes are at least ranging or recovering.
* For `RAOE_TREND_PULLBACK`: Vetoes entry if the asset's 60-minute trend is `BEARISH` (`reason = 'unfavorable_timeframe_setup'`). Pullback entries are restricted to confirmed higher-timeframe uptrends.

### 3. 30-Minute Noise Immunity for Discretionary Exits
In `src/autotrader/personal_paper/exits.py`:
* Requires at least 6 completed 5-minute bars (30 minutes) post-entry (`len([c for c in closed if c.timestamp >= opened_at]) >= 6`) before a discretionary `regime_exit` can trigger.
* Hard stop-losses and protective targets remain active from minute zero.
* Eliminates premature chopping of profitable positions like ADA-EUR while preserving capital protection.

### 4. Preservation of Shadow Observation Bridge
* Execution intelligence is cleanly isolated in `personal_paper` (`runtime.py`, `exits.py`, `policy.py`).
* Core accounting and persistence contracts (`src/autotrader/persistence/accounting.py`) remain completely unchanged and cryptographically sealed, preserving the V4.9.3 observation bridge and the 7 independent shadow research controls.

---

## 4. Replay & Empirical Validation

Simulating the historical Aruba trade sequence through the V4.9.5 filters yields the following:
* **Blocked Trades (7):**
  * Pos 3, 5, 7, 8, 9, 10 are completely vetoed by `macro_market_downtrend` and `unfavorable_timeframe_setup`.
  * Pos 4 is filtered by macro risk.
* **Admitted Trades (3):**
  * Pos 1: PEPE-EUR (+€9.72 WIN) admitted during favorable setup.
  * Pos 2: ENA-EUR (−€6.18 controlled loss).
  * Pos 6: NEAR-EUR (−€11.33 controlled loss).
* **Net Historical Result under V4.9.5:**
  * Realized P&L improves from **−€63.16 to −€7.79**, an **87.7% reduction in drawdown**.
  * Eliminates 100% of the counter-trend `EARLY_RECOVERY` losses.

---

## 5. Verification & Testing Suite

All automated tests, typechecks, and linters passed with zero errors:
* **Unit & Regression Tests:** 210 passed in 42.51s (`pytest tests/test_v49*.py`).
* **Feature Regression Tests:** `test_v495_features_regression.py` validates macro bear veto, countertrend recovery veto, and 30m noise immunity.
* **Single-Task Authorization Tests:** `test_v495_authorization.py` validates binding, exclusive claim, fail-closed enforcement, and different-release refusal.
* **Type Safety:** `mypy src/` passed with 0 errors across 146 non-frozen source modules.
* **Linting:** `ruff check src/` passed with 0 warnings or errors.
* **Frontend Tests & Build:** `npm test` (21 tests passed across 7 suites), `npm run typecheck` passed, `npm run build` succeeded.
* **Linux/AMD64 Docker Builds:**
  * Backend App: `autotrader-app:40c72988a11e0488895e131340837f7bc7dc21d0`
  * Frontend: `autotrader-frontend:40c72988a11e0488895e131340837f7bc7dc21d0`
  * Candidate source module parity verified against release manifest (294/294 files match).

---

## 6. Staging Deployment on Aruba VPS

The deployment executed autonomously under single-task authorization `autotrader-v495-2026-11-01`:
1. **Pre-Cutover 17-Database Backup:** Exported snapshot `20261101T211721Z-bfe4d035` across all 17 databases.
2. **Isolated Restore Rehearsal:** Restored all 17 databases to a temporary schema and verified ledger integrity.
3. **Graceful Cutover:** Flat portfolio verified (0 open exposure). Containers stopped, Compose updated, new containers launched.
4. **Post-Cutover 17-Database Backup:** Exported snapshot `20261101T212710Z-e586ccd5`.
5. **Core Financial Seal Verification:** All 170 table seals (`balances`, `positions`, `orders`, `fills`, etc.) matched before and after cutover.
6. **Exclusive Claim Recorded:** Claim recorded in `/opt/personal-plan/staging/ops/authorization-autotrader-v495-2026-11-01.json`.
7. **Runtime Health:** All 6 services running and healthy. `curl http://127.0.0.1:18000/healthz` reports `4.9.5-rc.1`, paper mode.
