# V4.5 trade gate investigation — Stage A release candidate

Production was inspected on 17 October 2026 using read-only SSH diagnostics, public market configuration, PostgreSQL read-only snapshots, logs and existing GET endpoints. No production service was restarted, source patched, configuration changed, account created, experiment stopped/archived, manifest rebound, migration run or financial record changed by this work. Real-money trading remains disabled.

## What production actually contains

The API reports V4.4.0. Backend and worker use image `sha256:b6c4c62383c1b05ebd468164cf3bac5a55a41641b79300192d82ba15a269e019`. Every execution source file matches baseline `ab742ee56c4774fb9a7b111f1f1043575f1743c9`; the installed `__init__.py` alone still reports V1.0/1.0.0. API/application provenance and execution identity are recorded separately in the evidence.

The prompt's registry snapshot is outdated. All four original V4.2 experiments are STOPPED and were already archived at approximately 21:01 UTC on 16 October. Their databases, funding journals and manifests remain present. Four replacement native V4.4 experiments occupy the four slots: B2 `40f3f370…`, A2 `dc1edd63…`, C2 `baac318a…` and E2 `b97173b5…`. These changes predate this investigation; this release does not undo them.

Production reports every original and replacement account compatible and reconciled. The worker/scanner heartbeat is fresh, the latest scanner evaluated BTC/ETH/SOL, and the official account remains subject to research approval. Requested coverage is 24 hours, but replacements have only about 11 hours of recorded lifetime. Snapshots were taken separately while the worker continued; counts are bounded to the exported observations, not an atomic cross-account cut.

## Actual causes and unresolved evidence

Each replacement has 411 captured decisions. Counts distinguish eligibility, accepted decisions, allocation, execution invocation, orders and fills.

| Active strategy | Eligible signals | Accepted BUY decisions | Main independent failures | Actual first blocking stages |
| --- | ---: | ---: | --- | --- |
| B2 | 0 | 0 | previous breakout 405/411 (98.54%); higher trend 363/411 (88.32%); breakout volume 339/411 (82.48%) | higher trend 363; previous breakout 48 |
| A2 | 6 | 4 | higher trend 363/411; previous-high reclaim 293/411; EMA9 recovery 286/411 | higher trend 363; EMA9 35; previous high 4; candle recovery 3; D2 veto 2; four downstream outcomes unrecorded |
| C2 | 0 | 0 | See strategy-specific condition counts in attribution evidence | Original V4.4 explanations omitted C2 predicates; V4.5 explains them explicitly |
| E2 | 0 | 0 | market regime incompatible in 411/411 | Strategy and regime restrictions; no allocation of an eligible BUY |

Independent failures overlap; their percentages must not be added. A concurrent D2 veto is not automatically the first blocker. The original V4.2 accounts' 657 recorded evaluations produced no eligible entries. Their eligibility, veto and regime outputs replay identically using the frozen implementation and recorded decimal inputs.

The four accepted native A2 BUY decisions are real production evidence, not simulations. All four have separately persisted ACCEPTED allocation advice; none has a financial order or fill. Executed runtime control flow therefore indicates entry-gateway invocation after allocation. **The precise pre-order return reason was not retained and remains NOT_VERIFIED.** No execution-quality refusal is asserted as their historical cause.

A confirmed V4.4 bug explains the telemetry loss: `DECISION_ACCEPTED_PENDING_EXECUTION` has 35 characters, but `system_state.state` allows 32. PostgreSQL rejected all four explanation inserts. Worker logs contain four matching `StringDataRightTruncationError` events. The handler logged and continued; it did not itself prove execution was blocked. The fix uses `BUY_PENDING_EXECUTION`, preserves allocation evidence separately and records subsequent outcomes without changing strategy rules.

Local isolated replays of those four recorded decisions, using reconstructed best-level books and current public instrument metadata, refuse all four at `first_target_destroyed_by_execution_costs`. Their original first-target distances are about 14–18 bps while configured round-trip fee/slippage alone total 36 bps, before spread. These are intentional cost restrictions. Reconstructed depth and current instrument configuration are not historical L2 evidence. Local replay creates rejected order records, whereas production has none, so this result cannot be substituted for the missing production preflight reason.

## Indicators, momentum and market data

Recorded 15m/1h context is populated, complete and ready; required A2/B2 metadata is present in the exported observations. The bridge reconstructs frozen features from raw completed candles, then the original runtime computes context over the full observation window. EMA calculations use the last 240 five-minute bars; completed 15m/1h groups use up to 720 raw bars. No threshold was reduced, veto disabled or synthetic candle supplied to production.

Retest resistance excludes the breakout and retest candles; breakout volume uses the prior completed candle against the preceding 20-bar reference. UTC aggregation rejects duplicate/mixed feeds, incomplete groups, stale context and gaps in the required higher-timeframe window. Deterministic bridge tests deliberately corrupt incoming current indicators and verify that frozen reconstruction still produces the original qualified entry.

D2 is concurrently active in 281/411 observations in each active account. Only two of A2's otherwise eligible signals are vetoed. Frequencies, symbols, intersections and component evidence are in `momentum-veto-breakdown.json`. Historical benchmark batch timestamps were not retained: matching final candle timestamps can incorrectly add a benchmark that arrived in a later scan. Two veto differences per active account therefore remain NOT_VERIFIED; original V4.2 replay has none. V4.5 observes the actual in-memory benchmark cross-section and reports diagnostic parity/mismatches instead of treating reconstructed reasons as authoritative.

Production scans three markets every 60 seconds, with 720-bar shared completed-candle caching. At the inspected counter snapshot there were 4,761 successes, 253 HTTP 429 responses, 756 candle refreshes and 3,003 cache hits. Retained counters have a different scope from the shorter endpoint/symbol measurement windows; missing attribution must not be assigned to a symbol. Cache refreshes about three minutes old are expected inside a five-minute candle bucket and do not alone prove stale candles. Provider data validation, completed boundaries, bounded retries and shared cooldown remain enforced. The latest observed contexts are intact despite intermittent 429s; overwritten historical scanner rejections prevent a complete historical pre-strategy skip count.

Do not widen the frozen discovery universe automatically. A future separately approved discovery experiment should retain BTC/ETH benchmarks, reuse current five-minute caches, admit at most one rotating additional market per completed bucket, reserve a fixed request budget after protection, stop additions during cooldown, and require validated contiguous history before eligibility. A wider universe is not evidence of better expected net performance.

## Local changes and acceptance

- Add schema-versioned explanations with original input values, separate allocation/execution telemetry, complete A2/B2/C2/E2 gates, independent failures, pairwise intersections and causal-stage attribution. Unknown or unsupported evidence remains unknown.
- Persist scan observations for coordinator refusal, candle deduplication, frozen data validation and per-experiment exceptions. Observers do not authorize or veto orders. Frozen validation short-circuit order is preserved.
- Add authenticated, bounded/keyset-paginated `/api/trade-gates/{identity}` and Trade Gate Diagnostics navigation. Counts identify their page window; fills/positions are independent financial counts. Historical missing explanations join existing allocation records without inventing execution outcomes.
- Include risk, reconciliation staleness, Redis health, worker freshness, shadow compatibility and conservative incident visibility in health summaries. Live trading derives from validated configuration. Known risk/operation alerts follow their current recorded state. Other append-only incidents lack resolution links; the monitor exposes this limitation instead of silently hiding unrelated errors.
- Fix order history to exclude PENDING/ACCEPTED orders. PARTIALLY_FILLED is terminal for this IOC engine and belongs in history.
- Disable HTTP/UI archival by default behind `SHADOW_ARCHIVE_ENABLED=false`. Existing archived histories and four-slot capacity are preserved.
- Expand execution identity to cover bridge/observer, worker, discovery transport, registry and hash helpers. Pin reviewed adapter files separately from the original 71-file V4.2 source closure. Native accounts with the old fingerprint fail entry admission; no manifest migration is performed.

The PostgreSQL tests cover actual frozen A2/B2 setup → allocation → order → fill, duplicate-candle suppression, restart/partial-exit recovery, funding uniqueness, risk/data/cost failures, observer failure attribution, account isolation, bounded/authenticated API behavior, history filtering and fingerprint tampering. Synthetic execution acceptance is engineering evidence only.

Historical validation uses genuine saved Coinbase EUR proxy observations with fixed production parameters, chronological train/validation/test separation, purge/embargo and four walk-forward windows. Fees are 10 bps/side, slippage 8 bps/side and assumed spread 10 bps, with additional cost sensitivity. No historical L2 or untouched prospective holdout exists. Prior studied intervals are disclosed; the conservative multiple-comparison penalty remains. The completed out-of-sample run lost €11.18 across 27 A2 closed positions (2.26% maximum drawdown) and €1.04 across two B2 positions (0.21% maximum drawdown). Neither strategy passed validation. No strategy is approved or claimed profitable. Reproducible results and unverified regime coverage are recorded in the evidence; no synthetic performance is substituted for a missing market regime.

## Release and rollback gates

This is a Stage A candidate, not an approved production recovery. Deployment readiness is BLOCKED by the four native V4.4 manifest identities and the unrecorded A2 production preflight reasons. Keep A2/B2 unchanged and unvalidated; do not replace, retire, fund or promote an account based on this investigation. There is insufficient out-of-sample support for an A2_NEXT/B2_NEXT proposal or a capacity expansion.

Before any Stage B work, obtain approval for an exact immutable commit and a separately reviewed native-account compatibility design. Then verify scoped source/financial backups and isolated restores for official plus all eight retained databases; record manifests, journals, funding, reservations, fills and position reconciliation at the cut. Stop on any failed backup, restore, migration or reconciliation check. No account manifest is rebound by this release.

Use only manifest/full-commit guarded deployment tooling. Preserve project `autotrader-v41`, URL, loopback ports, PostgreSQL/Redis volumes, TLS/Nginx, rollback images and other projects. No global prune, `down -v`, exchange orders or production source development. For rollback, retain current financial databases and restore only the approved application image when schema compatibility is verified. Never restore a financial backup over newer transactions. If deployment fails, preserve diagnostics and fix/test/commit/push locally before a separately approved release.

The release manifest supplies the exact final commit and hashes after Stage A packaging. Final test counts, source comparison, package verification and remaining limitations are in `docs/evidence/v4_5/test-results.json` and `release-readiness.json`.

## Reproduction

With the project's development dependencies and an explicitly isolated local PostgreSQL admin DSN configured:

```sh
python3 scripts/v45_analyze.py
python3 -m pytest tests -q
python3 -m ruff check src tests scripts alembic deploy
python3 -m mypy src/autotrader
cd frontend
npm test
npm run typecheck
npm run build
```

The saved public observations and allocation records reproduce the attribution without production access. The read-only collector is intended only for the authorized VPS/backend stdin diagnostic context; it does not retrieve or print credentials. The fixed historical study can be repeated from the preserved local `.data/research` store using `scripts/v45_research.py --output-root .tools/v45-research-repeat --evidence docs/evidence/v4_5/repeated-walk-forward.json`. Run it from immutable source and do not edit application files during evaluation. The completed study retained its source snapshot; only API incident classification changed afterward, and the entire execution fingerprint still matches the final release code. Original research pointers and financial history were preserved.

The generic post-trade classifier does not support experimental A2/B2 fills and raised `StopIteration`. Its classifications are marked NOT_VERIFIED. The separate historical summary reports only direct `FAILED_BREAKOUT` exit-predicate counts, with that definition and its limits. Liquidity-stress market performance is NOT_VERIFIED because the historical proxy used a fixed 10 bps spread and did not contain that regime; deterministic spread/liquidity rejection tests are separate engineering evidence.
