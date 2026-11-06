# €7,000 crypto paper loss forensics

**Account** `PERSONAL_PLAN_PAPER_7000`

**Archive** `crypto-paper-loss-audit-20261106T114139Z.jsonl.gz`

**SHA-256** `e4cb30a5634e761d878ec3bc03f68ccb546eaf10567475246564956bfdca4dd7`

**Capture** 6 November 2026 at 11:41:39 UTC

**Source reviewed** `201f8e98e1d09f695f7c433009c04a16cc49197f`

The read-only export passed gzip, declared counts, account identity, unique ID and position/order/fill/journal reconciliation checks. All 15 closed positions reconcile to linked cash and realized-P&L postings within €0.000001 of the export. The analysis uses the entry plan for strategy ownership and retains original order labels. Some buys were partially filled. The report contains derived findings; the archive stays outside Git.

```sh
PYTHONPATH=src python3 -m autotrader.crypto_research audit \
  "$HOME/Downloads/crypto-paper-loss-audit-20261106T114139Z.jsonl.gz" \
  --output /tmp/crypto-7000-forensics.json
```

## Ledger results

Equity was €6,900.67 versus €7,000 funded. The 15 trades realized −€99.33 after €20.84 in fees, with one winner and fourteen losers (6.7%). Price P&L before fees was −€78.49, and mean realized P&L was −€6.62 per closed trade. The last seven realized −€60.94. Summing before rounding gives −€39.09 across seven A3 trades, −€24.74 across five Early Recovery trades and −€35.49 across three Trend Pullback trades. The same method yields −€84.30 for nine stop exits, −€19.87 for four market-risk exits and +€4.84 for two time exits. These totals use the raw ledger precision and can differ by a few cents from the request. The 360 exported equity snapshots all have the same terminal equity, so they cannot establish peak-to-trough mark-to-market drawdown. The comparisons below calculate closed-trade drawdown only.

## Original entry evidence and completed-candle reconstruction

Times are UTC. BTC/ETH are percentage returns over 12 five-minute close-to-close intervals ending at the most recent fully completed bar before the earlier recorded execution event. Asset return and structure use the original signal's completion time. Bar observation receipts were absent from the audit. Completion is the earliest possible availability and the reconstruction cannot establish when the live worker actually received each bar. Entry book and fill values are recorded facts. Displayed book timestamp is a provider timestamp. The position event precedes the order database timestamp by milliseconds in this export, so the earlier event bounds entry features. The reconstructed stop/noise column divides the filled-entry-to-stop distance by a prior-bar ATR proxy; this differs from the original quality-policy ratio.

| UTC entry | Asset / strategy | Profile / recorded benchmark | BTC / ETH 1h | Asset 1h / reconstructed structure | Stop / prior ATR | Exit / min | Net EUR |
|---|---|---|---:|---|---:|---|---:|
| 10-27 18:40:55 | PEPE-EUR / A3 | 4.7.1-paper.1 / supportive | -0.04% / -0.11% | -0.32% / unconfirmed | 1.64 | time exit / 180.1 | +9.72 |
| 10-27 20:01:05 | ENA-EUR / A3 | 4.7.1-paper.1 / supportive | +0.25% / +0.14% | +0.32% / unconfirmed | 1.70 | stop / 21.0 | -6.18 |
| 10-28 15:06:18 | PEPE-EUR / Recovery | 4.9.0-paper.1 / mixed | -0.25% / -0.18% | -0.25% / persistent recovery | 3.33 | market risk / 85.2 | -8.92 |
| 10-28 15:08:42 | ENA-EUR / Recovery | 4.9.0-paper.1 / mixed | -0.25% / -0.18% | -1.02% / persistent recovery | 2.90 | market risk / 12.8 | -0.52 |
| 10-28 22:16:26 | PEPE-EUR / Pullback | 4.9.0-paper.1 / mixed | -0.07% / -0.07% | -0.74% / persistent recovery | 1.32 | stop / 79.9 | -10.72 |
| 10-28 22:30:00 | NEAR-EUR / A3 | 4.9.0-paper.1 / mixed | +0.11% / +0.01% | -0.09% / persistent recovery | 1.46 | stop / 148.6 | -11.33 |
| 10-29 02:56:49 | ZRO-EUR / Recovery | 4.9.0-paper.1 / mixed | -0.37% / -0.40% | -1.21% / persistent recovery | 2.23 | market risk / 19.3 | -9.36 |
| 10-29 04:41:22 | ADA-EUR / Recovery | 4.9.0-paper.1 / mixed | +0.29% / +0.43% | +1.07% / breakout unretested | 3.99 | market risk / 79.4 | -1.06 |
| 10-29 16:55:33 | PEPE-EUR / Pullback | 4.9.1-paper.1 / mixed | -0.47% / -0.35% | +0.41% / persistent recovery | 1.31 | stop / 89.2 | -18.34 |
| 10-30 06:56:08 | XRP-EUR / Pullback | 4.9.2-paper.1 / mixed | -0.02% / +0.40% | +0.79% / unconfirmed | 2.06 | stop / 15.7 | -6.44 |
| 11-02 01:10:57 | ETH-EUR / Recovery | 4.9.5-paper.1 / supportive | -0.02% / +0.56% | +0.56% / breakout unretested | 4.37 | time exit / 360.0 | -4.88 |
| 11-04 16:51:21 | XRP-EUR / A3 | 4.9.5-paper.1 / supportive | +0.35% / +0.64% | -0.37% / unconfirmed | 1.38 | stop / 13.9 | -6.48 |
| 11-04 18:04:15 | NEAR-EUR / A3 | 4.9.5-paper.1 / supportive | -0.29% / -0.60% | -0.14% / unconfirmed | 2.20 | stop / 32.4 | -14.85 |
| 11-04 18:10:38 | SOL-EUR / A3 | 4.9.5-paper.1 / supportive | -0.00% / +0.00% | -0.44% / persistent recovery | 0.87 | stop / 28.3 | -3.98 |
| 11-04 18:36:12 | ADA-EUR / A3 | 4.9.5-paper.1 / supportive | +0.38% / +0.44% | +0.82% / breakout unretested | 1.83 | stop / 1.7 | -5.99 |

A3 recorded strategy version `4.6.0-experimental.2`. Both RAOE strategies recorded `4.9.0-raoe.1`. Profile prefixes in chronological order were `e52e6634a4ea` (4.7.1), `071dc966890e` (4.9.0), `0a121031ee69` (4.9.1), `27512b3460ea` (4.9.2) and `76b7e5d31cdb` (4.9.5). XRP on October 30 recorded backend `1c1b758f80deac18725167c234469cc0895a0120`, ETH on November 2 recorded `40c72988a11e0488895e131340837f7bc7dc21d0`, and the four November 4 trades recorded `a5720dca2592929c69d99442e8a89450fbb0c06b`. Earlier buy evidence lacks a full backend identity. The reproducible JSON emits the original admission gates where recorded, exact manifest identifiers, entry/exit prices, and trade path coverage.

| UTC entry / asset | Entry ask → fill | Initial stop → exit fill | Entry / exit spread bps | Modeled signal / locked loss EUR | Exit top-bid gap / depth and slippage EUR |
|---|---:|---:|---:|---:|---:|
| 10-27 18:40 PEPE-EUR | 0.0000040156 → 4.018812e-06 | 0.0000039832 → 4.082931e-06 | 10.5 / 10.0 | 8.14 / — | — / 0.57 |
| 10-27 20:01 ENA-EUR | 0.1891 → 0.18925128 | 0.1881 → 0.18794952 | 15.9 / 15.9 | 6.20 / — | 0.00 / 0.55 |
| 10-28 15:06 PEPE-EUR | 0.0000043683 → 4.371794e-06 | 0.0000043193 → 4.324556e-06 | 10.3 / 8.3 | 9.94 / 10.31 | — / 0.60 |
| 10-28 15:08 ENA-EUR | 0.1750 → 0.17514 | 0.1729 → 0.1753596 | 17.2 / 17.1 | 11.28 / 10.84 | — / 0.56 |
| 10-28 22:16 PEPE-EUR | 0.0000045233 → 4.526918e-06 | 0.0000044811 → 4.46636e-06 | 17.3 / 4.9 | 8.83 / 9.04 | 0.85 / 1.42 |
| 10-28 22:30 NEAR-EUR | 4.2338 → 4.23720092 | 4.2081 → 4.17671589 | 21.3 / 62.4 | 7.22 / 7.20 | 4.08 / 1.08 |
| 10-29 02:56 ZRO-EUR | 1.4600 → 1.46868546 | 1.4476 → 1.45193752 | 22.6 / 67.2 | 11.98 / 11.98 | — / 0.55 |
| 10-29 04:41 ADA-EUR | 0.17829 → 0.178432632 | 0.17662 → 0.178519216 | 18.0 / 7.8 | 9.16 / 9.14 | — / 0.63 |
| 10-29 16:55 PEPE-EUR | 0.0000048199 → 4.823755e-06 | 0.0000047128 → 4.706202e-06 | 14.1 / 15.9 | 18.99 / 18.11 | 0.25 / 0.71 |
| 10-30 06:56 XRP-EUR | 1.1320 → 1.1329056 | 1.1261 → 1.12470673 | 15.0 / 16.9 | 6.02 / 6.19 | 0.25 / 0.61 |
| 11-02 01:10 ETH-EUR | 2046.36 → 2047.99709 | 2029.36 → 2037.75821 | 10.8 / 5.9 | 8.20 / 8.35 | — / 0.90 |
| 11-04 16:51 XRP-EUR | 1.1704 → 1.17142607 | 1.1639 → 1.16286896 | 8.5 / 12.9 | 6.59 / 6.46 | 0.06 / 0.55 |
| 11-04 18:04 NEAR-EUR | 3.6600 → 3.67921887 | 3.6322 → 3.60840118 | 0.3 / 71.8 | 11.04 / 10.88 | 1.56 / 2.96 |
| 11-04 18:10 SOL-EUR | 85.218 → 85.2861744 | 85.045 → 84.9690116 | 11.3 / 9.8 | 5.20 / 3.92 | 0.04 / 0.58 |
| 11-04 18:36 ADA-EUR | 0.17581 → 0.175950648 | 0.17499 → 0.174790056 | 22.8 / 14.9 | 5.81 / 5.75 | 0.24 / 0.55 |

### Reading each position

- **October 27 PEPE A3.** The original 15-minute and hourly continuation flags passed and the trade made €9.72 at expiry. It is the sole winner. Both research horizons declined together, so the proposed shared macro filter would also have rejected this position.
- **October 27 ENA A3.** The original higher frames passed with supportive benchmarks. The subsequent stop executed at the observed stop bid before modeled costs. This is a losing setup under favorable benchmark context and provides a control against attributing all losses to macro.
- **October 28 PEPE Recovery.** Recorded 15-minute bearish structure coexisted with a locally persistent bounce and a ranging hour. The market-risk exit followed a negative excursion. A confirmed higher-timeframe reversal is a testable alternative to wider stops.
- **October 28 ENA Recovery.** Both recorded asset frames were bearish and the asset fell about 1% over the preceding hour. The small realized loss followed a market-risk exit, so the full planned risk was never realized.
- **October 28 PEPE Pullback.** Higher frames were bullish and a recovery persisted, but the asset had fallen about 0.74% over the prior hour. It held over an hour before stopping. The stop fill involved both a below-stop bid and additional depth/slippage.
- **October 28 NEAR A3.** Benchmark returns at the signal and execution cutoffs differed materially. The entry sat about one extra bar behind the execution cutoff. The €11.33 loss exceeded the locked €7.20 estimate, with about €4.08 in stop-to-top-bid gap and €1.08 total modeled exit depth/slippage, some of which the original plan already included.
- **October 29 ZRO Recovery.** Original 15-minute and hourly trends were bearish. Both benchmarks fell over the reconstructed hour and the asset was weaker still. The entry was a partial fill. It exited on market risk after a short-lived recovery.
- **October 29 ADA Recovery.** Original hourly and four-hour trends were bearish despite local strength. The pattern was an unretested breakout in the reconstruction. Completed bars show about 1.10% favorable excursion during the hold, with a negative market-risk exit.
- **October 29 PEPE Pullback.** The original hourly EMA checks called both benchmarks bullish despite negative recent returns. The trade achieved about 2.20% favorable completed-candle excursion and stopped at −€18.34. A giveback rule requires executable depth evidence even when the OHLC path shows a gain.
- **October 30 XRP Pullback.** The original higher context was 15-minute bullish and hourly ranging. The admission proof reported BTC ranging and ETH bearish. It stopped after a short hold despite positive asset relative momentum.
- **November 2 ETH Recovery.** Original 15-minute, hourly and four-hour trends were bullish. The six-hour hold reached about +1.11% favorable completed-candle excursion before a −€4.88 time exit. That makes it useful for a giveback test. The export has no executable book during the favorable excursion.
- **November 4 XRP A3.** The asset fell about 0.37% while both benchmarks rose. Original A3 qualified on continuation and cost conditions. A synchronized relative-strength requirement rejects this case.
- **November 4 NEAR A3.** Original admission called both hourly trends bullish, and the A3 label was supportive. The recorded signal closed at 18:00, and both benchmarks had fallen substantially over the hour by execution at 18:04. The market-data reconstruction does not prove live receipt. The €14.85 loss exceeded the locked €10.88 estimate. The exit book was about 71.8 bps wide, with €1.56 stop-to-top-bid gap and €2.96 top-bid-to-fill impact/slippage. Top bid displayed only 3.24503 units versus roughly 190 units sold.
- **November 4 SOL A3.** The stop was about 0.28% below the filled entry. The original quality ratio was 1.55 ATR; a prior-bar true-range reconstruction gives 0.87 ATR. The trade was active while NEAR was open. Both stops completed shortly after the ADA entry.
- **November 4 ADA A3.** The original admitted with bullish higher context and passing economics. The research pattern was unretested. The stop was hit in about 104 seconds with no fully held candle. This supports a test of entry timing; it cannot distinguish intrabar noise from a failed continuation using five-minute bars alone.

Intent-to-fill intervals in the linked export were roughly 0.03–0.17 seconds. They measure simulated bookkeeping after the exit intent. First adverse bid, polling latency, and the continuous depth path are absent. The two NEAR losses are consistent with gaps and thin executable bid depth; there is insufficient evidence to attribute them to delayed protective monitoring. Planned stop losses are conditional estimates and the realized bid path can exceed them. Wider stops were tested only with size capped to the original modeled risk and a €35 ceiling.

## Source findings

- `personal_paper/runtime.py` reads `raoe_regime` for its supplementary BTC/market-risk check. `raoe/regime.py` supplies that shape for RAOE. `opportunity/engine.py` supplies `regime_assessment` for A3, so its supplementary lookup is empty. A3 still passes through `personal_paper/admission.py`, which vetoes two completed bearish hourly EMA trends. November 4 evidence records BTC and ETH bullish on this EMA definition for all four A3 buys. `opportunity/regime.py` uses synchronized benchmark trend support rather than short-horizon downside momentum. A fast joint selloff can pass these conditions.
- `personal_paper/selection.py` already checks A3 hourly confirmation, resistance, cost headroom and stop distance relative to ATR. The A3 recipe in `opportunity/engine.py` recognizes a local pullback and recovery. B3 separately tests a delayed retest. The present RAOE runtime rejects a bearish hour and additionally a bearish 15-minute Early Recovery; primary admission already requires a rising 15-minute reclaim. The October 28–29 adverse recovery cases occurred under an earlier profile. Reintroducing the current requirements would not be a new edge.
- A3 rank uses conditional target reward/risk and reward/cost. Its expected value field is explicitly unestimated. Achieving a target must be modeled separately from the payoff if achieved.
- The locked account repository treats coins as one conservative capital cluster and limits aggregate stop risk. The runtime has a per-symbol cooldown after a recent loss. Together these controls can still permit three differently named €700 positions sharing the same market thesis. The historical ablation tests a 30-minute window and a realized-loss cooldown separately from the shared macro observation. It never reads the future loss when admitting an earlier trade.
- `position_manager.py`, `personal_paper/exits.py`, and `execution/pricing.py` preserve position-specific stops, hold-time and plan semantics with book-based execution. Spread, depth, gaps, fees and modeled slippage change realized risk. The challenger has no gateway or order authority.
- The five trades cited in the request with both benchmarks down lost €51.99 combined. With the explicit 12-interval close-to-close method used here, three of those five satisfy strictly below −0.2% on both benchmarks (ZRO, October 29 PEPE, November 4 NEAR, total −€42.55 before per-trade rounding). The two October 28 ETH reconstructions are about −0.18%. All five have negative benchmark returns. This definition sensitivity and the inspected sample preclude using −0.2% as a policy boundary.

## Historical comparison and frequency

The split below uses November 2 at 00:00 UTC. Both intervals were already inspected. Only recorded entries can be removed in this ablation. It cannot measure replacement trades or rebuild an executable account trajectory. A failed gate may remove observed losses or winners. A zero-trade result carries no expectancy estimate.

| Entry hypothesis | Earlier kept / blocked / unknown | Earlier net EUR | Later kept / blocked / unknown | Later net EUR | Observed losses removed / winners missed |
|---|---:|---:|---:|---:|---:|
| baseline | 10 / 0 / 0 | -63.16 | 5 / 0 / 0 | -36.17 | 0 / 0 |
| shared macro | 6 / 4 / 0 | -32.49 | 5 / 0 / 0 | -36.17 | 3 / 1 |
| early recovery | 6 / 4 / 0 | -43.29 | 4 / 1 / 0 | -31.29 | 5 / 0 |
| a3 confirmation | 8 / 2 / 0 | -66.69 | 1 / 4 / 0 | -4.88 | 5 / 1 |
| cluster | 8 / 2 / 0 | -51.30 | 4 / 1 / 0 | -32.19 | 3 / 0 |
| combined | 1 / 9 / 0 | -6.44 | 0 / 5 / 0 | +0.00 | 13 / 1 |

The earlier baseline mean is −€6.32 with a descriptive UTC-day bootstrap interval of [−€9.06, +€0.59]. The later set has two trading days, too few for even this descriptive interval. Day resampling preserves within-day loss clusters, but the small selected sample and reused dates make the interval unsuitable for inference. The JSON output includes net mean, fees, turnover, exposure minutes, EUR capital-minutes, closed-trade drawdown and counts by market regime.

| Price-path hypothesis | Resolved / no entry at base cost | Base net EUR | +20 bps net EUR | +50 bps net EUR |
|---|---:|---:|---:|---:|
| bracket | 15 / 0 | -111.63 | -132.37 | -163.46 |
| progress time | 15 / 0 | -111.24 | -131.98 | -163.08 |
| giveback | 15 / 0 | -101.04 | -121.80 | -151.00 |
| partial | 15 / 0 | -111.63 | -132.37 | -163.46 |
| failed breakout | 15 / 0 | -108.06 | -128.80 | -159.91 |
| regime exit | 15 / 0 | -97.79 | -118.55 | -149.69 |
| consolidation | 15 / 0 | -63.52 | -84.34 | -115.59 |
| structural | 15 / 0 | -98.81 | -119.56 | -150.68 |
| delayed confirmation | 6 / 9 | -61.30 | -77.76 | -102.32 |

Price-path tests use original entry price and quantity except for risk-constrained structural sizing and the delayed-entry proxy. They omit entry-straddling candles, use a bid haircut based on entry spread, apply fees on both legs and exit slippage, honor gaps through the stop and resolve ambiguous stop/target bars against the strategy. The delayed test also stresses the next-bar ask. Partial profit-taking uses half at the modeled target and continues on the remaining half. Discretionary changes learned from a close take effect from the next bar. Because these paths lack contemporaneous depth, even the base bracket is a different observation from the historical broker baseline. Later trades can already have exited before a complete bar. Every variant remains negative and all probability/expectancy estimates report `INSUFFICIENT_EVIDENCE`.

The 600 linked decisions and signals cover 10:56:34–11:41:31 UTC on November 6 across 17 markets, and all 600 waited. Overlapping blocker counts were 284 target/cost, 254 local reclaim, 222 resistance, 191 hourly trend and 150 stop/noise. The latest scanner snapshot covered SOL, BTC, ETH, INJ and XRP. This is a bounded slice, not the whole funnel. The audit lacks an eligible ticker universe at each historical cycle and counterfactual execution books, so expanded discovery, the false-positive rate across all opportunities, and missed executable opportunities are **INSUFFICIENT_EVIDENCE**.

## Prospective experiment and interpretation

The separate public collector preregisters development, holdout and subsequent shadow windows and archives receipt-time observations, raw candle inputs, sampled books and modeled plans. One-cycle discovery rotates through a liquidity-screened set with a bounded budget. It evaluates A3 continuation ablations, a probe cohort of rejected A3 setups, and a shorter range-reclaim challenger, records synchronized breadth and changes in benchmark spread/near-bid depth, and models a maximum one €700 research position with a fixed horizon reservation and cooldown. Report outcomes use only the first observed completed bar within the allowed receipt window. Split-boundary overlaps are purged. If the symbol is not revisited in time, its path is censored. Coverage and stress checks expose this limitation explicitly. Revolut X documents both the historical OHLCV endpoint and a current public book snapshot endpoint; OHLCV does not provide historical executable depth. [Revolut X REST API](https://developer.revolut.com/docs/api/revolut-x-crypto-exchange)

The proxy review requires at least 60 outcomes and 30 UTC days for each paired proxy cohort, ≥90% observed paths, positive lower bootstrap bound, positive expectancy under +50 bps, better net results and no worse drawdown than the incumbent setup proxy in both later periods. These are prespecified review criteria. Any transition still requires independently matched executable evidence, a reviewed risk budget, and explicit approval of a new version. There is no prospective profitability result or untouched holdout in this export.
