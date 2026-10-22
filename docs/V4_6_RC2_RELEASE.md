# Personal Plan V4.6 RC2 — Stage A engineering report

Engineering acceptance and historical strategy validation are separate. This release makes no production changes, creates no production accounts and grants no new capital or approval. Deployment recommendation: **BLOCKED**. The October 22 read-only inventory failed SSH authentication; current production state and fresh backups are unverified. Separate approval of the exact packaged commit is also required.

## A. Problems discovered

Confirmed bugs: a five-minute observer was labeled stale after 90 seconds; provider failures could resemble ordinary zero opportunity counts; generic trade/trades replacement changed financial meaning; the gateway's hypothetical target/break-even calculation omitted observed exit depth impact; research sizing and actual account sizing were not aligned. During cost sensitivity verification, an ask-based anti-chase check also classified wider spreads as technical price extension. Midpoint movement now defines extension while executable bid/ask prices remain in cost checks.

Observed strategy limitations: cost-feasible entries were rare, structural stops could expose weak net reward/risk, retest-only confirmation missed held breakouts, and independent asset/benchmark variances ignored residual co-movement. These are hypotheses to test, not established explanations for every loss. Missing contiguous candles, weak demand and adverse higher-timeframe conditions also legitimately block entries. The first blocking stage is counted separately from overlapping failed conditions.

The last retained production observation is October 19: 29 accepted A2 BUY decisions had 29 durable rejected orders, zero fills, each with `execution_quality:first_target_destroyed_by_execution_costs`. That attribution belongs to those recorded orders only. An accepted decision without a recorded order is explicitly distinct. No fresh October 22 production result is claimed.

## B. Changes implemented

- `opportunity/status.py`, observer service and `/api/opportunities`: scheduled research freshness, quote freshness and worker/scanner health are independent, including restart recovery, waiting, partial failures and unknown counts. Successful buckets deduplicate; failed buckets may retry.
- `opportunity/engine.py`, features and patterns: experimental version `.2`; A3 earlier controlled EMA reclaim, B3 retest or completed hold, E3 synchronized residual volatility plus positive local persistence. RC1 implementations remain separately replayable in `rc1.py` and `rc1_economics.py`.
- `opportunity/sizing.py`, economics, runtime and decision flow: account-constrained proposals, realistic stop risk, partial-exit minimums and precision, executable depth and fresh downstream admission. Frozen V4.2/V4.4 source is unchanged.
- API diagnostics correlate actual order and fill records. Observer ranking scores cannot produce PAPER_ELIGIBLE or EXECUTED_IN_SIMULATION. Full research evidence loads only on request.
- Frontend routes and charts load lazily. Financial labels are deliberate; identifiers and raw technical evidence are preserved.

## C. Buy-gate analysis

Matched reused test: October 4 06:00 through October 16 00:00 UTC, same eight EUR assets, causal completed candles, costs and RC1 selected parameters. Counts are evaluation events, not independent opportunities. Open positions suppress some evaluations, so the RC1 B3 denominator differs by one. Economics includes explicit unvalidated-edge evidence; it does not establish research approval.

| Strategy / revision | Evaluations | Technical | Economic | Simulated entry fills | All execution fills | Closed positions | Net P&L EUR |
|---|---:|---:|---:|---:|---:|---:|---:|
| A3 RC1 | 12016 | 407 | 2 | 1 | 2 | 1 | -0.484101 |
| A3 RC2 | 12016 | 406 | 1 | 1 | 2 | 1 | -0.014440 |
| B3 RC1 | 12015 | 49 | 2 | 2 | 5 | 2 | -0.945246 |
| B3 RC2 | 12016 | 62 | 0 | 0 | 0 | 0 | 0.000000 |
| E3 RC1 | 12016 | 14 | 0 | 0 | 0 | 0 | 0.000000 |
| E3 RC2 | 12016 | 35 | 1 | 1 | 2 | 1 | 0.054980 |

| RC2 first stage | A3 | B3 | E3 |
|---|---:|---:|---:|
| DATA_VALIDATION | 2227 | 2227 | 2227 |
| TECHNICAL_SETUP | 9383 | 9727 | 9754 |
| COST_FEASIBILITY | 405 | 62 | 34 |
| ECONOMICALLY_FEASIBLE_EDGE_UNVALIDATED | 1 | 0 | 1 |

Research-qualified strategies: **0**; new approved runtime paper orders: **0**. The historical simulator has synthetic execution events rather than durable PostgreSQL paper orders, so its fill counts must not be described as account-ledger fills. Exact order/rejection history remains available separately. No new prospective account was launched. Overlapping condition failures, symbol/regime contributions, exposure and cost details are in [full evidence](evidence/v4_6_rc2/research-comparison.json).

## D. Opportunity-engine improvements

Discovery ranks capped movement relative to costs, spread quality and liquidity; extreme illiquid percentage moves cannot dominate. A configurable maximum of 0–20 extra markets operates inside request/time budgets, caches and a shared provider scheduler. Latency/429 feedback reduces detail work; recently failed markets cool down. Protective monitoring and the official path precede experimental discovery.

Structural invalidation determines stops; a stop is never pulled closer simply to pass reward/risk. Targets use observed higher-timeframe volatility or price structure. Proposed sizes start from an explicit research assumption (default EUR75), or real account cash/exposure/allocation/position/stop-risk caps. They can rise only enough to meet executable partial minimums within every hard cap, or fall to fit modeled stop loss. Fees, slippage, spread through bid/ask, depth impact, base precision and partial minimums are included. No spread is counted twice. Future target proceeds assume the current observed exit impact fraction; future liquidity is unknown. The gateway independently checks current risk and executable data.

A3 investigates early reclaim; B3 supports two completed holds as an alternative to a retest, with expiry/invalidation retained; E3 requires residual strength and local persistence, rather than merely outperforming a benchmark. These are research candidates, not validated profit models. Expected value and calibrated win probability remain unknown. Conditional bid/pullback/retest entries use expiring IOC watches and subsequent observed opens; no passive queue or touched-price fill guarantee is assumed.

## E. Strategy research results

Seventeen preregistered training configurations (six A3, five B3, six E3) used a chronological 60/20/20 split with a 72-bar purge/embargo. The original selected RC1 results were reproduced exactly for P&L and closed-position counts. Parameters were locked before acquiring the added October 16–22 interval, with October 13–16 warmup. The spread/extension correction was then evaluated without retuning; **all final evaluation intervals are now reused**, including the added interval. Both the [initial](evidence/v4_6_rc2/research-initial.json) and corrected reports are retained with source/data hashes. The corrected financial math matches final source; only API summary serialization differs from its executed snapshot.

| Strategy | Validation P&L / closed | Reused test P&L / closed | Added interval P&L / closed | Added RC1 P&L / closed |
|---|---:|---:|---:|---:|
| A3 | EUR-3.176457 / 5 | EUR-0.014440 / 1 | EUR-0.548950 / 1 | EUR-1.194992 / 2 |
| B3 | EUR-1.799292 / 3 | EUR0.000000 / 0 | EUR0.000000 / 0 | EUR0.000000 / 0 |
| E3 | EUR-0.017379 / 1 | EUR0.054980 / 1 | EUR-1.412440 / 2 | EUR0.000000 / 0 |

All strategies fail validation. Increased cost assumptions (15bp each fee, 12bp slippage, 15bp spread, lower assumed liquidity) produce zero feasible entries for all three. Technical counts remain unchanged under spread-only technical classification. Expiring alternative entries generated no fills in this matched test; a zero result from nonfills is not improved execution performance. EUR25/75/100 sensitivities and three-market comparisons are retained, without choosing settings from test results. Runtime defaults are explicit; train-selected configurations are research evidence and are not silently promoted into accounts.

E3's single reused-test winner earned about EUR0.055 after EUR0.150 fees; its added interval lost EUR1.412 across two closed positions. A3's reused-test loss was smaller than RC1, but one position supports no robust improvement claim. All validation intervals lost money. Win rates, profit factors and low drawdowns with near-zero exposure do not establish an edge.

There is no historical connected-provider depth: Coinbase EUR candles are a proxy, with fixed cost/depth assumptions and current-survivor asset selection. Added six-day candle counts range from 849/1728 for AVAX to 1728/1728 for BTC; gaps are rejected, not interpolated into fictitious opportunities. Cross-asset/serial dependence, repeated research and the short interval prevent an independent holdout or prospective claim. [Coverage](evidence/v4_6_rc2/additional-history-coverage.json) and [metric summary](evidence/v4_6_rc2/research-metrics-summary.json) include exact values.

## F. Personal Plan UI

Seven navigation destinations: Overview, Opportunities, Strategies, Activity, Research, Decision Insights and Settings. Generic trade-word replacement and recursive text rewriting are removed. Orders, execution fills, positions and decisions retain distinct labels. Ordinary screens use Personal Plan and connected market provider; technical JSON is explicitly raw evidence and retains identifiers for auditability.

Opportunities show research schedule, stale quotes, worker/scanner health, qualification, observed entry/stop/targets, size scope, costs, net reward/risk and uncertainty separately. Modeled full-size target scenarios are labeled distinctly from actual partial exits. Decision Insights uses recorded downstream order/fill evidence. Desktop/mobile, keyboard, error and missing-data states passed browser checks. Screenshots are synthetic acceptance fixtures, not production observations:

[Desktop](evidence/v4_6_rc2/rc2-opportunity-1440.png) · [Mobile](evidence/v4_6_rc2/rc2-opportunity-375.png).

## G. Measured performance

Frontend main JavaScript: **622.01 → 176.28 kB** (uncompressed, −71.66%); largest deferred chart chunk 372.04 kB. The >500 kB build advisory is gone. Final research JSON serialization: **581,304 → 17,365 bytes (−97.01%)**; full details remain available on demand. This measures payload size, not network latency.

One actual public observation expanded detailed valid markets from 3 to 9 using 13 additional successful requests, zero observed 429/failures and 7.328 seconds of extra observer work. Shared baseline preparation took 3.681 seconds; the base-only observer reused those observations in 0.010 seconds. Neither sustained 429 improvement nor false-positive quality is established. All nine markets had zero qualifying setups in that observation. The 65-second controlled UI poll comparison recorded 10 baseline requests versus 11 current requests including Opportunities, with broad-history polling removed; it does not show a reduction in total request count. No unmeasured speedup is claimed.

## H. Validation

Final source-bound counts, hashes, images and checks: [tests](evidence/v4_6_rc2/tests.json), [runtime compatibility](evidence/v4_6_rc2/runtime-compatibility.json), [AMD64 containers](evidence/v4_6_rc2/container-tests.json), [dated financial restore](evidence/v4_6_rc2/financial-restore.json), [readiness](evidence/v4_6_rc2/deployment-readiness.json).

All 271 backend tests passed with real PostgreSQL, alongside Ruff, Mypy (95 files), 13 frontend unit tests, TypeScript/build, 30 browser checks and three additional compiled lifecycle checks. The only backend warning is a Starlette/AnyIO deprecation. Both final AMD64 images built successfully. AMD64 candidate acceptance passed all 15 synthetic account lifecycles. The first AMD64 run correctly kept A3 open because its fixture price (127) exceeded the recorded structural stop (126.561); the fixture was corrected to cross each actual stop without changing application protection or assertions. Independent compiled React/API/worker tests cover partial exits, process kill/restart and official isolation. The dated October 19 set is restored in an internal-only network, all nine databases reconciled under candidate and known-good rollback images, and the actual all-database backup discovery/parse/restore path exercised. No workers, new funding or migrations run on production-derived clones. Original 71 V4.2 and 76 V4.4 Python files and all eight retained experiment identities/manifests remain unchanged.

The production preflight intentionally remains **BLOCKED**. Passing local engineering acceptance on dated archives cannot certify fresh production state. No production container was built/restarted and no remote file, configuration or database changed.

## I. Remaining limitations

No strategy has validated positive expected value, calibrated probabilities, sufficient independent closed positions or completed prospective observation. Newer data is short, incomplete and reused after correction. Historical liquidity, passive queue fills and target-hit probabilities remain unknown. Discovery has one measured observation. Current production access, inventory, backups and protection state require fresh checks; dated local restore proves compatibility only. No profitability or completed 30-day claim follows from engineering tests.

## J. Release information

Branch: `feature/autotrader-v46-intelligent-opportunity-engine`. Tag: `v4.6.0-rc.2`, created only after local engineering gates pass. Main and RC1 remain untouched. Exact full commit, archive path and SHA-256 are reported in the final delivery record beside `.tools/releases/v4.6.0-rc.2/`; an immutable source document cannot contain its own Git commit or archive hash. Packaging verifies the committed manifest against every released file.

Deployment status: **BLOCKED**, due to unavailable fresh production verification and separate exact-commit approval. The immutable production preflight rejects this candidate as required; approval alone cannot bypass it. Missing verification must produce newly committed readiness evidence in a separately identified release, without overwriting RC2. The [deployment and rollback procedure](V4_6_RC2_DEPLOYMENT.md) is prepared only. No deployment was executed. Real-money execution remains disabled.
