# V4.9.7 micro-move source changes — UNTESTED / UNVALIDATED

This is a code-only development change on `feature/autotrader-v46-intelligent-opportunity-engine`, based on application commit `a5720dca2592929c69d99442e8a89450fbb0c06b` plus existing committed operator work at `0ab61c7`. It creates no release/tag and has not been pushed. No strategy has been activated.

## Scope and source reviewed

Reviewed the perpetuals engine, market adapter, service, models, worker, authenticated routes, dashboard, V4.9.6 design notes, and the separate perpetuals migration. Also inspected `learning/features.py`, `learning/targets.py`, `learning/model.py`, `learning/evaluation.py`, API registration/lifespan, frontend resource handling, and current repository status. The post-a572 deployment operator and its documentation are preserved.

One read-only SSH status request was issued at the start of this task while the attachment was being opened, before its no-SSH restriction was read. It showed V4.9.6 running and made no changes. No further SSH, Docker, deployment, migration, worker-control or account-control operation was issued for this task. The scope restriction is fully observed for the implementation work below.

## Confirmed weaknesses

- The baseline's 1% minimum stop and twice-stop target are not micro-move geometry. The 15-minute breakout waits for a completed multi-hour reference range and can miss short-lived continuation.
- The queue records a decision before a later minute, but fills retrospectively at that completed minute's opening price. Checking the candle is recent does not establish that an order could reach that opening price. OHLC-only stops/targets also lack intraminute path and depth. These baseline records remain historical hypothetical paper proxies.
- Fixed fees and slippage imply roughly 0.22% round-trip cost before funding and any extra observed spread/depth. A 0.2% underlying target can therefore have negative net proceeds even if direction is correct.
- Previous dashboard values did not distinguish underlying change, gross/net unrealized P&L, margin return and account return. Cohorts with the same notional can have similar account P&L despite different collateral.
- There is no qualified BTC micro-barrier/holding-period model. The existing spot learner uses different symbols, horizons, cost assumptions, features and labels. Its probabilities cannot be imported as perpetuals profitability probabilities.

## New isolated strategy family

`micro/types.py` defines immutable typed contracts, three new policy identifiers and separate feature, outcome and execution schemas. Internal money and returns use `Decimal`; percentage fields are explicitly multiplied by 100 at projection boundaries. No serialized V4.9.6 state field is renamed, replaced or migrated.

| Policy | Completed-data hypothesis | Main abstention checks |
| --- | --- | --- |
| `BTC_MICRO_CONTINUATION_V1` | 1-minute acceleration, 3/5-minute confirmation, persistent efficient trend, controlled pullback and recovery | Extended entry, poor body/close, disordered regime, missing or insufficient relative volume, uncontrolled expansion |
| `BTC_MICRO_RETEST_V1` | Earlier completed range breakout, subsequent completed retest, then reclaim/confirmation | Touch without reclaim, failed/misaligned trend, extension, unconfirmed volume |
| `BTC_MICRO_RANGE_V1` | Repeatedly observed extremes in a low-efficiency range; wick/reversal confirmation toward midpoint | Trend/disorder, insufficient touches, location outside the edge band, expanding volatility |

Features use exactly 90 consecutive completed one-minute candles. Three- and five-minute candles align to UTC interval boundaries; partial resampling groups are excluded. The window is hashed at decision time. True range, directional efficiency, persistence, recent candle geometry, expansion and optional relative volume are deterministic descriptions, not probability or confidence estimates. Missing volume stays unknown. Aggressor buy/sell pressure stays unknown because a candle or a depth snapshot is not signed executed trade flow.

Candidate target distance comes from structural room and volatility. The 0.2%–1% range is a research-scope filter, not a universal profit target. Stops use volatility and structure, with an additional spread/noise floor in the scorer. The current constants and 10/12/15-minute time limits are unvalidated hypotheses.

## Economic opportunity scoring

`micro/scoring.py` sizes each hypothetical cohort with the existing 0.5% risk fraction, 25% collateral cap, twice-equity/2,000 USDT notional caps, one-position gate and 10% peak drawdown halt. It rounds to venue quantity steps and checks minimum size/notional. If exact depth-priced stop risk exceeds budget, size is reduced and the depth estimate recalculated. Higher leverage does not increase the risk budget.

The calculation includes entry and exit fees, observed spread/depth, a residual slippage floor each way, and an explicit ATR-per-minute latency stress. Spread is already inside VWAP versus mid and is not added twice. Exit depth is a current snapshot assumption, not future liquidity. The zero-net price equation is solved separately through signed long/short arithmetic, including the different fee denominators. Structural target and stop prices remain tied to the decision reference, so a move consumed before the quote is rejected rather than silently moving the target farther away.

If a funding event could occur within the planned horizon, funding cost is unknown and the candidate abstains. An indicative ticker funding rate is displayed as such and is never treated as the future settled rate or a guaranteed credit. Gap overruns and actual future liquidity remain additional risks even when no scheduled event falls inside the time budget.

The response separates **target scenarios** from **expected outcomes**. `expected_underlying_move_pct`, `expected_net_move_pct`, expected P&L, expected holding time, expected margin/account ROI and probability remain `null` without qualified evidence. A transparent two-barrier break-even probability is an illustrative threshold only; it does not establish a win probability and omits time outcomes. `estimated_win_probability`, when qualified in a future adapter, means probability of target first, not next-candle direction and not the probability that every time exit is profitable.

`OutcomeEvidence` requires policy/regime/cost/schema identity, the current feature hash, independent labels, chronological training/calibration/evaluation before the decision, timely prediction and expiry, reviewed status, and a complete target/stop/time competing-outcome distribution. Expected net P&L is the probability-weighted net target, stop and time-exit scenarios. Nonpositive expected value rejects the candidate without a universal win-probability cutoff. There is no loader, trained artifact, training call or automatic promotion here; the serving path supplies no evidence and remains `UNQUALIFIED`.

## Execution timing and data efficiency

The optional preview fetches completed candles, metadata and a read-only account snapshot first, fixes decision availability, then requests the book and ticker. `micro/execution.py` rejects predecision/future/stale/crossed/unsorted/empty depth, inadequate capacity and expired intent. It walks both sides for the whole proposed quantity, uses VWAP, and applies one adverse residual slippage assumption per side. An estimate must come from matching-engine time at or after the decision and expire within three seconds; book age must be within 1.5 seconds. Clock skew may therefore cause conservative abstentions.

The [Bybit order-book API](https://bybit-exchange.github.io/docs/v5/market/orderbook) supplies `cts` matching-engine time and visible bid/ask levels; hidden/RPI liquidity is not included. The [ticker API](https://bybit-exchange.github.io/docs/v5/market/tickers) supplies mark, indicative funding and next funding time. No live API call was made to exercise this adapter. Responses are read-only estimates and explicitly **not fills**. No candle's future high/low chooses an earlier entry, no limit touch creates an execution, and missed/expired proposals have no catch-up fill path.

`micro/research.py` has a one-request lock, one completed 90-minute window cache, a 60-second instrument cache and a one-second annotated response cache, with a bounded request timeout and at most 50 visible levels per side. A failure clears cached research data and returns unavailable. It never shares requests, budgets, sessions, scheduling or caches with the protective worker. No background tasks or services were added.

The new `PERPETUALS_MICRO_RESEARCH_ENABLED` flag defaults false and gates only the authenticated read-only preview. It additionally requires existing local/staging paper mode. Setting that flag in a separately authorized future configuration would not activate a strategy. There is no new activation endpoint, account funding path, worker integration or micro order dispatch.

## Separate exit proposals and risk

`micro/exits.py` accepts only a new micro `ResearchPosition` contract. It has no call from the baseline worker and cannot reinterpret an old position. Initial and current stops must be consistent; the target must exceed the supplied economic break-even distance. Liquidation risk is checked independently first. An optional closed mark candle must be wholly after entry; partial entry candles cannot provide adverse-path proof.

After liquidation risk, near-liquidation buffer, stale-data, depth-impact and imminent unknown funding conditions can propose an emergency exit. Remaining proposals prioritize stale-data/priceability risk, stop, spread/mark deviation, a marketable cost-covered target, time limit, failed structure and momentum deterioration. A bar with ambiguous path cannot establish a favorable target fill. Two completed post-entry candles are required for structure/momentum deterioration. Trailing protection is proposed only after costs and a volatility/spread buffer are cleared, tightens monotonically, and applies to later observations. No stops are widened, partial fills invented or losses averaged down. A proposal still requires a new post-intent depth observation; no settlement is posted.

Planned stop loss is not a guaranteed maximum. The scorer also exposes isolated margin plus entry fee at risk, liquidation distance and the stop-to-liquidation cushion. Market gaps, missing observations and basis dislocation may cause losses substantially beyond planned stop risk. Liquidation is labeled a distinct emergency risk event.

## ROI and dashboard

The additive `projections.py` reads existing position and account values without changing them:

- Raw underlying change is `mark / entry − 1`; direction-adjusted change multiplies by side.
- Gross position P&L is `side × quantity × (mark − entry)`.
- Estimated net unrealized P&L adds accrued funding and deducts paid entry fees, modeled closing slippage and estimated closing fees. The unchanged account-equity mark projection reserves closing fees but not this extra slippage, so the two valuation conventions are explicitly identified. It is explicitly before a possible legacy isolated settlement adjustment.
- Margin ROI divides position P&L by the position's original isolated margin.
- Position contribution to account return divides position net P&L by cash + locked margin + paid entry fee, reconstructing account equity just before entry.
- Cumulative account ROI divides total marked account net P&L by its original 1,000 USDT, never by margin.
- Margin utilization uses current total account equity. Liquidation distance uses signed current mark distance.

The dashboard now identifies the baseline policy/timeframe, unvalidated qualification, actual queued direction, unknown regime where absent, modeled break-even movement and costs. It displays gross/net position P&L, margin utilization, margin ROI, total-account ROI, target scenario and liquidation distance. The research panel shows its disabled/unqualified state, candidate directions, regimes, cost floors, sizes, stops/targets, scenario and expected values, probability source and rejection reasons. Expired quotes are labeled historical estimates. Decimal strings are formatted only at the UI edge; unknown values remain unknown. There is no micro activation button.

## State compatibility and future requirements

`engine.py`, `models.py`, `worker.py` and all migration files are unchanged. `BTC_15M_BREAKOUT_ISOLATED_V1`, its three cohorts, balance/event tables, state encoding, pending orders, generation-based atomicity and existing stop/target/holding contracts remain unchanged. Existing audit events are returned without alteration. `Bar` gains only optional volume, defaulting to unknown, for source-compatible construction. Volume parsing is opt-in on research requests; baseline market-data callers retain their previous default behavior. The service/API gain additive read-only fields and one optional endpoint.

The preview deliberately makes no persistent research experiments or fill engine. A future activation needs separate experiment identity/storage and reviewed persistence changes: immutable policy and cost contract, append-only decision/quote/outcome records, a durably committed intent before requesting executable evidence, unique intent/fill keys, account ownership/row locking, atomic balance/event/cursor commits, one open/pending position per cohort, total exposure reconciliation and restart expiry. None of those requirements are silently satisfied by an in-memory quote. No database change is needed for this read-only addition and no migration was run.

Future learning needs prospectively timestamped books, decisions, actual availability and missed-fill records, funding, mark/trade paths, competing stop/target/time labels, execution ambiguity and observed adverse excursion. Labels must follow decisions and be complete after their horizon; unresolved and ambiguous cases cannot be selected as wins. Reuse the existing immutable feature hashing, independent episode grouping, chronological calibration, purge/embargo and untouched holdout approach, with separate BTC micro schemas and challenger artifacts. Correlated cohorts must not be counted as three independent outcomes. Current spot labels/weights cannot qualify these hypotheses. No data was collected and no model was fitted.

All new thresholds, latency/funding/exit-liquidity assumptions, ROI projections, API paths, TypeScript and Python changes remain unexecuted and unverified. No profitability or performance advantage is claimed.

**Code improvements completed. Tests, backtests, model training, builds and deployment were intentionally not performed. New strategy performance is unvalidated, and the running Aruba installation remains unchanged.**


## Exact working-tree changes and Git state

The repository remains on `feature/autotrader-v46-intelligent-opportunity-engine`, HEAD `0ab61c7` (pre-existing committed deployment operator). No commit, push, tag or CI/CD action was performed for V4.9.7. The source changes are intentionally uncommitted: six tracked files modified and ten new files.

Modified:

- `.env.example`
- `frontend/src/Perpetuals.tsx`
- `frontend/src/styles.css`
- `src/autotrader/api/perpetuals.py`
- `src/autotrader/perpetuals/market.py`
- `src/autotrader/perpetuals/service.py`

New:

- `docs/V4_9_7_MICRO_MOVE_REVIEW.md`
- `src/autotrader/perpetuals/projections.py`
- `src/autotrader/perpetuals/micro/__init__.py`
- `src/autotrader/perpetuals/micro/types.py`
- `src/autotrader/perpetuals/micro/signals.py`
- `src/autotrader/perpetuals/micro/execution.py`
- `src/autotrader/perpetuals/micro/market.py`
- `src/autotrader/perpetuals/micro/scoring.py`
- `src/autotrader/perpetuals/micro/exits.py`
- `src/autotrader/perpetuals/micro/research.py`

All other source, previous operator work, existing records, release artifacts, package versions and migration files are preserved. Review consisted of reading source/diffs and Git status only; no code from these components was imported or executed.
