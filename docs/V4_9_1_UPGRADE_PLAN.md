# V4.9.1 audit and upgrade plan

The development audit covers 28 October 2026 18:47:54 UTC through 29 October 06:47:54 UTC. It contains four closed primary trades with net loss €32.472721319668, including €5.555030050344 fees. The primary remains funded once, reconciled, and paper-only. The full V4.9 period currently has six losing primary trades; this small, correlated sample does not establish statistical expectancy.

## Evidence and causal limits

Preserve every actual entry, refusal, fill, fee, exit, original profile and shadow history. Reconstruct completed-bar context at each decision, separating saved entry evidence from retrospective reconstruction. Compare independent futures percentage paths with EUR spot paths; futures books and present-day indicator readings do not establish historical Revolut execution. Do not optimize thresholds on these four losses or claim a favorable filtered replay is prospective profit.

The old diagnostic collector materialized large history into a PostgreSQL JSON aggregate. It exhausted a database process memory limit during this audit and had caused the same failure earlier that morning. Replace it with a read-only row stream, fixed cutoff, explicit byte limits and completeness metadata. No service restart or live-source patch is part of local implementation.

## Frozen implementation scope

1. Add a **primary-only, versioned admission policy**, leaving the six existing strategy recipes, seven V4.9 shadow control hypotheses, costs, stops, exit priority and numerical risk limits unchanged. Record the base eligibility and the new policy separately.
2. At both locked admission and dispatch, require the signal's completed five-minute candle to be the current requested completed candle. A scan crossing the next boundary must wait for a new evaluation. NEAR's saved 22:20 signal reached admission at 22:30:00, after the next candle had completed; this is a freshness defect, not proof that the replacement decision would win.
3. Require aligned completed BTC/ETH context and sufficient contiguous completed hourly history. Reject primary longs when **both** benchmark hourly trends are BEARISH under the existing EMA9/21 classifier. A short five-minute MIXED reading is not evidence of an established favorable hourly environment.
4. Require the asset's latest completed close to reclaim its EMA9 while that mean is not falling. For early recovery, additionally require a completed fifteen-minute close above EMA21 with a rising close. These are conservative structural hypotheses using existing periods, not estimated probabilities or asset-specific fitted thresholds.
5. Keep the existing shadow controls running under their original execution identity if that fingerprint remains byte-for-byte unchanged. They are controls with different entry policies, not matched executions of the new primary guard. Do not create/reset funding to improve statistics.
6. Report the entry-time bearish/ranging context, actual local reversal exit, gross price result, fees and stop slippage honestly. Preserve generic intent codes and raw history; display the recorded detailed cause rather than implying every MARKET_RISK exit was a broad market crash.
7. Test positive, negative, missing, malformed, stale, boundary-crossing and retry cases, including real locked PostgreSQL admission. Replay all recorded entries, including the earlier winning control, as development diagnostics. Preserve any loss the new policy still permits. Full source-bound tests, builds and restore rehearsal are release gates; positive expectancy remains UNKNOWN.

## Release and deployment

Use the existing feature branch. Prepare V4.9.1 with a new primary runtime profile and immutable source/image identity. Preserve the current seventeen databases and seven original control ledgers. The deployment must pause new entries, retain old protection until every retained account is flat, back up and restore-verify all seventeen databases, rehearse the new primary profile without re-funding, cut over the exact approved commit, and verify all ledgers again before resume. Keep old source/images and rollback capability. Do not touch the old production server, Tailscale access, unrelated services or real trading.

The audit window is development evidence. Neither avoiding known losing entries nor a short paper run proves positive expectancy. Any later profitability claim requires a new preregistered evaluation on unused data and sufficient independent prospective episodes. The repository's exact-release approval boundary applies after Stage A.
