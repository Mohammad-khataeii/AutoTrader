# V4.9.9-rc.1 — evidence-driven paper intelligence

Implementation only. Tests, linters, type checks, frontend/Docker builds,
migrations, backtests, simulations, application startup and deployment were
explicitly prohibited for this task and were not performed. No VPS connection
or financial database access was made. Git inspection and source editing are
not executable validation. This release has no engineering acceptance or
profitability claim.

## Evidence and design

The local private V4.9.8 archive was available. Its directory listing, analysis
hint and Bybit reference-envelope format were inspected in place. The archive
was not copied into this repository and no raw diagnostic output is committed.
The hint discloses row caps and an incomplete database extract; it cannot
establish complete account history. No historical evaluation was executed.

The supplied eight-day personal result (one winner in twelve closures, about
−€74.52 realized net) argues against adding activity or loosening risk. Fees
and modeled slippage are already in those net results. The supplied multi-coin
reviews concern overlapping hypothetical observations, including technically
invalid signals; neither the target touches nor market volatility demonstrate
predictive edge.

## What is implemented

### Bounded causal scanning

`adaptive_screen` reuses the last detailed completed-candle feature snapshot.
It considers actual candle ranges over 1/3/5 minutes, relative candle volume,
acceleration, trend persistence, controlled expansion, liquidity, spread and a
material sampled-mid change. Features expire after five minutes. Missing
candles remain unknown. Rolling 24-hour turnover changes receive no short-window
volume credit. Half the six detail slots retain oldest-first rotation.

No extra candle call is required by this scheduler. Detail concurrency remains
two and the separate protective loop and provider priority remain intact.
Selected/deferred rows expose ranking components, last-visit age, feature
freshness and the sampled move since the previous scan. Those sampled changes
do not reconstruct missed intrainterval execution or profit.

The default remains the V1 scheduler. The optional V2 research flag selects the
adaptive scheduler; decisions identify that scheduling version. This changes
the observation selection population, which must be controlled in comparisons.

### V2 strategy research, isolated from financial authority

`MULTI_USDT_MICRO_RESEARCH_V2` introduces eight observations per detailed market:
the continuation, compression/retest, range and failed-break hypotheses, each
evaluated independently long and short. Their policy IDs end in `_V2`.

They require completed candles and use structural remaining room, buffered
targets, volatility-scaled protective distances, follow-through, and entry
extension checks. Continuation and retest add completed 15-minute alignment.
Range visits must be separated rather than counting adjacent extreme candles
as independent support. Reversals require two completed reclaim closes and
avoid the opposing strong trend. These are unvalidated causal hypotheses, not
thresholds fitted by executing the private archive.

`PAPER_MULTI_V2_RESEARCH_ENABLED=false` is the default in Compose and the example
environment. It requires the existing multi feature and paper worker. It never
enables entries, provisions accounts or reserves capital. The ledger explicitly
refuses V2 entry policies. Qualified research candidates use a fixed virtual
1,000-USDT sizing reference at each leverage, separately labeled from actual
account allocation. At most one additional book/mark observation per detailed
market is requested, and only if a V2 technical hypothesis passes. Journaling
precedes creation of the V1 decision, preserving V1's short intent TTL.

The V2 policy hash binds its terms, generator and relevant source dependencies.
Changing those bytes changes its identity. The V1 experiment, policy terms/hash,
four original generators, initial balances, cohort IDs and historical records
are preserved. V1 scenario ranking retains its existing rule. V2 research adds
a cost-burden tie break; both report unknown future success probability/EV.

### Economics and research evidence

Economic plans now explain gross directional room, conditional target net,
planned stop loss, entry/exit costs, fees, spread, observed depth impact,
residual slippage, latency stress, funding-window exclusion, account notional
and quote ages. Components explicitly disclose overlap: spread and impact
are already in VWAP and must not be charged again. Expected adverse excursion
and success probability remain unknown.

All three cohorts receive independent scenario qualification and their own
refusal reason. Matched V1 admission still requires all three to pass. Account
risk checks are evaluated before any reservation, with cohort-specific
refusals; no size, leverage, margin or loss limit is relaxed to make them match.

New immutable signal payloads capture decision time, completed-data cutoff,
contract hash, quote availability/freshness, per-cohort economics, entry-control
state and risk halts. Decision categories distinguish technical invalidity,
economic/safety failure, data quality, risk/control, alternative selection,
research only and admitted intent. An admitted intent is not a fill; actual
fills and settlements retain their own journal events and signal references.
Reviews link committed fill and settlement facts as of a named cutoff, separately
from the no-fill proxy; a later funding-delayed settlement remains its own event.
Older missing contexts stay `LEGACY_CONTEXT_UNKNOWN`.

New due reviews use `multi-candle-review/2`. Existing completed reviews are not
rewritten. Reviews exclude the partial decision minute, require a complete
observation window, resolve ambiguous barriers stop-first and stress a gap
through the stop. Barrier/time returns, horizon movement, MFE/MAE and touch-time
upper bounds are descriptive. The separate fee/slippage proxy is explicitly
no-fill, with historical spread, depth, latency and funding unknown when absent.
Tags such as false-breakout or late-entry are hypotheses, not proved causal
attributions. Correct rejection and missed profitable trade remain unknown.
Review idempotency is checked under the same state lock as journal insertion.

`multi/research.py` reads the archived public-data envelope, distinguishes LAST
and MARK, excludes open acquisition candles, rejects conflicting duplicate
observations and retains acquisition time. Metadata acquired later cannot be
claimed known at the decision. Explicit complete funding input uses historical
rates and the preceding completed mark. LAST barriers and MARK adverse
excursions remain separate: this is not a simulated depth fill or a historical
liquidation engine. `compare_frozen` returns new baseline/candidate reports
without rewriting prior results. Per-contract nonoverlap filtering, exclusions,
daily groups and bias limitations are reported explicitly.

Realized distributions use already-net settled results exactly once and separate
symbol, policy, direction, regime, leverage and calendar month. They include
net/trade, profit factor, win/loss ratio, worst/tail losses and closed-P&L
drawdown. An approximate daily-cluster interval is unavailable below 30 trades
and 20 distinct daily clusters. Even above that threshold it is descriptive;
serial dependence, correlated markets and selected admission remain limitations.
Leverage cohorts are never pooled as independent evidence or turned into an
invented probability of future success.

### Personal account and backend fixes

The personal account adds an entry-only maximum book age of 20 seconds, with
two seconds of future-time tolerance. This is an engineering starting point,
requiring provider-age observation during validation. The gateway already
requests an uncached execution book; stale entries defer until a fresh
observation instead of reusing 38–48-second books. Entry age is checked both
before reservation and at dispatch. Protective SELL orders do not call the
new entry hook and retain their existing 90-second execution allowance.
No stale-book fill, synthetic liquidity or zero-data protective fill is invented.

Personal scan evidence, API orders and the dashboard expose quote age and
freshness. New order payloads trace modeled planned loss, its unchanged limit
and any excess. This explains `risk_rejected:planned_loss` without increasing
the limit. Existing rejection codes and historical orders remain unchanged.

The new personal profile is `4.9.9-paper.1` / execution policy `4.9.9-shared.1`.
It preserves the €7,000 account origin, database, positions and ledger.
Deployment does not silently revise the account: the existing paused, flat,
reconciled explicit profile-revision path remains required. While a frozen
profile differs, new entries suspend and existing protective monitoring remains.
No research strategy or ML weights are promoted into the primary account.

Shadow reporting now treats an absent winning SUM as zero only when a known
loss denominator exists (all-loss profit factor is zero), leaves no-loss and
empty profit factors unavailable, reports missing P&L separately, and returns
unknown drawdown when there are no usable equity observations. A new pinned
reporting/account-hook compatibility bridge retains the original V4.9.3 bridge
and original strategy/risk hashes. Its shared account hook is a no-op for
shadows. Frozen V4.2/V4.4 strategy sources are not modified. Bridge behavior
and protective recovery must be validated before deployment.

### Dashboard

Multi-coin status now distinguishes worker, scanner, feature and entry-control
state. It shows last-scan no-entry reasons, recent-window decision categories,
research hypotheses with decision/cutoff times and cohort economics, explicit
no-fill proxy provenance and separate realized distributions/sample sizes.
Counts are labeled as bounded recent windows, not all-time totals. Personal
Plan branding and paper-only identity remain.

## Persistence and release identity

No migration is added or executed. Existing append-only signal/event JSON and
the mutable scan cache accommodate the additive evidence. No account is
created, reset, renamed or funded by this implementation. Existing 17-account
financial inventory and balances were not accessed or changed. Existing BTC
perpetual records and the three V1 cohorts remain in their original storage.

Application, package and frontend metadata identify `4.9.9-rc.1` (`4.9.9rc1` in
Python package metadata). This is an unvalidated source candidate. No release
tag, package, image or deployment acceptance is produced by this task.

## Validation required before your deployment

1. Run the new `tests/test_v499_evidence.py`, existing multi-perpetual/accounting/
   personal/shadow/authorization regressions, type/lint checks, frontend tests
   and production builds, and Linux/AMD64 image identity checks.
2. Verify frozen V1 strategy/policy bytes, V2 source binding, bridge/package-data
   inclusion and all existing shadow compatibility/protective runners. Prove
   stale BUY rejection, fresh BUY acceptance and protective SELL availability
   independently, including restart recovery and delayed dispatch.
3. Reconcile the full 17-account financial set, current open exposure, source
   identities and backups using your existing deployment workflow. Do not use
   the capped private archive as a full restoration source. Do not cut over
   the personal profile while positions or intents remain open.
4. Validate matched-cohort refusal traces, immutable signal/review deduplication,
   source cutoffs, same-candle ambiguity, funding coverage and absence of
   double-counted costs. Check empty/all-loss/all-win/missing-aggregate views.
5. Keep V2 off initially. If enabling research, observe request budgets, quote
   ages, scanner fairness, stale-feature fallback, queue growth and protective
   loop latency. It adds no financial accounts or entry authority. Future V2
   fills require their own isolated accounting configuration and validation.
6. Replay frozen baseline/candidate reports only in your validation session,
   then collect genuinely prospective observations before assessing edge.
   Candle proxies cannot establish executable expectancy, completed 30-day
   performance, or future profitability.

Known limits: no code has been executed for validation; new regression sources
may need correction. V2 cannot place paper trades. The 20-second freshness
limit and V2 thresholds are not empirically calibrated. Daily-cluster intervals
are approximate, not calibrated forecasts. Last-500-settlement and recent-event
API windows are bounded samples. LAST/MARK/funding research is incomplete
without the caller's verified coverage and does not reconstruct historical
depth, intrabar order, adverse selection or exact liquidation paths.
