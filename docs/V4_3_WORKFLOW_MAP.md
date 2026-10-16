# V4.3 workflow inventory before implementation

Baseline:4df605687aeb54d24f70e511f6d8e8dc5ff9dcec, immutable v4.2.0. Backend fingerprint9f03f481049165cba9b54082d6f45f6e06e76d4b0a1625832b5f8434f8ace23a. Work is frontend-only on feature/autotrader-ui-simplification; no SSH, production mutation or tag replacement is authorized.

Public production inspection: the HTTPS page serves the existing Revolut X AutoTrader login with username/password and Sign in. No production login was attempted; authenticated production state was not fetched. The four production experiment IDs and three-B2/one-A2 composition are user-supplied requirements, not newly observed financial data. Acceptance fixtures will identify themselves as synthetic and will never be posted to production.

| Existing workflow | New location | Contract retained |
|---|---|---|
| Login/logout | Login and account menu | Basic auth, credentials in memory, no persistent storage |
| Command Center/account KPIs/chart | Overview | GET overview/system; selected account history only |
| Market Scanner and Opportunities | Overview activity; Advanced → Market monitor | GET scanner; real candidates/rejections/features retained |
| Autonomous Decisions/transitions | Trades details; Advanced → Decision journal | GET history; no generated explanations |
| Portfolio/Position Management | Trades → Open positions/details | Official positions/targets and shadow detail history; no financial aggregation |
| Order History/fills | Trades → Trade history/details | All available orders/fills, correct account association |
| Execution Quality | Trades details; Advanced → Execution diagnostics | GET execution; freshness/partial-depth uncertainty retained |
| Strategy Lab/comparison | Research default and Advanced Research → Historical lab | GET research/artifacts/promotions; configurable jobs, history, costs, walk-forward, benchmarks retained |
| Backtesting Lab | Advanced Research → Replay | GET/POST backtests; explicit action, actual run evidence |
| Trade Failure Explorer | Advanced Research → Trade diagnostics | Existing filter/detail endpoint, limits and provenance disclosed |
| Opportunity Intelligence | Advanced Research → Opportunity outcomes | GET intelligence; hindsight limits retained |
| AI Intelligence/budgets | Advanced → AI & budgets | GET ai; quotas/pricing/spend not changed |
| Risk Center/recovery | Advanced → Risk & recovery | GET settings/history, POST risk/recover with confirmation |
| System Health/market diagnostics | Advanced → System & data health | GET system/market-data/health; actual failures visible |
| Paper Pilot/JSON/CSV | Advanced Research → Paper pilot; Advanced menu shortcut | Existing explicit start, reports and CSV; frozen history retained |
| Shadow Trading Laboratory | Experiments cards/details | Existing registry, immutable identities, state rules, per-domain equity, history and all five exports |
| Official start/pause/resume/stop/emergency | Advanced → Official Account Controls | State-valid controls only; high-impact confirmation; approval gate unchanged |
| Settings | Advanced → Settings | Read-only backend settings and technical disclosure |

Fetching plan: shared in-memory per-auth cache, in-flight deduplication, sequential completion-based timers and explicit invalidation after actions. Only mounted/current sections subscribe; hidden pages stop polling. Overview/system refresh periodically; shadow registry is the existing full-detail response because no lightweight endpoint exists. Research/history/execution/AI/settings/intelligence/backtests load only when used, retain cached results and disclose refresh errors/staleness. Browser background visibility suspends polling. No backend contract changes.

Safety plan: four retained slots includes stopped accounts; never show a create action at capacity. Creation requires explicit review of irreversible slot use. Active→Pause, paused→Resume, stopped→no resume; permanent Stop is secondary and confirmed. Official controls and pilot starts are explicit and confirmed. Current price/open P&L require a verifiably timestamped valid mark; otherwise Unavailable. No fabricated timestamp, trade, data-quality state, or specificity beyond a recorded rejection.

The existing regression scenarios will be adapted to the new navigation, retaining authentication, full exports, controls, research job completion, historical replay, pilot and real API/worker lifecycle assertions. New fixtures cover four retained IDs, duplicate B2 strategies, unavailable marks, failed refresh, no automatic mutation, deduplicated polling and four viewport sizes.
