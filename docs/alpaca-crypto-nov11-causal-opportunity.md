# AlpacaCrypto Nov 11 no-trade analysis / opt-in opportunity patch

Scope: the isolated **Alpaca Crypto spot paper strategy** inside the existing
StocksWatch process. The legacy AutoTrader crypto engine and the StocksWatch
stock EOD execution rules are not changed.

## Audit facts and safety boundaries
- Nov 9–11 2026: 2,453 AlpacaCrypto execution cycles; no strategy-owned
  crypto paper intents. A qualified Nov 9 PEPE signal was blocked by the
  mixed-account stock-order interlock.
- 79 cycles returned 'crypto_shared_account_stock_orders_pending'.
  Blocking ALL stock orders is broader than a capital-availability check.
- 160 WAIT decisions involved untraded midpoint-price outliers. A zero-volume
  bogus quote close can contaminate EMA indicators for days, but using the
  original raw candle as executable price would be incorrect.
- The continuation signal flag previously depended on a special file only,
  not the inspected environment variable.
- 25/33 executable USD pairs fell Nov 10 (UTC day); permitting indiscriminate
  dip buys would not be justified by this evidence.

## Changes
1. Pending stock **limit** BUYs reserve their remaining qty × limit price
   from both paper cash and non-marginable buying power. Valid existing stock
   SELLs consume no new cash; genuine matched OCO exits are not double-counted.
   Any unknown stock order or uncapped stock market BUY still blocks new
   crypto buys. Existing owned crypto exits continue unaffected.
2. Re-read both stock and crypto broker positions/orders immediately before
   submitting crypto paper BUY. If the book or cash changed, stop and retry
   next cycle. POST remains single-attempt with durable idempotency.
3. Validate raw candles, quarantine **old** zero-volume anomalous CLOSES
   only in indicator calculations, without overwriting market evidence.
   Recent suspicious candles and inadequate history still block entry.
4. Honor explicit \`ALPACA_CRYPTO_CONTINUATION_ENABLED=1\` in addition to
   the previous on-disk switch (default remains off).
5. Surface a second *causal post-selloff recovery candidate* from finished
   hourly candles with trade volume, stabilization and limited rebound size.
   \`ALPACA_CRYPTO_RECOVERY_MODE=research\` is the default and submits NO
   recovery orders. \`paper\` explicitly opts into this policy; recovery
   position weight and per-trade risk are halved versus normal entries.
   All existing price/quote/depth/ownership/account checks still run.

## Limitations
- A strategy may remain flat in falling or illiquid markets; more trade
  attempts are not a profitability guarantee.
- Confirm broker state and current software-only crypto SL/TP before stopping
  its worker. Do not restart while any bot-managed crypto spot position has
  software-only stops or uncertain order intent.
- Validate candidate entry and recovery with *causal* out-of-sample price and
  quote/depth replay before using opt-in mode. Hourly Alpaca bars are midpoint
  observations, not guaranteed executable fills.
- This release doesn't retroactively recover missed trades or alter existing
  orders, stocks OCOs, financial balances, crypto strategy performance ledger,
  or account risk limit constants.
