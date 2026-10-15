# Financial risk and promotion validation

Hard repository limits remain EUR500 assigned, EUR350 total exposure, EUR150
uncommitted reserve, EUR100 per position, three positions, EUR5 planned loss,
EUR15 daily / EUR35 weekly equity loss and six entries per day. No shorts,
leverage, averaging down or real exchange order path is enabled.

Account-first locking, reservations, immutable attributed fills/journal, proportional
basis release, atomic target progress and idempotent recovery are retained. Pure
closing postings are shared with research; durable economic effects remain in the
transactional repository. Protective exits remain possible during entry halts.

Conservative/balanced/opportunistic profiles cap proposed quote at50/75/100 and
apply increasingly permissive positive-correlation thresholds, without relaxing
hard financial limits. Missing correlation is explicit; the conservative profile
rejects it when positions exist. Other profiles retain hard portfolio checks.

After TP1, trailing stops use executable bid peaks and observed completed ATR.
Breakeven includes opening basis and closing fee/slippage. The stop never moves
down, even if volatility increases. Stop updates persist an audit incident with
old/new stop, ATR, distance, costs and policy version. Time expiry, failed-breakout
and bearish/stressed-regime reductions retain exact exit attribution and cooldowns.

Production persists VALIDATED_ONLY policy. Approval alone cannot bypass research,
live-timeframe, exact-parameter or source-fingerprint checks. With no validated
strategy, zero new positions is the intended result. Test-only financial acceptance
mode is labeled explicitly and does not manufacture validation metrics.

Execution tests cover bid/mid discrepancies, net target floors, gaps, wide spreads,
finite shared depth, collisions, provider outages, stale watches and repository
reopen. The combined actual-process proof rejects a cost-destroyed BTC proposal,
enters ETH, partially fills TP2, terminates/restarts the interpreter, completes
TP2 and closes protectively. The authenticated API observes five unique fills,
original target attribution and zero reconciliation differences.
