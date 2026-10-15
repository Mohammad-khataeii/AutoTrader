# V2 Backtesting

Current state:

- Backtester reuses the strategy, decision, risk, portfolio, and paper broker layers.
- It reports net profit, total return, max drawdown, profit factor, win rate, expectancy, Sharpe, exposure, turnover, and trade count.
- It avoids fabricating profitability; tests assert reproducible report generation only.

Still pending:

- Multi-asset backtests
- Walk-forward validation
- Out-of-sample evaluation
- Parameter sensitivity analysis
- Monte Carlo resampling
- Strategy/regime attribution
- Missed-opportunity research pipeline

