# StocksWatch November 10 entry / protection / audit corrections

Base: \`fix/stockswatch-oco-exit-broker-readiness-20261110\`.
This patch does **not** change the crypto strategy, paper account balances, old
fills, historical candles, existing broker order IDs or live-money authorization.

## Root causes and scope
* The EOD limit at last close × 1.005 is marketable at the open; it is a
  maximum price, **not** a passive bid designed to buy lower.
* An open-stock pause or a disabled protection opt-in can leave existing
  EOD-owned stock longs unprotected even when they were bought correctly.
* The Nov 10 log collector capped intraday rows before filtering by session,
  so its absence of Nov 10 decisions was inconclusive.
* Alpaca GET transport failures interrupt observation; retry safe GET only,
  never POST/PATCH/DELETE automatically on uncertain outcomes.
* Account equity movement is not stock-strategy realized P&L, especially
  when a paper account also holds crypto.

## Changes

1. **Adaptive paper EOD entry**, explicit \`STOCKSWATCH_EOD_ENTRY_MODE=adaptive\`
   opt-in. Wait 12 minutes, sample completed last 8 IEX minutes, and use a
   fresh IEX quote. Defer during accelerating stock or SPY selling,
   unverified prices, quote spreads or oversized premiums. Execute at a
   quote-derived limit within the original certified daily cap. Stop
   attempting after 55 minutes. No claim of hitting intraday lows.
   Existing EOD stock SELL decisions and crypto orders are unaffected.
   \`legacy\` default retains prior behavior if not opted in.
2. **No new EOD BUY when any currently held strategy-owned EOD long lacks a
   verified broker stop**, or paper OCO orders aren't armed. This is not a
   substitute for a protective order; inspect existing ACN/AMGN in Alpaca.
   The OCO monitor continues to run even if new entries are paused.
3. **Broker-cycle decision log** in isolated SQLite, including individual
   reason codes, times, and candidate entries. Authenticated, paginated
   GET \`/api/stockswatch/session-audit?day=2026-11-10&offset=0&limit=100\`
   filters \`sw_intraday_cycles.at\` and \`sw_intraday_observations.at\` on
   New York local session dates, before LIMIT.
   Historical broker decision cycles start only from this upgrade.
4. **GET-only retry** for broker snapshots. POST/PATCH outcomes still fail
   closed and require reconciliation, with no automatic blind retries.

## Rollout

- Keep the paper account paused at cutover. Verify new source and untouched
  database contents; review open orders at Alpaca before enabling new entries.
- Preserve existing protection flags; don't treat planned stops as active.
- Explicitly configure \`STOCKSWATCH_EOD_ENTRY_MODE=adaptive\` on the
  StocksWatch container. The strategy will not buy during the first 12 minutes
  and may miss some fast breakouts. Assess across many out-of-sample sessions.
- Test patched modules and broker lifecycle before cutover. Review the
  session-audit route after opening and independently verify broker stop legs.
- No automatic release of real money; the only target is Alpaca Paper.
