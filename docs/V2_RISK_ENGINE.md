# V2 Risk Engine

The existing deterministic risk engine continues to enforce:

- EUR 500 maximum allocation
- EUR 350 maximum open exposure
- EUR 150 minimum reserve
- EUR 100 maximum position size
- Three maximum positions
- EUR 5 default planned risk per trade
- Daily and weekly loss thresholds
- Six new entries per day

V2 change: decision sizing now includes an execution-cost cushion before quantity calculation so persistent market orders do not require spending more than reserved capital.

Still pending:

- Correlation controls
- Maximum spread/slippage checks inside risk policy
- Emergency stop table/state
- Consecutive-loss cooldown
- BTC breakdown detection
- Database/API failure circuit breaker

