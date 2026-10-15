# Paper microstructure assumptions

The model is an immediate-or-cancel walk of the visible ask ladder for buys and
bid ladder for sells, with deterministic adverse slippage and explicit fees.
Participation defaults to 100% of displayed quantity; the pure pricing service
supports a smaller explicit fraction. No hidden depth, queue priority, matching
probability, latency guarantee or exchange order is represented.

Impact measures the difference between raw depth VWAP and the best executable
side. Slippage is applied separately to each level. Quantity rounds down to the
market step; arithmetic persisted to the ledger uses twelve decimal places.
Budgets include entry fees. Terminal IOC remainders release reservations.

An identical canonical snapshot supplies finite liquidity across all intents and
restarts. A changed snapshot supplies a new displayed-liquidity assumption. This
does not reconstruct real cancellations or intervening trades. Consumption records
currently accumulate in system_state; retention/archival is pending and must never
erase observations that a pending durable order can still dispatch.

OHLCV replay has no historical L2. Its configured spread, slippage and volume
participation are assumptions. Zero-volume bars supply no depth. Intrabar stops
use bid-adjusted lows with stop-first collision handling and worse gap opens.
Targets require a completed close quote; touching a candle high does not prove a
fill. This conservative asymmetry must be disclosed in every research comparison.
