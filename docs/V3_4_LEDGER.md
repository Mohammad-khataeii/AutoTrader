# V3.4 financial journal

`AccountingRepositoryMixin._journal` writes immutable events under the account row lock. A fill and its cash/quantity/basis/P&L postings commit with materialized balances and position state in one transaction.

* INITIAL_FUNDING: +500 economic cash exactly once.
* CASH_RESERVATION / RESERVATION_RELEASE: signed reservation movement; no economic cash movement.
* BUY_FILL: negative notional cash, positive quantity and opening basis.
* FEE: negative cash; opening fees increase basis, closing fees reduce realized P&L.
* SELL_FILL: positive notional cash, negative quantity, proportional basis release and gross realized P&L.

Cash is `sum(cash_delta)`. Available cash is cash less active reservations. Equity is cash plus freshly marked open positions. Reservations never add or subtract equity.

Cost basis includes entry fees. Partial closes release basis proportionally; the final close releases the exact remaining basis. Realized results are recorded at closing fills, not recomputed from a mutable present-day average price. Monetary postings are quantized to 12 decimal places.

`verify_invariants` independently sums immutable postings and fills, then compares balances, reservations, quantities, basis, realized P&L and target progress. Entry admission repeats reconciliation under the account lock. Exits also validate position projections against immutable history before they can execute. A mismatch creates a persisted halt; no balancing entry is manufactured.

Command: `autotrader-reconcile` with the selected DATABASE_URL. It exits nonzero on mismatches. External deposits/withdrawals remain disabled under the fixed EUR500 funding policy. Reviewed projection correction is implemented separately; it cannot create external cash flows or alter immutable source events. Ambiguous legacy history requires reviewed source evidence, not automatic attribution or funding fabrication.


## Reviewed corrections

An authenticated operator pauses entries, reads `GET /api/reconciliation/repair-plan`, reviews the proposed balance/quantity/basis/P&L/target projection changes, then explicitly posts its fingerprint, unique request ID and meaningful reason to `POST /api/reconciliation/repair`. Active orders/reservations must first be resolved. A stale fingerprint is rejected.

The account lock covers source verification, plan validation, projection changes, audit postings and final reconciliation. `AUDITED_CORRECTION` records the operator, reason, original problems, before/after fields and immutable-history digest. A balance projection repair also appends `BALANCE_ADJUSTMENT`, explicitly with zero economic cash delta: it restores the projection instead of manufacturing funding. Concurrent identical requests return one durable audit identity; different content cannot reuse that identity. Financial history is neither edited nor deleted. A correction leaves the existing halt in place until the separately authenticated recovery checks pass.

This tool refuses unresolved legacy attribution, unsupported/unlinked economic events, impossible quantities and nonzero economic adjustments. It cannot guess what a historical trade meant. Tests: `tests/test_v34_corrections.py` and the populated legacy migration test; actual API process, four targeted cases passed, then broader migration/correction regression six passed.
