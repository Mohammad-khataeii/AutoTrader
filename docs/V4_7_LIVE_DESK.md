# V4.7 live trader desk

The Overview, Opportunities, Activity and Decision Insights views now show **What the trader is doing** above the primary virtual portfolio. Open [Personal Plan](http://localhost:3000) and refresh once to load the new interface.

The desk shows the most recently saved candidate, its market/strategy and observation time, then a visual path through observation, technical setup, estimated costs, account decision and paper broker. Failed predicates are explained in ordinary language. A different saved candidate can be pinned for inspection; **Follow latest** returns to the newest evaluation.

The work timeline reads durable primary-account decisions, broker orders and fills from PostgreSQL. It refreshes every five seconds while the page is visible and supports All work, Candidates and Orders & fills filters. **Bought** and **Sold** appear only for persisted fill records. An accepted decision and a rejected order remain distinct. Historical evaluations retain their original times; refreshed connectivity never invents new trading events. Completed-candle strategies can legitimately produce no new decisions between candles.

The header shows scan age, position-monitor age and feed refresh age. If refresh fails or worker status becomes stale, it shows the last saved evidence with a waiting indicator. Only the connectivity icon pulses; the pipeline reflects recorded checks rather than a simulated sequence. Reduced-motion settings are respected.

## Implementation and data boundaries

`GET /api/personal-paper/activity` is authenticated and reads the existing isolated primary ledger in a PostgreSQL read-only transaction. It projects the latest 40 decisions with their original strategy evidence, the latest 20 orders plus orders linked to those decisions, and the latest 20 fills. The combined timeline is capped at 80 events; this is a recent-work window, not a complete history export. No schema, strategy parameters, market requests, financial journal, funding event, risk policy or execution identity changed.

The unchanged execution fingerprint is `fd20b6e6e61e5c775ff8bd62b3fc87095fa55c6ea7e0d290fb6209eb6a9c1e77`. Backend and frontend images were updated locally; the existing trading worker and research worker stayed running. Worker process identity/start time were checked before and after. The primary manifest is unchanged and reconciliation passes. The old frozen shadows still account for overall monitoring being Degraded.

The Mac had moved from its previous LAN address to `192.168.1.104`; the private local environment binding was corrected to that current address. Frontend remains available at `localhost:3000`, also on the current LAN address at port 3000. PostgreSQL/Redis, financial volumes and old rollback images were retained. No VPS access, migration, release tag or real order was performed.

An owned `caffeinate -i -w <Docker backend PID>` process prevents idle system sleep during the current Docker session while allowing display sleep. Its PID and Docker PID are recorded privately in `.tools/v47/live-desk-awake.json`. It ends with that Docker backend process. Manual sleep, lid closure, shutdown or Docker shutdown can still interrupt monitoring; this is not a boot-time launch service.

## Verification and actual evidence

- 15 focused primary-account lifecycle/read-model tests passed, including persistent rejection/fill separation, isolation and reopen behavior.
- 11 API/discovery/frozen-identity regressions passed, with one existing Starlette/AnyIO deprecation warning.
- 16 frontend unit tests, TypeScript/build, strict Mypy (104 Python files) and Ruff passed.
- Four desktop/mobile scenario-browser cases passed, including no-buy reasons, rejected order, BUY/SELL fill records and stale-feed handling. These use explicitly labeled test fixtures.
- Two read-only browser cases against the actual Mac server passed at 375px and 1440px, checking automatic refresh, candidate pinning, seven application areas, no horizontal overflow, no browser errors and no API mutations.
- Native ARM64 backend source matched the local source. The running worker’s execution fingerprint matched the active manifest. Existing financial lifecycle checks remain applicable; no new backup/restore claim is made for this display-only update.

Actual feed capture contains 40 decisions and one rejected order, with no prospective fills at capture. Equity remains EUR7,000. No profitability claim follows from the display or tests. Exact runtime values are in [runtime evidence](evidence/v4_7_live_desk/runtime.json); source identity and test counts are in [verification](evidence/v4_7_live_desk/verification.json).

[Actual desktop desk](evidence/v4_7_live_desk/actual-live-desk-1440.png) · [Actual mobile desk](evidence/v4_7_live_desk/actual-live-desk-375.png). Screenshots named `synthetic` show test fixtures and are separate from real prospective evidence.

All changes remain on `feature/autotrader-v46-intelligent-opportunity-engine`. The delivery receipt identifies the final pushed commit and immutable source package. Real-money execution remains disabled.
