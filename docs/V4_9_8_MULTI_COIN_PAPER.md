# V4.9.8 — independent multi-coin leveraged paper engine

This is local development based on `5630a70b1cc40a60b81235c28c1a305dff9b87a7`, preserving both pre-existing local commits and the V4.9.7 research path. No server, running account, deployment, exchange credential, or real order was accessed. The new feature defaults off and entries default paused. There is no claim of positive expected value or demonstrated trading profitability.

## End-to-end behavior

`dashboard asset identifiers → paginated USDT contracts → broad public tickers → fair detailed analysis → deterministic hypothesis + cost/risk qualification → durable collateral reservation → new public depth snapshot → atomic simulated fill → independent protective monitoring → captured exit proxy → complete funding → reconciled settlement`.

`MULTI_USDT_MICRO_PAPER_V1` owns new virtual 1×, 3× and 10× cohorts of 1,000 USDT each. These allocations are not transferred from, or substituted for, the old BTC experiment or any EUR account. Matched opportunities are evaluated for all three cohorts; if a cohort fails qualification, the matched opportunity is rejected. Quantity can differ because margin constraints differ. Cohorts are not three independent samples of market edge.

## Modules and isolation

- `perpetuals/multi/policy.py`: immutable experiment identity, policy fingerprint, cohorts, fees and risk limits.
- `contracts.py`: instrument and risk-tier contracts, leverage/quantity validation, tier-aware maintenance and liquidation mathematics, and immutable entry metadata.
- `market.py`: hard-coded public GET endpoint allowlist, full instrument/risk pagination, separate HTTP pools, bounded caches, provider cooldown and protective request priority.
- `scanner.py`: dashboard base-asset mapping, cheap full-universe summaries, liquidity/cost/range prioritization and fair revisit slots.
- `strategies.py`: four independent, versioned, completed-data entry hypotheses.
- `economics.py`: conditional target/stop proceeds, break-even movement, cost buffers and risk-based cohort sizes.
- `models.py` and `ledger.py`: independent state, immutable signal records, append-only journal, collateral, durable intents, atomic fills/exits, leases, reconciliation, recovery and read projections.
- `runtime.py`: distinct scanner, monitoring and ownership-renewal tasks; forecast review and persistence.
- `api/perpetuals_multi.py`: authenticated snapshot, paginated history and entry-pause/resume endpoints using the existing authentication/CSRF dependency.
- `frontend/src/MultiPerpetuals.tsx`: market scanner, recent matched opportunities, open positions, cohort accounts, paginated journal and measured outcome summaries.

The legacy BTC engine, BTC state format, BTC migration stream, V4.9.7 previews, primary spot execution and 15 shadows retain their identities and accounting. The existing perpetuals worker optionally starts the independent runtime; no new service is required. If the new schema is absent, it logs that condition and leaves the BTC task running. The new migration never runs automatically during worker startup.

## Universe and discovery

Only identifiers cross the spot/perpetual boundary. All persisted trading-pair base assets and all rows of dashboard `raoe_discovery` are considered; explicit `-EUR` suffixes are parsed as identifiers. EUR prices, signals, quantities and indicators are not execution inputs.

The Bybit instrument catalog is paginated until its cursor is empty. Repeated cursors or the explicit 100-page safety budget fail closed, rather than treating a partial first page as the entire universe. Only actively trading, standard, non-prelisting USDT linear perpetuals are eligible. Settling/quoted currency, market sessions, delisting status, quantity steps, minimum and maximum size/notional, price ticks and leverage rules are checked. Missing, ambiguous and pegged mappings are reported.

Mapping uses the exact published base asset. A multiplier contract such as `1000PEPE` is not silently interpreted as `PEPE`; a future explicit, validated unit mapping is needed. This can exclude otherwise available contracts and is reported as unsupported rather than fabricating equivalence.

Stage A obtains all linear tickers in one request. Liquidity and spread dominate ranking. Timed summary-mid ranges become available after successive observations; otherwise a capped 24-hour range proxy is explicitly labeled. A small, capped change in rolling 24-hour turnover can affect priority, but is not called executed short-window volume. Large positive price changes do not receive an unconditional ranking bonus.

Stage B inspects at most six markets per scan with concurrency two, retrieving complete one-minute candles, completed 3/5/15-minute context, risk metadata, mark/ticker data and public depth. Half the slots rotate through least-recently-inspected eligible markets. Failures still count as visits, and rotation state survives scanner restarts and temporary failed scans. Under healthy scheduling the fair revisit bound is approximately eligible-market count divided by three scans, not a promise that every asset gets expensive analysis every minute.

Instrument metadata is cached for five minutes, contract risk metadata is bounded to 256 entries, and completed candle windows to 128. Requests are limited to about five per second with up to eight protective grants before a waiting scanner gets one slot. Provider rate-limit responses initiate a shared cooldown. Protective traffic has a separate connection pool and task; scanning cannot hold its HTTP pool or ledger transaction while awaiting market requests.

## Strategy selector

All four strategies are explicitly experimental deterministic hypotheses. They use real completed price/volume inputs when eventually run, with no invented probabilities, trained model or automatic strategy rewriting.

| Policy | Entry hypothesis | Specific exit/invalidation |
| --- | --- | --- |
| `MULTI_CONTINUATION_V1` | Efficient, persistent directional trend; 3/5-minute agreement, acceleration and controlled micro pullback; avoid extended or unstable moves; confirm relative volume | Stop/target/time plus two completed adverse post-entry candle bodies |
| `MULTI_COMPRESSION_RETEST_V1` | Narrow consolidation relative to broader completed range; an earlier break, subsequent retest and reclaim; sufficient remaining room | Stop/target/time plus completed closes failing the saved structure |
| `MULTI_RANGE_V1` | Repeated range extremes in low-efficiency, stable conditions; rejection at the edge with room toward midpoint | Stop/midpoint target/time, failed structure or repeated adverse bodies |
| `MULTI_FAILED_BREAK_REVERSAL_V1` | Failed up/down excursion, two closes back inside structure, confirmed opposite acceleration; avoid strong persistent trends and volatility spikes | Stop/target/time and recapture of the invalidation structure |

A source forecast retains its reference, target, stop, decision time, completed cutoff, feature hash, regime, policy and holding budget. Signal consumption keys use symbol + policy + cutoff, so a provider candle revision cannot replay a previously consumed decision. Technical structure must support at least 0.5% remaining movement; targets are capped at 1% and checked again after tick rounding and at the fresh fill quote. No minimum target is forced when structural room is absent.

Among technically eligible strategies, selection compares the worst cohort's conditional net target/planned-loss ratio. It does not rank unobserved expected returns or prefer leverage for its own sake. `expected_net_pnl_usdt` and win probability remain unknown. A scenario-qualified deterministic hypothesis may enter this isolated virtual experiment to collect outcomes, as requested; it does not acquire official strategy approval or prove positive expectancy.

## Economics and fill causality

Fees remain a versioned 0.06% each way and residual slippage 0.05% each way. Visible bid/ask spread and full-size depth VWAP are included once; spread is not added twice. Planning adds an explicit ATR-per-minute latency stress and solves the long/short fee-adjusted break-even price equation. This buffer is planning risk, not an extra invented cash fee. Exit liquidity is modeled from the current opposing book; actual future depth is unknown.

The current public [instrument specification](https://bybit-exchange.github.io/docs/v5/market/instrument), [risk tiers](https://bybit-exchange.github.io/docs/v5/market/risk-limit), [order-book snapshot](https://bybit-exchange.github.io/docs/v5/market/orderbook), [ticker](https://bybit-exchange.github.io/docs/v5/market/tickers) and [settled funding](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) schemas informed the adapter. No live public-market requests were used as acceptance tests in this task.

Plans first pass size and net-scenario checks. A database transaction then consumes the immutable signal, reserves each cohort's collateral and records order intents. Only after that transaction commits is a new book requested. Full-size quotes must be post-intent, fresh and within a three-second intent deadline. Marketable depth, quantity increments, bounds, stop/target geometry, remaining movement, leverage, account exposure, fresh existing-position values, funding horizon, fee-adjusted loss and liquidation buffers are requalified atomically at fill time. All cohorts fill together or the reservation is cancelled/expired. Price revalidation failures record a missed opportunity and release the collateral.

Public depth is not guaranteed exchange liquidity. Entries and ordinary exits are labeled `LIVE_OBSERVED_POST_INTENT_DEPTH_PROXY`, not actual exchange executions. No private endpoint is supported and no real exchange credentials are read. Residual execution slippage is separately recorded, without confusing it with observed spread/depth or adverse gap stress.

## Risk, monitoring and settlement

The maximum planned loss is 0.5% of current cohort equity per trade. Sizing is not increased to make account returns imitate leverage. A 12% free-collateral sizing target and 50%-of-equity asset sizing target leave room for multiple coins; hard guards remain 25% trade margin, 40% aggregate margin, 1,000 USDT per asset, min(2× equity, 2,000 USDT) aggregate notional, three concurrent positions/reservations, and at most 1× equity in one directional crypto cluster. All crypto is conservatively treated as correlated. Aggregate planned risk is bounded and existing asset stacking is rejected. A 10% peak drawdown latches a cohort halt.

Contract risk tiers and maintenance deductions are snapshotted per entry. Margin rate units must agree with the reciprocal initial-margin/max-leverage relation; ambiguous data rejects the contract. Maintenance and liquidation are solved using the contract's tier, deduction and closing-fee reserve, instead of BTC constants. Protection uses the more conservative of stored and current maintenance requirements. Missing or changed metadata can trigger a risk exit rather than silently changing the saved contract.

Monitoring remains active with new entries paused. It compares current mark and wholly post-entry completed mark/trade bars; liquidation precedes a stop, and stop evidence precedes a favorable target. Entry-partial candles are excluded. If an outage reveals a prior stop/liquidation breach, settlement can use an adverse OHLC stress proxy at the current exit observation time, explicitly labeled as hypothetical stress, rather than claim a historical executable fill. An unresolved path is labeled a reconnect proxy and does not establish what happened inside missing intervals. This uncertainty, sampling between requests and lack of tick-level history are material limitations.

Exits themselves use a durable intent before a new depth request. A known exit observation is persisted immediately. If funding history is missing, price/time stay frozen and collateral remains unavailable while settlement waits. Restart cannot reprice that captured exit to a more favorable later market. Funding pagination recovers all supplied events, verifies the position's saved schedule, uses signed long/short transfers and an event-time mark proxy, and deduplicates each position/timestamp. Funding schedule changes or missing events block financial settlement; they do not become zero cost. The funding mark proxy is the preceding completed minute's close, not an exact exchange settlement print.

Cash, isolated collateral, reserved entry funds and closed P&L reconcile after every mutation. Independent journal cash totals are also checked. PostgreSQL row locks, generation predicates, unique signal/event keys and worker leases serialize ownership. PostgreSQL triggers make events and signals append-only. SQLite `BEGIN IMMEDIATE` is used only by isolated development checks. A restart reloads positions and pending funding, expires old entry intents, and resumes unexpired intents only with a new valid quote. Pausing cancels reservations but leaves positions protected. No balances or financial history are reset.

Normal exit settlement adds signed gross P&L and funding, subtracts actual modeled entry/exit fees, releases collateral and records net return using the correct margin/account denominators. A gap can exceed planned risk. Liquidation forfeits isolated collateral under this model; the difference from uncapped P&L is an explicit settlement adjustment. Venue insurance, ADL, insurance-fund fees, partial liquidations, queue dynamics and actual exchange tier implementation are not reproduced.

## Evidence and dashboard

The Perpetuals screen now includes the new workspace as well as the unchanged BTC lab/research panels. It shows all mapped scanner rows, unsupported reasons, source scan counts and freshness, scenario-qualified opportunities and cohort plans, open positions, margin/notional/fees/funding/slippage, correct ROI denominators, liquidation distance and drawdown. Entry controls affect only this experiment and require a fresh scan and healthy monitor. Unprovisioned/disabled states show no invented funded account balances.

History is authenticated and paginated; original entry, close, missed, rejected and forecast-review evidence stays available, including losses and gap adjustments. Per-coin/policy/cohort performance displays actual totals from the last 500 settlements with that scope labeled. This is a recent evidence window, not an all-history performance claim.

Each eligible and rejected deterministic forecast is saved once. Later reviews use only whole completed candles after the decision became available and before the horizon ends. They compare saved target/stop/movement with observed paths; ambiguous target/stop bars are treated conservatively. Reviews are explicitly hypothetical with no fill or executable-profit claim. Actual settlements retain reason, signed movement, margin/account return, fees, funding, adverse/favorable excursions and whether the loss exceeded planned risk. Regime-classification accuracy stays unknown without independent labels. Outcomes do not rewrite policies or promote ML weights.

## Migration, compatibility and verification boundary

The additive `alembic/perpetuals_multi` stream owns `paper_multi_schema_version`, `paper_multi_state`, `paper_multi_events`, `paper_multi_signals` and `paper_multi_scan`. It does not update the spot `alembic_version` or old BTC tables. Its downgrade refuses to discard populated financial history. Only the migration test's temporary local SQLite database was migrated; no running database was touched.

The backup helper source now includes the optional new tables in consistent seals and read-only restore reconciliation whenever they exist. Existing 17-ledger discovery, funding records and backup retention remain intact. This code was not deployed or invoked against server backups.

Local checks: focused synthetic/mocked-provider and temporary SQLite tests cover margin/risk math, long/short plans, net returns, matched atomic fills, concurrent duplicate attempts, expiry, pause protection, cash-journal reconciliation, multiple symbols, funding direction/pagination/missing-data holds, independent migrations, authenticated API gating/history, full scan-detail-to-monitor settlement wiring, ambiguous gap ordering and strategy-specific exits. Frontend TypeScript checking also passes. These are engineering checks, not historical or prospective market performance.

Before any deployment, verify PostgreSQL triggers, row locking and crash/migration recovery in an isolated PostgreSQL environment; realistic provider limits, timestamps, full catalog coverage and funding schedule changes; conservative latency/depth and market-data outages; independent backup/restore with populated new tables; browser presentation; Linux/AMD64 image/source identity; rollback with preserved financial history; and prospective paper outcomes across coins/regimes. A separately approved release remains required. No deployment, live migration, server access, real orders, model training or profitability claim was made.

## Recorded local results and working-tree delivery

- `PYTHONPATH=src python3 -m pytest tests/test_v498_multi_perpetuals.py -q`: **28 passed**. All market inputs were fixtures/mocked responses; financial state was temporary SQLite, not any running account.
- `frontend/node_modules/.bin/tsc --noEmit -p frontend/tsconfig.json`: passed.
- `git diff --check`: passed.

No backtest, model training, image build, remote command, deployment, production migration, commit, push or tag was performed. The existing development branch and HEAD `5630a70b1cc40a60b81235c28c1a305dff9b87a7` are preserved. The branch was already two commits ahead of its remote before this work; these source changes are delivered uncommitted. Candidate package/API/frontend identifiers are aligned at V4.9.8-rc.1; this does not create an approved immutable release.

Modified files:

- `.env.example`
- `deploy/staging_backup.py`
- `docker-compose.yml`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/src/Perpetuals.tsx`
- `pyproject.toml`
- `src/autotrader/__init__.py`
- `src/autotrader/api/main.py`
- `src/autotrader/api/perpetuals.py`
- `src/autotrader/perpetuals/worker.py`
- `tests/test_v492_learning.py` (the expected API version only; that PostgreSQL-dependent test was not run)

New files:

- `alembic/perpetuals_multi/env.py`
- `alembic/perpetuals_multi/versions/0001_multi_paper.py`
- `docs/V4_9_8_MULTI_COIN_PAPER.md`
- `frontend/src/MultiPerpetuals.tsx`
- `src/autotrader/api/perpetuals_multi.py`
- `src/autotrader/perpetuals/multi/__init__.py`
- `src/autotrader/perpetuals/multi/contracts.py`
- `src/autotrader/perpetuals/multi/economics.py`
- `src/autotrader/perpetuals/multi/ledger.py`
- `src/autotrader/perpetuals/multi/market.py`
- `src/autotrader/perpetuals/multi/models.py`
- `src/autotrader/perpetuals/multi/policy.py`
- `src/autotrader/perpetuals/multi/runtime.py`
- `src/autotrader/perpetuals/multi/scanner.py`
- `src/autotrader/perpetuals/multi/strategies.py`
- `tests/test_v498_multi_perpetuals.py`
