# V4.2 historical experimental results

Run `research-20261016T114522`; source `9f03f481049165cba9b54082d6f45f6e06e76d4b0a1625832b5f8434f8ace23a`; strategy `4.2.0-experimental.1`.

Chronological test: 2026-09-10T01:20:00+00:00 to 2026-10-16T00:00:00+00:00 exclusive, UTC. Each independent portfolio starts with EUR 500. Normal modeled spread/fee/slippage:10/10/8 bps; depth:1% of prior completed volume. **These dates were already examined in V4/V4.1 and failure attribution. They are not untouched evidence.**

**NO STRATEGY PASSED VALIDATION.**

| Experimental entry | Original comparator | Original net EUR / closed | Experimental net EUR / closed | PF | Max DD % | Mean exposure EUR | Fees EUR |
|---|---|---:|---:|---:|---:|---:|---:|
| A2_CONFIRMED_PULLBACK | A_TREND_PULLBACK | -24.1342 / 126 | -3.8036 / 8 | 0.0620 | 0.7807 | 0.5394 | 1.1930 |
| B2_CONFIRMED_COMPRESSION | B_COMPRESSION_BREAKOUT | -11.7928 / 77 | -0.9386 / 2 | 0.0000 | 0.1877 | 0.0273 | 0.2878 |
| C2_LIQUID_RETEST | C_BREAKOUT_RETEST | -18.4963 / 67 | -0.3534 / 1 | 0.0000 | 0.0707 | 0.0072 | 0.1492 |
| E2_ABSOLUTE_RELATIVE_STRENGTH | E_RELATIVE_STRENGTH | -6.1916 / 17 | 0.0000 / 0 | Unavailable | 0.0000 | 0.0000 | 0.0000 |
| F2_RESTRICTED_RANGE | F_MEAN_REVERSION | -18.8279 / 79 | 0.0000 / 0 | Unavailable | 0.0000 | 0.0000 | 0.0000 |

D2_MOMENTUM_QUALITY is a veto applied to the experimental entries, not a sixth independent trading portfolio. Original D_VOLUME_ACCUMULATION remains preserved: net EUR−33.3256 /129 closed positions in the common 5m period.

The stricter variants sharply reduced participation. Lower absolute losses and drawdown do not establish a better edge: A2/B2/C2 have negative expectancy with only8/2/1 closed positions; E2/F2 held cash and provide no trade evidence. These positions cannot support a credible continuation probability or strategy approval.

## Benchmarks on the same dated EUR 500 reference

| Reference | Net EUR | Return % | Max DD % |
|---|---:|---:|---:|
| CASH | 0.0000 | 0.0000 | 0.0000 |
| BTC_BUY_HOLD | 41.8939 | 8.3788 | 8.1235 |
| ETH_BUY_HOLD | 10.7318 | 2.1464 | 15.6982 |
| EQUAL_WEIGHT_CURRENT_UNIVERSE | 49.9088 | 9.9818 | 15.4365 |

Passive references apply the same endpoint cost assumptions, but deploy capital without the bot’s EUR100 position cap/reserve constraints. Their larger exposure and gap/common-mark limitations are disclosed in each raw artifact. Do not interpret a cash-like drawdown as outperformance. Original strategy comparisons come from the separately reproduced original portfolios, not a relabeled experimental ensemble.

## Validation, stress and frozen parameters

| Strategy | Validation net EUR | Fee20bps net EUR | Spread25/slippage20bps net EUR | Expectancy EUR/closed | Frozen parameters |
|---|---:|---:|---:|---:|---|
| A2_CONFIRMED_PULLBACK | -16.6677 | -1.6069 | -1.8347 | -0.4755 | `{"breakout_buffer": "0.001", "compression_width": "0.06", "relative_return": "0.02", "relative_volume": "1.2", "stop_atr": "1.5", "target_atr": "1.5"}` |
| B2_CONFIRMED_COMPRESSION | -0.6595 | 0.0000 | 0.0000 | -0.4693 | `{"breakout_buffer": "0.001", "compression_width": "0.06", "relative_return": "0.02", "relative_volume": "1.2", "stop_atr": "1.5", "target_atr": "1.5"}` |
| C2_LIQUID_RETEST | 0.0000 | 0.0000 | 0.0000 | -0.3534 | `{"breakout_buffer": "0.001", "compression_width": "0.06", "relative_return": "0.02", "relative_volume": "1.2", "stop_atr": "1.5", "target_atr": "1.5"}` |
| E2_ABSOLUTE_RELATIVE_STRENGTH | 0.0000 | 0.0000 | 0.0000 | 0.0000 | `{"breakout_buffer": "0.001", "compression_width": "0.06", "relative_return": "0.02", "relative_volume": "1.2", "stop_atr": "1.5", "target_atr": "1.5"}` |
| F2_RESTRICTED_RANGE | 0.0000 | 0.0000 | 0.0000 | 0.0000 | `{"breakout_buffer": "0.001", "compression_width": "0.06", "relative_return": "0.02", "relative_volume": "1.2", "stop_atr": "1.5", "target_atr": "1.5"}` |

All normal/adverse scenarios retain initial capital, dated population, frozen member parameters, risk and execution model. Partial exits, costs and residual marked positions remain in the accounting; none is forced closed simply to improve a statistic.

The prospective shadow defaults (2ATR stop/target, volume1.5 for the new variants) were declared before these final-period outcomes. The training selection here chose grid0. These are distinct frozen parameter configurations; the default shadow curve must not borrow the selected-grid historical outcome as if it were the same configuration.

Full canonical manifest, training/validation/OOS metrics, four walk-forward windows, all failures, fills and curves: `evidence/v4_2-research-run.tar.gz`. Reproduce with `autotrader research evaluate --experimental --root .data/research --timeframes 5m`. No paid AI was called.
