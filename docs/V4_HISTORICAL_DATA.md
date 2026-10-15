# Genuine historical datasets

Source: Coinbase Exchange public GET candles, direct EUR products. No authenticated exchange access or orders.

Official specification: https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles

Executed command: `python -m autotrader.research.cli research download --root .data/research --start 2020-01-01 --hourly-days 180 --intraday-days 2`.

Result: 48 datasets, 76,606 observations, zero acquisition failures. Source responses and hashes are cached locally under `.data/research/raw`; content-addressed gzip JSONL and full manifests are retained under `.data/research`. Summary evidence: `evidence/v4-datasets.json`.

| Symbol | TF | Count | First bar | Last bar | Missing in requested interval |
|---|---|---:|---|---|---:|
| BTC-EUR | 1d | 2479 | 2020-01-01T00:00:00+00:00 | 2026-10-14T00:00:00+00:00 | 0 |
| BTC-EUR | 1h | 4315 | 2026-04-18T00:00:00+00:00 | 2026-10-14T23:00:00+00:00 | 5 |
| BTC-EUR | 4h | 1078 | 2026-04-18T00:00:00+00:00 | 2026-10-14T20:00:00+00:00 | 2 |
| BTC-EUR | 1m | 2732 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:59:00+00:00 | 148 |
| BTC-EUR | 5m | 576 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:55:00+00:00 | 0 |
| BTC-EUR | 15m | 192 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:45:00+00:00 | 0 |
| ETH-EUR | 1d | 2479 | 2020-01-01T00:00:00+00:00 | 2026-10-14T00:00:00+00:00 | 0 |
| ETH-EUR | 1h | 4315 | 2026-04-18T00:00:00+00:00 | 2026-10-14T23:00:00+00:00 | 5 |
| ETH-EUR | 4h | 1078 | 2026-04-18T00:00:00+00:00 | 2026-10-14T20:00:00+00:00 | 2 |
| ETH-EUR | 1m | 2607 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:59:00+00:00 | 273 |
| ETH-EUR | 5m | 576 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:55:00+00:00 | 0 |
| ETH-EUR | 15m | 192 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:45:00+00:00 | 0 |
| SOL-EUR | 1d | 1946 | 2021-06-17T00:00:00+00:00 | 2026-10-14T00:00:00+00:00 | 533 |
| SOL-EUR | 1h | 4315 | 2026-04-18T00:00:00+00:00 | 2026-10-14T23:00:00+00:00 | 5 |
| SOL-EUR | 4h | 1078 | 2026-04-18T00:00:00+00:00 | 2026-10-14T20:00:00+00:00 | 2 |
| SOL-EUR | 1m | 2635 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:59:00+00:00 | 245 |
| SOL-EUR | 5m | 576 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:55:00+00:00 | 0 |
| SOL-EUR | 15m | 192 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:45:00+00:00 | 0 |
| XRP-EUR | 1d | 1575 | 2020-01-01T00:00:00+00:00 | 2026-10-14T00:00:00+00:00 | 904 |
| XRP-EUR | 1h | 4315 | 2026-04-18T00:00:00+00:00 | 2026-10-14T23:00:00+00:00 | 5 |
| XRP-EUR | 4h | 1078 | 2026-04-18T00:00:00+00:00 | 2026-10-14T20:00:00+00:00 | 2 |
| XRP-EUR | 1m | 1547 | 2026-10-13T00:03:00+00:00 | 2026-10-14T23:59:00+00:00 | 1333 |
| XRP-EUR | 5m | 546 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:55:00+00:00 | 30 |
| XRP-EUR | 15m | 192 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:45:00+00:00 | 0 |
| ADA-EUR | 1d | 2037 | 2021-03-18T00:00:00+00:00 | 2026-10-14T00:00:00+00:00 | 442 |
| ADA-EUR | 1h | 4314 | 2026-04-18T00:00:00+00:00 | 2026-10-14T23:00:00+00:00 | 6 |
| ADA-EUR | 4h | 1077 | 2026-04-18T00:00:00+00:00 | 2026-10-14T20:00:00+00:00 | 3 |
| ADA-EUR | 1m | 1033 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:59:00+00:00 | 1847 |
| ADA-EUR | 5m | 479 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:55:00+00:00 | 97 |
| ADA-EUR | 15m | 190 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:45:00+00:00 | 2 |
| LINK-EUR | 1d | 2277 | 2020-07-21T00:00:00+00:00 | 2026-10-14T00:00:00+00:00 | 202 |
| LINK-EUR | 1h | 4294 | 2026-04-18T00:00:00+00:00 | 2026-10-14T23:00:00+00:00 | 26 |
| LINK-EUR | 4h | 1060 | 2026-04-18T00:00:00+00:00 | 2026-10-14T20:00:00+00:00 | 20 |
| LINK-EUR | 1m | 774 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:58:00+00:00 | 2106 |
| LINK-EUR | 5m | 408 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:55:00+00:00 | 168 |
| LINK-EUR | 15m | 187 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:45:00+00:00 | 5 |
| AVAX-EUR | 1d | 1841 | 2021-09-30T00:00:00+00:00 | 2026-10-14T00:00:00+00:00 | 638 |
| AVAX-EUR | 1h | 4137 | 2026-04-18T00:00:00+00:00 | 2026-10-14T23:00:00+00:00 | 183 |
| AVAX-EUR | 4h | 929 | 2026-04-18T00:00:00+00:00 | 2026-10-14T20:00:00+00:00 | 151 |
| AVAX-EUR | 1m | 832 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:54:00+00:00 | 2048 |
| AVAX-EUR | 5m | 413 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:50:00+00:00 | 163 |
| AVAX-EUR | 15m | 184 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:45:00+00:00 | 8 |
| DOT-EUR | 1d | 1947 | 2021-06-16T00:00:00+00:00 | 2026-10-14T00:00:00+00:00 | 532 |
| DOT-EUR | 1h | 3591 | 2026-04-18T00:00:00+00:00 | 2026-10-14T23:00:00+00:00 | 729 |
| DOT-EUR | 4h | 615 | 2026-04-18T00:00:00+00:00 | 2026-10-14T20:00:00+00:00 | 465 |
| DOT-EUR | 1m | 808 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:57:00+00:00 | 2072 |
| DOT-EUR | 5m | 387 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:55:00+00:00 | 189 |
| DOT-EUR | 15m | 178 | 2026-10-13T00:00:00+00:00 | 2026-10-14T23:45:00+00:00 | 14 |

Requested daily window: 2020-01-01 through 2026-10-15 exclusive. Hourly/4h: last180 completed days; intraday: last2 completed days. Four-hour bars aggregate exactly four contiguous completed UTC hourly bars. Missing/no-trade periods are never filled. Intraday coverage is too short to establish regime robustness.

Per-bar metadata: source, symbol, base, quote, UTC start, timeframe, OHLCV, ingestion time, quality flags and content dataset version. Validation rejects currency mismatches, invalid values, inconsistent OHLC, future/incomplete bars, conflicting duplicates and corrupt hashes. Identical duplicates are counted and removed. Suspicious ranges and zero volume are flagged. Current inactive products would be flagged; the current eight were online when fetched.

Limitations: current product universe creates survivorship bias; the dataset does not include all delisted assets. Missing history before listing or during unavailability is explicit. No historical L2, queue or order latency is reconstructed. Local full data is ignored by Git to avoid committing a large generated cache; manifests and reproducible source requests are preserved.

Unit validation: 9 passed in1.13 seconds (`evidence/v4-data-unit.xml`), using explicitly labeled unit fixtures for error/aggregation/cache contracts. These tests are distinct from the genuine acquisition above.
