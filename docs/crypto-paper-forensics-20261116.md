# November 16 AlpacaCrypto PAPER no-trade forensic audit

Evidence: Read-only user-provided Aruba export collected 2026-11-16 09:54:49 UTC. The export contains 8,996 execution cycles, 4,950 first-seen USD signal-audit rows, 6,844 historical signal rows, and 46,071 USD hourly/daily midpoint candles. It contains **no broker fills or bid/ask snapshots at signal timestamps**.

## Exact execution attribution

| Cycle outcome | Count |
|---|---:|
| no_approved_spot_long_signal | 8,742 |
| crypto_new_entries_paused | 88 |
| crypto_shared_account_stock_orders_pending | 79 |
| crypto_waiting_for_completed_hour_finalization | 75 |
| crypto_paper_transport_unavailable | 12 |

Paper order permission=1, LIVE_TRADING_ENABLED=false, all 33 USD pairs marked eligible. There are **zero** ac_intents, ac_managed and ac_admission_audit records. The append-only signal audit (Nov 10 onward) has 4,541 HOLD, 409 WAIT, 0 BUY; **however** the older mutable ac_signals table preserves **one valid PEPE/USD BUY** from the completed Nov 9 15:00 UTC candle, evaluated Nov 9 16:57 UTC, reference close 0.00000532, score 1.0. Its cycle outcome was crypto_shared_account_stock_orders_pending, so no order was created. Do not claim there were zero computed BUY signals ever.

The stock-order interlock stops after November 10; from November 13 to 15, almost every execution cycle returns no_approved_spot_long_signal. The reasons are now mainly *technical filters*, not an Alpaca paper API rejection.

## Exact gate bottlenecks

Among 4,541 HOLD observations: hourly_uptrend true 74; daily_above_ema200 true 741; 20_hour_breakout true 45; rsi_volatility_healthy true 1,764. Of four checks, 0/1/2/3/4 passing counts are 2,235/2,015/264/27/0. The 27 near misses are concentrated in PEPE (20), HYPE (6), RENDER (1). There were 104 continuation candidates, 23 recovery candidates, and 30 shadow early-rebound candidates; continuation flag was unset, recovery_mode was research.

## Market condition and causal forward comparison

All 33 USD pairs declined from 2026-11-09 16:00 UTC candle close to 2026-11-16 08:00 UTC candle close. Examples BTC -14.10%, ETH -15.33%, SOL -18.57%, AVAX -18.19%, AAVE -18.73%, UNI -25.95%, PEPE -28.48%. PEPE had 54% zero-traded-volume hourly bars during this period: midpoint observations must not be treated as executions.

Using the next hourly *midpoint* open if reported volume is positive and measuring the midpoint close six hours later, with 0.15% fee and 0.10% slippage **per side**, the rejected-candidate categories have these purely hypothetical outcomes:

| Research entry type | 6h observations | Mean 6h cost-adjusted midpoint return | Six-hour positive |
|---|---:|---:|---:|
| 3 of 4 original gates | 16 | -1.715% | 25.0% |
| Continuation candidate | 69 | -1.211% | 14.5% |
| Recovery candidate | 20 | -1.038% | 20.0% |
| Shadow rebound watch | 27 | -1.302% | 14.8% |
| Proposed paper_active_hourly_reclaim | 71 | -1.461% | 11.3% |

These are **overlapping observations, not independent trades**, and do not include actual historical quoted spreads, depth, paper fill probabilities, stop executions, position allocation, or outcome certainty. In particular, the active-reclaim candidate yielded 94 signal bars, 71 with enough positive-volume next-hour and six-hour follow-up evidence. All 94 passed the initial three-hour BTC stabilization rule, which is not an effective broad-downtrend screen. This proposed experimental long entry should **not be represented as profitable, backtested and approved for production**, or activated by default.

A candidate HYPE recovery watch at Nov 12 15:00 had modeled +0.45% over 6h, +2.14% over 24h, whereas the PEPE near-miss Nov 10 14:00 had approximately -5.89% over 6h and -11.54% over 24h. Individual positive observations are not an exploitable strategy.

## Changes on this draft branch

- Add a causal, completed-candle, quality-aware exploratory paper entry with explicit ALPACA_CRYPTO_ACTIVE_PAPER=1 opt-in (default disabled).
- Preserve real broker Alpaca Paper identity, stock OCO/account cash isolation, quote/depth admission, software exits, one-shot order submission, and crypto spot LONG/FLAT. No live execution.
- Apply BTC four-bar stabilization and one new experimental entry per hour; BTC screening must be redesigned before claims of profitable behavior.
- **Cap each experimental paper entry at $25–$200 notional**, additionally bounded by equity 0.2%, cash, displayed order depth and existing portfolio risk ceilings.
- Include read-only candidate replay and unit tests.

This release is **research / controlled paper experimentation only**, not a validated strategy or a current deployment recommendation. No broker orders or VPS deployments were performed.

## Additional observed issues

- Exported ac_state count is 1, but its row was omitted by the forensic exporter due to a duplicate SQL LIMIT clause. Current paused state therefore requires a corrected collector or direct read-only query.
- November 12 logs contain warnings about missing verified stock protection on ACN/AMGN and November 13 stock worker SQLite OperationalError events. Diagnose independently; do not modify stock positions/OCO to force crypto orders.
- Docker logs in this archive begin Nov 12 despite the SQLite execution history beginning Nov 9.

## Next checks

Full-source integration tests, actual read-only SQLite replay on a stable copy, exact running Python file hashes and broker inventory, bid/ask/depth and market risk checks, paper-only canary with very small notional, and an explicit review of realized/slippage performance. No automatic deployment or order activation.