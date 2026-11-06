# StocksWatch: Alpaca paper broker integration

The StocksWatch paper backend uses *only* `https://paper-api.alpaca.markets` for account/order activity. Market bars continue via the existing Alpaca data service (`https://data.alpaca.markets`); quotes/data are not simulated broker fills. The original SQLite portfolio is retained as **legacy audit**, never shown as the Alpaca balance.

## Server-only configuration (after an approved, isolated deployment)

These environment variables belong on the **StocksWatch** service, not in the frontend or git:

```text
STOCKSWATCH_EXECUTION_BACKEND=alpaca_paper
STOCKSWATCH_PRICE_PROVIDER=alpaca
STOCKSWATCH_ALPACA_KEY=...                  # existing market-data API key
STOCKSWATCH_ALPACA_SECRET=...               # existing market-data API secret
STOCKSWATCH_ALPACA_PAPER_KEY=...            # Paper Trading API key
STOCKSWATCH_ALPACA_PAPER_SECRET=...         # Paper Trading API secret
STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID=...     # Full id or account_number returned by /v2/account
STOCKSWATCH_ALPACA_PAPER_ALLOW_ORDERS=0    # explicitly keep OFF initially
```

**Read-only onboarding:** deploy with `...ALLOW_ORDERS=0` and verify the dashboard reflects the expected cash, equity, positions, order history and paper account suffix in Alpaca. Confirm the broker mode status is CONNECTED and local legacy orders are separate. Validate market price feed, complete EOD bars and risk events. The code also has a persistent broker pause which defaults to ON.

**Later, separately approved enablement:** only after the correct account and risk/operational behavior are verified, set `...ALLOW_ORDERS=1`, restart *only* StocksWatch, and explicitly resume its paper engine from the authenticated dashboard. Neither setting permits live-money trading. Never route this adapter to `api.alpaca.markets`.

## Execution characteristics

- Alpaca account, positions, account history, order states and fill activities are authoritative.
- Deterministic `swp2-*` client IDs and local durable intents prevent duplicate autonomous attempts after uncertain POST outcomes; uncertain submissions remain blocked until reviewed.
- Whole-share cash-backed **limit BUYs**, `day` validity, no extended hours, with conservative size caps; strategy-managed **market SELLs** at the next Alpaca session after validated end-of-day signals. Not instantaneous intraday stops.
- Existing/manual Alpaca positions count toward exposure. Unattributable or externally modified positions are shown but cannot be sold automatically.
- Existing legacy AAPL, MA, V, ABBV and COST SQLite orders are **not transferred**, submitted, filled, canceled or netted against broker positions.
- Existing local signals, strategy, SEC/Gemini and scanner remain available; the synthetic StocksWatch ledger is never advanced when broker mode is active.
- Real-time paper quote feeds are not used by the strategy; it relies on certified close observations. Actual fills and prices are whatever the Alpaca paper broker reports. Free IEX may not represent consolidated market conditions.

## Important restrictions

- **No server deployment is performed by the source installer.** The currently running crypto and old StocksWatch services remain untouched.
- Changing a source branch cannot start paper orders. This requires separate validated deployment, paper credentials, and explicit server enablement/resume.
- Testing must use mocked Alpaca responses, never the user's paper account.
- The recent monthly history drawdown is an approximation; it cannot establish older high-water levels. Additional risk controls and an intraday stop-order system would require separate implementation and validation.
- In the rare case the broker has more than 500 recent orders, or a prior POST had an uncertain outcome, automatic new submissions stop until an operator reviews and reconciles.
