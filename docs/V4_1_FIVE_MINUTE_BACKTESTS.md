# V4.1 executed five-minute research

Run `research-20261016T044934`; source `e0140ff18c36d86ac4c676e07aa650c2d93bac3fcfa6b708e0025f6573d66c5e`.
Full JSON artifacts: `.data/research/runs/research-20261016T044934`. Reproduce: `python3 -m autotrader.research.cli research evaluate --root .data/research --timeframes 5m 15m`.

**NO STRATEGY PASSED VALIDATION**. Historical simulated results are not forecasts. No strategy is automatically approved.

| TF | Strategy | Net EUR | Closed trades | Max DD | Profit factor | Fee stress EUR | Spread/slippage stress EUR | Passed |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 15m | A_TREND_PULLBACK | -12.7027 | 91 | 3.3780% | 0.5246 | -13.8265 | -20.1824 | False |
| 15m | B_COMPRESSION_BREAKOUT | -14.3024 | 50 | 3.2572% | 0.3529 | -16.4585 | -14.3102 | False |
| 15m | C_BREAKOUT_RETEST | -11.9309 | 40 | 2.4444% | 0.2173 | -9.8004 | -8.9945 | False |
| 15m | D_VOLUME_ACCUMULATION | -29.2628 | 84 | 6.1774% | 0.2583 | -42.2450 | -48.9895 | False |
| 15m | E_RELATIVE_STRENGTH | -1.5114 | 25 | 0.9756% | 0.8736 | -4.4585 | -7.2293 | False |
| 15m | F_MEAN_REVERSION | -16.5550 | 48 | 3.4696% | 0.0594 | -15.9350 | -15.1853 | False |
| 5m | A_TREND_PULLBACK | -24.1342 | 126 | 5.8851% | 0.3895 | -27.2028 | -28.2535 | False |
| 5m | B_COMPRESSION_BREAKOUT | -11.7928 | 77 | 2.8146% | 0.5338 | -9.2855 | -8.0434 | False |
| 5m | C_BREAKOUT_RETEST | -18.4963 | 67 | 3.8708% | 0.2170 | -13.2940 | -9.3456 | False |
| 5m | D_VOLUME_ACCUMULATION | -33.3256 | 129 | 6.9025% | 0.3084 | -30.1809 | -30.2796 | False |
| 5m | E_RELATIVE_STRENGTH | -6.1916 | 17 | 1.4539% | 0.2765 | -7.4705 | -8.0651 | False |
| 5m | F_MEAN_REVERSION | -18.8279 | 79 | 3.7804% | 0.0723 | -10.3224 | -7.5753 | False |

## Frozen intervals

- 15m: training ends 2026-09-09T21:00:00+00:00; validation 2026-09-10T00:15:00+00:00 to 2026-09-27T21:00:00+00:00; strict test 2026-09-28T00:15:00+00:00 to 2026-10-16T00:00:00+00:00. Ends exclusive; UTC.
- 5m: training ends 2026-08-05T01:35:00+00:00; validation 2026-08-05T02:40:00+00:00 to 2026-09-10T00:15:00+00:00; strict test 2026-09-10T01:20:00+00:00 to 2026-10-16T00:00:00+00:00. Ends exclusive; UTC.

## Common-capital references

| TF | Reference | Net EUR | Return | Max DD |
|---|---|---:|---:|---:|
| 15m | BTC_BUY_HOLD | -8.4990 | -1.6998% | 7.7999% |
| 15m | CASH | 0.0000 | 0.0000% | 0.0000% |
| 15m | EQUAL_WEIGHT_CURRENT_UNIVERSE | -42.8227 | -8.5645% | 14.9576% |
| 15m | ETH_BUY_HOLD | -41.6752 | -8.3350% | 15.1296% |
| 15m | V3_4_SIGNALS_COMMON_EXECUTION | -26.1847 | -5.2369% | 5.2369% |
| 15m | V4_1_INDEPENDENTLY_FROZEN_PARAMETERS | -21.0742 | -4.2148% | 4.5454% |
| 15m | V4_RUNTIME_DEFAULT_PARAMETERS | -21.4043 | -4.2809% | 4.6112% |
| 15m | VALIDATED_ENSEMBLE | 0.0000 | 0.0000% | 0.0000% |
| 5m | BTC_BUY_HOLD | 41.8939 | 8.3788% | 8.1235% |
| 5m | CASH | 0.0000 | 0.0000% | 0.0000% |
| 5m | EQUAL_WEIGHT_CURRENT_UNIVERSE | 49.9088 | 9.9818% | 15.4365% |
| 5m | ETH_BUY_HOLD | 10.7318 | 2.1464% | 15.6982% |
| 5m | V3_4_SIGNALS_COMMON_EXECUTION | -50.4310 | -10.0862% | 10.0873% |
| 5m | V4_1_INDEPENDENTLY_FROZEN_PARAMETERS | -26.7101 | -5.3420% | 5.6125% |
| 5m | V4_RUNTIME_DEFAULT_PARAMETERS | -28.2552 | -5.6510% | 6.1756% |
| 5m | VALIDATED_ENSEMBLE | 0.0000 | 0.0000% | 0.0000% |

Costs: 10 bps per-side fees, 10 bps full spread, 8 bps per-side slippage; fee stress 20 bps; friction stress 25 bps spread and 20 bps slippage. Shared liquidity is assumed at 1% of previous completed volume. Current-bar final volume is never known at the open. Fixed historical quantity precision is an assumption. No actual historical order book is claimed.

Cash, BTC/ETH buy-and-hold, current-universe equal-weight, legacy signals on common execution, runtime-default V4 parameters, independently frozen V4.1 members, and the validated ensemble use EUR 500 initial capital. Passive references use full capital with estimated endpoint liquidation costs and have different exposure; bot positions obey the existing reserve and risk controls. Residual positions are marked, not forcibly liquidated. Mock AI is an integration comparison only.

Exports: 2204 fills and 72474 equity/drawdown rows across 12 independent strategy/timeframe simulations. See gzip CSV exports and grouped statistics. These are not real-market paper-account fills.

BTC/ETH have longer five-minute training coverage than other assets; the cross-sectional universe therefore changes as genuine data becomes available. Missing recent histories block signals. No absence of a trade is imputed as a zero-price candle. Per-asset diagnostics are portfolio contributions and do not establish a standalone edge.

Additional reproducible diagnostics: `python3 scripts/export_v41_diagnostics.py` derives 833 closed-position records, 135 detailed asset/regime rows and 24 UTC-month rows from the frozen run. Group metrics include independent entry dates, gross gains/losses, mean wins/losses and holding time, losing streak, entry notional, turnover and actual modeled costs. Monthly rows separate marked equity change from closed-position statistics and fill-month costs. Unsupported subgroup confidence intervals remain null; no subgroup parameter retuning is implied. Checksums are in the export manifest.
