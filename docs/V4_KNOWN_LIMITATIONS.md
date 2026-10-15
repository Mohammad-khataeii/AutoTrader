# Known limitations

- No strategy passed validation. Positive isolated returns are not an approved edge.
- The validated ensemble is empty and its cash result is verified. A nonempty
  ensemble of validated candidates has not been demonstrated. Research ensemble
  simulations currently use runtime-default parameters; before reporting a
  nonempty optimized ensemble, replay each member with its own frozen parameters.
  Production's exact-parameter gate independently refuses nonmatching research
  parameters. No nonempty ensemble or optimized-ensemble return is claimed here.
- Coinbase EUR history is a proxy for Revolut X; current-universe survivorship bias
  and delisted/missing intervals remain explicit. Multi-year depth exists for daily
  bars; hourly/4h cover180days and intraday only2days by default.
- No historical L2, queue position, actual latency, or historical tick-size schedule
  is available. Historical spread, volume participation, precision, sizing cushion
  and IOC availability are assumptions. Runtime uses current venue metadata.
- Research is a deterministic in-memory event simulation sharing core calculations;
  production durability is verified separately on PostgreSQL. OHLCV targets require
  close quotes and one target/event; intrabar stops use conservative ordering.
- Source candles identify starts; research `available_at` identifies when the full
  candle becomes knowable. No pre-close eligibility is claimed.
- Historical test segments were reused during engineering fixes. No prospective
  never-seen live result or future profitability claim is made.
- Bootstrap and independent-entry-date counts approximate dependence; sparse assets,
  regimes and no-entry weeks limit statistical confidence.
- Remaining open positions are disclosed and marked, not silently liquidated.
  Passive reference endpoints include estimated liquidation costs and different
  exposure; their full-capital allocations are not executable bot recommendations.
- Paid GPT-6 Sol account access, paid predictive contribution and independently
  sourced news edge are unverified. Mock comparisons establish integration only.
- Authentication failure throttling is bounded per API process. A deployment with
  multiple API processes needs a shared throttle/proxy policy.
- Consumed-book observations and feedback JSON currently accumulate; safe archival
  must preserve any observation referenced by pending intents and audit retention.
- Research jobs use durable leases and restart by recomputing a run after lease
  expiry. Partial failed artifacts remain available; they are not completed studies.
- Support-image security findings remain separately assessed; optional monitoring
  must remain disabled while its applicable/unresolved high/critical findings remain.
- Original user database migration was not executed; testing/deployment/restore
  used explicitly isolated databases and preserved existing volumes.
