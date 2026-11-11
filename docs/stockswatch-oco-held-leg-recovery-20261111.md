# 2026-11-11 StocksWatch OCO verification repair

## Exact broker evidence (read-only, Alpaca PAPER)
At 2026-11-11 ~21:26 CET, operator independently checked:
- AAPL: 33-long, 0 available. OCO TP \`new\` qty 33,
  stop-leg \`held\` qty 33 at $329.12.
- ABBV: 40-long, 0 available. OCO TP \`new\` qty 40,
  stop-leg \`held\` qty 40 at $275.61.
- ACN: 46-long, 46 available. **No broker-side OCO order** in snapshot.
- AMGN: 25-long, 25 available. **No broker-side OCO order** in snapshot.
- StocksWatch local AAPL/ABBV protections: \`UNVERIFIED\`,
  \`last_error=protection_oco_stop_missing\`.

For November 11 first-hour EOD broker cycle, 77 iterations, with 6,900
ticker-level rejections, predominantly
\`stock_protection_not_armed_blocks_new_entry\`.
New stock-entry pause and stock paper OCO permission were already enabled
correctly: \`paused=False\`, \`STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS=1\`,
\`STOCKSWATCH_PROTECTION_ALLOW_PAPER_ORDERS=1\`.

## Root cause and fix
1. \`profit_oco._validate_pair\` recognized only \`new\`, \`accepted\`,
   \`pending_new\`, \`partially_filled\` as valid stop-leg statuses.
   Alpaca reports contingent OCO stop legs as \`held\`.
2. \`UNVERIFIED\` then disarmed mutation and *also* prevented nested open-order
   GET, so the monitor could never revalidate a recovered broker stop.
3. \`_verify_strategy_exit\` had the same held-leg status omission.
4. Broker-cycle status remained \`NO_APPROVED_BROKER_SIGNAL\` although
   most candidate buys were refused by the protection interlock.

The patch accepts \`held\` ONLY for contingent STOP children of otherwise
valid OCO parents. It checks child identity, symbol, equal share quantity,
price and stop monotonicity; it never treats a \`held\` parent as active.
The manager continues **read-only nested GET reconciliation** while
uncertain records disable OCO POST/PATCH. One cycle re-verifies existing
OCOs, and a subsequent cycle may resume strictly validated exits and
protection creation for **owned** unprotected shares.
The new \`BLOCKED_BY_PROTECTION\` reason is explicit in the broker decision
journal; it does NOT override the entry protection gate.

## Scope and recovery
This commit modifies StocksWatch stock paper code ONLY, based on confirmed
deployed commit e74c1eb3c1d24b990667d8abf0a1d62fdd876a09.
It does not change Alpaca credentials, crypto strategy, live trading, the
database schema, money management, or existing broker orders.

On deployment, **no broker order is placed by the deployment script**.
The running stock protection worker may attempt normal OCO exits on future
regular-session cycles, if order and position ownership are validated.
No OCO is promised for ACN/AMGN until broker API confirms it.
Never clear, recreate, or cancel uncertain orders merely to force entries.

Verify after the next core-session cycles: \`sw_protection\` AAPL and ABBV
should become \`ACTIVE\` with broker-verified stops; ACN/AMGN must each
have separately verified broker-native OCO exit legs, OR remain explicitly
unprotected and block new entries. Unknown/partial stop coverage fails closed.

A pending OCO stop is not a guaranteed fill; gaps, halts and slippage remain.
