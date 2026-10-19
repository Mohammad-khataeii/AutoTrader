# V4.6 release candidate: opportunity quality and Personal Plan

Stage A only. No production deployment or account changes. Real-money execution remains disabled.

## Diagnosis and design

The October 19 read-only production observation retains nine reconciled financial databases and all eight original experiment identities. A2 has now recorded **29 accepted BUY decisions and 29 rejected orders, zero fills**. Every refusal is `execution_quality:first_target_destroyed_by_execution_costs`. The October 18 evidence had 13; the increase is normal continued production evaluation, not a rewritten historical result. Missing historical stage traces remain explicitly unverified alongside durable orders.

Five-minute first targets frequently cannot cover fees, slippage and spread. More permissive momentum thresholds cannot repair that mismatch. New successors derive technical evidence first, then check depth, executable prices, precision, quantity, target proceeds, stop loss and net reward/risk. Spread enters once through bid/ask pricing. The minimum feasible target is diagnostic; it never automatically moves the proposed target farther away. Future liquidity and target-hit probability remain unknown.

Independent trend, structure, volatility, liquidity and benchmark dimensions preserve bullish compression. Completed UTC 5m/15m/1h context excludes forming candles and future benchmark joins. The original classifier and frozen V4.2/V4.4 packages remain unchanged.

A3 combines higher trend with controlled recovery, invalidation and higher-horizon target economics. B3 reconstructs a bounded breakout/retest state machine from completed candles, including range, event identity, retest age, confirmation, invalidation and expiry. E3 tests volatility-normalized, persistent benchmark excess rather than requiring a fixed 2% return. Transparent weighted ranks are explicitly not calibrated probabilities. New candidates report data, regime, technical, cost, unknown expected value, unchanged portfolio risk and actual gateway stages separately.

Only explicitly created independent experimental accounts can execute successor signals. No account is created, allocated, reset or promoted by discovery or this release. Existing occupied slots and archive controls remain authoritative. The official account still requires its existing research approval. Observation has no execution authority.

## Research results

The repeatable `scripts/v46_research.py` study uses 60 days of retained Coinbase EUR 5m history, chronological 60/20/20 splits, 72-bar purge/embargo, fourteen preregistered training configurations and locked subsequent comparisons. Previously examined intervals are **not an untouched holdout**. All models remain unvalidated. Original 2×ATR baselines and successors share the event loop, risk and cost assumptions.

| Matched test | Closed positions | Net result | Technical / feasible |
|---|---:|---:|---:|
| A2 | 1 | −€0.26 | Legacy stage counts unavailable |
| A3 | 1 | −€0.48 | 407 / 2 |
| B2 | 0 | €0.00 | Legacy stage counts unavailable |
| B3 | 2 | −€0.95 | 49 / 2 |
| E2 | 0 | €0.00 | Legacy stage counts unavailable |
| E3 | 0 | €0.00 | 14 / 0 |

Validation was also negative: A3 −€5.82/15 positions, B3 −€0.87/2, E3 −€0.71/2. Increased costs removed all test fills. Applying the old single-label bullish filter removed all new fills; removing that exclusion did not establish better returns. The wider eight-asset proxy universe added a few technical observations but no feasible candidates or improved realized test results versus BTC/ETH/SOL. Surviving assets and incomplete candles introduce selection limitations.

Targets test 5m 3×/4×ATR, higher 15m ATR, observed resistance and longer holding, with existing partial targets/trailing protection and time exits. Training parameter stability, regime/symbol group metrics, drawdown, exposure, Sharpe and cost stress are retained in `research-comparison.json`. Training selections are research records, not automatically installed profitable settings; runtime defaults remain experimental.

Bid, pullback and retest entry watches retry IOC at subsequently observed opens for at most three bars. They do not assume a passive queue fill, intrabar first touch or maker pricing. All three test watches were missed/expired; zero net result reflects no fills, not improved profitability. Adverse selection and realized L2 execution cannot be measured with these candles. Historical spread (10bps), per-side fees (10bps), slippage (8bps) and depth (1% prior completed volume) are assumptions, not connected-exchange replay.

The conditional D2 study found 70 primary setups in 12,057 observations. Only 35 observations exceeded E2's fixed 2% excess threshold, and none met all E2 conditions. After conditioning on other vetoes, extension had six active nonoverlapping outcomes and bearish benchmarks five; other active strata were empty. Spread is fixed by the proxy. Independent predictive value is not established, so frozen safeguards were preserved. These forward mark diagnostics are not strategy PnL or causal estimates.

No strategy passed validation. No profitability, prospective performance, 30-day completion or live-execution claim follows from engineering acceptance. A new sufficiently long independent holdout and real historical depth are still needed.

## Discovery and reliability

Supported active EUR pairs receive a cheap cached public ticker screen before at most three extra detailed history/depth validations per five-minute bucket (configurable 0–6), bounded to twelve seconds. The original financial scan executes first. Protective monitoring keeps its separate loop and request priority. On provider deferral, further detail requests stop. Missing, stale and provider failures remain data outcomes, never ordinary strategy failures.

A real public-data measurement screened **61 supported EUR pairs**, excluding the three shared baseline markets; ten passed the summary screen. XRP, PEPE and ADA received details, giving six valid markets in total. The incremental pass took **2.97s and seven successful requests with zero 429s**, with no technical setups or economic candidates. This single warm-cache observation cannot establish sustained rate-limit reduction, false-positive rate or profitability. No production connection or order was used. Public schema follows the [official exchange API documentation](https://developer.revolut.com/docs/api/revolut-x-crypto-exchange).

Deterministic decision/order identities retain durable recovery. A failed gateway attempt preserves its original decision and signal, retries that decision with fresh safety checks and records both attempts. A candle is completed only after the gateway outcome. Historical rejected orders are never replaced with inferred fills.

## Personal Plan and verification

The interface uses Personal Plan, Overview, Opportunities, Strategies, Activity, Research, Decision Insights and Settings. Visible legacy branding/language is normalized without changing backend routes or identifiers. Overview includes available/reserved/allocated funds and realized/unrealized results. Opportunities separates technical, economic and unverified predictive value; unknown values remain unknown and stale quotes become watch-only. Strategy comparison preserves negative results. Immutable images include the completed comparison as a read-only fallback without writing to the existing research store.

Verification evidence is in `docs/evidence/v4_6`. It includes real PostgreSQL financial tests; original identity and source checks; A3/B3/E3 entry, protection and restart tests; desktop/mobile browser checks; AMD64 backend/frontend builds; fifteen actual image lifecycles; and restoration of all nine production-derived databases on an internal network with candidate and rollback-image reconciliation. Synthetic lifecycle success is software evidence only. An initial local restore readiness race was corrected to wait for TCP readiness; its failure diagnostics remain private. Existing production and historical evidence remain intact.

Deployment requires separate approval of the exact full release commit. The approved Stage B must take fresh backups, verify restoration, preserve project `autotrader-v41`, its ports, volumes, financial history, Nginx/TLS and unrelated services, and stop on any failed migration or reconciliation. No new successor account or strategy promotion is included automatically.

Final acceptance: **253 backend tests plus two additional causal research/preflight tests**, 13 frontend unit tests, 27 browser checks, three compiled real API/worker lifecycle checks, Ruff, Mypy (91 files), TypeScript and both AMD64 builds passed. Fifteen image lifecycles and all nine candidate/rollback database restorations passed. Nonblocking notices: the frontend main chunk exceeds the 500 kB advisory, and Starlette emits an AnyIO test-client deprecation. Exact source and image identities are in the hash-bound engineering reports.
