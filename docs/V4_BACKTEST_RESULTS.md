# V4 executed historical results

Run: `research-20261015T205023`. Source fingerprint: `b31992258941962d61ee8bfaa7b38ea882a7f5449099ff78fb0045fc15e4966d`.
Original complete artifacts: `.data/research/runs/research-20261015T205023`. Summary: `evidence/v4-research-results.json`.

**NO STRATEGY PASSED VALIDATION**. No candidate is approved. The validated ensemble stays in cash.
All amounts below are observed historical simulation outcomes, not forecasts.

| TF | Strategy | Net EUR | Closed positions | PF | Max DD | Passed |
|---|---|---:|---:|---:|---:|---|
| 1d | A_TREND_PULLBACK | -13.7885 | 53 | 0.9169 | 6.8824% | False |
| 1d | B_COMPRESSION_BREAKOUT | 3.5351 | 2 | 2.1446 | 0.8427% | False |
| 1d | C_BREAKOUT_RETEST | -19.8174 | 15 | 0.3031 | 4.4103% | False |
| 1d | D_VOLUME_ACCUMULATION | 18.1586 | 8 | 2.4773 | 2.9074% | False |
| 1d | E_RELATIVE_STRENGTH | 0.4681 | 67 | 1.0264 | 7.2639% | False |
| 1d | F_MEAN_REVERSION | -0.0657 | 2 | 0.7824 | 0.0602% | False |
| 4h | A_TREND_PULLBACK | -21.2079 | 39 | 0.5972 | 4.4575% | False |
| 4h | B_COMPRESSION_BREAKOUT | -8.0442 | 9 | 0.1828 | 1.7725% | False |
| 4h | C_BREAKOUT_RETEST | 5.5781 | 12 | 1.6790 | 0.8762% | False |
| 4h | D_VOLUME_ACCUMULATION | -7.2273 | 29 | 0.7854 | 2.5301% | False |
| 4h | E_RELATIVE_STRENGTH | -2.8868 | 43 | 0.9472 | 6.2664% | False |
| 4h | F_MEAN_REVERSION | -10.2133 | 8 | 0.0000 | 2.2911% | False |

## Frozen intervals

- 1d: validation 2024-01-28T00:00:00+00:00 to 2025-05-25T00:00:00+00:00; test 2025-06-07T00:00:00+00:00 to 2026-10-15T00:00:00+00:00. UTC, exclusive ends.
- 4h: validation 2026-08-04T04:00:00+00:00 to 2026-09-07T00:00:00+00:00; test 2026-09-09T04:00:00+00:00 to 2026-10-15T00:00:00+00:00. UTC, exclusive ends.

## Benchmarks

| TF | Reference | Net EUR | Return | Max DD |
|---|---|---:|---:|---:|
| 1d | BTC_BUY_HOLD | -103.8371 | -20.7674% | 51.7035% |
| 1d | CASH | 0.0000 | 0.0000% | 0.0000% |
| 1d | EQUAL_WEIGHT_CURRENT_UNIVERSE | -174.0448 | -34.8090% | 70.9845% |
| 1d | ETH_BUY_HOLD | -5.3156 | -1.0631% | 66.7181% |
| 1d | V3_4_SIGNALS_COMMON_EXECUTION | 5.9760 | 1.1952% | 16.7741% |
| 1d | VALIDATED_ENSEMBLE | 0.0000 | 0.0000% | 0.0000% |
| 4h | BTC_BUY_HOLD | 35.9279 | 7.1856% | 6.0796% |
| 4h | CASH | 0.0000 | 0.0000% | 0.0000% |
| 4h | EQUAL_WEIGHT_CURRENT_UNIVERSE | 30.8063 | 6.1613% | 11.5615% |
| 4h | ETH_BUY_HOLD | 2.3650 | 0.4730% | 11.5904% |
| 4h | V3_4_SIGNALS_COMMON_EXECUTION | -20.4754 | -4.0951% | 7.7050% |
| 4h | VALIDATED_ENSEMBLE | 0.0000 | 0.0000% | 0.0000% |

V3.4 denotes its signals on the common V4 historical execution/cost/risk model, not a replay of the original durable application over every historical bar. Passive EUR500 references have different exposure and estimated endpoint liquidation costs. Candidate residual positions are disclosed as marks.

Full JSON retains frozen training choices, validation, four walk-forward windows, cost stress, sample uncertainty, regime/strategy contributions, closed positions and explicit failure reasons. No strategy is selected by test performance. No historical L2 is reconstructed.

CSV exports contain 623 simulated fills and 4260 equity/drawdown rows across twelve separate strategy/timeframe simulations. They are not production account fills.

Earlier diagnostic studies remain on disk. The suspicious-candle correction retains its open execution event and marks quality only after close; the legacy comparison uses the same known-data-quality gate. Reported historical test segments were reused during engineering; prospective never-seen validation is not claimed.

## Comparison to V3.4

Execution realism improves through bid-triggered protection, net target floors and finite shared depth. Costs are more explicit; reduced realized costs are not established. Eligibility and causal regimes replace score-only admission, but no validated signal/regime edge is established. Profiles/correlation add allocation controls without proving superior returns. Financial durability is separately verified. The deployment research gate keeps entries disabled.
