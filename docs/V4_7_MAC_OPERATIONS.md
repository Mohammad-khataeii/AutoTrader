# Personal Plan V4.7 on the Mac

Use the existing `autotrader-v46-mac` Compose project, native ARM64 images, persistent PostgreSQL/Redis/research volumes and local ports 3000/8000. The VPS and its project are outside this release. Keep the Mac awake, online and Docker Desktop running.

The private `.env.local` selects the verified image tag. Do not display or commit its credentials. Normal scoped operating commands, from the repository:

```sh
docker compose -p autotrader-v46-mac --env-file .env.local \
  -f docker-compose.yml -f docker-compose.mac.yml --profile research ps

docker compose -p autotrader-v46-mac --env-file .env.local \
  -f docker-compose.yml -f docker-compose.mac.yml --profile research \
  up -d --wait --no-build --no-deps backend worker frontend research-worker
```

Mac overrides enable `PERSONAL_PAPER_ENABLED=true`; the production default remains false. The worker creates exactly one `PERSONAL_PLAN_PAPER_7000` account in a deterministic separate PostgreSQL database, registered by an immutable `personal_paper_v47` manifest in the official database. It uses the existing versioned migrations and shadow identity marker. Existing accounts are neither refilled nor reset. Funding is EUR7,000 once, shared by the selected A3/B3/E3 strategies. Shadow comparison balances never enter that equity.

Five-second protection, ownership renewal, approximately one-minute scans and bounded five-minute discovery share the existing priority scheduler and cache. Fresh executable books are required for every fill; discovery has bounded time/request budgets. Restart recovery resumes persisted intentions and consumes each strategy/candle at most once after a durable outcome. Hourly reviews retain evidence and propose research; they never change active parameters or authorize another strategy.

Risk defaults are frozen in the experiment manifest: EUR700 position cap, EUR35 planned stop risk, EUR140 aggregate stop risk, EUR2,100 crypto-cluster and per-strategy capital caps, EUR2,800 minimum reserve, six positions, 24 entries/day, EUR140 daily/EUR350 weekly loss limits and 10% drawdown halt. The crypto-cluster cap is deliberately conservative when pairwise correlation estimates are uncertain. It is currently more restrictive than the separate EUR4,200 overall exposure ceiling. Stop risk is an estimate; gaps can lose more. Pausing entries preserves protection. Emergency closes execute only against fresh available bids, so network outages can delay them. Risk halts need reviewed recovery and cannot be cleared by repeatedly pressing Resume.

API: `/api/personal-paper` returns financials, broker activity, strategy attribution, live diagnostics and hourly review; `/api/personal-paper/research` serves separate historical evidence. Authenticated pause/resume/emergency routes only affect this account. The Personal Plan Overview, Opportunities, Strategies, Activity, Research and Decision Insights display its distinct evidence. Old official/shadow views remain available below it.

The primary runtime and costs are pinned. Changing execution source suspends new entries while exits continue; do not overwrite its manifest to bypass this boundary. Existing V4.6 shadow manifests similarly retain their source identities; this update does not silently rewrite their histories or upgrade their strategies. Required previous images must be retained for a separate compatible-runner continuation.

`deploy.financial_set.discover` includes the primary database as well as all retained shadows. For consistent local backup sets, stop only this project's writing services, create and checksum custom-format dumps, verify a restore into a separate internal Docker network, then resume services. Never restore over newer financial transactions or remove volumes. The generic production restore verifier remains strict about execution compatibility; preserving a historical ledger does not authorize it on new code.

Financial fills, journals, decisions and research evidence are retained. Per-cycle request work and dashboard tables are bounded; financial audit storage still grows with operation and requires monitored disk/backups. No automatic deletion of financial history, global prune or volume reset is configured. The first release does not implement a passive queue simulator, USD/FX ledger, authenticated read-only data adapter, autonomous parameter-search deployment, or verified real-exchange adapter. EUR public observations suffice for current operation. These limitations remain explicit in the release report.

## Recorded runtime correction

The first forward identity, `4.7.0-paper.1`, retained one naturally triggered PEPE BUY rejection. The ledger had priced its planned loss using the highest ask anywhere in the observed book. The corrected `4.7.0-paper.2` uses the side-aware quote for the quantity the IOC can actually consume, at both reservation and dispatch. Instrument, freshness, fee, exposure and loss gates remain in force.

The correction used an explicit paused, flat, reconciled cutover. The original account marker and manifest remain unchanged. An immutable revision is stored both in the primary database and the official registry, with a parent hash and a distinct active-profile pointer. Signals, decisions and fills identify their execution profile. There is still one EUR7,000 funding event and one shared financial account. Old outcomes are retained; no history or parameters were rewritten. `scripts/v47_activate_revision.py` requires an expected parent-profile hash and an explicit Mac invocation. Worker startup never creates a new revision automatically. Changing source without a new reviewed version continues to suspend entries.
