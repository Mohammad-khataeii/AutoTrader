# V4.2 frozen strategy hypotheses

Version `4.2.0-experimental.1` is unvalidated. Original `4.0.0` strategies and historical artifacts remain unchanged. The original diagnostics motivated these rules before any experimental final-period results were inspected. The historical dates have already been examined in V4/V4.1 and during failure attribution; there is no untouched historical holdout claim.

| ID | Hypothesis | Declared rule | Invalidation / horizon |
|---|---|---|---|
| A2_CONFIRMED_PULLBACK | Reduce extended and unconfirmed pullback entries | Completed 15m and 1h bullish EMA context; EMA9 touch/recovery; green close above previous high; no >2 ATR extension | Existing bid stop, failed breakout and adverse regime; 12 primary bars |
| B2_CONFIRMED_COMPRESSION | Avoid entering the first breakout impulse | Prebreak 20-bar compression; prior breakout with relative volume; current acceptance outside old range; completed higher bullish context; extension veto | Existing protective exits; 12 bars |
| C2_LIQUID_RETEST | Require recovery after a retest and executable depth | Prior breakout, boundary retest, green recovery above previous high, current relative volume and higher bullish context | Existing protective exits; 10 bars |
| D2_MOMENTUM_QUALITY | Reject extended or weakening momentum | Veto >2 ATR extension, falling close with falling volume, bearish BTC/ETH trend, spread >25 bps or unsafe regime | Filter only; never standalone BUY |
| E2_ABSOLUTE_RELATIVE_STRENGTH | Relative strength must coexist with absolute market support | Local higher bullish context; both BTC and ETH above rising EMA21/50; 20-bar excess return, green recovery and volume | Existing protective exits; 10 bars |
| F2_RESTRICTED_RANGE | Avoid mean reversion during directional deterioration | RANGE only, lower-band proximity, RSI <35, green recovery; completed higher context must not be bearish | Existing protective exits; 4 bars |

All five entry variants pass through D2, actual execution quality, fees, finite depth, precision and unchanged deterministic risk controls. Historical depth is a prior-completed-volume assumption; actual live shadow orders use incoming public order books. No queue or continuation probability is estimated. Zero signals or failed validation are acceptable outcomes.

Primary features retain the last 240 completed 5m candles. A separate 720-candle observation window supports up to 60 complete UTC hours. Incomplete groups, gaps, future groups and insufficient EMA history cannot confirm a trade. Both replay and worker use the same context builder and strategy engine.

The experimental default is relative volume 1.5, compression width .06, breakout buffer .001, relative return .02, stop 2 ATR and target spacing 2 ATR. Existing three predeclared research neighbors are retained for robustness, not expanded into an indicator search. Parameters, version, source, costs, feed kind and funding are frozen per shadow experiment; a source mismatch blocks new entries while protection continues. Each independent experiment receives EUR 500 once, with no loss resets.

Promotion requires every existing gate, positive validation, multiple-timeframe evidence, matched-cost comparisons and explicit approval. A profitable shadow interval alone cannot grant approval. A minimum 30-day future observation window starts after configuration freeze; it has not yet been completed.
