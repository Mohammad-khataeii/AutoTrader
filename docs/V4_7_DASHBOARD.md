# Dashboard, coin charts and refresh-safe sign-in

[Open Personal Plan](http://localhost:3000). **Dashboard** is the default page and combines the primary €7,000 paper account, market charts and the live trader desk. The previous official/shadow overview remains under **Settings → Accounts overview**.

Dashboard shows portfolio value and total return, original budget, available cash, cumulative spending on buys including fees, current marked investment, reserved cash, all execution fees, holdings, realized/unrealized results and actual filled buys/sells. The official €500 account and historical shadows are excluded from these totals. The live desk appears once on Dashboard; other research and account tools remain accessible.

Spending and sale proceeds aggregate the complete financial journal linked to BUY/SELL fills, with buys including fees and sales net of fees. They use posted ledger amounts, preserving the ledger’s decimal precision. The recent-fill table remains bounded to 80 records; that display limit does not truncate totals. Current holdings use fresh recorded midpoint marks and show unavailable values when marks are stale. Cumulative spending can exceed the starting budget when cash is reused after a sale.

## Coin charts

Select a coin in Markets, holdings, the fill table or the live trader desk to open its chart. The chart supports 1H, 6H and 24H ranges, candlesticks or closing-price lines, hover/keyboard OHLC inspection and timestamps. Mobile uses a horizontal coin selector and a responsive chart.

The authenticated chart endpoint reads the existing primary account’s saved five-minute Revolut X candles. It performs no exchange request and does not compete with protective market-data requests. Only closed candles are included, duplicate observations are resolved to the latest persisted row, and missing intervals remain visible as gaps. A partial window and the latest saved candle time are disclosed. This is recorded market history, not a streaming tick feed or a promise of current executable prices. Empty history appears only after the query finishes; loading data is not presented as zero holdings or no trades.

## Sign-in persistence

The previous sign-in lived only in React memory, which refresh discarded. Sign-in now exchanges Basic credentials for a signed, seven-day, host-scoped HttpOnly cookie with SameSite=Strict. HTTPS sessions also use Secure. The local Mac app currently serves HTTP. The password is not saved to localStorage/sessionStorage. On refresh the app verifies the existing cookie and restores the workspace; temporary server unavailability offers retry without presenting a false sign-out.

Cookie-authenticated writes require a CSRF proof returned by the session endpoint and retained in memory. Existing Basic-authenticated API clients remain supported. The research job UI now uses the shared authenticated client, including CSRF headers. Sign-out clears the browser cookie, and refresh after sign-out stays signed out. Password changes invalidate existing signatures; expired sessions return to sign-in. Sessions survive backend restarts while the configured credentials remain the same. Closing the app or refreshing does not stop the trading worker.

An existing tab from the earlier memory-only version needs one sign-in to establish the new cookie. Subsequent refreshes preserve that session for its lifetime.

## Verification and operations

- 24 focused backend tests passed: primary account lifecycle/isolation, exact journal cash-flow identity, closed-candle deduplication/gaps, API/discovery regressions, signed-session tampering/expiry/password rotation, restart restoration, CSRF and sign-out.
- 19 frontend unit tests passed; TypeScript/build, strict Mypy across 106 Python files and Ruff passed.
- 27 scenario/browser regressions passed across the Dashboard, financial presentation, legacy account tools, live desk and responsive layouts.
- Two browser cases against the actual persistent Mac server passed at 375px and 1440px. They verify real charts, coin switching, session restoration after reload, HttpOnly/SameSite cookie attributes, successful sign-out after reload, seven navigation areas, no browser errors or horizontal overflow, and no financial API mutations. Session login/logout are the only explicit API mutations in these cases.

The running native ARM64 backend source matches the locally tested source. No strategy, risk, execution identity, schema or financial history changed. The active execution fingerprint remains `fd20b6e6e61e5c775ff8bd62b3fc87095fa55c6ea7e0d290fb6209eb6a9c1e77`. The same trading-worker process stayed running throughout the backend/frontend update. PostgreSQL, Redis, research worker, volumes, backups and rollback images were retained. The Mac idle-sleep guard remains active for the current Docker session; manual sleep/shutdown or stopping Docker still interrupts operation.

No VPS access/deployment, release tag or real exchange order occurred. Main and the existing RC2 tag remain untouched. Work stays on `feature/autotrader-v46-intelligent-opportunity-engine`; the delivery receipt supplies the full pushed commit and immutable package identity.

## Real prospective activity

The unchanged autonomous worker has now generated genuine prospective paper BUY and SELL fills from Revolut X observations. ENA and INJ entries and their exits are shown in the actual fill table. These were not injected by UI tests. The completed positions lost money; this update establishes no profitability claim or real-money authorization. The timestamped [runtime snapshot](evidence/v4_7_dashboard/runtime.json) records the exact activity, cash flow, equity and reconciliation at capture. Values continue changing after capture.

The overall header still shows Degraded because the preserved old A2/B2 shadows have incompatible frozen source identities. The primary account’s health, monitor and reconciliation are reported separately. Charts depend on saved worker observations and can show older/partial history. Clearing cookies or session expiry requires sign-in again.

[Actual desktop Dashboard](evidence/v4_7_dashboard/mac-live-dashboard-1440.png) · [Actual mobile Dashboard](evidence/v4_7_dashboard/mac-live-dashboard-375.png). Files named synthetic/acceptance contain test fixtures and are separate from actual prospective activity.
