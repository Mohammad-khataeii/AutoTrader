# V4.2 trade failure analysis

All 833 original positions (2,204 fills) across six strategies and two timeframes were reconstructed from the frozen V4.1 run. All are closed; no position was omitted. Original results and financial records were not rewritten. These are previously examined historical Coinbase EUR OHLCV proxies, not Revolut X historical order books.

Reproduce: `autotrader research diagnose --root .data/research --run .data/research/runs/research-20261016T044934`. The output contains every causal entry feature, reproduced signal, initial stop/targets, fees/spread/slippage, exit posting, classification predicate, excursion bounds and matched-entry exit hypothesis. Full immutable evidence: `evidence/v4_2-original-trade-diagnostics.json.gz`.

## What the records support

| Timeframe / strategy | Closed | Losers | Net EUR | Fees EUR | All modeled cost drag EUR | Losses positive without modeled costs at fixed fills | Mean age min |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5m A_TREND_PULLBACK | 126 | 89 | -24.1342 | 15.2596 | 35.0972 | 23 | 40.0 |
| 5m B_COMPRESSION_BREAKOUT | 77 | 51 | -11.7928 | 11.1276 | 25.5935 | 16 | 24.0 |
| 5m C_BREAKOUT_RETEST | 67 | 54 | -18.4963 | 8.4476 | 19.4294 | 17 | 22.2 |
| 5m D_VOLUME_ACCUMULATION | 129 | 93 | -33.3256 | 18.2554 | 41.9874 | 27 | 28.2 |
| 5m E_RELATIVE_STRENGTH | 17 | 11 | -6.1916 | 2.2908 | 5.2688 | 3 | 23.2 |
| 5m F_MEAN_REVERSION | 79 | 64 | -18.8279 | 8.2424 | 18.9576 | 22 | 20.1 |
| 15m A_TREND_PULLBACK | 91 | 65 | -12.7027 | 10.1917 | 23.4408 | 17 | 97.4 |
| 15m B_COMPRESSION_BREAKOUT | 50 | 35 | -14.3024 | 7.0953 | 16.3192 | 6 | 66.6 |
| 15m C_BREAKOUT_RETEST | 40 | 32 | -11.9309 | 4.8568 | 11.1705 | 12 | 70.9 |
| 15m D_VOLUME_ACCUMULATION | 84 | 64 | -29.2628 | 12.3444 | 28.3921 | 16 | 97.5 |
| 15m E_RELATIVE_STRENGTH | 25 | 13 | -1.5114 | 3.1616 | 7.2717 | 4 | 104.4 |
| 15m F_MEAN_REVERSION | 48 | 37 | -16.5550 | 5.9072 | 13.5866 | 14 | 54.1 |

Cost attribution holds recorded quantities and execution events fixed. Adding costs back is not a zero-cost portfolio simulation: entries, exits and capital constraints would change. Costs materially consume small price moves; they do not explain all losses. High turnover and small reward relative to friction warrant testing fewer, better-confirmed entries. There is no evidence here that a new rule will be profitable.

## Measured classifications

| Label | Positions | Rule / interpretation |
|---|---:|---|
| ADVERSE_TREND | 61 | causal EMA21 below EMA50 |
| CORRELATION_EXPOSURE | 102 | causal 20-return correlation at least .75 with an already-held position; diagnostic context, not proof of loss or a .90 balanced-cap violation |
| COST_EXCEEDS_EDGE | 177 | loss changes sign adding modeled costs back at fixed recorded fills; not a no-cost portfolio replay |
| ENTRY_TOO_LATE | 333 | entry mid exceeds causal EMA21 by more than 2 ATR |
| FALSE_BREAKOUT | 210 | recorded failed-breakout exit predicate fired |
| INSUFFICIENT_EVIDENCE | 833 | OHLCV proxy: no historical L2, queue, intrabar path or per-position rejected-risk history |
| LATE_EXIT | 74 | earlier completed-close liquidation mark positive, final realized loss; alternative fill unproven |
| LOW_LIQUIDITY | 273 | entry consumed at least 80% of modeled prior-volume depth; historical L2 unknown |
| PREMATURE_EXIT | 299 | one-bar-later matched-entry IOC scenario improves P&L; hypothesis only, ignores intervening protective obligations |
| STOP_TOO_TIGHT | 198 | initial stop distance no greater than modeled round-trip cost fraction |
| TIMEOUT_EXIT | 278 | recorded maximum-holding-time exit |

Counts overlap. ENTRY_TOO_LATE is the declared >2 ATR extension diagnostic, not proof that waiting would improve the portfolio. LOW_LIQUIDITY refers to the assumed prior-volume depth, not observed exchange depth. FALSE_BREAKOUT means a recorded exit predicate fired. A loss alone never receives a causal explanation. No observed 10 bps spread is classified as >25 bps. There are no fabricated probability estimates.

## Excursions and exit quality

Of 608 losing positions, 181 had a positive modeled net favorable-price lower bound; 74 had an earlier positive completed-close whole-lot liquidation mark. 56 positions had a recorded stop bar whose high also touched the initial first target. Stop priority remains conservative. A candle high is never treated as proof of executable target liquidity.

The net excursion formula includes recorded opening basis and modeled bid-side spread, sell slippage and sell fee. It marks the original lot, so it must not be confused with realized P&L after partial exits. Stop-bar highs enter only the opportunity upper bound; their unknown adverse path is censored. Trailing-stop evolution is not fully archived in old artifacts. The recorded stop posting remains authoritative.

Earlier (two bars) and later (one bar) exit scenarios retain the same original entry and require full whole-lot modeled finite depth to report P&L. Missing data, zero depth, partial depth or observations outside the run produce unavailable results. These scenarios ignore intervening protective obligations and replace actual partial exits; they are hypotheses, not executable portfolio returns or reasons to delay a protective stop.

## Examples from actual records

| Timeframe / position | Net EUR | Net MFE lower / upper | Final exit | Labels |
|---|---:|---|---|---|
| 5m research-AVAX-EUR-2026-09-20T16:55:00+00:00 (D_VOLUME_ACCUMULATION) | -2.0979 | -0.0009550782378518482760523100 / -0.0009550782378518482760523100 | STOP_GAP | INSUFFICIENT_EVIDENCE, TIMEOUT_EXIT |
| 5m research-AVAX-EUR-2026-09-20T16:15:00+00:00 (E_RELATIVE_STRENGTH) | -1.7331 | 0.000168932974848730410867752 / 0.000168932974848730410867752 | STOP_INTRABAR_CONSERVATIVE | INSUFFICIENT_EVIDENCE, PREMATURE_EXIT |
| 5m research-ETH-EUR-2026-09-11T13:45:00+00:00 (B_COMPRESSION_BREAKOUT) | 1.9670 | 0.044133748608280205739276942 / 0.044133748608280205739276942 | TAKE_PROFIT_CLOSE_IOC | INSUFFICIENT_EVIDENCE, PREMATURE_EXIT |
| 5m research-ETH-EUR-2026-09-11T13:35:00+00:00 (A_TREND_PULLBACK) | 2.4787 | 0.051093607741363970417919371 / 0.051093607741363970417919371 | TAKE_PROFIT_CLOSE_IOC | CORRELATION_EXPOSURE, INSUFFICIENT_EVIDENCE, PREMATURE_EXIT |
| 15m research-LINK-EUR-2026-09-28T17:15:00+00:00 (E_RELATIVE_STRENGTH) | -2.5969 | -0.0022851594278101916528718517 / -0.0022851594278101916528718517 | STOP_INTRABAR_CONSERVATIVE | ENTRY_TOO_LATE, INSUFFICIENT_EVIDENCE, PREMATURE_EXIT |
| 15m research-LINK-EUR-2026-09-28T13:30:00+00:00 (E_RELATIVE_STRENGTH) | -2.2163 | 0.009013028219523099594174178 / 0.009013028219523099594174178 | STOP_INTRABAR_CONSERVATIVE | ENTRY_TOO_LATE, INSUFFICIENT_EVIDENCE, LATE_EXIT |
| 15m research-LINK-EUR-2026-09-28T16:00:00+00:00 (A_TREND_PULLBACK) | 2.5921 | 0.048301338733286921186610733 / 0.048301338733286921186610733 | FAILED_BREAKOUT | FALSE_BREAKOUT, INSUFFICIENT_EVIDENCE, PREMATURE_EXIT |
| 15m research-LINK-EUR-2026-09-28T16:00:00+00:00 (E_RELATIVE_STRENGTH) | 2.5921 | 0.048301338733286921186610733 / 0.048301338733286921186610733 | FAILED_BREAKOUT | FALSE_BREAKOUT, INSUFFICIENT_EVIDENCE, PREMATURE_EXIT |

## Asset and regime attribution

### Asset

| Group | Positions | Net realized EUR | Mean winner EUR | Mean loser EUR |
|---|---:|---:|---:|---:|
| ADA-EUR | 125 | -11.2589 | 0.5343 | -0.4175 |
| AVAX-EUR | 100 | -19.7964 | 0.4646 | -0.5243 |
| BTC-EUR | 65 | -20.8023 | 0.5365 | -0.4577 |
| DOT-EUR | 19 | -2.8738 | 0.2739 | -0.5339 |
| ETH-EUR | 104 | -25.9572 | 0.3884 | -0.4846 |
| LINK-EUR | 88 | -25.0153 | 0.6106 | -0.6394 |
| SOL-EUR | 152 | -45.3966 | 0.3467 | -0.4508 |
| XRP-EUR | 180 | -47.9334 | 0.3621 | -0.5013 |
### Regime

| Group | Positions | Net realized EUR | Mean winner EUR | Mean loser EUR |
|---|---:|---:|---:|---:|
| COMPRESSION | 539 | -128.7341 | 0.3266 | -0.4259 |
| EXPANSION | 200 | -51.2269 | 0.5494 | -0.5541 |
| MODERATE_BULL | 56 | 1.0288 | 0.6887 | -0.5222 |
| RANGE | 4 | -1.5317 | 0.0271 | -0.5196 |
| STRONG_BULL | 34 | -18.5698 | 0.8056 | -1.1926 |

These totals combine separate EUR 500 simulations and are diagnostic sums, not one funded account or a tradable ensemble. Each strategy/timeframe result remains independently comparable.

## Frozen hypotheses motivated by these observations

Test controlled pullbacks and extension rejection (A2/D2); acceptance after compression and retest recovery (B2/C2); absolute benchmark risk alongside relative strength (E2); and a restricted RANGE-only mean-reversion hypothesis (F2). Use causal completed 15m/1h context. Preserve failed original strategies, strict gates and all negative results. Do not treat the examined intervals as untouched holdouts.

## Limits and verification

No per-position rejected-risk sequence or historical queue/L2 is available. Entry cash and concurrent positions are reconstructed in recorded fill order. Causal20-return correlations use only matching completed-feature timestamps;102 positions meet the declared .75 diagnostic threshold, below the existing .90 balanced cap. This is association/context, not proof of loss. Only narrow exit counterfactuals are implemented; stop/entry alternatives remain untested hypotheses. Every record carries INSUFFICIENT_EVIDENCE for these limits. Eight targeted tests cover actual signal reconstruction, full coverage/cost reconciliation, lookahead/provenance rejection, exact late-entry/spread/cost/false-breakout/premature-exit predicates and conservative stop/target collision. Command: `python3 -m pytest -q tests/test_v42_diagnostics.py`: **8 passed**.

Diagnostic schema4.2.0-diagnostics.4 distinguishes the admission bid-target scenario, a hypothetical midpoint touch and the executed net target floor. Recorded exit VWAP/fees enter net excursion bounds, including adverse gap exits. Counterfactuals require exact earlier/later timestamps and a contiguous prior depth bar. The corrected cost-sign-crossing count is177; the initial midpoint-target flags are retained as superseded evidence. Full chronological entry cash, concurrent positions, correlation context and observed curve risk halts are included per position.
