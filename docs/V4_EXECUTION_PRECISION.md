# Executable pricing

`execution/pricing.py::quote_execution` is the single depth walk used by durable
dispatch and position target feasibility. Midpoint remains a valuation mark.
Long protection and post-TP monitoring use best bid. A gap stop executes against
the observed bid ladder, including configured slippage and fees; the stop price
is not a promised fill. Protection takes priority over time, market-risk and targets.

Target prices are minimum net unit proceeds. Repository admission upgrades every
target-linked SELL to LIMIT IOC, even for direct callers requesting MARKET.
The gross price floor is target divided by one minus the fee rate, rounded upward
to accounting precision. Slippage-adjusted bid levels below that floor cannot fill.
A partial fill advances only its attributed target by the confirmed filled quantity.

The book must be finite, positive, sorted, uncrossed, two-sided and no older than
90 seconds (future tolerance 5 seconds). Wide spreads do not suppress valid
protective exits. Stale/missing protection creates a durable position watch and a
deduplicated CRITICAL incident. It creates no invented fill; fresh data is evaluated
on the next cycle. Persistent stronger risk/reconciliation halts are preserved.

Every economic dispatch records VWAP, costs, fillable/unfilled quantity, both
displayed depths, age, spread and level allocations in its order execution JSON.
Per-side consumed quantities are stored under a digest of the canonical book in
`system_state`, under the account lock and in the same transaction as the fill,
journal, cash and target changes. Rollback rolls back consumption too. Distinct
intents and restarted workers cannot spend the same observation twice.

`ExecutionQualityEngine` screens new entries for spread, executable minimum
notional, observed exit depth and first-target reward destroyed by costs. It reports
breakeven bid, immediate round-trip loss and target scenarios. These are cost
calculations, not win probabilities or evidence of predictive edge. Existing hard
portfolio risk checks remain authoritative under the account lock.

Verification is tracked in V4_TEST_EVIDENCE.md and V4_COMPLETION_MATRIX.md.
