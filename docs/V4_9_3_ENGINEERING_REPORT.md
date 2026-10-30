# V4.9.3 — staged observations and cautious market-state research

This release repairs the learning funnel and public-data acquisition. It does not establish a better trading strategy. The primary admission policy remains `4.9.1-primary-admission.1`; position sizing, risk limits, pricing, stops and managed exits are unchanged. Real exchange orders and automatic primary ML replacement remain disabled.

## Recorded investigation

The read-only export covers 30,760 original signals from October 28–30, ending **2026-10-30 05:46:12 UTC**. This includes several original execution profiles; it is not a sample consisting entirely of V4.9.2. Of the 4,678 V4.9.2 signals, 98 passed technical checks, 17 passed economics, and none passed final primary admission. The recorded hourly macro gate failed in all 4,678 evaluations. The earlier user audit had a shorter cutoff and different counts.

The initial live SQLite diagnostic contained 40,235 failed rows: 19,964 `vwap` key failures, 19,798 unbound legacy snapshots, 254 stale snapshots, 163 invalid geometries and 56 missing completed timestamps. Requiring execution VWAP from a signal rejected before pricing is the principal architectural error. Legacy coverage, infeasible candidates and malformed observations also needed separate dispositions.

Reprocessing the immutable source signals retains **7,558 causal market observations**, including **5,142 matured midpoint paths** and **2,416 pending paths**. There are **23,202 coverage exclusions and no genuine corrupt records identified in this sample**. Coverage exclusions comprise old snapshots without a data hash, missing completed-close/context evidence and stale decision snapshots. They are retained, never repaired with later feature values. The original failed SQLite rows and artifacts are also retained for audit.

The exported financial records still contain nine primary closed positions, net P&L **−€56.724117969028**, and one winner. The original PEPE entry/exit books still reproduce the latest **−€18.338337569309** result. There is no new evidence of a broker, stop-execution or accounting defect. Several shadow positions changed through normal paper trading during development; their separate ledgers, sizes and policies prevent treating absolute P&L as a controlled primary comparison.

## Observation and model lifecycle

The additive SQLite schema records one funnel row per original signal. Technical rejection, technical-but-unpriced, economic rejection, primary rejection and complete priced candidates have distinct stages. Coverage/source exclusions differ from genuine corruption. Persisted decision/order/position links record actual accepted orders, fills and closures separately; eligibility is never treated as a fill.

Three outcome domains remain separate:

* **Market task:** completed decision-close reference, immutable completed momentum/context/volume features, and contiguous 60/240-minute future midpoint paths with MFE/MAE. No VWAP, execution cost, entry fill or achievable profit is invented.
* **Priced-plan task:** a complete positive-quantity immutable plan, entry VWAP/costs, stop/targets and existing conservative costed path labels, including 2× cost stress. Rejected geometry is ordinary infeasibility; missing higher-context coverage does not invalidate otherwise legitimate market observations.
* **Actual-position task:** recorded managed-position P&L, fees, original profile and entry evidence. It is never silently mixed with fixed-horizon path labels.

Fresh inference and historical repair use separate transactional keyset cursors. Source queries are bounded at the tick timestamp, preventing rows arriving during collection from losing their prospective inference opportunity. Duplicate/restart ingestion is idempotent. Maturity shares bounded future-bar reads per asset. Training and research writes run in the dedicated research process; PostgreSQL financial sessions are read-only. HTTP reads only load published status.

Small deterministic L2 logistic models use training-only normalization and chronological calibration. Global overlapping crypto signals share a four-hour episode. Fitting, calibration, two forward evaluation blocks and the final holdout are chronological and embargoed. Consumed holdout windows, including overlapping label intervals, never re-enter fitting. Qualification requires 240 independent episodes across at least 45 days, sufficient partitions, calibration, drift and regime robustness; the priced task additionally requires baseline and execution-cost-stress advantages. Retraining requires both elapsed time and new independent evidence. Artifacts are immutable content-addressed JSON, checked on read. Deteriorating forward calibration or drift quarantines research challengers.

The market task evaluates midpoint direction against training-period prevalence. Its output names explicitly say `probability_mid_up` and `conditional_expected_mid_return`; execution cost stress is inapplicable without a priced plan. A directional challenger cannot masquerade as trade EV. Priced-plan predictions retain calibrated conditional net-return estimates and bounded research sizing. Neither task has primary execution authority.

**Only four independent market episodes** are available in this repaired export. No model is qualified and no primary weights are installed. The actual-position sample is also insufficient. Expected significant-adverse-move modeling and adaptive exits remain research questions; storing adverse excursions does not establish a validated adverse-risk predictor.

## Market states and hypotheses

A versioned research recipe distinguishes sustained bear, relief rally, emerging recovery, bullish continuation, range, high-volatility breakout, exhausted momentum, uncertain transition and unknown context. It observes completed 5m/15m/1h/4h structures, EMA slopes/persistence, BTC/ETH short-term versus hourly context, relative performance, volume and current spread. Missing higher context cannot count as bullish continuation. New producer snapshots include the completed close and bound context once per asset, outside the strategy loop.

Recovery while both hourly benchmarks remain bearish requires completed short/medium benchmark improvement, asset reclaim, positive relative strength and volume confirmation. This is a predeclared research hypothesis, not another primary veto or an authorized bypass. Research breakout/retest and patient-execution alternatives remain separate. A future candle touch is never assigned an executable patient fill.

The historical reconstruction examines all technical candidates and hourly samples, using exported completed bar versions. It does **not** prove their original first-observed availability and is excluded from model feature construction. It found seven emerging-recovery contexts, but no additional qualified priced opportunity establishing an advantage. Baseline and confirmed-transition comparisons contained the same three matured signals in one independent episode, with negative modeled net R. This is inconclusive. Original gate eligibility is never relabeled across profiles.

Nine-entry fixed-stop scenarios preserve actual entry VWAP/fee and original targets, then compare the original stop with minimum 1.5/2 ATR distances under declared path-cost assumptions. Recorded entry-to-stop distances span approximately 1.38–3.67 ATR. Most scenarios still stop out; the winning scenario's risk-normalized outcome worsens when widened. The latest PEPE still stops under all tested distances. These are historical fixed-plan scenarios, not replicas of the production's managed exits, equal-capital portfolios or executable alternatives. No live stop is widened, and no avoided-loss benefit is asserted.

## Provider efficiency and attribution

The bounded initial worker log covered approximately 81 minutes and contained 23 HTTP 429 responses. Its window differs from the user's earlier 157-minute/27-response audit. Old cumulative counters are not labeled as measurements since this release.

The public adapter now coalesces concurrent identical reads within the same priority, shields a shared read from one cancelled waiter, reuses a valid all-ticker cache for subset requests without refreshing its timestamp, and adds a 50ms cross-process reservation margin for actual public endpoint families. Protection has a separate coalescing key. Completed order books are not cached. Existing fresh locked admission, protective priority, endpoint-family breakers, bounded retries and shared cooldowns remain active. Actual HTTP time is measured separately from existing queue-inclusive latency.

Revolut documents `Retry-After` in **milliseconds**; the existing parser was correct and is retained. See [official API documentation](https://developer.revolut.com/docs/api/revolut-x-crypto-exchange) and [official API repository](https://github.com/revolut-engineering/revolut-x-api/blob/master/api/README.md). A pacing margin is not a promise that the provider will never return 429. Compare dated post-release windows only after observing them; engineering fixtures do not demonstrate a sustained production reduction.

The original seven active shadow manifests remain unchanged. Their native strategy identity receives an explicit, verified `public-acquisition/4.9.3.1` compatibility revision. The bridge pins the entire old closure, allows only reviewed acquisition/compatibility changes, verifies the repository outside the reservation method byte-for-byte, and rejects altered pricing, accounting or strategy files. Frozen V4.2/V4.4 source packages are untouched. Future observations can differ because acquisition timing changes; historical trades are not assigned a new manifest.

## Interface and engineering verification

Learning & Performance shows dynamic backend/profile identity; the latest candidate's asset and benchmark timeframes; actual failed admission gates; stage/disposition counts; unpriced market coverage versus complete priced plans; separate model/forward states; actual primary costs/outcomes; and dated provider windows. Legacy exclusions are explicitly retained separately, including in the API. Mobile/desktop browser checks cover recovery, relief, unknown context, collector staleness, qualification and quarantine.

Machine-readable gates in `docs/evidence/v4_9_3` record final native and installed Linux regressions, targeted causality/model/provider/deployment tests, frontend checks, browser verification, hashes and limitations. The installed package is compared against all **294 source modules**. One early wheel omitted the new compatibility JSON; package metadata was corrected and installed-image identity/restore checks repeated. A stale synthetic direct-cycle clock and a fixture missing the new manifest were corrected without changing production admission. A transient Docker build DNS failure produced no accepted image; the successful rebuild passed source verification.

Seventeen fresh read-only database dumps were parsed and restored locally on an internal Docker network with no host ports. Before/after seals cover twelve financial tables per account across profile revision, authenticated API startup and collector restart. One original €7,000 funding event, €6,943.275882 primary cash, all orders/fills, all fifteen shadow manifests, seven active controls and eight archived controls are preserved. A shadow open position in the snapshot remains intact. This local proof does not replace the mandatory fresh Aruba backup and restore checks immediately before activation.

## One-time deployment boundary

The October 30 task explicitly authorizes one conditional unattended V4.9.3 release. `AGENTS.md` and the committed task policy record its request hash, starting commit, branch, exact staging scope and safeguards. `deploy/staging_v493.py` verifies source-bound gates and candidate source/platform identities, then records full Git SHA and source/image archive digests in an exclusive durable task claim. Another commit or different artifact identity cannot reuse it. No exact-commit human approval is fabricated.

The cutover pauses new entries while old protective monitoring manages existing positions, waits for a bounded natural flat state, verifies all seventeen backups/restores and the candidate profile, replaces only scoped application services, re-verifies all seventeen post-cutover restores, compares **170 core financial table seals**, checks freshness/isolation and resumes the original controls. PostgreSQL/Redis volumes, rollback sources/images, routing, Tailscale, unrelated applications and real-money prohibitions remain intact. Failures preserve diagnostics and protection; no financial database is automatically restored over newer transactions.

The exact release commit, tag, canonical Linux image configuration IDs and archive digests are generated after the clean source commit and recorded in immutable release bindings. Deployment and post-activation observations are recorded separately in the private release evidence, avoiding a circular self-commit claim. Engineering acceptance is not profitability or a completed 30-day claim.
