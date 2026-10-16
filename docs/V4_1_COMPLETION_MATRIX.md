# V4.1 completion matrix

Overall: PARTIALLY_COMPLETE_WITH_BLOCKERS. Allowed statuses describe demonstrated scope, not profitability. Evidence paths below are relative to docs/evidence; implementation paths are relative to the repository root. Python source fingerprint `e0140ff18c36d86ac4c676e07aa650c2d93bac3fcfa6b708e0025f6573d66c5e`.

| Requirement | Implementation / runtime invocation | Executed test/check and actual result | Evidence | Status | Remaining limitations |
|---|---|---|---|---|---|
| M1 / P0 existing baseline | Existing financial/research modules; pytest before edits | 118 passed on realPG15; clean2033c7b baseline | v4_1-baseline.xml; V4_1_BASELINE_AUDIT.md | END_TO_END_VERIFIED | Earlier-machine V4 artifacts not reused as current proof |
| M2 / P1 genuine intraday | research/data.py, cli.py → research download/availability |48 datasets,351788 observations,0 acquisition failures;12data tests | v4_1-datasets.json; v4_1-data.xml | END_TO_END_VERIFIED | Sparse no-tick gaps retained; Coinbase proxy |
| P1 immutable/resumable storage | atomic datasets/coverage/raw-page cache → ingest_incremental | checksum/duplicate/UTC/incremental/crash-resume tests pass | test_v4_data.py; final148JUnit | INTEGRATION_TESTED | Cache needs disk monitoring/off-host backup |
| M3 / P2 six 5m strategies | workflow.py → research evaluate --timeframes5m15m |6strategies×2TF,allfailvalidation;833 closedpositions,2204fills exported | v4_1-research-results.json; V4_1_FIVE_MINUTE_BACKTESTS.md | END_TO_END_VERIFIED | No positive edge; historical dates reused during engineering |
| P2 causal features/liquidity | panel.py, indicators.py, simulation.py → completed-prefix features/priorvolume |future-volume, unfinished-higher-candle and future5m mutation tests pass | test_v4_research.py; finalJUnit | INTEGRATION_TESTED | Completed four-primary-bar context; no claim of independent4h join |
| P2 chronological statistics | workflow.py → training/validation/test/walk-forward, strict gates |frozen grid,12bar purge/1bar embargo,bootstrap/gates/stress executed | research manifest/results/curve/group exports | END_TO_END_VERIFIED | Independent dates approximate dependence; no untouched holdout claim |
| P2 asset/regime/period diagnostics | simulation groups + export_v41_diagnostics.py |135group details,24monthlyperiods,833 closedpositions; actual cost/attribution | gzipCSV + exportmanifest | INTEGRATION_TESTED | Group curves commonEUR 500 contributions; no unsupported groupCI |
| M4 / P3 ensemble exact parameters | simulation member_parameters → workflow ensembles → strategy engine |exact-member mismatch/parameter effect regressions pass | test_v4_research.py; finalJUnit | INTEGRATION_TESTED | Empty genuine approved ensemble; nonempty acceptance is synthetic |
| P3 durable promotion | research_policy.py → worker refresh → account-locked admission/dispatch |explicitapproval/timeframe/source/suspension/restart/failedcandidate tests pass | test_v41_promotion_operations.py; finalJUnit | INTEGRATION_TESTED | Any source change requires matching new research |
| P3 zero approved | scanner/worker/API/dashboard → RESEARCH_ONLY |actualrunningdeployment NO VALIDATED STRATEGY,cash500,zeroorders | v4_1-runtime.json; browser screenshot | END_TO_END_VERIFIED | Legitimate cash holding; not a broken scanner |
| P3 isolated acceptance | config + research policy productionDB guard → test fixture worker |actualentry/targets/restart/exits pass; testdatabase guard passes | v4_1-lifecycle.xml; test_config.py | INTEGRATION_TESTED | Administrators trusted; acceptance never forward evidence |
| M5 / P4 daily/hourly quotas | ai_budget.py PGaccount lock → reserve/submit |30/31,6/7,rollingexpiry,concurrency/restart/calendar tests pass | v4_1-quotas.xml; finalJUnit | INTEGRATION_TESTED | Actual paid provider not exercised |
| P4 monthly budget/billing | migration0010, durablehold/settle/reconcile → AIprovider |USD 10 hold checks,unknown/duplicate/overbound/reconcile tests pass | test_v41_quotas.py; safety/finalJUnit | INTEGRATION_TESTED | External invoice guardrail limits explained; unknown holds need evidence |
| P4 event selection/cache/risk reserve | ai_events.py, ai.py → dedup/cached/provider |mock/OFF/schema/timeout/event/riskcapacity tests pass | test_decision_ai.py; test_v4_ai_security.py; finalJUnit | INTEGRATION_TESTED | No predictive AI contribution established |
| P4 production pricing/access | config/AIprovider → verifiedprice + modelretrieval |safeconfig/tests pass; mockruntime | V4_1_AI_QUOTAS.md | IMPLEMENTED_UNVERIFIED | Real entitlement/prices/billing not tested; no paidcall authorized/needed |
| M6 / P5 single worker/retry | operations.py + worker/runner.py →15slease/5srenew |ownerclaim/fence/crashprocess tests; outage recovery pass | finalJUnit; dependency-recovery.json | END_TO_END_VERIFIED | No independent supervisor of unhealthy live process |
| P5 cadence/states | scan60s/position5s → persisted metrics/operation state |actualworker/positionheartbeats,RESEARCH_ONLY,recoveredPG | runtime/deploymenthealth | END_TO_END_VERIFIED | Targets not SLA under rate limits/hostsleep |
| P5 outages | PGtransaction/leasefailclosed; Redisoptional → scopedstop/start |Redisunavailable+APIready;PGreadiness503;recoverledger | v4_1-dependency-recovery.json | END_TO_END_VERIFIED | Localcontrolledoutage; not remotechaostest |
| P6/P12 pilot infrastructure | persistence/pilot.py → POST/api/pilots, autotrader-pilot, dashboard |configfreeze/idempotency/syntheticseparation tests + browseractualobservation/export | finalJUnit; v4_1-runtime.json; browser | END_TO_END_VERIFIED | Only localshortprospectiveRESEARCH_ONLY observations |
| P6/P12 actual 30days | frozen prospectivepilot → daily reports |Startedlocalpilot;30dayshaveNOTelapsed | V4_1_PAPER_PILOT.md; runtimepilotreport | BLOCKED | Requires genuineelapsedtime/coverage; nopositiveperformanceclaim |
| M7/P7 PostgreSQL security | Dockerfile.postgres + local upstream backport |selected image: zero high/critical findings; patched bounds test + vulnerable negative control, XML/extensions/restore/restart pass | v4_1-postgres-final.sarif; backport functional/runtime/provenance | END_TO_END_VERIFIED | Local backport maintenance; destination-architecture verification required |
| P7 Grafana security | quarantined-monitoringprofile → stopped |fullscan21distinctCVEs(2 critical/19high);notrunning | v4_1-grafana.sarif; securityreport | BLOCKED | Patchedbundledplugins/runtime+functionalrescanneeded |
| P7 source/auth/secrets/network | sharedPGauththrottle,GET-onlyclient,privateenv/loopback |sharedAPIthrottle + anonymous401 + secret/exchangemethodchecks pass | source-security.json; browser/finalJUnit | END_TO_END_VERIFIED | RemoteTLS/firewall/hostnotverified |
| M8/P8 isolated deployment | compose + deploy/vps.py → scopedbuild/up/verify |localPG16core/researchworkerhealthy;portsprivate;reconcileempty | deploymenthealth/runtime | END_TO_END_VERIFIED | DockerDesktopaarch64,notuserUbuntuVPS |
| P8 populated migrations | Alembic0010 → migrationrun |V4→V4.1hold/historypreservation passes onPG16 | test_v41_migration.py; safety/Linuxrepairs | INTEGRATION_TESTED | Noautomaticdestructivedowngrade |
| P8 backup/restore | vps.py → binarypg_dump/checksum/newDBrestore |archivesparsed;isolatedrestore;emptyreconciliation;originalunchanged | backup-restore.json; upgrade.json | END_TO_END_VERIFIED | Privatebackupsneedsecureoff-hostcopy |
| P8 upgrade/rollback/restart | vps.py retainedimages + verifier --restart |actualupgrade/rollback/fullrestartpass,journal/controlpreserved | upgrade/rollback/deployment-restart.json | END_TO_END_VERIFIED | Schema-changingrollbackrequiresreviewedseparaterestore |
| P8 actualUbuntuVPS | deploy/vps.py + documentedremotecommands |NoSSHhostprovided;notdeployedremotely | V4_1_VPS_DEPLOYMENT.md | BLOCKED | Inventory,host/TLS/firewall/restart/destinationimagescanrequired |
| M9/P9 dashboard | React16pages → authenticatedFastAPI |browser16pages,researchjob,LIMITreplay,controls,quota,pilotexports pass49s | v4_1-playwright.json; screenshots | END_TO_END_VERIFIED | Denseevidencetables;existingbundlewarning |
| M10/P10/P11 financialacceptance | existingbroker/gateway/ledger/targets/risk → actualprocesses |148 final native + 148 final installed-Linux pass; five-fill lifecycle | finalJUnit/Linuxrepairs/lifecycle | INTEGRATION_TESTED | Synthetic financial fixture is not evidence of predictive edge |
| P17 paperonly/capital/risk | config/gateway/accounting → startup/admission/dispatch |EUR 500,noreset,nolivepath;lossthreshold/concurrency/recoverytests pass | finalJUnit; source-security/runtime | END_TO_END_VERIFIED | Read-onlyrealexchangedata;nomoneyorders |

Independent outcomes: engineering passes in the tested local scope; research evaluation is complete and rejects every candidate; local isolated deployment/recovery is verified, remote deployment is blocked. Required security and elapsed-pilot work prevents COMPLETE_AND_VERIFIED.

## Named regression mapping

Module names above are relative to `src/autotrader` unless a repository-level path is written. Export/verification commands live under `scripts`; deployment commands under `deploy`. These exact pytest node names are present in both final148-case JUnit suites (zero failures/errors/skips):

| Requirement | Executed named test |
|---|---|
| P1 storage/incremental integrity | `tests/test_v4_data.py::test_incremental_extension_reuses_verified_coverage_and_crash_pages` |
| P2 causal liquidity | `tests/test_v4_research.py::test_entry_liquidity_does_not_see_future_bar_volume` |
| P2 higher-timeframe boundary | `tests/test_v4_research.py::test_unfinished_higher_timeframe_candles_cannot_change_historical_confirmation` |
| P2 historical decisions | `tests/test_v4_research.py::test_five_minute_decisions_do_not_change_when_future_candles_change` |
| P2 insufficient statistical evidence | `tests/test_v4_research.py::test_no_trade_or_tiny_sample_cannot_pass_validation` |
| P3 frozen members | `tests/test_v4_research.py::test_ensemble_uses_exact_frozen_parameters_and_refuses_missing_members` |
| P3 promotion lifecycle | `tests/test_v41_promotion_operations.py::test_explicit_approval_timeframe_restart_and_durable_suspension` (5m and15m cases) |
| P3 failed research | `tests/test_v41_promotion_operations.py::test_failed_research_never_approves` |
| P3/P17 acceptance separation | `tests/test_config.py::test_acceptance_cannot_use_production_paper_database` |
| P4 daily quota | `tests/test_v41_quotas.py::test_daily_thirty_then_reject_thirty_first` |
| P4 rolling/concurrent/restart quota | `tests/test_v41_quotas.py::test_rolling_hour_concurrency_restart_and_exact_expiry` |
| P4 UTC/calendar boundaries | `tests/test_v41_quotas.py::test_utc_day_and_calendar_month_boundaries_keep_rolling_hour` (parameterized dates) |
| P4 monthly/overrun guard | `tests/test_v41_quotas.py::test_monthly_budget_and_provider_cost_bound_violation_fail_closed` |
| P4 unknown billing/reconciliation | `tests/test_v41_quotas.py::test_duplicate_unknown_billing_holds_and_audited_reconciliation` |
| P4 material-event cache | `tests/test_v4_ai_security.py::test_persistent_event_cache_singleflight_and_material_change` |
| P4 protected risk capacity | `tests/test_v41_quotas.py::test_portfolio_review_capacity_is_protected` |
| P5 coordinator fencing | `tests/test_v41_promotion_operations.py::test_single_coordinator_and_old_owner_financial_fence` |
| P5 provider outage/protective intent | `tests/test_v4_execution.py::test_provider_outage_records_watch_without_fabricated_fill` |
| P5 stale data | `tests/test_v4_execution.py::test_stale_protection_durable_critical_watch_then_fresh_exit` |
| P6/P12 pilot freeze/separation | `tests/test_v41_promotion_operations.py::test_pilot_freezes_configuration_reports_actual_cash_and_separates_synthetic` |
| P7 shared authentication throttle | `tests/test_v41_promotion_operations.py::test_shared_login_cooldown_across_two_api_instances` |
| P8 populated migration | `tests/test_v41_migration.py::test_v4_to_v41_preserves_existing_ai_holds_and_financial_history` |
| P10/P11 full lifecycle | `tests/test_v4_lifecycle.py::test_v4_real_worker_cost_rejection_partial_targets_restart_and_api` |
| P10/P11 targets/restart/stop | `tests/test_v34_acceptance.py::test_proof_a_targets_survive_actual_worker_restart_and_stop` |
| P10/P11 equity halt | `tests/test_v34_acceptance.py::test_proof_b_unrealized_equity_halt_survives_process_restart` |
| P10/P11 concurrency/idempotency | `tests/test_v34_acceptance.py::test_proof_d_concurrent_buys_idempotency_and_sell_race` |
| P17 immutable finance | `tests/test_v34_acceptance.py::test_journal_and_fills_are_immutable_in_database` |
| P17 live trading disabled | `tests/test_config.py::test_live_trading_cannot_be_enabled` |

Research results, browser actions, image scans and deployment recovery have their separately executed commands/artifacts in the main table; they are not inferred from these unit/integration node names. Security/remote/elapsed-period blockers remain as stated.
