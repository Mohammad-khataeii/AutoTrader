# Point-in-time market regimes

`research/regimes.py`, version `regimes-4.0.0`, classifies completed observations
as STRONG_BULL, MODERATE_BULL, RANGE, COMPRESSION, EXPANSION, BEAR,
LIQUIDITY_STRESS or UNCERTAIN. These are observable rule states, not retrospectively
assigned truth labels or a validated forecast.

Inputs include EMA21/50 trend, close, ATR/close, Bollinger width, relative volume,
momentum, recent drawdown, available BTC/ETH trend and observed/assumed spread.
Missing history, recent gaps or invalid data force uncertainty; bearish or stressed
conditions veto entries. Mean reversion is eligible only in range/compression.

MarketScanner prepares the cross-section before evaluating BTC/ETH comparisons.
Future benchmark timestamps are excluded. Source feature/signal timestamps identify
the source candle start. Research additionally records `available_at` at its close;
the event loop cannot execute that signal before the next observed open.

Feature windows contain up to 240 observed bars. At least 50 contiguous recent
primary bars and 50 completed four-bar groups are required by the combined rules.
Gaps are not filled. Older gaps can remain inside a window of observed bars;
this is a limitation of the heuristic indicator history, not invented observations.

Tests cover future benchmark exclusion, bad-data/risk-off vetoes, independent
strategy enablement, exact linear EMA equivalence, and prefix invariance when
future observations are appended. The full research reports show actual realized
contributions by entry regime. No regime-specific predictive edge passed validation.
