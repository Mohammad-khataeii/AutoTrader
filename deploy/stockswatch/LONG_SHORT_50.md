# StocksWatch 50 equities and autonomous long/short paper execution

The release starts from `9403d79da5a0d592d51065eb5fc152ad2222e85f`. It preserves the previous 30 companies and adds the requested 20, with SPY and QQQ reserved for benchmarks. StocksWatch owns a separate SQLite schema. The upgrade adds tables and instruments, preserves existing enabled states and account history, and shares the existing worker lock, Alpaca paper account, kill switch and uncertain-order reconciliation across all three strategies.

## Universe and history

The registry records expected instrument type, name, sector and strategy participation. Broker verification checks the active US equity asset identity, exchange and tradability, using the authenticated paper host. Broker eligibility and history are separate evidence. If a listing fails verification, it stays visible with a reason and cannot receive new broker orders under the affected gate. The local release cannot validate real listings without configured credentials. No substitute instrument was selected. [52-instrument verification report](UNIVERSE_50_VERIFICATION.md)

The live scanner requests all 52 instruments in at most 32-symbol REST batches with explicit feed, bounded pagination and no WebSocket subscriptions. Entries require a complete snapshot universe, both benchmarks, and 42 valid observations by default. Set `STOCKSWATCH_INTRADAY_REQUIRE_ALL_VALID=1` to require all 52. SIP is required for execution. Basic IEX can continue monitoring with single-venue labeling. Existing EOD long eligibility still requires a certified raw IEX window of 201 consecutive XNYS sessions with completed-session publication and corporate-action checks. New companies additionally require recent asset verification and the current EOD check before entering the ranking.

Use a disposable or authorized, offline SQLite path. The CLI takes the same writer lock as the service. Report mode opens an existing SQLite file read-only. Actual backfill and asset verification use GETs and the configured credentials in the caller's environment.

```sh
python3 -m stockswatch.backfill --new-universe --dry-run --minute-days 20
python3 -m stockswatch.backfill --db "$STOCKS_HISTORY_DB" \
  --new-universe --verify --feed iex --minute-feed sip --minute-days 20
python3 -m stockswatch.backfill --db "$STOCKS_HISTORY_DB" \
  --new-universe --resume --feed iex --minute-feed sip --minute-days 20
python3 -m stockswatch.backfill --db "$STOCKS_HISTORY_DB" --report
python3 -m stockswatch.directional_research --db "$STOCKS_HISTORY_DB" --feed sip
```

Omit `--minute-feed sip` when SIP is unavailable. Request `--adjustment split` or `--adjustment all` separately for research. Daily archives request up to ten years in bounded partitions. Minutes default to 20 eligible days across the full universe and are retained for 30 sessions in the **new historical archive**. Raw, adjusted, IEX and SIP series have separate keys. Page tokens and latest accepted timestamps are committed with each page. GETs respect retry headers within a bounded request budget. The background worker processes one page per 120-second loop and refreshes asset inventory every six hours, separately from broker and intraday locks. Set `STOCKSWATCH_HISTORY_BACKGROUND=0` to suspend the background job. Existing price and journal tables retain their prior semantics. Historical timestamps, receipt times and corporate-action events are stored separately. No historical bar supplies a live executable quote.

## Actions and risk

| Application intent | Alpaca side | Ownership required |
|---|---|---|
| `BUY_TO_OPEN_LONG` | buy | Flat symbol, fresh long admission |
| `SELL_TO_CLOSE_LONG` | sell | Confirmed EOD or intraday long fill trail and available shares |
| `SELL_TO_OPEN_SHORT` | sell | Flat symbol, verified margin account, fresh ETB and restriction checks |
| `BUY_TO_COVER_SHORT` | buy | Confirmed `sws1-` short opening and cover fill trail, available shares |

Legacy `swp2-` and `swx1-` identities remain valid. New short IDs use `sws1-`. A same-symbol conflict, unexplained fill, unavailable ownership, unknown POST outcome or ambiguous broker state fails closed. Shorts reduce signed inventory. Long P&L is `(exit − entry) × qty`, and short P&L is `(entry − cover) × qty`. Reported costs are shown separately. Unavailable broker charges and financing remain unknown. Aggregate broker realized P&L is unavailable when Alpaca does not return it. StocksWatch shows separately attributed FIFO price P&L from verified fills.

The short strategy requires a bearish gap and a support breakdown or failed rebound, weak relative momentum against SPY and QQQ, sector context, persistence, adequate turnover and spread-adjusted payoff. It competes with the long strategy after exit checks. The default extra long edge floor is zero bps and the short net edge floor is 35 bps. The two documented settings are `STOCKSWATCH_INTRADAY_LONG_MIN_EDGE_BPS` and `STOCKSWATCH_SHORT_MIN_EDGE_BPS`. Threshold changes belong in a reviewed configuration. Gemini cannot place or size orders.

Each short entry rechecks paper account status, shorting permissions, margin configuration, Reg T buying power, live asset identity and borrow status. Legacy `easy_to_borrow` is used only when the current `borrow_status` field is absent. An HTB locate, recall, explicit restriction or reported chargeable borrow blocks new entries. The conservative Rule 201 check requires complete SIP regular-session minute coverage for the prior and elapsed current session, regular-close references, and avoids declines of 8% or more. Opening sell limits are above the observed bid and never marked short-exempt. This proxy does not certify official restriction status or quote stability. The broker remains responsible for routing restrictions. [Alpaca short-selling requirements](https://docs.alpaca.markets/us/docs/margin-and-short-selling) · [Asset schema](https://docs.alpaca.markets/us/reference/get-v2-assets-1) · [Account configuration](https://docs.alpaca.markets/us/reference/getaccountconfig-1) · [SEC Rule 201](https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions-7)

Short caps are 3% of equity per symbol, 10% gross short notional including reservations, two opening attempts per trade date and 0.25% modeled loss under a 6% adverse move. Shared position count, gross and sector caps, cash buffer, and non-marginable buying power also apply. Short proceeds are excluded from long-entry cash. Collateral uses at least a 50% modeled requirement or the higher broker asset value. Account drawdown and broker limits can further reduce capacity. When the pinned short capability is configured, the 2% daily-loss latch applies across entries. A master paper pause still stops all new submissions. Disabling the short entry flag alone leaves eligible protective covers enabled when the separate proof, common authority and master control remain valid.

Short execution is core-session only, with whole-share DAY limits. An adverse +1.5% move, favorable −2.5% move, 75-minute age, reversal, loss/exposure breach, missing ETB or recall can request a cover. The worker stops new shorts and starts trying to flatten 30 minutes before the calendar close. It requests cancellation of aged or closing-window opening orders once and waits for broker terminal confirmation. Manual orders and externally opened inventory remain outside its authority. Stale or unavailable quotes, fractional remainders, a halt, data/broker outage, corporate action or unfilled limit can leave short exposure overnight. The software thresholds are decision triggers and do not cap realized loss. Accepted orders remain at Alpaca after a master pause.

## Research and acceptance

The walk-forward runner uses five development sessions to derive a momentum threshold and disjoint two-session evaluation blocks. It compares long-only, short-only, combined and intraday momentum proxies plus two short cover variants, and attaches the existing EOD ensemble report when present. It reports net returns, turnover, drawdown, exposure time, profit factor, volatility, tail losses, regime breakdowns and squeeze/overnight-gap stress. Outcomes use next-open OHLC prices and hypothetical friction. They lack historical ETB, depth and executable fills, and the current universe is survivorship-biased. The actual local report is `INSUFFICIENT_DATA` because no Alpaca history was available to this checkout. Offline fixtures verify the replay mechanics and produce no production edge evidence.

```sh
PYTHONPATH=.:src python3 -m pytest -q tests/stockswatch
(cd frontend && npm ci && npm run build && npm test)
python3 deploy/release.py prepare --ref HEAD --output deploy/releases/stockswatch-50
```

The local Docker socket timed out during both Linux AMD64 image build attempts. Build from the extracted manifest-verified source on a working local AMD64 builder, using the pinned approved StocksWatch base image and exact source revision. The Dockerfiles and image commands are in the [previous operator guide](EXTENDED_HOURS_PAPER.md). Candidate image IDs, actual broker/entitlement and history verification, and target read-only rehearsal are outstanding.

## Scoped cutover and shared frontend compatibility

Use the current scoped StocksWatch Compose definition and recorded container/image identities. Keep the same `autotrader-aruba-stockswatch` project, existing SQLite bind, ports, network aliases, credentials and paper account. Preserve the crypto backend, collector, volumes, shared authentication, TLS and other services. The historical scoped helper's initial-install path rejects an already populated project. Use an approved replacement of only the scoped targets. Before replacing anything, pause, reconcile open orders and ambiguous outcomes, verify a SQLite backup/restore and preserve the rollback images. The backup helper verifies the legacy ledger and seals the broker and directional fill tables when present.

Build the shared frontend separately from its **verified deployed source revision**. The StocksWatch branch has older crypto views. Do not use its raw frontend image as a replacement for the shared dashboard. The stock-only overlay was tested in a detached checkout of crypto branch commit `fb9d577db5a7c63001fef4beb1a3330242045153`. It adds the StocksWatch view files, route and isolated authentication handling, leaving the crypto view files intact. The integrated frontend built and passed its 21 tests. For a source that already includes StocksWatch, manually merge the same small surface because the script refuses to overwrite it.

```sh
python3 deploy/stockswatch/frontend_overlay.py \
  --stocks-frontend "$VERIFIED_STOCKS_SOURCE/frontend" \
  --shared-frontend "$VERIFIED_SHARED_FRONTEND_SOURCE/frontend"
```

Review the combined diff, rerun all frontend tests, smoke-test crypto navigation, session isolation and the StocksWatch API proxy, and package the integrated source as a distinct reviewed commit and image. This release does not establish the identity of the currently running shared frontend.

Ship the first candidate read-only. Short entry requires `STOCKSWATCH_SHORT_ALLOW_ORDERS=1`, a read-only mounted `STOCKSWATCH_SHORT_PREFLIGHT` file, its SHA-256 in `STOCKSWATCH_SHORT_PREFLIGHT_SHA256`, and the existing pinned SIP intraday authority. The short proof must name `stockswatch-short/1`, the exact image-embedded source commit, `paper_only: true` and actual PASS evidence for `native`, `frontend`, `linux_amd64`, `offline_broker`, `read_only_rehearsal`, `account_short`, `etb`, `history` and `sip`. Keep activation off until these pass. A later approved server configuration can enable autonomous orders without approving individual decisions.

For rollback, disable short entries first, reconcile outstanding intents and ensure existing strategy-owned shorts are safely handled before replacing the worker with an older image. Restore the prior scoped application configuration and frontend image while preserving the current SQLite database. Use a verified financial backup for disaster recovery only after reconciling subsequent broker activity. Keep open-position protection and operator control in view throughout.
