# StocksWatch paper execution reliability

This branch is a local implementation and review candidate. The running Aruba
services, database, timers, crypto workers, backend image, and configuration
were inspected read-only. Its local execution tests used disposable SQLite.

## Source provenance

- GitHub baseline `feature/autotrader-v46-intelligent-opportunity-engine`
  resolved to `201f8e98e1d09f695f7c433009c04a16cc49197f` after fetching.
  The local checkout was clean and one commit behind with zero local-only
  commits. The task-specific branch starts at the fetched commit.
- The user archive
  `stockswatch_running_source_review_20261106T051512Z.tar.gz` SHA-256 was
  `7bcc4ae569e3f59c9642a6e18b5cb80651961fbb4d42ccae1baa9ed3a98e7cbc`.
  Its ten `runtime/*.py` files matched the image at
  `/opt/stockswatch/stockswatch` by SHA-256. Compared with saved v1,
  `app.py`, `ledger.py`, `market.py` and `service.py` differed.
  `observer.py` existed only in the running set. Research, storage, signal
  scoring and package entry files matched saved v1.
- Frontend source came from
  `/opt/personal-plan/staging/integrations/stockswatch-scanner-monitor-20261105-v1/frontend`.
  The recovered source and lockfile built locally to the exact hashes of
  the deployed `index.html` and all 22 assets. The Nginx configuration hash
  also matched the image. The recovery commit keeps the StocksWatch and
  Scanner Monitor tabs, Perpetuals redesign, WorkspaceVisual, and the Gemini
  manual and automatic panels. The candidate changes the StocksWatch proxy
  to request-time DNS resolution to keep core-only frontends bootable. It
  retains the cookie and CSRF forwarding contract and the core session API
  remains the authentication authority.
- The backend patch in `deploy/stockswatch/gemini/backend-main.patch`
  reproduces staged `gemini-auto-20261105-v2/backend/main.py` when applied to
  the fetched core source. That staged file matched the live installed file
  at SHA-256 `c3b0b1c7ee4c5441e174a30a0e51053b375e2c3a56dfa4788d50757343ee7b44`.
  The recovered advisory module hash
  `354017f4bb414d20c1396f9a17ea19cfdfe167c67a91e1764d2efc40facb1215`
  matched both live containers. Gemini Auto matched at
  `fae7cfa4ab7f19c079ff1e9579e447dd028734be24106b10ddcfbfdb1d627b26`.
  The source-only overlay is available for future rebuilds. This candidate's
  image override keeps the running Gemini backend and the core Git sources.
- Recovery commit `4e77ebc005b5ed361e55e889d2319fa31ff1d34a` contains
  the recovered source before the execution changes.

| Running service | Verified image configuration ID |
| --- | --- |
| StocksWatch scanner monitor | `sha256:d5246b4190be6f2ec4c40f87e3037ca486419694e9ac3f7d86decc7d5bd07ff2` |
| Frontend scanner monitor | `sha256:92e09a772fa2cc1f9aad791046f36b7460ddb50be385943a2fc208ae1a4e3f81` |
| Crypto backend with Gemini Auto | `sha256:bb3497c4a0598255fabe3df71152265d7db35a711729ba35379653b7ac113b5c` |

## Read-only Aruba diagnosis

On **6 November 2026**, the latest observed scanner cycle ran from
**06:35:50 to 06:35:59 CET**. The configured Alpaca IEX provider succeeded
as recently as **06:35:57 CET**. All 32 symbols had price history and zero
source rows recorded a current error. The latest price session was November 5.
The most recent first-observation timestamp in the legacy price table was
November 5 at **23:44:52 CET**. Coverage was 50,476 rows from April 25, 2018
to November 5, 2026.

The effective database is `/stockswatch-data/stockswatch.sqlite3`, backed by
the existing writable bind mount from
`/opt/personal-plan/staging/integrations/stockswatch-20261105-v1-3/data`.
It reports `stocks-v1`. SQLite quick check and cash, shares, realized,
fill/order, and equity reconciliation passed. Cash and equity were
**$10,000 USD** with zero exposure and zero positions.

- **Zero BUY fills and zero SELL fills**, both lifetime and over the last
  30 published market sessions, September 25 to November 5. No last fill exists.
- **Five pending BUYs** from the November 5 signal day, approximately
  7.6–8.5 hours old. AAPL, MA, V, ABBV and COST had no later market-day row.
  There were 35 recorded decisions, comprising five BUY and 30 WATCH, and
  no canceled or expired orders. The legacy schema did not record per-gate
  rejection distributions.
- The direct cause of no fills at this audit was absence of the next session's
  observation. The audit took place before the next regular session opened.
  A provider failure or permanently stalled executor was not observed.
- Code inspection separately found unsafe paths. The running adapter
  requested daily bars through wall-clock now and persisted first-seen values
  with `INSERT OR IGNORE`. The running settlement used the next date's open
  without checking first observation time, quote or calendar. The queued
  daily admission counter was local to one invocation, which accounts for
  five same-day BUYs despite the apparent two-entry limit. Queue sizing
  counted pending SELLs toward BUY slots, and a paused account skipped
  fresh exits. The running executor did not recheck all position, gross and
  sector caps inside the fill transaction. The legacy worker reported
  `RUNNING` from successful HTTP acquisition alone.
- Docker reported one Python process and zero container restarts.
  `Service.loop` owns a periodic in-process scanner. `Observer` journals
  its stages rather than running a second poller. The old ownership was
  process-local and startup could initialize an empty ledger if pointed at
  the wrong mount. The candidate holds a nonblocking lock on the durable
  mount and requires an existing recognized ledger by default.

## Candidate execution contract

- Alpaca raw IEX daily bars are partitioned by New York market date. The
  XNYS calendar covers holidays, DST and shortened core sessions. The
  candidate waits until 00:15 New York time after the bar date. An IEX
  minute-bar check requires activity near the core close, and a corporate
  actions lookup blocks ambiguous share or cash changes. IEX is one venue
  and these checks cannot prove consolidated halt coverage or guarantee
  all events have arrived.
- The frozen score remains the signal model. Execution policy
  `stockswatch-eod-paper-v2.0` adds verified freshness, coherent 201-session
  history, time-stamped decisions, a deterministic rank and stable tie
  breaks. It reserves pending BUY capacity and admits at most two BUYs per
  signal day. The existing five-position, 12% symbol, 26% sector, 60%
  gross, 40% initial cash reserve and loss limits are checked in the
  write transaction. Sell exits can use an eligible symbol observation
  while new BUYs are paused or SPY is stale.
- `EOD_OBSERVED_PAPER` uses the next session's first eligible observed
  daily close, with 12 bps modeled adverse price friction per side and zero
  modeled commission. Observation, publication boundary, fill and signal
  times remain distinct. Late or pre-known prices cannot settle an order.
  Orders expire once the next core session starts after their target date.
  The candidate records an explicit cancellation outcome for a legacy
  pending order without forward evidence. Legacy orders, decisions and
  fills remain in their existing tables.
- Stooq is optional EOD research only. Malformed responses, HTML challenge,
  denied permissions and throttling are exposed and backed off. Configure
  `STOCKSWATCH_PRICE_PROVIDER=alpaca` and provision
  `STOCKSWATCH_ALPACA_KEY` and `STOCKSWATCH_ALPACA_SECRET` only on the server
  for market-data access. The app has no broker order code. The real
  configured endpoint returned HTTP 200 for IEX daily history, IEX minute
  history, and corporate actions in separate read-only probes.
- Corporate actions with ambiguous held share count or cash entitlement
  block valuation/execution for that symbol pending reconciliation.
  Automated share rebasing, cash dividends, ticker remapping and delisting
  liquidation require a verified event feed and accounting workflow.
  `FORWARD_PAPER_QUOTE` requires a separately validated, authorized quote
  feed with spread, session and halt support. This candidate is EOD-only.
- SEC official metadata and XBRL use a declared contact User-Agent. Gemini
  classifies verified SEC metadata with source URL, event/observation time,
  known and unknown evidence, risks, contradictions and uncertainty. It
  uses the existing shared 3/hour and 12/day atomic Redis quota with a
  StocksWatch 1/day cap and per-filing cache. It has no authority over
  signals or orders. FRED current values remain current context.
- The authenticated dashboard separates pending orders, terminal outcomes,
  certified observations, real paper fills and historical replay. It
  shows per-symbol reasons, cycle funnel, provider and scanner health,
  ledger state and last BUY/SELL. No outbound alert service is connected
  by this candidate.

Sources [Alpaca market data coverage](https://docs.alpaca.markets/us/docs/about-market-data-api),
[Alpaca daily aggregation](https://docs.alpaca.markets/us/docs/market-data-faq),
[Alpaca corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1),
[NYSE sessions](https://www.nyse.com/markets/hours-calendars),
[SEC fair access](https://www.sec.gov/about/privacy-information),
[SEC APIs](https://www.sec.gov/edgar/sec-api-documentation),
[ALFRED](https://alfred.stlouisfed.org/).

## Offline research

The prior deployed `research_runs` results are preserved. Its last stored
report contained 150 symbol/strategy runs using a next-open proxy at 15 bps
per side. The frozen ensemble's mean single-symbol return was 11.17% and
mean max drawdown 30.18%. Those figures have different mechanics from the
portfolio comparison below.

The offline comparison uses 778 aligned real IEX daily bars each for AAPL,
MSFT, JPM, V, XOM, CVX, PG, KO, CAT, UBER, SPY and QQQ from October 2, 2023 to
November 5, 2026. Warm-up was 252 sessions. The earlier interval was
October 2, 2024 to November 5, 2025. The fixed holdout was November 6, 2025 to
November 5, 2026. Holdout SPY gained 9.428% and QQQ 5.944% on a price-only
basis. The report includes input hashes, turnover, modeled dollar friction,
net P&L per candidate opportunity and closed trade expectancy.

| Policy | Earlier return at 12 bps | Holdout return at 12 / 30 / 60 bps | Holdout max drawdown at 12 bps | Closed trades at 12 bps |
| --- | ---: | ---: | ---: | ---: |
| Frozen score baseline | 4.145% | 9.055% / 8.342% / 7.153% | 3.494% | 16 |
| Sector-normalized relative strength | −0.696% | 8.152% / 6.994% / 7.059% | 3.201% | 33 |
| Uptrend pullback | 2.999% | 10.104% / 9.178% / 7.682% | 2.676% | 21 |
| Volatility and volume breakout | 0.792% | 7.063% / 6.267% / 5.592% | 2.043% | 9 |
| Regime-filtered mean reversion | 0.257% | −0.531% / −0.685% / −0.942% | 0.673% | 4 |
| SPY/QQQ and sector regime | 3.897% | 11.427% / 10.095% / 7.378% | 3.424% | 32 |
| Baseline entries with ATR and time exits | 3.195% | 9.506% / 8.146% / 5.577% | 3.266% | 34 |
| Challenger ensemble | 3.606% | 13.580% / 11.829% / 4.824% | 2.202% | 32 |

The pullback results warrant continued research given higher holdout returns
across the three friction assumptions, but were weaker than baseline in the
earlier period at 12 bps. The ensemble advantage reversed at 60 bps. The
sample uses current names and raw prices with gap vetoes, partial sector
coverage and no original publication timestamps, survivorship correction,
dividend accrual or measured spreads. The simulator uses a next-close
proxy and does not reproduce all production admission and data gates.
The frozen score stays authorized. Earnings surprise and post-earnings
drift are `INSUFFICIENT_SOURCE` without timestamped actuals and historical
consensus. There is no new ML promotion or model performance claim.

To reproduce with the same Alpaca IEX daily data, put one
`<SYMBOL>.research.json` per symbol in a private local input directory.
Each file is an ascending array of `[YYYY-MM-DD, open, high, low, close,
volume]` rows. `python -m stockswatch.challengers <input_directory>`
produces the bundled aggregate JSON. No vendor raw bars or databases are
stored in Git.

## Local verification and separately reviewed upgrade

- Install `deploy/stockswatch/requirements.txt` into the existing project
  test environment. Run `python -m pytest -q tests/stockswatch`. The
  startup/backfill/full paper round trip, atomic rollback, concurrency,
  restart, stale/pre-known data, caps, holidays, early close, DST, provider
  denial, authentication, quota and read-only audit checks use isolated
  data. Fixture fills are engineering evidence only.
- `cd frontend && npm test && npm run typecheck && npm run build` verifies
  the frontend. The image-only Compose override was validated against a
  local scoped fixture for service identity, mount and loopback ports. It
  changes only `stockswatch.image` and `frontend.image`.
- `python -m stockswatch.audit` verifies the fixed Aruba Compose identities
  and mount, reads only whitelisted Docker fields, then queries SQLite
  using read-only mode. With no sidecars it opens an immutable handle and
  rejects a changing snapshot. The command transfers code via stdin and
  returns aggregates and source hashes. It makes no provider or Gemini
  calls. Re-run after an unstable SQLite snapshot.
- Before any separately approved cutover, bind the full candidate Git SHA,
  manifest and Linux/AMD64 image IDs. Build and test with the exact
  inspected sidecar base and local frontend source. Confirm authenticated
  Nginx routes, core session and CSRF, data-only Alpaca scope, feed checks,
  ownership, unchanged crypto container image IDs, disk space and both
  loopback ports. The sidecar build uses the exact live base as a
  prerequisite and adds the pinned calendar package. The exact image and
  candidate AMD64 image were not available locally for runtime verification.
- Take and hash a consistent SQLite online backup on the VPS and verify an
  isolated restore. Compare cash, realized, shares, fills, decision and
  order counts, and schema. Coordinate a flat/no-working-order window or
  explicitly defer. Review legacy pending-order cancellations against the
  latest audit. Keep the bound database path and ownership, with
  `STOCKSWATCH_ALLOW_INIT` unset. Start just one sidecar. Its changes are
  additive tables. The crypto backend and workers stay out of the change.
- Keep the current StocksWatch and frontend images by their IDs. Reconcile
  after activation and after each naturally qualifying session before
  claiming deployed BUY/SELL fills. If rollback is required, stop the
  candidate writer and re-audit first. If there are candidate-era
  financial events or working orders, hold the writer and review before
  running a legacy executor against that ledger. Avoid restoring over
  newer financial activity. Keep verified backups and rollback images,
  avoid global cleanup, and remove only scoped artifacts after verification.
