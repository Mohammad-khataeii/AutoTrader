# V4.9.2 rc.2 — loss investigation and controlled learning

This release adds a continuously collected, trained and evaluated **research** system. It does not assert a profitable strategy, promote ML into the primary account, widen stops, or erase losses. The primary prospective profile changes to `4.9.2-paper.1` because its observation/provenance code and frozen manifest change. The existing V4.9.1 admission rules, sizing, hard risk limits and exit policies retain their identities and behavior. The seven original forward controls and eight retained archived ledgers keep their original manifests and execution fingerprint.

## Latest PEPE loss: findings from original PostgreSQL records

The primary ledger confirms entry at **29 October 2026 16:55:33.186711 UTC (17:55:33 CET)** and close at **18:24:47.801627 UTC (19:24:47 CET)**. The entry identity is `RAOE_TREND_PULLBACK`, execution profile `4.9.1-paper.1`, base strategy `4.9.0-raoe.1`. Original order records do not embed a Git SHA, so the contemporaneous backend commit cannot be established from those orders alone. New prospective orders record installed build version and the full immutable build commit when supplied to the image build.

| Recorded quantity or result | Value |
|---|---:|
| Quantity | 144,302,100 PEPE |
| Actual simulated buy VWAP | €0.000004823755 |
| Actual simulated sell VWAP | €0.000004706202 |
| Original and final protective stop | €0.0000047128 |
| First / second / third structural bid targets | €0.0000050192 / €0.0000050473 / €0.0000050714 |
| Gross price P&L, already including modeled impact/slippage | −€16.963144761300 |
| Buy and sell fees | €1.375192808009 |
| Net linked journal and position P&L | **−€18.338337569309** |
| Locked dispatch planned stop loss | €18.106310211985 |

The original entry book at 16:55:33.010 UTC had bid **0.0000048131**, ask **0.0000048199**, approximately **14.12 bps spread**. The actual entry used the first ask level and the recorded 8 bps slippage assumption. Its recorded scan-time book was older and slightly more expensive; locked admission and dispatch used the newer book and recomputed economics. Entry and exit replay through the actual pricing module reproduces both VWAPs, both fees and the exact net loss. Slippage and impact must not be subtracted a second time.

The saved exit book at 18:24:46.439 UTC had top bid **0.0000047111**, below the unchanged stop. Exit filled across the first two bid levels with modeled slippage at **0.000004706202**. The realized loss exceeded the locked planned stop estimate by approximately €0.2320, consistent with the observed bid falling below the trigger and finite-depth execution. A stop price is a trigger, not a guaranteed fill. The stop intent and recorded entry plan agree; no missing cash, duplicate fee or bypassed protective stop was demonstrated.

### Information actually available at entry

The recorded signal used the 16:50 five-minute candle, completed at 16:55. Its 1,152 completed PEPE candles reconstruct the **exact original time/close/high/low data hash**. Independent immutable closed-bar first-observation records recover 1,152 candles each for PEPE, BTC and ETH. All 3,456 were first recorded before the order. Rebuilding the primary context from these versions reproduces its saved inputs and every gate exactly. This is stronger evidence than merely downloading later historical candles. The original hash did not bind open/volume; recovered first-observation versions provide those fields separately.

All six recorded RAOE quality gates passed: causal data, setup, structural plan, net economics, noise floor and known benchmark context. All five primary gates passed: ready context, current completed candle, macro context, local reclaim and the strategy-specific recovery condition. The complete inputs, gates, plans, books, projected execution and fills are in `docs/evidence/v4_9_2/forensics.json`; the causal bar versions and reconstruction result are in `entry-candles.jsonl.gz` and `entry-context.json`.

At entry, PEPE had bullish completed 5m/15m/1h/4h EMA contexts. Its completed close **0.0000048216** exceeded rising EMA9 **0.0000048029195351**. The last completed fifteen-minute close **0.0000047510** was below its previous **0.0000048026**, despite the higher trend classification. The pattern was a confirmed pullback/recovery beneath the meaningful prior high **0.0000050795**, with anchor **0.0000047329**. Extension was approximately **0.233 ATR**, and the actual fill-to-stop distance approximately **1.382 entry ATR**. The original evidence does not describe an exhausted-move entry or a stop arbitrarily inside a sub-ATR fluctuation.

Both recorded hourly benchmark trends were bullish. Their most recent 30-minute returns were already negative: BTC **−0.14847%**, ETH **−0.04171%**. Both five-minute classifications were ranging, and PEPE's relative 30-minute return was approximately **−0.56831 percentage points** against their mean. Thus a bullish higher trend coexisted with weakening short-term participation. The guard's macro rule deliberately rejects *joint bearish hourly* context; it is not a rule requiring positive benchmark returns at every horizon. Calling this trade a violation of that rule would be incorrect.

By the last completed retained benchmark bars before exit, BTC had fallen from **72,754.90** to **72,322.36**, and ETH from **2,108.95** to **2,093.31**. These later benchmark reconstructions are labeled separately from the authoritative saved entry proof. The held position reached a recorded highest bid of **0.0000049264**, below its first target; no target fill was due before the reversal.

### After exit and causally available alternatives

The last completed PEPE mid closes available before the requested post-exit checkpoints were approximately:

| Checkpoint | Completed mid close | Change from actual sell VWAP |
|---|---:|---:|
| 15 minutes | 0.0000047210 | +0.3144% |
| 30 minutes | 0.0000047125 | +0.1338% |
| 60 minutes | 0.0000047329 | +0.5673% |
| 120 minutes | 0.0000046509 | −1.1751% |
| 240 minutes | Missing at collection | Unavailable |

The short rebounds remained below entry and do not prove that holding would have produced a net gain. The 120-minute decline argues against presenting the stop as an obvious avoidable mistake. The 240-minute outcome was not yet recorded and is not fabricated. Mid closes are not executable bid depth.

A causal no-trade decision was possible, as always. Negative relative strength and the falling last fifteen-minute close were observable reasons to research more patient entries. Adding a new veto after seeing this loss would not establish a better policy: it changes the set of later opportunities, available capital and position paths. No executable alternative, avoided-loss P&L or superior wider stop is proven. This is a valid adverse path under an unvalidated pullback hypothesis, with execution costs and short-term market weakness; no implementation defect explaining the loss was demonstrated.

## Complete primary account history

All nine original closed positions reconcile independently to their linked journal cash flows. The account retains exactly one original €7,000 funding event. Total net closed P&L is **−€56.724117969028**, with **€12.506612619540** fees, one winner and eight losers. Gross price P&L is −€44.217505349488. Fees matter, but removing them would not turn the combined result positive.

| Asset / entry strategy | Entry UTC | Profile | Net P&L EUR |
|---|---|---|---:|
| PEPE / A3 continuation | 27 Oct 18:40 | 4.7.1-paper.1 | +9.716354556351 |
| ENA / A3 continuation | 27 Oct 20:01 | 4.7.1-paper.1 | −6.184163997126 |
| PEPE / early recovery | 28 Oct 15:06 | 4.9.0-paper.1 | −8.924553754647 |
| ENA / early recovery | 28 Oct 15:08 | 4.9.0-paper.1 | −0.520695884629 |
| PEPE / trend pullback | 28 Oct 22:16 | 4.9.0-paper.1 | −10.716678609739 |
| NEAR / A3 continuation | 28 Oct 22:30 | 4.9.0-paper.1 | −11.334809352064 |
| ZRO / early recovery | 29 Oct 02:56 | 4.9.0-paper.1 | −9.364998139337 |
| ADA / early recovery | 29 Oct 04:41 | 4.9.0-paper.1 | −1.056235218528 |
| PEPE / trend pullback | 29 Oct 16:55 | 4.9.1-paper.1 | −18.338337569309 |

Profile totals are **+€3.532190559225** for V4.7.1 (two trades), **−€41.917970958944** for V4.9.0 (six), and **−€18.338337569309** for V4.9.1 (one). Old losses are not assigned to the newest strategy. The previous V4.9.1 audit documents the older stale-admission clock defect and weak higher-context recovery entries; those corrections already existed at the latest entry and are not claimed as new V4.9.2 fixes.

PEPE supplies repeated exposure across both winning continuation and losing recovery/pullback hypotheses. Several other losses occur in the same broad crypto decline. Trades and rejections overlap and are correlated longs; nine closes cannot establish robust per-asset, regime or time-of-day effects. The new dataset stores these dimensions for conditional analysis rather than assigning confident causal importance to a handful of cases.

### Existing shadow accounts

All fifteen original ledgers remain present, each with one original funding event. Seven were running at the focused export; eight were stopped historical controls. Full-history realized totals of the running A3, early-recovery and pullback ledgers were respectively **−€4.213474384304** (10 closes), **−€4.769035552165** (5) and **−€3.038015568467** (2). The other four had no closes. They were flat at their individual focused-export snapshots. These independent €500 ledgers use different sizes and admission rules; their absolute P&L is not a controlled comparison with the €7,000 primary account.

## Implemented learning system

`autotrader.learning` implements a deterministic L2 logistic classifier and chronological Platt calibration using ordinary Python. It requires no large neural network, external AI call, new financial database schema or mutable source generation. Inference estimates probability of a **defined net outcome** and a conditional expected return using training-class return means. It supplies ranking and bounded size-multiplier **research**, without broker authority.

Features use immutable decision snapshots: completed momentum, volatility, spread, recorded depth, volume ratio, local and higher trends, BTC/ETH returns and relative strength, strategy/profile identity, stop/target geometry, execution costs and time of day. Missing snapshots and invalid plans are explicit exclusions. New primary observations bind the full completed OHLCV snapshot, retain volume provenance and record installed build identity. Old absent features are not reconstructed with future knowledge.

Labels use 60- and 240-minute contiguous genuine recorded paths, a declared entry spread/depth-impact assumption, fees and slippage, partial structural targets, conservative stop-first ambiguity and adverse opening gaps. Two-times cost stress is stored separately, doubling the extra entry fee/slippage once without charging the already costed entry VWAP twice. Partial entry/end candles are excluded. There is no claim of historical future L2, executable counterfactual fills or exact reproduction of the production's discretionary/trailing exit policy. Actual managed-position outcomes form a separate learning task, normalized by recorded entry costs and planned stop risk, and never silently mixed with fixed-horizon proxy labels.

The research worker automatically imports source rows in keyset batches, matures labels and retains actual closed outcomes. Read-only PostgreSQL connections enforce `default_transaction_read_only=on`; attempts to mutate a financial table are tested to fail. Cursor and imported rows commit atomically. SQLite research state and content-addressed JSON artifacts survive restarts. Incomplete future windows retry on a bounded schedule without starving newer observations, then remain explicit failures. No financial table, ledger balance or old exit plan is rewritten.

Training is evidence-driven and runs in the separate research process/thread. Indexed seeks select independent episodes across retained history before applying the 50,000-episode capacity limit, so dense early raw signals cannot hide later months. A regression fixture with 50,001 overlapping observations plus 600 later episodes proves automatic qualification remains reachable; it is synthetic mechanics, not market performance. Conditional path summaries use the latest 50,000 labels and rejection/coverage counts the latest 10,000 per state; complete raw research history remains retained and the UI exposes this summary limit. It requires at least **240 nonoverlapping global crypto episodes spanning 45 days**. At least 48 new independent episodes and six hours are needed before another completed-model training attempt. Simultaneous/overlapping assets share conservative four-hour episodes. Normalization fits training only; calibration fits its own later partition. Two chronological walk-forward blocks and a final untouched holdout follow with a full-horizon purge/embargo. Used holdout intervals are permanently sealed out of future fitting and fresh final holdouts are required. Current-baseline evaluation requires the exact recorded approved execution profile; older profiles cannot masquerade as the approved policy.

Offline qualification and forward shadow use the same original baseline eligibility, confidence and positive expected-return selection rule; favorable rejected candidates cannot inflate validated trading gains. Qualification checks selected-sample sufficiency, equal-risk net expectancy versus the frozen deterministic baseline, drawdown, Brier/calibration, two-times costs, multiple regimes, overfitting gap and feature drift. Qualified JSON models automatically become isolated research challengers; inference must occur after training and within the fresh decision window to count as forward prediction. Historical backlog inference is excluded from forward claims. Weak or deteriorating challengers are quarantined; no trusted model means the frozen deterministic paper strategy continues. Primary ML weights remain explicitly unapproved (`approved_ml_model: null`). No learning process changes active primary weights, hard risk controls, official approval gates or the seven financial control ledgers.

Exit feedback records conservative stop ambiguity, observed recovery/deterioration within the fixed horizon, short/long horizon disagreement and matched stop-distance/regime groups. It does not install an adaptive exit policy. Any future such policy requires its own versioned causal validation and approval.

## Genuine-data result and limits

The recovered 24-hour signal section contains **13,506** original primary observations. The causal pipeline produces **81** complete modeled labels, **13** pending observations and **13,412** exclusions: 6,703 lack a bound usable feature snapshot, 6,570 have no usable modeled entry VWAP, 98 are stale/future for their creation clock, and 41 have invalid plan geometry. Many are ordinary rejected/incomplete setups, not 13,412 software failures. The model dashboard distinguishes missing/invalid evidence from actual losing targets.

Those 81 rows supply only **four** conservative independent episodes. The result is **INSUFFICIENT_EVIDENCE**. No genuine market model was trained/promoted as an approved challenger and no profit comparison is asserted. Synthetic separable fixtures verify training, qualification, restart, automatic shadow activation and drift quarantine mechanics; they are never presented as market performance. Forty-five days is a research qualification requirement, not a new entry veto on the deterministic strategy.

The broad legacy collector timed out while reading a later primary section. Its partial source is retained with explicit provenance; parsed signal rows are development research, not a complete audit export. The replacement focused collector completed all seventeen financial database exports and supplies the forensic gate. Private full database dump streams and restored-copy checks are separate evidence. Two initial streams failed full restore with EOF; both were retained as failed evidence and replaced with validated read-only exports. All seventeen subsequently restored successfully. The final candidate profile, API startup and two learning-collector iterations preserve all financial-table hashes, one original primary funding event and all fifteen shadow manifests. The installed collector imports all nine genuine closed positions; its separate actual-outcome model also reports insufficient evidence. No remote files were created, credentials copied, containers restarted or production configuration changed during Stage A.

## Dashboard and release verification

The Personal Plan Research page now includes Learning & Performance: dynamic backend/profile versions, approved baseline/challenger identity, collector freshness, training status, dataset coverage and independent episodes, calibration and chronological/cost comparisons, strategy/regime results, actual fees/slippage/drawdown/profit factor/expectancy, attributed loss explanations, rejection/coverage warnings and exit feedback. Historical modeled paths, actual primary paper results, forward shadow predictions and synthetic fixtures remain labeled separately. Reporting falls back to RAOE regime evidence when the older field is absent; the latest PEPE record already contained both fields, so this fallback does not explain its loss.

Source-bound test/build/restore results are recorded in `docs/evidence/v4_9_2/staging-readiness.json` and its hashed gates. Immutable release identity is the complete commit and file hashes in the generated `release-manifest.json`; final image binding verifies platform config IDs and every saved layer, avoiding OCI index/config-ID confusion. The release must not be tagged ready or deployed while a mandatory engineering gate is unresolved.

`deploy/staging_v492.py` preserves the existing Aruba Compose project and ports, gates exact commit approval, performs seventeen-ledger restore verification, waits for natural flat exposure under existing protection, revises only the primary frozen profile and retains original shadow manifests. It does not recreate PostgreSQL/Redis. Duplicate activation of a healthy installed candidate verifies without pausing or restarting, even with newer positions. Interrupted post-cutover activation can resume only with durable backup/control-preservation proof; failed releases stop and require a separately approved correction. See the release handoff for commands and rollback limits.

### Verification results

The native verified union covers **479 cases** (468 in the full run plus current focused additions/corrections). The installed Linux AMD64 verified union covers **474 cases**; the five additional native cases require host Docker orchestration. Four initial Linux release-fixture failures were caused by missing Git in the test-only overlay and pass after adding that test tool. A final 26-case native and installed-image recheck covers shared research selection, doubled-cost arithmetic and long-term dense-history capacity; four learning modules and two release-version modules changed after the full run, and every other application hash is verified unchanged. The final installed API and seventeen-ledger rehearsal use all 291 final application modules.

Ruff passes and strict mypy passes all **143 non-frozen application modules**. Frontend unit tests pass **21 cases**, TypeScript and production Vite builds pass, and the final browser gate covers **32 cases**, including eight learning states/layouts at 375/1440 px. The separate legacy V4.3-versus-V4.4 two-image polling comparison requires its old baseline frontend and is outside this release’s browser selection. Deterministic UI fixtures and synthetic ML qualification tests prove engineering behavior only. Original and merged JUnit evidence, source revisions and all gate hashes remain available in the evidence directory. The learning-375/1440 screenshots are synthetic UI layout fixtures, including example comparison values, and are not genuine model-performance evidence.

The already published `v4.9.2-rc.1` tag remains unchanged and unapproved. Candidate rc.2 supersedes it after the dense-history regression exposed a raw-row capacity issue that could prevent the required long-term evidence from reaching training. No Aruba deployment occurred for either candidate during Stage A.
