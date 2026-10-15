# V3.4 risk and equity

Hard policy: EUR 500 initial virtual capital; EUR 350 maximum open exposure; EUR 150 free reserve; EUR 100 entry maximum; three positions; EUR 5 planned trade risk; six new daily entries; EUR 15 daily and EUR 35 weekly equity loss limits. No leverage, shorts or averaging down.

Equity is available cash + reserved cash + freshly marked open positions. Entry risk uses marked exposure, not just acquisition cost. Planned risk includes a conservative execution-cost allowance and the worst quoted ask. Risk is checked under the account lock at admission and again before dispatch.

The first funding observation establishes day/week equity baselines. On period rollover, the latest known valid prior observation supplies the baseline. Closing a position moves value from unrealized to realized without counting the same equity loss twice. Closing-fill journal timestamps determine realized reporting periods.

Persisted states: HEALTHY, DATA_DEGRADED, RISK_HALTED, RECONCILIATION_REQUIRED, RECOVERING, STOPPED. Missing or stale open-position marks leave equity unavailable and block entries. They never imply zero loss. Loss breaches persist through process restart and cancel pending entries. Supportable protective exits remain permitted.

Authenticated recovery independently checks journal reconciliation, valuation freshness and both period thresholds. Resume cannot clear an active equity breach. Normal market recovery cannot clear a hard halt.

Proof B values cash=300 and open marks=180, producing equity=480 and daily change=-20 through the real persistence path. Additional tests cover weekly loss after day rollover, stale marks, corrupted projections and exposure changes between intent and dispatch.
