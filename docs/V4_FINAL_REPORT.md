# V4 final engineering report

## 1. Implementation status

**PARTIALLY_COMPLETE_WITH_BLOCKERS**. V4 execution, research, allocation, AI mock/off, feedback, dashboard and dedicated research-worker paths are implemented and connected. Full-stack acceptance remains blocked by assessed PostgreSQL/Grafana security findings. Paper-only restrictions remain enforced. No strategy passed validation, approved IDs are empty, and no forced entries are permitted.

Implementation branch: codex/v4-execution-research. Current Python source commit ee272db; source fingerprint b31992258941962d61ee8bfaa7b38ea882a7f5449099ff78fb0045fc15e4966d. Evidence-only/build commits follow it.

## 2. Execution defects

Long buys walk asks; long sells walk bids. Stops compare executable bid, not midpoint. Targets require fee/slippage-adjusted net proceeds and a repository-enforced LIMIT IOC floor. Finite shared snapshot consumption survives restart; multiple intents cannot reuse its displayed quantity. Gap stops use available worse bid levels, partial fills preserve exact basis/target attribution, protective exits win collisions, and stale observations produce a durable waiting watch without invented fills. Cost/spread/depth filtering rejects entries while wide spreads alone cannot block protective exits.

Execution suite12passed; actual autonomous lifecycle verifies BTC cost rejection and ETH entry/TP1/partial TP2/restart/protective exit with five unique fills and exact reconciliation. See V4_EXECUTION_PRECISION.md, V4_MARKET_MICROSTRUCTURE.md and V4_TEST_EVIDENCE.md.

## 3. Financial regression results

Unchanged baseline80passed. Post-execution/data98passed. Final native Windows118passed, zero failures/skips,516.60s. Actual interpreter termination, API, immutable ledger/position identity, cash/basis, reservations, concurrent risk checks, recovery, migrations and equity-based halt tests remain included. Final installed-Linux118passed, zero failures/skips,445.74s. V4_TEST_EVIDENCE.md and both release JUnit artifacts retain actual PID and financial evidence.

Backup/restore preserves51journal events,19fills,6positions, cash499.110340421159 and schema0009_legacy_quarantine; independent reconciliation is empty. The original tracked SQLite blob remains b2b81065cd9f90c2d2f728cb3e5c8a7d6e424c31. User database/volumes were not reset.

## 4. Research datasets

Coinbase Exchange public GET candles, direct EUR: BTC,ETH,SOL,XRP,ADA,LINK,AVAX,DOT.48datasets contain76606bar records across six TF. Daily history is requested from2020-01-01 through2026-10-14; actual listing starts/unavailable intervals vary by asset. Hourly/4h cover2026-04-18 through2026-10-14. Intraday covers2026-10-13/14. No gaps or FX conversions were invented. Records across TF overlap and are not independent observations.

| TF | Actual records |
|---|---:|
| 1d | 16581 |
| 1h | 33596 |
| 4h | 7993 |
| 1m | 12968 |
| 5m | 3961 |
| 15m | 1507 |

V4_HISTORICAL_DATA.md lists all48actual counts/ranges/missing values. Raw cached responses, provenance and content hashes are local under .data/research; compact dataset evidence is committed.

## 5. Strategy results

Final full run research-20261015T205023 matches current source. Six hypotheses were evaluated on daily and4h with train-only finite grids, frozen choices, validation/test, purge/embargo, four walk-forward windows, cost stress, uncertainty and benchmarks. **NO STRATEGY PASSED VALIDATION**. No test-period retuning or profitable-strategy claim.

| Strategy | Daily OOS net EUR / closed | 4h OOS net EUR / closed |
|---|---:|---:|
| Trend pullback | -13.7885 /53 | -21.2079 /39 |
| Compression breakout | +3.5351 /2 | -8.0442 /9 |
| Breakout retest | -19.8174 /15 | +5.5781 /12 |
| Volume accumulation | +18.1586 /8 | -7.2273 /29 |
| Relative strength | +0.4681 /67 | -2.8868 /43 |
| Mean reversion | -0.0657 /2 | -10.2133 /8 |

Daily/4h validated ensemble: cash,0return. Positive isolated PnL fails sample/diversity/robustness gates and is not proof of edge. Full PF, drawdown, split dates, benchmarks and failure reasons are in V4_BACKTEST_RESULTS.md and JSON;623simulated fills and4260equity/drawdown rows are exported. Residual positions are disclosed as marks. Older studies are diagnostic. Historical holdouts were reused during engineering, not prospective never-seen trials.

## 6. Comparison to V3.4

| Axis | Established result |
|---|---|
| Execution realism | Improved: bid/ask, net floors, finite shared depth, gaps/stale data |
| Trading costs | Explicitly estimated and filtered; lower realized costs not established |
| Signal quality | Explicit causal eligibility replaces score-only admission; no validated edge |
| Regime adaptation | Observable point-in-time regime rules and vetoes; predictive benefit unproven |
| Allocation | Profiles/correlation controls added inside hard limits; superior returns unproven |
| Risk management | Original durability retained; durable protection and promotion gates added |

V3.4 signals on the common V4 historical execution model returned +5.9760EUR daily and -20.4754EUR4h. This is not a multi-year replay of the original durable application. No general V4 profitability superiority is established.

## 7. Security

Backend/frontend all-severity container scans, pip/npm audits and Redis high/critical scan are clear. Authentication cooldown is bounded and checked before credential comparison. Source secret/GET-only exchange/loopback audit passes.

Prometheus3.15.0 was rebuilt from a pinned upstream commit with checksum-verified official UI assets, Go1.27.2 and x/net0.60.0. Its high/critical scan is clear, and actual Compose config, embedded UI asset, API query and authenticated backend scrape up=1 passed. Compose selects the rebuilt image. Superseded official-image findings are retained.

PostgreSQL16 libxml2 CVE-2026-86140 remains1high package finding after fresh support-image rebuild. Grafana13.2.4 raw scan has2critical/14high unique CVEs;13unique CVEs remain unresolved after scoped Windows-platform/current-no-Tempo-server assessments. No silent suppression or unsupported exploitability claim. Exact packages, binaries, image IDs, fixes and dispositions: V4_SECURITY_REMEDIATION.md and evidence/v4-security-assessment.json. Optional monitoring remains stopped.

## 8. Deployment

Executed against isolated project autotrader-v34-acceptance, preserving its volumes:

```powershell
docker compose -p autotrader-v34-acceptance --env-file .tools/v34-test.env build backend worker migrate research-worker frontend
docker compose -p autotrader-v34-acceptance --env-file .tools/v34-test.env --profile research up -d --no-build backend worker frontend research-worker
.\.venv\Scripts\python scripts/verify_deployment.py --env-file .tools/v34-test.env --project autotrader-v34-acceptance --restart
.\.venv\Scripts\python scripts/verify_restore.py --env-file .tools/v34-test.env --project autotrader-v34-acceptance
```

Readiness, real PG/Redis, authentication/metrics, scanner, persistent controls, journal preservation and restore pass. Dashboard: http://127.0.0.1:13000; API: http://127.0.0.1:18000. Credentials stay in ignored private files. Final Playwright1test passed46.6s covering15pages, genuine queued research job, curves/trades, historical LIMIT replay and all controls; zero page errors. Ruff/mypy/TypeScript/Vitest pass. Exact Linux/runtime commands: V4_DEPLOYMENT.md. No remote VPS was deployed.

## 9. Remaining limitations

V4_KNOWN_LIMITATIONS.md lists all material limits: Coinbase proxy venue/survivorship/gaps; short intraday history; no historical L2/tick schedule/queue/latency; assumed OHLCV spread/liquidity/precision; separate deterministic simulation and durable runtime; reused holdouts and approximate dependence; residual marks/passive exposure differences; optional paid Sol access/AI predictive value/news edge unverified; per-process auth throttle; unarchived observation/feedback growth; job crash recomputation; unresolved support-image security. The empty ensemble is verified; a future nonempty optimized ensemble needs member-specific frozen-parameter replay. Production's exact source/timeframe/parameter/approval gate remains independent.

No live exchange order or paid AI request was submitted. No future profitability is guaranteed.

## 10. Exact next action

Remediate PostgreSQL16 libxml2 using a verified compatible fixed build/package while preserving SQL/XML and populated PG16 volumes; verify XML behavior, restart and isolated restore. Then obtain/rebuild patched Grafana bundled Go plugins, verify persistent login/dashboard/provisioning/queries, rescan exact images and rerun the security assessment. Keep monitoring stopped until clearance. Before any nonempty optimized ensemble claim, implement/test per-member frozen-parameter replay. Predictive research advancement requires more appropriate history and prospective validation; it is not achieved by forcing trades.
