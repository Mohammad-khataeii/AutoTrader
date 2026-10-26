# Personal Plan V4.7 — Mac paper execution release

Status: the shared virtual portfolio is running on the Mac. Engineering acceptance, historical proxy research and prospective paper performance are separate evidence categories. This is Stage A local development, with no VPS access/deployment and no release tag. Real trading remains disabled. Exact Git commit/push and the final numerical observation snapshot accompany delivery.

## Why the prior system did not trade

| Finding | Classification and measured evidence | Resolution |
|---|---|---|
| Official strategy approval has no validated member | Expected safeguard. Baseline operation was `RESEARCH_ONLY`; the official EUR500 account had no orders or fills. | Preserve its approval policy and financial history. |
| Successor observation has no funded execution domain | Missing capability. `OpportunityObserver` records research, while `scan_successor` needs an active successor experiment. The two actual active shadows were A2/B2, not A3/B3/E3. A PEPE A3 observation could be economically feasible without reaching a broker. | Explicit primary experimental account and a coordinator consuming the existing shared baseline/discovery observations. |
| Existing A2 and B2 fail technical confirmation | Strategy/data limitation. Each baseline shadow had 39 evaluations, zero eligible signals, zero allocation or execution attempts; `higher_timeframe_bullish` was the causal first blocker in all 39. Other independent failures included breakout/recovery and volume conditions. | Retain evidence and frozen identities. Evaluate other hypotheses independently; do not weaken the official gate. |
| EUR500 sizing/policy is embedded in decisions, allocation and ledger admission | Appropriate original policy, unsuitable for a different funding scope. Default decisions/allocation clipped proposals to EUR75–100 and ledger risk instantiated EUR500 defaults. | Overridable account policy, with unchanged old defaults and an isolated primary policy. Primary sizing uses stop loss, cash, exposure, depth and instrument constraints. |
| Successor holding time falls back to 24 hours | Execution fault: the ledger recognized older strategy versions when translating holding bars into an exit plan. | The new primary account records the intended 36 five-minute bars, approximately three hours, instead of the fallback. Historical frozen behavior is retained. |
| Distant ask levels inflate planned loss | Latent execution fault confirmed by the first real primary admission. A PEPE BUY was persisted as rejected: an unused ask at 0.0000045950 was treated as the entry price although its consumed-size quote was 0.000003913163. | Correct both locked reservation and dispatch checks to use consumed ask liquidity. Preserve the EUR35 risk limit, original rejected order and original profile. Explicitly start runtime profile `4.7.0-paper.2`; never resubmit that historical order. |
| Net reward/risk, invalid/missing completed candles, minimum exits, costs and liquidity | Genuine economic/data safeguards. The baseline and forward records distinguish technical, economic, account and broker failures. | Keep rejection evidence. Fresh books and valid completed context remain mandatory; no synthetic candles or zero-cost assumptions force activity. |

Relevant paths: `worker/runner.py`, `decision.py`, `opportunity/service.py`, `opportunity/runtime.py`, `opportunity/engine.py`, `opportunity/economics.py`, `shadow/runtime.py`, `execution_gateway.py` and `persistence/accounting.py`. The baseline trade-gate and recorded-depth diagnosis JSON files contain the measured evidence. No incomplete fill-handling failure was observed in the inactive old accounts; complete order/fill/recovery behavior was verified separately.

## Shared account and execution architecture

`PERSONAL_PLAN_PAPER_7000` has exactly one EUR7,000 virtual funding event in a separate PostgreSQL database, using the existing Alembic schema, identity marker, paper gateway, order transitions, capital reservations, side-aware fill model, exit plans, journal and reconciliation. The official EUR500 and both old shadow balances are excluded from its equity. No existing account was reset or refilled.

A3, B3 and E3 compete for one cash pool. Completed observations are enriched with synchronized context; economic qualification precedes transparent score ranking. The strongest qualified candidates receive priority, duplicate asset entries are blocked, and final admission/reservation/fill checks run under the same account lock. Pending commitments consume cash and exposure. Strategy and asset attribution remain durable. Equal prior weights avoid chasing statistically insignificant early P&L.

Defaults: EUR700 position cap; EUR35 planned loss per position; EUR140 aggregate stop risk; EUR2,100 crypto-cluster and per-strategy capital caps; EUR2,800 cash reserve; six positions; 24 new entries/day; EUR140 daily/EUR350 weekly loss thresholds; 10% drawdown halt. The conservative crypto-cluster cap currently binds before the EUR4,200 overall exposure ceiling. Stops are estimates, not guarantees against adverse gaps. These limits are enforced in the ledger, not merely the dashboard.

Entries consume observed asks with explicit fees, slippage, precision, minimums and finite depth. Exits consume bids. Partial fills and unused reservations are reconciled. Stops, economically feasible partial targets, trailing/break-even protection, time expiry, reversal/invalidation and emergency handling reuse the existing position manager. Target exits use executable net-price floors. Limits use conservative IOC execution; a passive touch/queue simulator is not implemented. Hypothetical future exit costs are not posted as realized fees. Spread is represented by executable bid/ask prices rather than charged again.

Protection and lease renewal run independently of scans, nominally every five seconds. Scans run about once per minute; discovery is bounded and runs on completed five-minute observations. Strategy/candle outcomes are committed after gateway completion with deterministic IDs. Interrupted durable reservations recover; retries and restarts cannot duplicate funding or positions. Hourly research reviews retain blocker/cost/regime evidence and versioned proposals. They do not rewrite parameters or deploy research candidates.

The original `4.7.0-paper.1` account marker and manifest remain immutable. The depth correction used an explicit paused, flat, reconciled cutover to an appended profile, with a parent-linked profile in both databases and an active hash pointer in the official registry. There is still one account and one funding event. New signals/decisions identify their profile; financial totals span the shared account while attribution distinguishes execution profiles. Worker startup never silently creates a revision.

## Revolut X observations

The [official API reference](https://developer.revolut.com/docs/api/revolut-x-crypto-exchange) was inspected on October 26, 2026. Public and authenticated versions differ.

| Used endpoint | Authentication | Cache/cadence and purpose |
|---|---|---|
| `/1.0/public/configuration/pairs` | None | About five-minute cache; region, availability, precision, order minimums/maximums. |
| `/1.0/public/tickers` | None | One-minute cache, bounded discovery roughly every five minutes; spread, liquidity/volatility ranking. |
| `/1.0/public/candles/{symbol}` | None | Incremental five-minute refresh, up to 720 primary bars, completed and contiguous context. |
| `/2.0/public/order-book/{symbol}` | None | Fresh entry quotes and higher-priority protective observations; actual bid/ask depth. |

Existing shared one-request-per-second family budgets, cache, retry, backoff and millisecond Retry-After handling remain in use. Discovery reuses observations and cannot bypass protective priority. Rate limits and incomplete candles remain visible limitations. Public EUR markets suffice for this release; USD is excluded until a genuine FX ledger is verified. Authenticated `/1.0/order-book/{symbol}` and read-only credential transport are not implemented because they were unnecessary for current public paper operation.

## Strategy research and evidence boundaries

The fixed panel contains 69 strategy/timeframe status rows across 5m, 15m, 1h and 4h, plus 19 execution/size/parameter sensitivity trials. It uses existing checksummed Coinbase EUR OHLCV proxies, eight available assets, chronological training/validation/reused-holdout segments and purges. It is not a EUR7,000 portfolio backtest. The original EUR500 research execution/risk model supplies explicit liquidity and cost assumptions without historical L2.

The datasets were used in earlier releases. A chronological label does not make that holdout independent again. No strategy is promoted from this descriptive panel. Parameter trials, cost stress and conservative patient IOC alternatives are retained, including failures and no-trade outcomes. Requested size sensitivity applies to successor runs; the original native simulator retains its EUR75 proposal cap.

| Strategy | Model version | Reused 5m holdout: net EUR / positions | Longer-horizon note | Primary execution |
|---|---|---|---|---|
| `A_TREND_PULLBACK` | 4.0.0 | -0.6115 / 8 | 15m: -17.02 / 51; 1h: -26.86 / 128; 4h: +1.18 / 35 | Isolated research only |
| `B_COMPRESSION_BREAKOUT` | 4.0.0 | -0.2261 / 3 | 15m: -3.65 / 21; 1h: -26.10 / 47; 4h: -2.64 / 7 | Isolated research only |
| `C_BREAKOUT_RETEST` | 4.0.0 | -0.5523 / 3 | 15m: -4.11 / 19; 1h: -1.98 / 34; 4h: +3.32 / 12 | Isolated research only |
| `D_VOLUME_ACCUMULATION` | 4.0.0 | -2.6621 / 9 | 15m: -15.71 / 41; 1h: -40.48 / 112; 4h: -4.51 / 34 | Isolated research only |
| `E_RELATIVE_STRENGTH` | 4.0.0 | +0.0000 / 0 | 15m: -1.05 / 11; 1h: +11.26 / 92; 4h: +11.35 / 43 | Isolated research only |
| `F_MEAN_REVERSION` | 4.0.0 | -0.5367 / 3 | 15m: -6.17 / 21; 1h: -13.38 / 31; 4h: -7.53 / 6 | Isolated research only |
| `G_FAILED_BREAKOUT_FILTER` | 4.0.0 | Veto only | No standalone orders | Isolated research only |
| `H_RISK_OFF_FILTER` | 4.0.0 | Veto only | No standalone orders | Isolated research only |
| `A2_CONFIRMED_PULLBACK` | 4.2.0-experimental.1 | +0.0000 / 0 | Frozen primary is 5m; higher context is joined causally. Other primary timeframes reported incompatible. | Isolated research only |
| `B2_CONFIRMED_COMPRESSION` | 4.2.0-experimental.1 | +0.0000 / 0 | Frozen primary is 5m; higher context is joined causally. Other primary timeframes reported incompatible. | Isolated research only |
| `C2_LIQUID_RETEST` | 4.2.0-experimental.1 | +0.0000 / 0 | Frozen primary is 5m; higher context is joined causally. Other primary timeframes reported incompatible. | Isolated research only |
| `D2_MOMENTUM_QUALITY` | 4.2.0-experimental.1 | Veto only | No standalone orders | Isolated research only |
| `E2_ABSOLUTE_RELATIVE_STRENGTH` | 4.2.0-experimental.1 | +0.0000 / 0 | Frozen primary is 5m; higher context is joined causally. Other primary timeframes reported incompatible. | Isolated research only |
| `F2_RESTRICTED_RANGE` | 4.2.0-experimental.1 | +0.0000 / 0 | Frozen primary is 5m; higher context is joined causally. Other primary timeframes reported incompatible. | Isolated research only |
| `A3_COST_AWARE_CONTINUATION` | 4.6.0-experimental.2 | -0.6305 / 4 | Frozen primary is 5m; higher context is joined causally. Other primary timeframes reported incompatible. | Selected, unvalidated |
| `B3_STATEFUL_BREAKOUT` | 4.6.0-experimental.2 | +0.0000 / 0 | Frozen primary is 5m; higher context is joined causally. Other primary timeframes reported incompatible. | Selected, unvalidated |
| `E3_ADAPTIVE_RELATIVE_STRENGTH` | 4.6.0-experimental.2 | +0.0550 / 1 | Frozen primary is 5m; higher context is joined causally. Other primary timeframes reported incompatible. | Selected, unvalidated |

The earlier V3.4 engine's eight signal hypotheses (volume accumulation, compression, retest, momentum, failed-breakout filter, risk-off filter, relative strength and order-book liquidity) were enumerated and evaluated as their implemented ensemble. Individual scores are not complete standalone order policies. Their observation/positive-score/veto counts are retained in the research result, rather than inventing independent legacy portfolios.

Exact frozen V4.2 and V4.4 runners also evaluated all six original entry hypotheses at 5m/4h and all five experimental entries at 5m: 34 additional frozen-generation result rows. All 71 V4.2 and 76 V4.4 source files verified unchanged. Container tests exercised original frozen, current-native and successor execution paths independently.

Within their matched windows, older five-minute entries generally lost after costs, the strict A2/B2/C2/E2/F2 holdout had no trades, A3 lost EUR0.6305 over four positions, B3 had none, and E3 gained only EUR0.0550 over one. That single small gain is not evidence of an edge. Original relative strength was more promising than several alternatives in the 1h/4h proxy windows. The E4 slow-rotation research identity changes only its documented parent parameters; it remains research-only. Windows, purge lengths and sample sizes differ by timeframe, so absolute P&L is not a cross-timeframe ranking. No configuration passed independent prospective validation or earned live authorization.

## Reliability and verification

The final backend run passed 289 tests on disposable PostgreSQL, with one existing Starlette/AnyIO deprecation warning. The 14 focused primary-account cases include funding/scope isolation, A3/B3/E3 BUY–partial SELL–stop lifecycles, reserved-cash crash recovery, actual worker kill/restart, genuine-manifest rejection of replay input, source/manifest tamper refusal, explicit flat revision and the unconsumed-depth regression. Additional final read-model checks validate execution-profile attribution. The native ARM64 image passed 15 original/frozen/successor account lifecycles and the new primary lifecycle. Ruff and strict Mypy passed (103 Python source files).

Frontend validation passed 14 unit tests, TypeScript/build, 29 mock desktop/mobile browser cases and two real-server read-only navigation cases covering seven areas at 375px/1440px. Actual captures show the primary account separately from the official and old shadows; no UI synthetic orders were injected into the persistent account.

Quiescent, checksummed backups and isolated internal-network, database-enforced read-only restores cover all four financial domains. They verify one funding per account, immutable identity markers, reconciliation and financial seals. The old three accounts' original manifests and core financial ledgers compare unchanged. Source Postgres/Redis volumes, research, historical files and known rollback images are retained. No restoration overwrote the active financial databases. An initial test-container default-database collision was corrected; failed setup diagnostics were preserved before scoped cleanup. Frontend restart after backend maintenance refreshes its Nginx upstream resolution.

The earlier A2/B2 native V4.6 experiment manifests are incompatible with the changed execution source and therefore remain entry-blocked, with their histories intact. This intentionally leaves overall monitoring **Degraded** while the new primary account is healthy. The new release does not silently migrate those experiments. A separately compatible historical runner/image would be needed to continue their original prospective identities.

Financial audit storage is retained and grows over time. Per-cycle requests, discovery work, dashboard rows and Docker logs are bounded; long-term database archival and sustained resource behavior remain unverified. Whole Mac/Docker Desktop reboot, a second physical LAN device and uninterrupted multi-day operation were not tested in this release. Docker Desktop, network access and an awake Mac remain operational dependencies.

## Interface evidence

[Desktop overview](evidence/v4_7/mac-live-overview-1440.png) · [Mobile overview](evidence/v4_7/mac-live-overview-375.png) · [Actual activity](evidence/v4_7/mac-live-activity-1440.png) · [Actual opportunities](evidence/v4_7/mac-live-opportunities-1440.png) · [Actual research](evidence/v4_7/mac-live-research-1440.png). Other areas have desktop/mobile captures in the same folder. Files named `synthetic`, mock acceptance screenshots and deterministic lifecycle JSON are separate engineering evidence.

## Future live readiness and remaining scope

**Not technically ready for a real-money pilot.** The paper gateway provides reusable intention, reservation, fill, journal, reconciliation and protective-management boundaries. Settings independently reject live mode and the provider transport admits only public GET requests. There is no signed order adapter, authenticated account synchronization, real-fee reconciliation, tested exchange acknowledgement recovery or verified exchange-side protection. No trading credentials were requested and no authenticated exchange mutation or transfer occurred.

See [live-readiness assessment](V4_7_LIVE_READINESS.md). A future pilot needs separate explicit real-money authorization, its own budget, broker contract tests, account restrictions/connectivity checks, emergency/recovery proof and adequate independent prospective performance across adverse regimes. Positive paper returns would not enable it automatically.

Passive queue fills, USD conversion accounting, authenticated read-only market transport, autonomous deployment of parameter-search winners and indefinite storage compaction are not implemented. Fixed research scripts and hourly evidence reviews can compare/propose new versions; active strategies remain frozen. The current implementation is an autonomous virtual execution system with honest rejection/evidence collection, not a proven profitable strategy or a completed 30-day test.

## Source and operations

All changes originate in `/Users/mohammadkhataei/Desktop/AutoTrader` on `feature/autotrader-v46-intelligent-opportunity-engine`, starting at `c224bc18c7259335f2dd3e0bb96867832f40c313`. No new branch, force push, Git release tag, VPS file, production restart or real order was created. The existing V4.6 RC2 tag and main are preserved. The immutable source package is prepared by `deploy/release.py`; its V4.7 VPS preflight explicitly refuses deployment. Final Git/packaging identities are reported with delivery.

[Mac operating instructions](V4_7_MAC_OPERATIONS.md) cover the existing `autotrader-v46-mac` project and persistent local ports. The final numerical runtime and verification records below are source-bound engineering evidence; the running worker continues collecting future paper observations after this report.


## Actual prospective paper activity and accounting

Snapshot: **2026-10-26T19:20:05.019029+00:00**. The original account began at 2026-10-26T16:23:33.412387+00:00; the explicitly appended active execution profile `4.7.0-paper.2` began at 2026-10-26T16:41:24.774568+00:00. The roughly three-hour account window is too short to establish performance or sustainable trading frequency.

| Measured item | Actual primary account |
|---|---|
| State / controls | PAPER_EXPERIMENTAL_ACTIVE / RUNNING |
| Initial / current equity | EUR7,000 / EUR7,000 |
| Cash / available cash | EUR7,000 / EUR7,000 |
| Reserved cash / open exposure | EUR0 / EUR0 |
| Genuine prospective BUY orders | 1, REJECTED under original execution profile |
| Genuine prospective SELL orders | 0 |
| BUY fills / SELL fills | 0 / 0 |
| Open / closed positions | 0 / 0 |
| Realized / unrealized / total net P&L | EUR0 / EUR0 / EUR0 |
| Fees / modeled slippage charged | EUR0 / EUR0 |
| Drawdown / utilization | 0 / 0 |
| Funding journal events | 1, exactly EUR7,000 |
| Reconciliation problems | None |
| Runtime source matches active manifest | Yes |
| Worker monitor / scan age | 3.09s / 21.15s |

The one accepted BUY decision became a **rejected broker order**, not a fill. It is retained under the original profile, as described in the depth-risk diagnosis above. The corrected profile has not yet produced a qualifying filled entry. No order was replayed to improve these numbers. Existing risk and economic gates continue to reject unsuitable setups. Simulated acceptance lifecycles prove engineering execution, accounting and exits only; they do not contribute to this table.

The durable decision ledger contains **234 strategy observations** (90 original-profile, 144 corrected-profile), 7 technical candidates and 1 economically qualified candidate, across 11 assets: ADA-EUR, BCH-EUR, BTC-EUR, ENA-EUR, ETH-EUR, INJ-EUR, NEAR-EUR, PEPE-EUR, SOL-EUR, SUI-EUR, XRP-EUR. Counts are overlapping correlated evaluations, not independent trials. Failure predicates include trend/context, confirmed retest, relative demand and cost-adjusted reward/risk; observations are retained for attribution rather than forcing trades.

## Operational verification record

The six persistent `autotrader-v46-mac` services are running on native ARM64, with frontend at [localhost:3000](http://localhost:3000) and backend at [localhost:8000](http://localhost:8000). App/worker/Redis/PostgreSQL health checks pass; the research worker remains running. Restart policies are `unless-stopped`. The worker scans, discovers markets, schedules paper entries when qualified, and manages exits independently; the hourly research reviewer stores immutable proposals without mutating active strategy parameters. Mac sleep or Docker Desktop shutdown suspends operation.

Final small-sample API medians were 12.88ms for primary detail, 6.14ms for overview and 4.86ms for twelve opportunities (three requests per endpoint, not a load test). Source PostgreSQL and Redis restarts, application restarts, account funding uniqueness, financial seals and isolated read-only restore passed for all four accounts. Only disposable test containers/network and the temporary browser-test server were removed; persistent services, volumes, backups and rollback images remain.

The running Python source fingerprint is `4378414d10e72964a915ed8d428937e6f195ea3572e2d4ac7f467e5ba7974c13` and primary execution fingerprint is `fd20b6e6e61e5c775ff8bd62b3fc87095fa55c6ea7e0d290fb6209eb6a9c1e77`. [Verification record](evidence/v4_7/verification.json), [operational snapshot](evidence/v4_7/operational-summary.json), [durable decision summary](evidence/v4_7/forward-database-summary.json) and [financial restore/restart record](evidence/v4_7/financial-final.json) retain exact evidence. The working-tree source and running image match. The final delivery receipt provides the full pushed commit and immutable package checksum; no release tag or VPS activation is part of this release.
