# 52-instrument release verification

Local check on 6 November 2026. The registry contains 50 company equities and two benchmarks with no duplicate symbols. The verification CLI used an isolated temporary SQLite file.

The paper asset request could not start because the expected paper credentials were absent. Historical ingestion could not start because the Alpaca data credentials were absent. The workspace has no verified eligibility, ETB, exchange assignment, data entitlement or market-backed comparison. These counts describe the isolated workspace. The existing paper database was outside this check.

| Symbol | Expected name | Sector | Instrument | Paper asset / ETB | Daily / minute rows | EOD gaps |
|---|---|---|---|---|---:|---:|
| AAPL | Apple Inc. | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| MSFT | Microsoft Corporation | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| GOOGL | Alphabet Inc. | Communication | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| AMZN | Amazon.com, Inc. | Consumer Discretionary | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| NVDA | NVIDIA Corporation | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| META | Meta Platforms, Inc. | Communication | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| AMD | Advanced Micro Devices, Inc. | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| TSM | Taiwan Semiconductor Manufacturing Company Limited ADR | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| QCOM | QUALCOMM Incorporated | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| AVGO | Broadcom Inc. | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| JPM | JPMorgan Chase & Co. | Financials | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| V | Visa Inc. | Financials | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| MA | Mastercard Incorporated | Financials | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| UNH | UnitedHealth Group Incorporated | Healthcare | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| JNJ | Johnson & Johnson | Healthcare | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| ABBV | AbbVie Inc. | Healthcare | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| LLY | Eli Lilly and Company | Healthcare | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| XOM | Exxon Mobil Corporation | Energy | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| CVX | Chevron Corporation | Energy | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| COST | Costco Wholesale Corporation | Consumer Staples | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| WMT | Walmart Inc. | Consumer Staples | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| PG | The Procter & Gamble Company | Consumer Staples | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| KO | The Coca-Cola Company | Consumer Staples | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| CAT | Caterpillar Inc. | Industrials | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| GE | General Electric Company (GE Aerospace) | Industrials | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| DIS | The Walt Disney Company | Communication | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| NFLX | Netflix, Inc. | Communication | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| UBER | Uber Technologies, Inc. | Industrials | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| ORCL | Oracle Corporation | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| CRM | Salesforce, Inc. | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| SPY | SPDR S&P 500 ETF Trust | Benchmark | BENCHMARK_ETF | Unverified | 0 / 0 | 201 |
| QQQ | Invesco QQQ Trust, Series 1 | Benchmark | BENCHMARK_ETF | Unverified | 0 / 0 | 201 |
| TSLA | Tesla, Inc. | Consumer Discretionary | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| PLTR | Palantir Technologies Inc. | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| COIN | Coinbase Global, Inc. | Financials | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| MU | Micron Technology, Inc. | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| AMAT | Applied Materials, Inc. | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| PANW | Palo Alto Networks, Inc. | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| CRWD | CrowdStrike Holdings, Inc. | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| ADBE | Adobe Inc. | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| NOW | ServiceNow, Inc. | Technology | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| BAC | Bank of America Corporation | Financials | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| GS | The Goldman Sachs Group, Inc. | Financials | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| SCHW | The Charles Schwab Corporation | Financials | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| HD | The Home Depot, Inc. | Consumer Discretionary | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| LOW | Lowe's Companies, Inc. | Consumer Discretionary | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| DE | Deere & Company | Industrials | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| PFE | Pfizer Inc. | Healthcare | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| MRK | Merck & Co., Inc. | Healthcare | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| ABT | Abbott Laboratories | Healthcare | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| NEE | NextEra Energy, Inc. | Utilities | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |
| MCD | McDonald's Corporation | Consumer Discretionary | COMPANY_EQUITY | Unverified | 0 / 0 | 201 |

For an authorized environment, use the verification and report commands in the [operator guide](LONG_SHORT_50.md). The JSON output includes the missing dates, per-series range, job states and verification timestamp when available.
