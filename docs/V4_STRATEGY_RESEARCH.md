# Versioned strategy research

The production scanner uses the V4 registry in `research/strategies.py`.
Six entry hypotheses are independently enabled: trend pullback, compression
breakout, breakout retest, volume accumulation, relative strength and range mean
reversion. Failed-breakout and risk-off filters never open positions. Each registry
entry includes version, hypothesis, inputs, entry, invalidation, exit, holding bars,
eligible regimes, cost assumptions, risk policy and validation status.

V4 decisions require explicit eligibility; an arbitrary aggregate score cannot
force entry. `LegacyStrategyEngine` preserves V3.4 signals for a separately named
common-execution comparison. The old unit force-entry fixture now declares V4
eligibility explicitly while retaining its risk-rejection assertions.

Historical research runs a deterministic in-memory event model. It shares the
production signal rules, RiskEngine, IOC quote kernel, proportional closing postings
and volatility trailing calculation. PostgreSQL durability and concurrency remain
properties of the real execution repository, independently verified by process tests.
This distinction is explicit in every report; the simulator is not a second durable
production ledger and cannot send orders.

Historical entries use next observed bar opens with an explicit sizing cushion.
The runtime uses current venue asks and metadata rounding. Research uses a fixed
base-quantity step and continuous modeled target prices; historical venue tick-size
changes are unavailable. Therefore historical hypotheses require additional venue
and deployment-timeframe acceptance before promotion. The existing full-component
Backtester also replays persisted 5m bars through the actual scanner/gateway/manager
and isolated repository; its shorter replay is an integration check, not proof of edge.

No candidate passed the final research gates. The validated ensemble stays in cash.
Production requires explicit approval, a matching source fingerprint, validation of
the live 5m timeframe, and exact matching frozen parameters. Daily/4h performance
cannot authorize the live 5m configuration. Financial acceptance tests are explicitly
ENVIRONMENT=test and exercise real rules/execution without claiming predictive validation.
