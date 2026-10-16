# V4.2 statistical validation

Canonical run `research-20261016T114522` uses source `9f03f481049165cba9b54082d6f45f6e06e76d4b0a1625832b5f8434f8ace23a`.

Chronological60/20/20 partitions retain12-bar purging and one-bar embargo. Each of three predeclared parameter neighbors is scored only in training; validation/test never retune the selected grid. Four rolling windows refit using earlier observations. The historical interval was already examined; genuinely new evidence requires observations after configuration freeze.

Existing thresholds are unchanged: positive test return/expectancy, PF>1.2, at least60 closed positions and30 independent entry dates, drawdown≤10%, positive/diverse assets and regimes, three positive walk-forward windows out of four, positive validation, cost robustness, parameter-neighbor robustness, no missing-position data, multi-timeframe validation and multiple-comparison-aware uncertainty.

The experimental family uses a conservative minimum300 comparisons, familywise alpha.05 and10,000 deterministic bootstrap repetitions with four-week blocks of active entry weeks where enough weeks exist. Sparse active weeks, omitted no-entry weeks, dependence and tail Monte Carlo resolution limit inference. No independent-trade assumption or fabricated p-value is used.

| Strategy | Closed / entry dates | Weekly block interval | Failed gates |
|---|---|---|---|
| A2_CONFIRMED_PULLBACK | 8 / 5 | None | positive_oos_net_return, positive_oos_expectancy, oos_profit_factor_above_1_2, adequate_closed_positions, independent_entry_dates, asset_diversity, regime_diversity, stable_walk_forward, cost_sensitivity, parameter_neighborhood, multiple_comparison_block_interval_positive, positive_validation_net_profit, multiple_timeframe_validation |
| B2_CONFIRMED_COMPRESSION | 2 / 2 | None | positive_oos_net_return, positive_oos_expectancy, oos_profit_factor_above_1_2, adequate_closed_positions, independent_entry_dates, asset_diversity, regime_diversity, stable_walk_forward, cost_sensitivity, parameter_neighborhood, multiple_comparison_block_interval_positive, positive_validation_net_profit, multiple_timeframe_validation |
| C2_LIQUID_RETEST | 1 / 1 | None | positive_oos_net_return, positive_oos_expectancy, oos_profit_factor_above_1_2, adequate_closed_positions, independent_entry_dates, asset_diversity, regime_diversity, stable_walk_forward, cost_sensitivity, parameter_neighborhood, multiple_comparison_block_interval_positive, positive_validation_net_profit, multiple_timeframe_validation |
| E2_ABSOLUTE_RELATIVE_STRENGTH | 0 / 0 | None | positive_oos_net_return, positive_oos_expectancy, oos_profit_factor_above_1_2, adequate_closed_positions, independent_entry_dates, asset_diversity, regime_diversity, stable_walk_forward, cost_sensitivity, parameter_neighborhood, multiple_comparison_block_interval_positive, positive_validation_net_profit, multiple_timeframe_validation |
| F2_RESTRICTED_RANGE | 0 / 0 | None | positive_oos_net_return, positive_oos_expectancy, oos_profit_factor_above_1_2, adequate_closed_positions, independent_entry_dates, asset_diversity, regime_diversity, stable_walk_forward, cost_sensitivity, parameter_neighborhood, multiple_comparison_block_interval_positive, positive_validation_net_profit, multiple_timeframe_validation |

The variants are specified for5m timing with completed15m/1h context. Independent15m primary-signal validation is unsupported; the existing multiple-timeframe promotion gate remains false. This is disclosed rather than weakened. Low drawdown alone passes one check and cannot compensate for a failed evidence base.

**NO STRATEGY PASSED VALIDATION.** No experiment is PAPER_APPROVED. All candidate identities preserve their computation source, parameter, dataset and execution-assumption hashes. A source mismatch blocks admission; shadow activity is explicitly unvalidated and confers no approval.
