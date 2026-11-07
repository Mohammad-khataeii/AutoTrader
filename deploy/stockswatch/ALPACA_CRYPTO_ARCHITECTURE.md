# AlpacaCrypto (spot paper-only) — architecture and activation

This branch adds **a new crypto strategy and interface**, not an integration with the
legacy crypto execution engine. The legacy modules, PostgreSQL state, API routes and
historical trade ledger remain in the repository. New frontend navigation shows
**StocksWatch** and **AlpacaCrypto**; it does not remove historical source.

## Alpaca capabilities, explicit exclusions

- Trading API: `https://paper-api.alpaca.markets/v2/` **only**.
  The live endpoint is absent from the crypto implementation.
- Supported spot order flow: fractional **market buy by USD notional** and
  **market sell by quantity**, with `time_in_force=gtc`.
- Crypto **short selling, margin, leverage, perpetuals, OCO/bracket and
  native trailing-stop orders are not implemented**. Alpaca crypto spot
  does not support shorts or margin. The UI must never suggest otherwise.
- Software stop / target triggers use a fresh Alpaca quote bid (<= 3 minutes)
  and submit an ordinary market sell; fills are not guaranteed, especially
  during network failures, spread widening or outages. No automated live trades.
- Alpaca v1beta3 `/crypto/us/bars` publishes quote-midpoint OHLCV, not
  actual trade execution prices. Historical signals cannot promise profit.

## Architecture

```text
Existing AutoTrader session / CSRF authority
  └── existing StocksWatch FastAPI process and mounted SQLite writer
       ├── StocksWatch equity backfill / EOD paper worker — unchanged
       └── AlpacaCrypto task (24/7, ~60-second worker)
           ├── Alpaca Data /v1beta3/crypto/us/bars + latest/quotes
           ├── stable monthly 1Day + weekly 1Hour backfill checkpoints
           ├── 10-minute just-completed hourly bar refresh
           ├── causal multi-timeframe long/flat breakout signal scanner
           ├── dedicated ac_* SQLite tables, no sw_* / legacy trade writes
           └── optional separate-account Alpaca Paper trading adapter

Frontend: AlpacaCrypto.tsx / AlpacaCrypto.css
          GET /api/stockswatch/alpaca-crypto (authenticated)
          POST /api/stockswatch/alpaca-crypto/control (session + CSRF)
```

The initial watch list contains BTC, ETH, SOL, AVAX, LINK, LTC, BCH,
DOGE, UNI and AAVE in USD pairs. Each must be confirmed as active,
tradable, fractional, **non-marginable** and **non-shortable** using
the dedicated paper account's Alpaca Assets API before submission.

### Historical and strategy guards

- Daily history: 735 UTC calendar days, chunked by fixed calendar months.
- Hourly history: 35 UTC days, chunked by fixed calendar weeks, plus
  recent completed-hour refresh.
- Persistent next-page tokens and retries; malformed, future, out-of-window,
  zero-price or currently forming bars are not accepted.
- A signal needs at least 220 completed bars in **each** timeframe,
  a recent completed hourly candle, higher daily close than daily EMA200,
  positive hourly EMA20/50/200 alignment, confirmed 20-hour breakout,
  bounded ATR percentage and RSI 45..72.
- No shorts, synthetic short fills, leverage, fabricated performance
  estimates or guaranteed profit.
- Stops: 2.5 × hourly ATR; targets: 4.5 × hourly ATR. These are
  software-managed monitoring levels, **not attached exchange orders**.
- Separate Alpaca Paper account required for broker execution to prevent
  interference with the already-running StocksWatch equities portfolio.

### Trading and financial safety

Default values:
```dotenv
ALPACA_CRYPTO_ENABLED=1
ALPACA_CRYPTO_ALLOW_PAPER_ORDERS=0
```
For any broker order submission **after** review, supply all of:
```dotenv
ALPACA_CRYPTO_PAPER_KEY=...
ALPACA_CRYPTO_PAPER_SECRET=...
ALPACA_CRYPTO_PAPER_ACCOUNT_ID=...
ALPACA_CRYPTO_ALLOW_PAPER_ORDERS=1
```
Crypto Paper credentials **must** belong to a different Alpaca paper account
from StocksWatch. Do not copy the existing stock paper key. Alpaca supports
opening an additional paper account from the account selector in its dashboard.

Both the configured account ID and the actual broker account identity are
verified on every account read. The stock paper account ID and credentials
must not match; any mismatches or unowned positions/open orders block crypto
order admission. New entries are additionally paused by default in `ac_state`.

Buy capital: max 4% of account equity per symbol, max 12% gross
crypto spot exposure, three crypto positions, max 0.35% stop-distance
budget per trade, no negative balance, plus a daily account loss
and drawdown gate. Software exit checks may continue while new entries
are paused. Any uncertain submission is persisted before the POST and
**not automatically replayed**; reconciliation uses broker client order IDs.

## Activation and deployment constraints

1. Test Python syntax, `tests/stockswatch/test_alpaca_crypto.py`, all
   existing StocksWatch tests, and `frontend/npm run build`.
2. Verify live Docker Compose topology and capture financial ledger backup.
3. **Backend-only canary:** build a pinned-image candidate and rehearse on
   a disposable SQLite copy with no broker network. Do not change the current
   equity EOD, short or intraday order flags.
4. Keep crypto paper order admission OFF and verify the authenticated API,
   10 pairs, worker progress, and EOD equity broker state.
5. The currently deployed shared frontend may have diverged. Do not replace
   it from this Git branch without verifying its live revision and merging
   navigation with the deployed source. Only then activate the new page and
   hide the legacy crypto UI. Preserve legacy backend code and data.
6. Opening a dedicated Alpaca paper account and adding its separate API key
   can happen after read-only crypto data has been validated. Order activation
   requires an explicit second review, live paper account reconciliation,
   and verified broker asset eligibility.

**This branch is not a live-trading release.** Paper results are simulated,
no crypto short functionality is present, and the stock paper positions
and legacy crypto data must be preserved.
