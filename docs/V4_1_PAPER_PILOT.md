# Prospective 30-day paper pilot

The pilot capability is prepared; a real 30-day observation period has **not** been
completed. Starting a pilot is explicit through the dashboard Paper Pilot page,
`POST /api/pilots` with an idempotent request_id, or:

```sh
autotrader-pilot start --request-id prospective-20261016
autotrader-pilot list
autotrader-pilot report --pilot-id PILOT_ID --output reports/pilot.json
autotrader-pilot report --pilot-id PILOT_ID --day 2026-10-16 --format csv --output reports/day.csv
```

Run the command in the configured application container/environment. Export commands
check schema compatibility; they do not silently migrate user data. HTTP report
exports are authenticated and support JSON/CSV. No pilot is automatically started by
deployment.

Pilot IDs, start/planned end, initial actual valuation, source/config fingerprints,
strategy members, source dataset versions, costs and safe runtime settings persist
in PostgreSQL `system_state`. Each scan records a prospective snapshot referencing
the existing paper account and operating state. Market candles, features, signals,
decisions, orders, fills and incidents remain in their existing authoritative tables.
No second financial ledger is created.

A pilot without approved strategies runs in RESEARCH_ONLY mode. Approved deterministic
strategies remain subject to every financial and research gate. Source, selected
members, costs or relevant configuration changes interrupt the comparison rather
than silently replacing the frozen manifest. Missing observations and restart gaps
remain visible. Daily UTC summaries are generated after midnight, including missed
dates after recovery. A 30-day elapsed window is distinguished from adequate coverage.

Reports use actual snapshots, journal postings, fills, decisions and incidents:
starting/ending observed cash/equity/exposure, net and realized P&L, fees, modeled
slippage, observed spread costs, closed trades and win rate, partial-exit posting
statistics, drawdown over observed marks, strategy contribution, rejections, gaps,
AI usage and estimated/confirmed spend. Missing equity is unavailable, never zero.
Observation gaps are not asserted to be measured process downtime.

Cash, BTC and ETH benchmarks use separate EUR 500 capital references. BTC/ETH require
at least two genuine new completed candles within the pilot interval, with modeled
entry/exit fees, spread and slippage. Missing benchmark history remains explicitly
unavailable. Passive references have different exposure and are not allocation
recommendations. One positive month would not establish long-term edge or statistical
significance; negative outcomes remain in the ledger/reports.

Engineering simulations require a separate database and carry
SYNTHETIC_ACCEPTANCE / EXCLUDE FROM FORWARD PERFORMANCE labels. ENVIRONMENT=test
cannot target the ordinary production PostgreSQL database name. The production
research policy refuses a test acceptance bypass on the production paper database.
Synthetic and real-market results are not combined.

Tests: `test_pilot_freezes_configuration_reports_actual_cash_and_separates_synthetic`
executes start, idempotency, snapshot, cash-only report, restart and incompatible
configuration interruption using isolated PostgreSQL. It does not establish an
actual elapsed prospective period. Database administrators are trusted; ordinary
application paths expose no account reset or live-money execution.

During browser acceptance, an explicit local RESEARCH_ONLY pilot started at 2026-10-16T05:39:21Z, with planned end 2026-11-15T05:39:21Z. It records genuine public-data observations and intentional local acceptance outage/restart gaps. It is not a remote VPS pilot, and thirty days have not elapsed. The acceptance scanner is capped at three symbols; the normal configurable default is eight.
