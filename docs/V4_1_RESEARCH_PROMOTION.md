# V4.1 research promotion and parameter consistency

The six V4 strategies and two defensive filters remain the registry in
`src/autotrader/research/strategies.py`. Application version is 4.1.0; unchanged
strategy mathematics retain strategy version 4.0.0. No scalping strategy or live
exchange adapter was added.

`workflow.run_full` freezes training-selected parameters separately for each
strategy. Each candidate contains strategy ID/version, canonical parameter JSON
and SHA256, source fingerprint, dataset fingerprint, run ID, actual timeframe,
cost-assumption hash and validation decision. The simulator's `member_parameters`
requires an exact set of members; fills carry the selected member's parameters.
Both provisional and intersected ensembles, and the matched rules/mock comparison,
reuse these frozen choices. A separate V4 runtime-default benchmark is explicit.

The persistent lifecycle uses `system_state` candidate projections and append-only
application-created `system_incidents` transition records:

`RESEARCH_CANDIDATE -> RESEARCH_REJECTED`, or
`RESEARCH_CANDIDATE -> RESEARCH_PASSED -> AWAITING_APPROVAL -> PAPER_APPROVED -> PAPER_ACTIVE -> PAPER_SUSPENDED`.

Research success does not approve trading. The authenticated promotion endpoint
`POST /api/research/promotions/{candidate_id}` requires an explicit decision and
reason. The original `APPROVED_STRATEGY_IDS` interface records a durable operator
approval only for a compatible waiting candidate. It cannot revive a suspension.
An explicit subsequent review is required. Rejected and incompatible candidates
cannot be approved even with a valid administrative login.

`configure_research_policy` imports genuine completed reports and suspends source,
version, parameter, dataset/run or execution-assumption incompatibilities. It runs
at startup and every scan. The scanner records policy rejection before execution.
The accounting repository independently checks identity, actual signal timeframe,
exact frozen parameters and actual fee/slippage assumptions under the account lock
both on admission and pending BUY dispatch. Protective exits remain available.
`BreakoutStrategyEngine` reuses approved member parameters, and `DecisionEngine`
selects risk/target parameters from the same strongest eligible strategy used for
accounting attribution. No global score substitutes for validation.

No approved strategy means `NO VALIDATED STRATEGY` / `RESEARCH_ONLY`. Data ingestion,
signals, rejection records, health, reconciliation and protective monitoring remain
active. Research reports are content-addressed and source-bound; a changed source
requires a fresh matching study. A mismatching prior report is diagnostic only.

Tests: `test_v41_promotion_operations.py` exercises daily/4h refusal, explicit 5m
approval, restart persistence, manual suspension, failed research and parameter,
source and cost mismatch. `test_v4_research.py` exercises exact member replay,
missing-member refusal and causal five-minute decisions. Actual financial process
acceptance remains a separate isolated PostgreSQL test, never research evidence.

The candidate projections and incident records are durable application records;
there is no cryptographic signature or external approval authority. Database
administrators remain trusted. No production force-trade endpoint was introduced.
