# StocksWatch EOD LONG protection — paper-only ATR + OCO + profit-lock

## Scope and operational truth
- Target: existing StocksWatch EOD-owned **LONG US equities** in the verified
  Alpaca **paper** account, including positions acquired before this release.
- Alpaca Paper OCO exits pair a fixed **take-profit limit** with a **stop-market
  sell**, with the stop leg modified upward by an explicitly verified PATCH.
- Protected TP/SL orders are broker-held, but do not trigger outside regular US
  equity hours. The stop is a trigger price, **not a guaranteed exit price**.
- Existing intraday, SHORT, crypto and live execution are not activated.
- Additional AlpacaCrypto and legacy crypto source are preserved.
- Feature remains **read-only by default**:
  `STOCKSWATCH_PROTECTION_ALLOW_PAPER_ORDERS=0` (unset is equivalent).
- No existing broker positions or protective orders are canceled to adopt a
  position. Unknown broker order outcomes are persisted and never retried.

## Mathematical policy (initial, not statistically optimized)

Let `E` = broker-verified average fill price, `Q` = broker-owned shares,
`A` = ATR14 from 15 consecutive certified Alpaca IEX RAW daily bars.

- Initial per-share risk = `max(0.03E, min(0.08E, 2.5A))`
- First broker stop = `floor_cent(E - risk)`
- Take-profit = `ceil_cent(E + 2.5 × (E - initial_stop))`
- Peak favorable movement `MFE = max(0, max_verified_bid - E)`
- Progress toward TP = `MFE / (TP - E)`
- At 40% toward TP: breakeven plus 0.2% execution-cost buffer
- At 60%: protect at least 25% of MFE
- At 80%: protect at least 60% of MFE
- At 90%: protect at least 70% of MFE
- Additional ATR Chandelier candidate: `max_verified_bid - 2.7 × ATR14`
- **Stop never decreases**; candidate needs sufficient clearance from fresh
  IEX bid and a verified matching OCO stop leg before any PATCH.
- The saved high-water mark uses only fresh bid observations taken after the
  protection monitor starts; it does not retroactively treat historical highs
  as broker-observable or achievable.

For a 40-share position at $100 with ATR14 of $0.48: initial stop $97.00,
TP $107.50 ($300 total desired gain), and an observed bid of $106.25
($250 unrealized profit) gives an upward stop trigger protecting **at least**
$150 *before slippage*. A larger stop lock can result from the Chandelier
candidate. Whether a SELL executes near that trigger is uncertain.

## Execution state machine
- `NOT_PLACED`: read-only planned stop/TP. No broker order exists.
- `PREPARED`: durable intent recorded **before** POST, must not be replayed.
- `ACKNOWLEDGED`: broker responded with matching paper OCO identity, but
  neither stop leg nor effective broker price has been verified yet.
- `ACTIVE`: broker nested OCO confirmed with one matching open stop leg,
  monotone stop, fixed TP and correct owned equity inventory.
- `REPLACE_PENDING`: desired higher stop persisted **before** PATCH; never
  issue a second PATCH until the broker shows the requested price.
- `REPLACE_UNCERTAIN`, `UNKNOWN`, `UNVERIFIED`: freeze new automated
  protection mutations until operator reconciliation. Do not clear the
  position or resubmit a second sell.

The shared StocksWatch broker-cycle lock serializes OCO and EOD
submission checks. Verified protective OCO order IDs are included in
risk-budget ownership accounting so unrelated stock buys are not
mistakenly blocked as external orders.

Only EOD-owned verified LONG holdings may be adopted. Existing manual
positions, shorts, corporate-action-ambiguous positions, partially
available positions, conflicting open orders and positions missing
certified ATR evidence are not automatically adopted.

## Important limitation before optional broker activation

The legacy EOD strategy can request an early trend-based SELL before the
broker-native TP/SL triggers. While the same shares are reserved by an
OCO, submitting a *second* market sell is unsafe. This patch intentionally
refuses that competing EOD SELL; it does **not** cancel existing protection
to force an early exit. A separately reviewed, broker-verified OCO-to-market
handoff is needed if strict early trend exit semantics are required.

**Do not arm OCO broker submissions until that design trade-off is reviewed.**
Until then the new Protection tab is a read-only advisory, showing broker
proof only when an order actually exists. Upward-only stops do not
eliminate gap risk, intraday gaps, high volatility, or failed broker orders.

## Release acceptance checklist
1. `python -m pytest -q tests/stockswatch` and frontend build pass.
2. Verify source commit exactly, broker account ID, scope, 2 existing LONGs,
   no unowned broker orders, ledger backups and disk health on Aruba.
3. Deploy backend with `STOCKSWATCH_PROTECTION_ALLOW_PAPER_ORDERS=0`.
4. Check the authenticated read-only
   `GET /api/stockswatch/profit-protection` report after broker refresh.
5. Separately merge/deploy the new frontend; protect current crypto UI
   revision and remove stale navigation only after validating the merge.
6. Paper OCO activation is a **separate future reviewed change**, not part
   of the read-only release. Do not enable production live trading.
