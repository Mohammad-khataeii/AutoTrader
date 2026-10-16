# V4.1 genuine intraday data

Source: Coinbase Exchange public GET `/products` and `/products/{symbol}/candles`. All eight direct EUR products were verified against the listing at acquisition. UTC completed bars only. No FX conversions or synthetic gap filling. 4h uses four contiguous completed 1h candles.

Executed: `python3 -m autotrader.research.cli research download --root .data/research --start 2020-01-01 --end 2026-10-16`. Run again to resume/extend verified coverage; `research availability --root .data/research` checks every dataset hash.

| Symbol | TF | First start UTC | Last start UTC | Bars | Missing requested bars |
|---|---|---|---|---:|---:|
| BTC-EUR | 1d | 2020-01-01T00:00:00+00:00 | 2026-10-15T00:00:00+00:00 | 2480 | 0 |
| BTC-EUR | 1h | 2026-04-19T00:00:00+00:00 | 2026-10-15T23:00:00+00:00 | 4315 | 5 |
| BTC-EUR | 4h | 2026-04-19T00:00:00+00:00 | 2026-10-15T20:00:00+00:00 | 1078 | 2 |
| BTC-EUR | 1m | 2026-10-14T00:00:00+00:00 | 2026-10-15T23:59:00+00:00 | 2747 | 133 |
| BTC-EUR | 5m | 2026-04-19T00:00:00+00:00 | 2026-10-15T23:55:00+00:00 | 51747 | 93 |
| BTC-EUR | 15m | 2026-07-18T00:00:00+00:00 | 2026-10-15T23:45:00+00:00 | 8640 | 0 |
| ETH-EUR | 1d | 2020-01-01T00:00:00+00:00 | 2026-10-15T00:00:00+00:00 | 2480 | 0 |
| ETH-EUR | 1h | 2026-04-19T00:00:00+00:00 | 2026-10-15T23:00:00+00:00 | 4315 | 5 |
| ETH-EUR | 4h | 2026-04-19T00:00:00+00:00 | 2026-10-15T20:00:00+00:00 | 1078 | 2 |
| ETH-EUR | 1m | 2026-10-14T00:00:00+00:00 | 2026-10-15T23:59:00+00:00 | 2648 | 232 |
| ETH-EUR | 5m | 2026-04-19T00:00:00+00:00 | 2026-10-15T23:55:00+00:00 | 51724 | 116 |
| ETH-EUR | 15m | 2026-07-18T00:00:00+00:00 | 2026-10-15T23:45:00+00:00 | 8640 | 0 |
| SOL-EUR | 1d | 2021-06-17T00:00:00+00:00 | 2026-10-15T00:00:00+00:00 | 1947 | 533 |
| SOL-EUR | 1h | 2026-04-19T00:00:00+00:00 | 2026-10-15T23:00:00+00:00 | 4315 | 5 |
| SOL-EUR | 4h | 2026-04-19T00:00:00+00:00 | 2026-10-15T20:00:00+00:00 | 1078 | 2 |
| SOL-EUR | 1m | 2026-10-14T00:00:00+00:00 | 2026-10-15T23:59:00+00:00 | 2635 | 245 |
| SOL-EUR | 5m | 2026-07-18T00:00:00+00:00 | 2026-10-15T23:55:00+00:00 | 25894 | 26 |
| SOL-EUR | 15m | 2026-07-18T00:00:00+00:00 | 2026-10-15T23:45:00+00:00 | 8640 | 0 |
| XRP-EUR | 1d | 2020-01-01T00:00:00+00:00 | 2026-10-15T00:00:00+00:00 | 1576 | 904 |
| XRP-EUR | 1h | 2026-04-19T00:00:00+00:00 | 2026-10-15T23:00:00+00:00 | 4315 | 5 |
| XRP-EUR | 4h | 2026-04-19T00:00:00+00:00 | 2026-10-15T20:00:00+00:00 | 1078 | 2 |
| XRP-EUR | 1m | 2026-10-14T00:02:00+00:00 | 2026-10-15T23:59:00+00:00 | 1699 | 1181 |
| XRP-EUR | 5m | 2026-07-18T00:00:00+00:00 | 2026-10-15T23:55:00+00:00 | 25127 | 793 |
| XRP-EUR | 15m | 2026-07-18T00:00:00+00:00 | 2026-10-15T23:45:00+00:00 | 8631 | 9 |
| ADA-EUR | 1d | 2021-03-18T00:00:00+00:00 | 2026-10-15T00:00:00+00:00 | 2038 | 442 |
| ADA-EUR | 1h | 2026-04-19T00:00:00+00:00 | 2026-10-15T23:00:00+00:00 | 4314 | 6 |
| ADA-EUR | 4h | 2026-04-19T00:00:00+00:00 | 2026-10-15T20:00:00+00:00 | 1077 | 3 |
| ADA-EUR | 1m | 2026-10-14T00:03:00+00:00 | 2026-10-15T23:59:00+00:00 | 977 | 1903 |
| ADA-EUR | 5m | 2026-07-18T00:00:00+00:00 | 2026-10-15T23:55:00+00:00 | 19916 | 6004 |
| ADA-EUR | 15m | 2026-07-18T00:00:00+00:00 | 2026-10-15T23:45:00+00:00 | 8286 | 354 |
| LINK-EUR | 1d | 2020-07-21T00:00:00+00:00 | 2026-10-15T00:00:00+00:00 | 2278 | 202 |
| LINK-EUR | 1h | 2026-04-19T00:00:00+00:00 | 2026-10-15T23:00:00+00:00 | 4294 | 26 |
| LINK-EUR | 4h | 2026-04-19T00:00:00+00:00 | 2026-10-15T20:00:00+00:00 | 1060 | 20 |
| LINK-EUR | 1m | 2026-10-14T00:00:00+00:00 | 2026-10-15T23:58:00+00:00 | 873 | 2007 |
| LINK-EUR | 5m | 2026-07-18T01:40:00+00:00 | 2026-10-15T23:55:00+00:00 | 18709 | 7211 |
| LINK-EUR | 15m | 2026-07-18T01:30:00+00:00 | 2026-10-15T23:45:00+00:00 | 7814 | 826 |
| AVAX-EUR | 1d | 2021-09-30T00:00:00+00:00 | 2026-10-15T00:00:00+00:00 | 1842 | 638 |
| AVAX-EUR | 1h | 2026-04-19T00:00:00+00:00 | 2026-10-15T23:00:00+00:00 | 4137 | 183 |
| AVAX-EUR | 4h | 2026-04-19T00:00:00+00:00 | 2026-10-15T20:00:00+00:00 | 929 | 151 |
| AVAX-EUR | 1m | 2026-10-14T00:10:00+00:00 | 2026-10-15T23:59:00+00:00 | 877 | 2003 |
| AVAX-EUR | 5m | 2026-07-18T00:15:00+00:00 | 2026-10-15T23:45:00+00:00 | 13719 | 12201 |
| AVAX-EUR | 15m | 2026-07-18T00:15:00+00:00 | 2026-10-15T23:45:00+00:00 | 6675 | 1965 |
| DOT-EUR | 1d | 2021-06-16T00:00:00+00:00 | 2026-10-15T00:00:00+00:00 | 1948 | 532 |
| DOT-EUR | 1h | 2026-04-19T00:00:00+00:00 | 2026-10-15T23:00:00+00:00 | 3595 | 725 |
| DOT-EUR | 4h | 2026-04-19T04:00:00+00:00 | 2026-10-15T20:00:00+00:00 | 617 | 463 |
| DOT-EUR | 1m | 2026-10-14T00:14:00+00:00 | 2026-10-15T23:39:00+00:00 | 713 | 2167 |
| DOT-EUR | 5m | 2026-07-18T00:25:00+00:00 | 2026-10-15T23:35:00+00:00 | 10884 | 15036 |
| DOT-EUR | 15m | 2026-07-18T00:15:00+00:00 | 2026-10-15T23:30:00+00:00 | 5389 | 3251 |

Total: 48 datasets, 351,788 observations, 0 acquisition failures. Timeframes overlap and are not independent samples.

Exact gap ranges, per-file SHA256, dataset content versions, request pages, provider product metadata, source identities and quality counts are in `evidence/v4_1-datasets.json`; bulk gzip JSONL and raw response cache are in `.data/research` (excluded from Git). No cache was supplied in the starting checkout. Missing early daily history can precede a listing. Missing no-tick intervals are provider omissions, not proof of an outage.

Five-minute requested windows: BTC/ETH 2026-04-19 through 2026-10-16 exclusive (180 days); other assets 2026-07-18 through 2026-10-16 exclusive (90 days). Other windows: 1m two days, 15m ninety days, 1h/4h 180 days, daily since 2020-01-01. These are acquisition objectives; actual counts and endpoints above are authoritative.

Immutable content-addressed datasets are published before atomic coverage/catalog pointers. Failed acquisition retains the previous dataset and verified completed raw pages. Extending only requests previously unrequested ranges. Recorded gaps are retained, not repeatedly downloaded. A corrupted cache/dataset blocks reuse; restore the damaged file from backup or quarantine that exact file before reacquisition. Old versions and raw pages are retained while any report or pilot references them; no automatic deletion is configured. The cache requires backup and disk monitoring.

Coinbase is a quantitative proxy for Revolut X, with different liquidity, tick/lot precision and fees. No historical Revolut X order books, venue latency, queue position or tick-size schedules are available. Research assumes 10 bps per-side fees, 10 bps full spread, 8 bps per-side slippage, 1% of the previous completed bar volume as shared modeled liquidity and fixed base precision. Fee/spread/slippage stresses are separate simulations. Historical volume is not executable L2. Runtime still requires fresh Revolut X quotes and current venue metadata.

Integrity tests: `tests/test_v4_data.py`, 12 passing cases in `evidence/v4_1-data.xml`. The research panel rejects non-contiguous recent signal histories. No cross-venue historical price comparison was acquired; major source discrepancies cannot be ruled out. Timestamp units, alignment, currency/symbol, OHLC consistency, missing volume, price validity, duplicate conflicts and raw/dataset checksums are checked. Large within-bar ranges are flagged after their close.
