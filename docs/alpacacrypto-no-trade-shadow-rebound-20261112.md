# November 12, 2026 — AlpacaCrypto no-trade investigation and shadow upgrade

## Verified production observations

Read-only audit at 2026-11-12 05:18 UTC:

- ALPACA_CRYPTO_ENABLED=1; ALPACA_CRYPTO_ALLOW_PAPER_ORDERS=1;
  durable ac_state.paused=0; broker account GET succeeds.
- 1,292 of the last 1,344 execution cycles ended in
  no_approved_spot_long_signal; 39 paused, eight hourly-finalization waits,
  five transient transport failures. There were no order intents.
- Current 33 USD pairs: 32 HOLD, one quality WAIT. Of the 32 HOLDs,
  32 failed 20-hour breakout, 31 failed hourly uptrend,
  28 failed RSI/volatility, and 26 failed daily EMA200.
- Continuation is disabled; recovery is research-only. The current
  recovery candidate check was false for all 32 HOLDs.
- Current TRUMP/USD close is a no-volume quote spike, not trustworthy
  executable price evidence. Do not remove its quarantine.
- No crypto holdings or open crypto orders were verified; stock account
  positions and protective orders exist, and must not be altered by
  crypto research.

## Independent historical market cross-check

Alpaca US crypto 1-hour bars fetched for the fixed UTC interval 2026-11-08
00:00 through 2026-11-12 06:00 (quote-midpoint observations):

| Pair | First close | Last completed close | Change |
| --- | ---: | ---: | ---: |
| BTC/USD | 75,699.7925 | 73,522.2705 | -2.88% |
| ETH/USD | 2,233.43 | 2,041.85 | -8.58% |
| SOL/USD | 89.33 | 82.833 | -7.27% |
| AVAX/USD | 8.20315 | 8.579855 | +4.59% |

AVAX showed relative strength against BTC over this window, but in the
production log its daily-EMA200 test was false and its breakout test was false.
The positive return alone is NOT proof that the model missed an executable
profitable entry. This argues for comparing a relative-strength challenger
against the strict trend baseline with a true cost-aware walk-forward replay.
These numbers are historical interval observations, not an entry forecast.

## Diagnosis

The strict breakout strategy is designed to avoid opening longs in falling
markets, rather than trading every hour. It is behaving consistently with its
rules. Blindly lowering RSI/EMA/breakout requirements would increase trade
frequency without establishing expectancy and could repeat earlier losses.

Alpaca historical crypto candles are *quote midpoints*, even when reported
volume is zero. They are not independently verified trade prints. History-only
positive backtests cannot prove actual bid/ask/depth execution.

## Change in this branch

1. Attach a **research-only early rebound watch** to each completed,
   validated candle evaluation. It requires a prior selloff, rising close
   and higher low, reclaim of a six-hour close average, recent positive
   trading volume, a bounded recovery, RSI 36..62, contiguous recent
   hourly timestamps, and bounded risk. It does not create BUY actions.
2. Add market breadth and exact entry bottleneck counts to the existing
   authenticated /api/stockswatch/alpaca-crypto JSON payload under
   market_breadth_research.
3. Add an isolated, read-only SQLite replay for the shadow watch. The replay
   requires benchmark BTC stabilization for non-BTC trades, uses next-hour
   entry, conservatively resolves overlapping exit thresholds at stop first,
   includes modeled costs, and rejects zero-volume midpoint-only modeled
   holding paths. No production database writes or broker calls.
4. Unit tests cover positive pattern detection, zero volume, missing hour,
   falling knives, chasing a rebound, invalid inputs, and bearish market
   breadth.

## Run in a reviewed container with its existing Python environment

    /opt/stockswatch/venv/bin/python -m pytest -q tests/stockswatch/test_crypto_rebound_watch.py

For offline replay using a **copy or read-only mounted SQLite ledger**:

    /opt/stockswatch/venv/bin/python -m stockswatch.crypto_rebound_replay \
      --db /path/to/readonly/stockswatch.sqlite3 --holdout-days 7

The report intentionally returns approved_for_paper=false even if exploratory
profit metrics look favorable. Historical bars do not contain the bid/ask and
depth evidence needed to validate the actual execution adapter. Replay
simulation also carries model-selection and regime bias; an exploratory
seven-day slice is NOT a prospectively untouched holdout.

## Safe follow-up criteria

- Compare original breakout, optional continuation, existing recovery, and
  rebound watch on forward-only / walk-forward observations with fees,
  realistic bid/ask spread, order size, market depth and missed fills.
- Keep a substantial unseen evaluation window, multiple market regimes,
  minimum sample size, worst-case slippage, and portfolio drawdown limits.
- Only after positive independent evidence, review a separate paper-only
  activation behind an explicit opt-in and the existing shared account,
  broker ownership, capital, depth, and stop-management safeguards.
- Never interpret "more signals" as "better performance." Flat is a valid
  decision in a bearish or data-deficient market.

## Changes expressly NOT made

- NO live trading, leverage, short selling, or extra order permissions.
- NO broker-order submissions, cancellations, account changes or ledger edits.
- NO relaxation of data quality, risk caps, equity OCO, stock pending-order
  reservations, pause, one-shot POST, reconciliation or software exit logic.
- NO deployment or enablement of the new research strategy.
