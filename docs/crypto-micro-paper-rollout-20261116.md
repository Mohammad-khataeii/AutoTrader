# AlpacaCrypto: 5-minute PAPER experiment (2026-11-16)

This is a **paper-only**, no-leverage, spot LONG/FLAT experiment on top of the
deployed StocksWatch service. It does not change stock signals, held stock
positions, OCO orders, or the legacy crypto ledger.

## Evidence and motivation

The second read-only Aruba archive (observed 2026-11-16 10:21 UTC) contains
9,021 execution cycles: 8,767 `no_approved_spot_long_signal`, 79 historical
stock-order interlocks, 75 completed-hour waits, 88 paused cycles and 12 GET
transport failures. The archive confirms `ac_state.paused=0`, paper admission
enabled and 0 crypto broker intents/managed positions.

The earlier long-only relaxed hourly candidate had predominantly **negative**
fee/slippage-adjusted returns in a falling crypto market. This change therefore
does not activate the rejected hourly experimental paper rule.
It introduces a separate, explicitly labeled **micro PAPER experiment** with
much smaller positions and faster exit logic.

Alpaca's US crypto 5-minute bars are quote-midpoints; candles with zero trade
volume do **not** demonstrate executable prices. Alpaca supports `5Min` at
`/v1beta3/crypto/us/bars`.

## What changes

- BTC/USD, ETH/USD, SOL/USD, AVAX/USD and LINK/USD receive a new causal 5-minute
  scan from one bounded GET. Only fully completed, contiguous candles are used.
- Require positive current and recent reported traded volume, rising EMA8,
  RSI and bounded volatility, 10-minute momentum, breakout or rising lows,
  limited extension, and a non-liquidating recent BTC reference for altcoins.
  No pretend short, futures, leverage, or live-money orders.
- Decisions are saved in independent `ac_micro_audit` records with 30-day
  retention. The authenticated crypto status API exposes mode and recent
  reasons; `python -m stockswatch.crypto_micro` prints a read-only summary.
- Only `ALPACA_CRYPTO_MICRO_MODE=paper`, existing paper order permission,
  unpaused crypto state and disabled live trading may route micro candidates to
  the established Alpaca Paper broker adapter.
- Every new micro BUY must pass current broker account identity, owned
  position checks, stock BUY cash reservation, fresh quote <=75s, spread <=0.35%,
  quote price <=0.6% above the signal, real quote depth, price/stop arithmetic,
  and 0.15%-equity / $150 maximum per experiment (also at least $25).
- At most one active managed micro position and one new micro BUY per 45min.
  The normal total crypto exposure/position/risk limits remain intact.
- Existing software stop and target checks execute every broker cycle; micro
  positions additionally exit after 90min via fresh-bid market sell.
  Protection checks continue even if an unrelated crypto order is open;
  same-symbol open orders still prevent duplicate exits.
- Preserve old crypto history, source and database; no data migration to stock
  or legacy crypto financial tables.

## Independent five-minute scan sanity check

A read-only Alpaca US five-minute sample for **2026-11-14 through 2026-11-16
10:00 UTC** had approximately 72 BTC, 36 ETH, and 43 SOL *overlapping* raw
pattern matches, before live bid/ask/depth, cooldown and broker admission.
These numbers are **NOT paper fills, portfolio trades, independent samples or
evidence of positive expectancy**.

A separate simple momentum scalp replay for the same bearish window showed
negative returns after hypothetical friction. The micro strategy is an
experiment, not an endorsed profitable strategy. Maintain small notional
until prospective paper fills and net P&L justify changes.

## Deploy from Mac using verified pinned SHA

`bash deploy/stockswatch/deploy_crypto_micro.sh FULL_40_CHARACTER_SHA`

For read-only preflight only:
`bash deploy/stockswatch/deploy_crypto_micro.sh --preflight FULL_40_CHARACTER_SHA`

The self-contained Mac script downloads six source files from that exact
GitHub commit, verifies local Python syntax, computes SHA-256 manifest, sends
them over `ssh aruba-vps`, then runs the Aruba Python helper. No GitHub branch
head is followed silently.

On Aruba, the helper checks:
- exact running Python base hashes from the 2026-11-16 forensic archive;
- paper-only account and crypto worker enabled; no live execution;
- completed broker snapshots, **zero crypto positions, open orders, managed
  positions and unresolved intents**, and existing crypto entries unpaused;
- U.S. stock core session must be outside 09:10–16:15 New York Mon–Fri;
- existing healthy StocksWatch/frontend, exact ledger bind, sufficient disk,
  exact pinned source bytes and compose topology.

It builds a new image **offline from the existing local StocksWatch image**,
overlays only the modified crypto Python modules, keeps all existing unrelated
stock module mounts and the same ledger bind, takes a SQLite online backup,
and recreates **only** StocksWatch. Frontend and other containers are untouched.
If a cutover fails without new crypto orders/positions, the prior image and
module mounts are restored without overwriting the active financial ledger.

Existing stock positions and native OCOs remain with Alpaca; source-image
changes do not place stock orders. Pausing the worker during cutover briefly
interrupts software-managed activity; abort if crypto holdings or unresolved
orders are present. The helper leaves the release directory and backups intact.

## Verify after deploy

Find the *service* container, never assume the Compose project is its name:

```bash
ssh aruba-vps 'CID=$(sudo docker ps -q --filter label=com.docker.compose.project=autotrader-aruba-stockswatch --filter label=com.docker.compose.service=stockswatch); sudo docker exec "$CID" /opt/stockswatch/venv/bin/python -m stockswatch.crypto_micro'
```

Inspect authenticated `/api/stockswatch/alpaca-crypto` for
`micro_5m_paper`, `crypto_execution_outcomes`, `immutable_admission_audit`
and `intents`. A computed BUY is not a broker fill. Check actual Alpaca order
IDs, fill prices and software exits before increasing paper size.

## Tests and limits

CI compiles all `stockswatch` modules and the Aruba helper, and runs a
focused synthetic-candle micro suite (including no-lookahead, zero-volume and
paper-only authorization). The historical full StocksWatch suite has existing
outdated 10-crypto/52-stock expectations and unrelated stock broker fixtures.
Its failure is not proof of a failed micro test but remains an integration
gap; do not claim full-suite success.

This is deliberately a **small, higher-frequency paper research experiment**,
not a way to force orders or to assert future profitability.
