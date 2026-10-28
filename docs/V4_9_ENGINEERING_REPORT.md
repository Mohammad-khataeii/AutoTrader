# Personal Plan V4.9.0 — engineering and research report

V4.9 consolidates the originally planned V4.8.1 execution fixes and V4.8.2 strategy improvements. This is a staging release candidate, not a demonstrated profitable strategy. Stage A verification and immutable packaging must pass before release-specific approval. **V4.9 has not been activated on Aruba.**

The exact source commit is recorded in the immutable release package's `release-manifest.json` and the release handoff; a document cannot embed the hash of its own containing commit. The source fingerprints and component evidence below bind this report to its tested implementation. No V4.8.1/V4.8.2 release was created. `main` and the old production server were untouched.

## A. Root-cause matrix

| Confirmed issue | Evidence / responsible code | Correction |
|---|---|---|
| Distant ask distorted shadow stop risk | 16 original rejected BUY orders; `persistence/accounting.py` | Account-agnostic `execution/admission.py` walks actual fillable asks, rounding, fees, slippage, budget and durable consumption. Dispatch reuses its exact quote. |
| Consumed depth could change dispatch economics | Durable admission/dispatch separation | Dispatch rechecks actual quantity, first-target cost feasibility, RAOE net R/headroom and exit-depth assumptions before committing a fill. |
| Pending aggregate risk could understate multilevel partial execution | Reservation estimate versus actual stored projection | Primary aggregate risk retains the greater of the existing reservation bound and the stored executable loss. All production risk caps remain unchanged. |
| Micro pivots became hard ceilings | Original 5m minimum-pivot planner, 144 reported technical signals and zero RAOE economic qualifications | Causal 5/15/60/240m significance model; minor 5m noise separated from meaningful overhead, broken/retested levels and bounded completed-range scenarios. |
| No target without an overhead pivot | PEPE case B empty original targets | A bounded measured-range scenario is available only when supported by completed structure; no economic target or stop is manufactured to qualify. |
| Exhaustion was a common veto | Original EMA extension >2 ATR | Existing three playbooks retain the conservative veto. A distinct continuation hypothesis uses two range-break closes, relative strength, spread, near-depth, wick/extension controls and its own exit version. |
| PEPE and peers used different completed snapshots | PEPE 01:25:25 decision preceded BTC/ETH 01:20-bar observations at 01:26:07 UTC | Independent BTC/ETH acquisition, one fixed completed cutoff, explicit availability/staleness/gap/error diagnostics. Missing peers remain UNKNOWN. |
| 4h classifier could never warm up normally | 720 five-minute bars produce about 14–15 complete 4h bars, while 21 are required | 1,152 genuine bars (96h), bounded cold pagination and incremental durable cache. Gaps/forming bars cannot be fabricated into valid history. |
| Narrow discovery missed intraday coverage | BCH and NEAR trigger episodes lacked saved evaluations | Cached completed short-window returns, actual timed summary-mid observations, bounded priority and rotation. Selected/deferred/rejected reasons are durable. 24h statistics never become fake 30m returns. |
| Path touches could imply profitable missed execution | Old outcome labels and per-half-hour grouping | Separate path, genuine quote, modeled execution, fixed counterfactual and actual fill evidence. Per-signal records plus overlap episodes; invalid economics cannot become a missed win. |
| Outcome backlog could strand older events | Newest-100 lookup stopped reaching old unassessed decisions | Oldest-first anti-join against versioned assessments; original reviews remain immutable. Conflicting candle versions produce missing evidence. |
| Shadow holding policy differed from primary baselines | Old successor records could use null seconds / 24h default | New manifests bind entry, exit, holding, costs, capital, risk, execution mode and data kind. Matched baseline exits are 3h; corrected RAOE 6h; continuation 4h. Old ledgers are retained. |

## B. PEPE forensic reconstruction

All six original records (three playbooks at each of two entries) are preserved in `evidence/v4_9/pepe-original-signals.json`; reconstructed structure and timing diagnostics are in `development-forensics.json`. These are known development cases, not validation samples. The named audit archive/CSVs were unavailable. Read-only exports recovered equivalent history; the persistence cutoff yields **5,460** V4.8 signals rather than the archive's reported 5,430. The scope difference remains explicit.

**Case A: 27 October 22:35 UTC / 23:35 CET.** The saved pullback entry ask was 0.0000040776 EUR, stop 0.0000040454, old first target 0.0000040798 and ceiling 0.0000040810. Benchmark context was MIXED. The meaningful completed structure model identifies overhead near **0.0000041044**, rather than treating the tiny pivot as the ceiling. Its first approach scenario is still below the recorded modeled break-even bid near **0.0000040928**. Reusing the original entry/exit cost summary as an explicitly conditional depth-impact assumption gives about **−€0.36** at the new first scenario and roughly €8.11 stop risk for that original size. It still fails net R and cost headroom. A later rally is not a causal target; this entry remains a justified economic refusal under the specified model.

**Case B: 28 October 01:20 UTC / 02:20 CET.** The saved ask was 0.0000042183 and recovery stop 0.0000041103; the original planner produced no targets. Its ~3.13 ATR EMA extension fails the old recovery rule. PEPE's book was observed around 01:25:01 and decision around 01:25:25. The matching BTC/ETH new-bar features were first persisted around **01:26:07**, after that decision. Thus original UNKNOWN was consistent with its actual stale peer snapshot; the later MIXED labels cannot authorize an earlier ask. A retrospective aligned reconstruction is labeled separately.

Continuation is a different hypothesis, not a relaxation of recovery: the preceding 01:15 PEPE close equals the preceding range high, so two completed closes above the range plus buffer were not yet confirmed. Saved near-depth sufficient for a new entry is also unavailable. The implementation does not force this known rally into a winning trade. A broader bounded scenario may still reject because targets are behind entry or fail costs.

For both cases, the forensic file compares the original prompt ask, next completed-candle quote, a patient ask within 15 minutes, the original structural stop, a 1.2 net-R cost barrier, fixed 20/60/180/240/360-minute quote checkpoints, and a declared two-entry-ATR trail after reaching that barrier. Stop-first ambiguity and missing quotes are retained. A bid observation is not a guaranteed sell fill. The full original rejected RAOE L2 book was not persisted; quote summaries and original cost projections cannot establish historical exchange execution. Current public PEPE instrument metadata confirms tick 1e-10 and quantity step 10, but its historical metadata version was not saved; current metadata is not proof of every old constraint. V4.9 now durably stores order constraints.

Both PEPE entries belong to the same broader rally and overlapping exposure window. They are never counted as two independent winning trades.

## C. Execution consistency

`quote_execution` supplies actual fillable quantity and slipped VWAP for every account. Entry fee, entry slippage and modeled stop-side fee/slippage are each charged once; spread enters through actual ask/bid geometry. Only uncovered configured minimum-cost allowance is added. Planned loss is conservatively rounded upward. Future depth is explicitly an assumption derived from current observed exit impact, not guaranteed liquidity or a bound on gap losses.

All 16 recorded distant-ask loss checks reproduce: approximately **€6.48–€20.21** originally versus **€0.43168–€1.48721** under the new actual-quantity model. All corrected loss checks are within €5; this does not establish that every other gate would pass. The earlier diagnostic's €0.53–€1.61 used a different, more conservative cost allowance; it is not falsely presented as identical accounting. No rejected historical order was replayed into a prospective ledger.

Real PostgreSQL regressions cover the 16 cases, multi-level VWAP, quantization, budgets, partial/consumed depth, unavailable/stale books, fee/slippage precision, near-cap refusal, duplicate intention, admission-to-dispatch separation and restart, full reservation release and reconciliation. The same authorized RAOE signal, quantity and observed book produce identical executed entry quotes in actual primary and shadow repository scopes. Existing process-kill/failpoint acceptance continues to exercise real worker interpreters and database recovery. The original IOC no-fill cancellation behavior is preserved.

## D. Structural planning

Completed bars are aggregated only from full, aligned same-asset source intervals. Swing pivots require two later completed timeframe bars before becoming known. Five-minute pivots remain visible as noise; 15m+ swing significance uses a fixed 1.25 ATR prominence threshold. Broken/retested zones, genuine higher overhead, price discovery and missing structure are explicit diagnostics. No future candle or later rally high supplies a target.

Targets approach the nearest meaningful overhead, or use fixed 0.5/0.75/1.0 extensions of a completed range, constrained by known higher structure. These are scenarios, not forecasts. A structural stop uses its strategy's invalidation plus 0.25 ATR, retains a one-ATR noise floor and is never tightened merely to pass R. Tick collisions, unsupported upside, nearby unconfirmed breaks, chased quotes and insufficient after-cost reward still reject entries. Continuation's invalidation is the broken range, distinct from an older recovery low.

All three existing RAOE entries retain 6h management. Continuation has a distinct 4h policy and needs two completed post-entry 15m failures for a discretionary breakout-failure exit; ordinary 5m noise alone cannot authorize it. Fresh-bid protection, emergency controls and expiry remain ahead of discretionary research. Bid scenarios are converted once to net exit floors.

## E. Strategy research

The registration preceded acquisition of the unused March 2025 Coinbase EUR proxy interval (BTC, ETH, SOL, LINK, ADA). Warm-up: March 1–5. Training: March 5–8; one-day purge; validation: March 9–11; two-day purge; untouched historical test: March 13–17, all end-exclusive. Each segment and variant has its own €500 research portfolio, €75 proposals, €5 stop-risk cap and €150 reserve. Financial independence does not imply statistical independence across shared market data.

Raw A3/B3/E3 retain their original 4.6 experimental entry recipes; an explicit registration amendment **before holdout observation** additionally binds the unchanged V4.7.1 primary quality review. Both are shown. V4.8 RAOE definitions are frozen separately with original 720-bar context. V4.9 uses the corrected structure and real extended context. Historical strategy comparisons share the corrected simulated broker/cost policy; frozen V4.8 refers to entry/regime/plan definitions, not replaying its execution defect. Original actual V4.8 refusals remain separate evidence. No threshold was retuned after viewing the held-out test. Complete training batches were resumed only after every numerical model dependency, registration and dataset hash matched; changes to unused telemetry are not silently treated as changes to the simulator.

Normal costs: 10 bps fee per side, 8 bps slippage, 10 bps spread. Stress: 15/12/20 bps. Historical L2 is unavailable: one finite level assumes 1% of the **previous completed** candle's volume, with stop-first intrabar ambiguity, partials, trailing and fixed expiry. This is a hypothesis about execution, never exchange-grade depth. Gaps remain gaps. Full executions, costs, drawdown, holding, risk, missed fills, rejections and residual exposure are retained in `research-results.json`.

Each cell below is **net EUR P&L / closed trades**, after modeled costs. Zero/inactive variants are not winners.

| Strategy / entry | Train normal | Train stress | Validation normal | Validation stress | Test normal | Test stress |
|---|---:|---:|---:|---:|---:|---:|
| A3_COST_AWARE_CONTINUATION · MARKET_AFTER_COMPLETED_SETUP | €-5.87 / 7 | €-3.07 / 3 | €-3.89 / 6 | €-1.50 / 2 | €-0.57 / 4 | €-0.36 / 1 |
| B3_STATEFUL_BREAKOUT · MARKET_AFTER_COMPLETED_SETUP | €0.00 / 0 | €0.00 / 0 | €-0.82 / 1 | €0.00 / 0 | €-0.65 / 1 | €0.00 / 0 |
| E3_ADAPTIVE_RELATIVE_STRENGTH · MARKET_AFTER_COMPLETED_SETUP | €-1.27 / 2 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| V471_A3_COST_AWARE_CONTINUATION · MARKET_AFTER_COMPLETED_SETUP | €-1.71 / 1 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| V471_B3_STATEFUL_BREAKOUT · MARKET_AFTER_COMPLETED_SETUP | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| V471_E3_ADAPTIVE_RELATIVE_STRENGTH · MARKET_AFTER_COMPLETED_SETUP | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| V48_RAOE_EARLY_RECOVERY · MARKET_AFTER_COMPLETED_SETUP | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| V48_RAOE_TREND_PULLBACK · MARKET_AFTER_COMPLETED_SETUP | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| V48_RAOE_BREAKOUT_RETEST · MARKET_AFTER_COMPLETED_SETUP | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €-1.20 / 1 | €0.00 / 0 |
| RAOE_EARLY_RECOVERY · MARKET_AFTER_COMPLETED_SETUP | €-0.12 / 2 | €-0.55 / 1 | €-5.63 / 5 | €-4.97 / 4 | €0.00 / 0 | €0.00 / 0 |
| RAOE_TREND_PULLBACK · MARKET_AFTER_COMPLETED_SETUP | €-1.32 / 2 | €-1.66 / 2 | €-0.62 / 1 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| RAOE_BREAKOUT_RETEST · MARKET_AFTER_COMPLETED_SETUP | €0.00 / 0 | €0.00 / 0 | €-0.54 / 1 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| RAOE_BREAKOUT_CONTINUATION · MARKET_AFTER_COMPLETED_SETUP | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| MOMENTUM_30M · MARKET_AFTER_COMPLETED_SETUP | €-19.19 / 47 | €-26.76 / 46 | €-1.07 / 2 | €-1.38 / 2 | €-8.83 / 42 | €-15.96 / 20 |
| BUY_AND_HOLD · MARKET_AFTER_COMPLETED_SETUP | €-9.76 / 3 | €-10.36 / 3 | €-29.45 / 3 | €-29.99 / 3 | €-2.75 / 2 | €-3.29 / 2 |
| CASH · MARKET_AFTER_COMPLETED_SETUP | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| RAOE_EARLY_RECOVERY · PATIENT_IOC | €0.00 / 0 | €0.00 / 0 | €-1.34 / 3 | €-1.97 / 3 | €0.00 / 0 | €0.00 / 0 |
| RAOE_TREND_PULLBACK · PATIENT_IOC | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| RAOE_BREAKOUT_RETEST · PATIENT_IOC | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| RAOE_BREAKOUT_CONTINUATION · PATIENT_IOC | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| RAOE_EARLY_RECOVERY · ONE_BAR_DELAY_CONFIRMATION | €0.22 / 1 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| RAOE_TREND_PULLBACK · ONE_BAR_DELAY_CONFIRMATION | €-0.76 / 1 | €-0.93 / 1 | €-0.67 / 1 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| RAOE_BREAKOUT_RETEST · ONE_BAR_DELAY_CONFIRMATION | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |
| RAOE_BREAKOUT_CONTINUATION · ONE_BAR_DELAY_CONFIRMATION | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 | €0.00 / 0 |

The forward V4.9 paper period has **not started**. Existing V4.8 prospective ledgers are retained separately; their age is not credited to V4.9. Matched successor exits are 3h, corrected RAOE 6h and continuation 4h, explicitly different hypotheses. New forward profiles keep separate €500 accounts; none of that cash is added to the primary portfolio.

## F. Missed-opportunity accounting

The fixed trigger (completed 30m return ≥0.8%, close over prior completed 60m high, 90-minute suppression) reproduces **13** price episodes. **11** have saved evaluations; BCH 23:10 UTC and NEAR 01:45 UTC are coverage gaps, not demonstrated missed profits. At a three-hour horizon, the cost-barrier diagnostic matches **1 target-first, 3 stop-first, 7 unresolved**. At one hour it is 1/1/9; at six hours it is 2/3/6, with the additional AAVE barrier reached after more than four hours. The result depends on horizon and costs.

Thirteen triggers collapse into six asset groups under overlapping six-hour holding windows, with further common crypto-market dependence. They do not create 13 independent bets. **No executable missed profit is proven by the barrier counts**, and no candle-only result is labeled a correct economic rejection. Primary V4.8 actual accepted BUY/fill count remains zero; the four legacy fills are separate evidence.

V4.9 persists every signal identity and derives episodes across strategies. Original rejection, future price path, genuine quote summaries, alternative plan, modeled execution and actual ledger fills remain distinct. Missing depth, conflicting bar versions, unresolved horizons and incomplete pagination are explicit. Counterfactual alternatives never rewrite the original event.

## G. Operational fixes

One cycle cutoff is shared across primary and shadow decisions. BTC/ETH are acquired independently of the shortlist. Requested/available candle, first successful observation, source, gap count, duplicate/invalid OHLCV, staleness and exact UNKNOWN reason are persisted. Genuine incomplete/future bars never become peer context. Valid 4h state survives a PostgreSQL cache reopen; missing history remains unknown. Backfilled bar time is not first-seen time.

Discovery uses cheap public summaries, genuinely cached completed returns or explicitly timed summary-mid changes, limited detail slots and oldest-observed rotation. BTC/ETH use extra benchmark slots. Cold warm-up uses bounded 720-bar requests; later updates overlap only recent bars. Existing per-family scheduling, shared 429 backoff and protective priority are retained; an unavailable candle family does not hold the book family. The provider documents public-family scheduling and millisecond Retry-After semantics in its [official Revolut X API documentation](https://developer.revolut.com/docs/api/revolut-x-crypto-exchange). No uncertain public page-size limit is asserted.

The authenticated radar/inspector displays precise PEPE prices, cost break-even, structure roles and blockers; competition shows exits, orders/fills, elapsed evidence age and retained archives. Runtime details expose scanner/protection, market metrics, benchmark status and 4h readiness. Android-width tables scroll within their containers.

Read-only collection: `python3 scripts/v49_diagnostics.py --hours 12 --output <new-local-directory>` (also 24 or 48). It streams code through `ssh aruba-vps`, discovers the actual official/primary/shadow database registry, uses repeatable-read **READ ONLY** SQL and selected Docker metadata, and creates only a local gzip bundle, manifest and hourly plain-language summary. It never reads credential files, SSH keys, full environments or process logs. Sensitive fields/URLs are redacted; row caps and per-database snapshot cutoffs are disclosed. Archived ledgers remain discoverable. A successful ten-database collection is recorded in the diagnostic evidence.

## H. Financial safety

At **2026-10-28 08:55:32 UTC**, the actual staging primary account was **RUNNING**, initially funded **once** with €7,000, cash/equity **€7,003.532190559225**, four orders/four fills, zero open positions, zero pending orders and zero reserved cash. The prior €3.53 is legacy V4.7.1 history, not V4.8/V4.9 strategy profit. The actual account reconciliation passed again at that time, with the existing profile fingerprint matching the live runtime and Tailscale Serve unchanged. A fresh live reconciliation is mandatory again during Stage B.

All ten original read-only exports were restored into an isolated local PostgreSQL cluster with no published ports or external network. The candidate preserved original funding, account marker, legacy manifests/orders/fills and checked financial-table hashes; reconciliation passed. Eight flat paused clone ledgers were safely retired without deleting databases or history, then seven new independent paused clone ledgers were provisioned. These are disposable clone acceptance results, not forward market performance. `financial-restore.json` binds the proof to source identity.

Primary caps remain €700 position, €35 planned loss, €4,200 exposure, €2,800 reserve, €140 aggregate stop risk, €2,100 correlation cluster, €140 daily and €350 weekly thresholds, six positions, 24 new entries/day and 10% drawdown halt. Shadow caps remain €500 capital, €5 planned loss, €150 reserve and the existing eight non-archived-account bound. Continuation is absent from primary authority. Old incompatible manifests cannot resume; archival requires flat, paused/stopped, reconciled accounts without unfinished/reserved exit intent.

Application family: 4.9.0 (staging candidate); primary profile `4.9.0-paper.1`; RAOE entry `4.9.0-raoe.1`; distinct matched successor/structure/continuation exit versions. Existing V4.7/V4.8 identities are never rewritten. Real-money trading stays disabled.

## I. Testing and source verification

Source fingerprint: `1817997582091b04b96988b990c242047214846a48d6750f42f5396728f69fe1` (279 Python modules). Ruff passed; mypy passed on 131 checked modules. Native full backend: **409 passed, zero failed/skipped**; frontend: **19 passed** plus TypeScript/Vite build; native Chromium/Nginx browser: **20 passed** at 320/375/390/1440px. The final installed Linux result, explicit host-only test scope and actual product API smoke are recorded in `linux-tests.json`. Real restored-ledger rehearsal passed for ten original accounts, preserving four fills and €7,003.532190559225, with eight safe local retirements and seven isolated new clone profiles. No prospective outcome follows from these checks.

All eight Stage A gate artifacts are source-bound and hash-pinned by `staging-readiness.json`. The release source manifest binds source, tests, frontend, scripts and documentation to the exact immutable commit. The installed product image's 279 Python hashes match local source; the candidate API reports the exact profile, rejects unauthenticated access, reconciles the restored ledger and serves all 144 research rows. Test overlays are excluded from deployment.

Meaningful failures were retained and corrected: IOC cancellation status; legacy baseline tests accidentally competing with new RAOE (now explicitly isolated baseline regressions); a missing new exit-policy field in an authorization fixture; an oversized durable observation key; retested support unreachable after confirmation; outcome-backlog starvation/conflicting versions; aggregate pending risk underestimation; a browser selector matching a cell containing additional holding text; and staging mocks missing the newly enforced read-only Tailscale check. Earlier Linux tooling lacked Git/Docker CLI. Host-only Docker orchestration tests remain covered by the native full suite; their exclusion from nested Linux runs is explicit, not an unreported skip. A direct synthetic lifecycle now holds its original observation-time clock so emulation crossing a five-minute boundary does not turn its fixture into stale data; production missing-bar refusal is unchanged.

Frozen V4.2/V4.4 source bytes remain hash-verified. The reviewed bridge boundary and full installed product Python file map are checked. The deployed image must match the approved full commit and Linux AMD64 architecture; test tooling images are never deployable release images. Proxy studies and synthetic acceptance do not prove prospective performance.

## J. Deployment and rollback

**Approved V4.9 commit: none yet. Activation: NOT ATTEMPTED.** This report completes Stage A only after its gates pass; repository instructions require approval of the exact newly packaged release before Stage B. Earlier V4.8 approval does not cover changed V4.9 source.

Actual Aruba staging remains commit `4b9c68862ef7d697f973614bd529362daf43b74e`; the later V4.8 mobile fix from `4ea71c889e5d49a5c28b916171208df9fdf45ab4` is included in V4.9 source. Compose remains **autotrader-aruba-test**, frontend `127.0.0.1:13000`, backend `127.0.0.1:18000`, with private [Tailscale access](https://trade-test.taila77b9e.ts.net). The Serve configuration SHA256 is `9486f159eb2847f1b15030d023437c6fcce73a54c2f8fc20775708151c547c6f` and the helper verifies it before/after activation. No Nginx/TLS/Tailscale/global Docker configuration is changed in Stage A.

After exact-release approval, `deploy/staging_v49.py` requires the immutable manifest, approved full commit and exact image bindings. It pauses new entries while old protection remains active, waits for every retained ledger to become flat without forced liquidation, verifies backup/isolated restore and candidate profile on real restored history, then performs the scoped cutover. All eight old ledgers remain accessible as retired records; seven new comparisons are explicitly bound and paused before the worker starts. A further backup/restore covers **all seventeen registered databases** before entries resume. A failed backup, reconciliation, migration/source/image/access check blocks activation. A failed release cannot be blindly retried; correction requires a new tested, separately approved commit.

Rollback retains the previous source wrapper and exact old images: app `sha256:06a142a28b2ed70f8ff0bacd66117e190d21dda900c1476116505e19831117e5`, frontend `sha256:0c70420ef93c98d2a5f75f0ca6da49d87375c2538d434e223092735f098508e5`. Financial databases are never rewound over newer transactions. Automatic image recovery is limited to known-flat accounts; otherwise entries pause while candidate protection and diagnostics remain. No global prune, `down -v`, old production operation or unrelated-container action is permitted.

## K. Performance assessment

**Positive net expectancy is not demonstrated.** In the held-out historical test all new V4.9 variants and reviewed V4.7.1 baselines were inactive, while active raw/momentum/hold controls lost after modeled costs. Corrected structural plans did produce economically feasible trades in training/validation, but their net outcomes were negative. Continuation's technical candidates failed structure/economics; its zero-trade result is an economically restrictive, unvalidated design, not a profitable cash strategy or proof that no opportunities existed.

Engineering acceptance corrects defects and enables accountable experiments. It provides no profitability, calibrated win probability, reliable risk-adjusted return, 30-day completion or primary allocation promotion. No favorable PEPE quote path overrides this conclusion.

## L. Next research phase

After approved paper-only deployment, collect at least the manifest's existing 30-day prospective minimum while preserving all negative/inactive results; a calendar threshold alone is insufficient. Seek enough non-overlapping episodes across different market regimes to estimate net expectancy and drawdown with dependence-aware uncertainty. Record decision-time bar availability, independent benchmark alignment, exact versioned plans, genuine depth, partial/missed fills, fees, adverse selection, stop gaps and protection latency.

Continuation especially needs a new preregistered structural/admission hypothesis if prospective technical candidates remain economically impossible. Do not retune on the now-inspected March test or the known PEPE rally. Compare prompt, delayed and patient policies with predeclared exits and stressed costs on newly unused data. Keep it isolated from primary authority until the relevant approval and evidence requirements are met. Retain a cash control and the original baseline definitions; never require a minimum trade count to manufacture activity.
