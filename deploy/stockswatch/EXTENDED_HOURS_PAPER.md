# StocksWatch autonomous intraday paper

This guide describes the original 32-instrument release. For the expanded universe, directional risk, and compatible shared-frontend cutover, see [StocksWatch Long and Short Paper](LONG_SHORT_50.md).

Implements [AutoTrader Issue #1](https://github.com/Mohammad-khataeii/AutoTrader/issues/1) on the StocksWatch Alpaca integration base `0925751f2c82e6ccad1ef404a8ae71408008f48c`. The release starts with intraday order admission disabled. The existing EOD scorer, order window, policy, and local ledger stay independent. The two Alpaca paper strategies share broker account truth, reconciliation, the order pause, and a serialization lock. No strategy reads or writes crypto storage.

## Phases and evidence

| New York phase | Observation | Order policy once configured |
|---|---|---|
| Premarket 04:00–09:30 | Explicit Alpaca feed and completed minute evidence | Whole-share DAY limit, extended flag on |
| Core 09:30–NYSE close | Same pipeline and same confidence requirements | Whole-share DAY limit, extended flag off |
| After-hours close–20:00 | Reference rolls to the just-completed regular close | Whole-share DAY limit, extended flag on |
| Overnight 20:00–04:00 | Separate explicit BOATS or derived overnight feed, where available | Observe and WAIT |
| Closed / unavailable / maintenance | Durable status and zero fresh coverage | WAIT |

The calendar uses `America/New_York` and XNYS sessions for holidays, DST and early closes. For a half-day, core closes at the exchange calendar close, after-hours stops at 17:00, and 17:00–20:00 is maintenance. The overnight session is associated with the following eligible trade date. A broker clock older than eight seconds, a future clock, and a disagreement about the core session block order admission. A 15-second opening and 45-second closing buffer protect phase transitions. [Alpaca trading hours](https://docs.alpaca.markets/us/docs/245-trading-for-trading-api) · [Alpaca half-day hours](https://alpaca.markets/learn/how-to-enable-stock-market-trading-from-4-am-to-8-pm-et) · [NYSE calendar](https://www.nyse.com/trade/hours-calendars)

The polling loop requests the configured 32 names in batches of up to 32, normally about every 25 seconds after the preceding cycle finishes. Closed or failed cycles defer for 60 seconds. It bounds pagination, reuses a complete regular-close cache, and requests snapshots and RAW 1-minute bars with an explicit feed. A previous regular close is the last observed minute close within the final two minutes of the applicable regular session, not the provider's daily aggregate. The collector preserves source, receipt time, event time, trade, bid/ask and displayed sizes, completed bars, turnover and validation reason. When a derived overnight bars route is unavailable, available snapshots can still be archived with a failed validation state. Real-time IEX is one venue and observation-only. Delayed SIP is never execution evidence. Overnight has no order authority in this release. [Alpaca feed entitlements](https://docs.alpaca.markets/us/docs/about-market-data-api) · [Snapshots](https://docs.alpaca.markets/us/reference/stocksnapshots-1) · [Bars](https://docs.alpaca.markets/us/reference/stockbars)

Executable candidates need fresh, same-phase quote and trade timestamps, a supported regular SIP quote condition and trade condition, six contiguous completed bars, and a recent regular-close reference. The first six minutes of a phase may therefore produce WAIT. The quote must be two-sided and non-crossed, spread at most 35 bps, with at least $750 of conservative displayed notional on either side. Size treats each displayed unit as at most one share for admission rather than multiplying by an assumed lot size. Explicit halt flags and nonregular quotes block entry, and stale or conflicting evidence fails closed. REST snapshots and asset flags cannot provide continuous consolidated halt status or guaranteed executable depth.

## Decisions, accounting and safeguards

- For buys, require all 32 configured symbols in the snapshot response, at least 26 individually valid observations by default, and valid SPY and QQQ. Set `STOCKSWATCH_INTRADAY_REQUIRE_ALL_VALID=1` to require 32 valid symbols. A symbol disabled in the configured universe remains observable but cannot receive new entries.
- A candidate needs at least +0.30% regular-close gap, +0.12% movement over the six-bar window, three improving closes, and $250,000 in the latest three completed minutes. Ranking deducts spread and 10 bps of modeled friction, and checks a further +20 bps stress. Both benchmarks down more than 15 bps over the short window block buys. Already observed SEC filings can add a ranking tie-break. Gemini has zero execution authority.
- New entries have a 5% equity position cap, a 15% aggregate intraday exposure cap including reserved buys, two BUY intents per trade date, a 1% modeled per-entry loss cap under a 5% adverse move, and the existing shared position, sector, gross, non-marginable buying power and cash-reserve limits. An observed 2% account daily loss latches an intraday entry pause through the trade date. Owned exit checks continue.
- Exits trigger at −1.5%, +2.5%, 90 minutes, or confirmed benchmark deterioration with adverse local momentum. Only demonstrably owned long shares with confirmed available quantity can be sold. The worker rechecks fill lineage, live orders, account identity, price, eligibility and corporate actions. Displayed liquidity can limit a sell to part of the position. Limit orders can rest, partially fill, or expire and provide no guaranteed stop or fill. A pause stops new automated buys and sells, while previously accepted DAY orders remain at the broker. [Alpaca order behavior](https://docs.alpaca.markets/us/docs/orders-at-alpaca)
- `swx1-` intents are durable before the POST and separate from EOD `swp2-` intents. One BUY ID per symbol and trade date, and one SELL ID per symbol and minute, survive restarts. Same-symbol cross-engine and manual-order conflicts block new submissions. A documented buying-power rejection is definitive. Unknown POST outcomes quarantine both engines until matching broker state establishes the outcome. A lookup 404 alone cannot clear an uncertain submission. Use the original confirmed-absence operator recovery only after an Alpaca support confirmation, with server order capability off and the shared pause on. A mismatched external broker order requires manual broker reconciliation.
- SQLite schema migration is additive. `sw_intraday_cycles`, `sw_intraday_observations` and `sw_intraday_followups` retain seven days. Broker intents, verified strategy fill activities and daily-loss latches are durable. Read-only replay recomputes ranks from recorded features. Forward quote probes follow qualified WAIT setups at 30–33 minutes and count a stressed bid-versus-original-ask proxy. They are descriptive observations. Strategy FIFO P&L only uses linked broker fills and is suppressed when quantity or lineage is incomplete. It is price P&L before charges and is separate from account P&L. A manual fill, corporate action, or capped broker fill history can prevent automated ownership proof even when a holding appears on the broker screen.

## Local release checks

Run in an isolated checkout with Python 3.12 and Node 22. Tests create temporary SQLite databases and use mocked Alpaca transports.

```sh
python3 -m pip install -r deploy/stockswatch/requirements.txt
PYTHONPATH=.:src python3 -m pytest -q tests/stockswatch
(cd frontend && npm ci && npm run build && npm test)
python3 -m stockswatch.intraday_replay /path/to/intraday_observations.jsonl
python3 deploy/release.py prepare --ref HEAD --output deploy/releases/stockswatch-intraday
```

Build the extracted verified source locally for Linux AMD64. Use the already verified StocksWatch base image pinned by an immutable digest or a local tag verified against its configuration ID. The repository does not publish that private base image.

```sh
docker buildx build --load --platform linux/amd64 \
  -f "$EXTRACTED_RELEASE/deploy/stockswatch/Dockerfile" \
  --build-arg BASE_IMAGE="$VERIFIED_STOCKSWATCH_BASE" \
  --build-arg RELEASE_COMMIT="$RELEASE_SHA" \
  -t "stockswatch-intraday:$RELEASE_SHA" "$EXTRACTED_RELEASE"
docker buildx build --load --platform linux/amd64 \
  --build-arg RELEASE_COMMIT="$RELEASE_SHA" \
  -t "stockswatch-intraday-frontend:$RELEASE_SHA" "$EXTRACTED_RELEASE/frontend"
```

Verify both Linux AMD64 image configuration IDs, source and commit labels, archive hashes, and offline fixture results before approval. A local runtime unable to contact its Docker engine cannot produce an image acceptance result. A successful mock run establishes engineering behavior only.

## Later approved staging cutover

Use the [existing deployment guide](ALPACA_PAPER_DEPLOYMENT.md) for a first scoped install only. Its initial-install helper deliberately refuses an already populated `autotrader-aruba-stockswatch` project. For an already scoped installation, rehearse a replacement of exactly its existing StocksWatch and frontend services using the retained verified Compose configuration, both pinned images, and the existing SQLite mount. Verify project membership, current account identity, backend authentication, network and loopback bindings before touching the two services. Preserve both prior image IDs and their exact scoped configuration. The core backend, crypto volumes and collectors, existing project membership, TLS and unrelated services stay outside cutover scope.

Before an approved replacement, keep order capability off, pause, wait for open orders and uncertain submissions to reconcile, and record current account, positions, fills, intents and control state privately. Use an online SQLite backup via `deploy/stockswatch/scoped_release.py`'s `backup(data, destination)` against the verified existing mount. It opens the copy independently, reconciles the legacy ledger, and compares broker table seals when present. Also rehearse starting the candidate against a disposable restored copy with the data and broker transports disabled or mocked. Confirm migration only adds intraday tables and that both the original and candidate can read the legacy ledger. Capture a final verified backup after the old writer stops. The new writer must acquire the same ledger lock before use.

The default candidate starts observing even while orders and the shared pause are off. Verify through the existing authenticated dashboard and `GET /api/stockswatch/intraday`: feed entitlement, current phase, 32 tracked, EOD due count, intraday validation count, reasons, quote ages and current account. Observe all enabled phases, transitions, transport recovery and ownership reconciliation before declaring a read-only rehearsal pass.

## Server-only activation after evidence review

A separately reviewed config change for the exact same image can activate autonomous paper orders. Retain the existing paper host, account ID and credentials. Set `STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS=1`, `STOCKSWATCH_INTRADAY_ALLOW_ORDERS=1` and `STOCKSWATCH_INTRADAY_FEED=sip` in the approved StocksWatch service only. Mount the reviewed proof read-only, set `STOCKSWATCH_INTRADAY_PREFLIGHT` to its container path and `STOCKSWATCH_INTRADAY_PREFLIGHT_SHA256` to the exact file SHA-256. The image embeds `STOCKSWATCH_BUILD_COMMIT`. The JSON must name that commit, `strategy: "stockswatch-intraday/1"`, `paper_only: true`, and a `checks` map with actual `PASS` evidence for `native`, `linux_amd64`, `frontend`, `offline_broker` and `read_only_rehearsal`. Keep the test outputs and image verification with the proof. The initial scoped helper emits intraday order capability off, even when its existing EOD arming path is used.

The shared StocksWatch pause is the immediate application kill switch. Once the verified service is armed and the operator lifts that pause, the machine selects every BUY, SELL and WAIT. If a cutover fails, keep the kill switch on and reconcile any broker orders before restarting a previous image. Preserve the current SQLite ledger and candidate evidence. Roll back the two scoped images and config after confirming that no open intraday order or unmanaged intraday inventory would be left behind by the old code. Preserve the latest database; a stale backup must never overwrite newer fills or intents.

## Issue #1 release verification

The local StocksWatch suite passed 103 tests, including the original EOD lifecycle and the offline broker and rank-replay cases. The frontend TypeScript and Vite production build passed, and Vitest passed 21 tests. Local Linux AMD64 build attempts for both image contexts timed out waiting for Docker Desktop. There are no candidate image IDs or actual feed entitlement results for this release. The intraday order gate remains off and the read-only target rehearsal is pending.
