"""Authoritative 50-equity and two benchmark StocksWatch registry."""

LEGACY = (
    ("AAPL", "Apple Inc.", "Technology"),
    ("MSFT", "Microsoft Corporation", "Technology"),
    ("GOOGL", "Alphabet Inc.", "Communication"),
    ("AMZN", "Amazon.com, Inc.", "Consumer Discretionary"),
    ("NVDA", "NVIDIA Corporation", "Technology"),
    ("META", "Meta Platforms, Inc.", "Communication"),
    ("AMD", "Advanced Micro Devices, Inc.", "Technology"),
    ("TSM", "Taiwan Semiconductor Manufacturing Company Limited ADR", "Technology"),
    ("QCOM", "QUALCOMM Incorporated", "Technology"),
    ("AVGO", "Broadcom Inc.", "Technology"),
    ("JPM", "JPMorgan Chase & Co.", "Financials"),
    ("V", "Visa Inc.", "Financials"),
    ("MA", "Mastercard Incorporated", "Financials"),
    ("UNH", "UnitedHealth Group Incorporated", "Healthcare"),
    ("JNJ", "Johnson & Johnson", "Healthcare"),
    ("ABBV", "AbbVie Inc.", "Healthcare"),
    ("LLY", "Eli Lilly and Company", "Healthcare"),
    ("XOM", "Exxon Mobil Corporation", "Energy"),
    ("CVX", "Chevron Corporation", "Energy"),
    ("COST", "Costco Wholesale Corporation", "Consumer Staples"),
    ("WMT", "Walmart Inc.", "Consumer Staples"),
    ("PG", "The Procter & Gamble Company", "Consumer Staples"),
    ("KO", "The Coca-Cola Company", "Consumer Staples"),
    ("CAT", "Caterpillar Inc.", "Industrials"),
    ("GE", "General Electric Company (GE Aerospace)", "Industrials"),
    ("DIS", "The Walt Disney Company", "Communication"),
    ("NFLX", "Netflix, Inc.", "Communication"),
    ("UBER", "Uber Technologies, Inc.", "Industrials"),
    ("ORCL", "Oracle Corporation", "Technology"),
    ("CRM", "Salesforce, Inc.", "Technology"),
    ("SPY", "SPDR S&P 500 ETF Trust", "Benchmark"),
    ("QQQ", "Invesco QQQ Trust, Series 1", "Benchmark"),
)

ADDITIONS = (
    ("TSLA", "Tesla, Inc.", "Consumer Discretionary"),
    ("PLTR", "Palantir Technologies Inc.", "Technology"),
    ("COIN", "Coinbase Global, Inc.", "Financials"),
    ("MU", "Micron Technology, Inc.", "Technology"),
    ("AMAT", "Applied Materials, Inc.", "Technology"),
    ("PANW", "Palo Alto Networks, Inc.", "Technology"),
    ("CRWD", "CrowdStrike Holdings, Inc.", "Technology"),
    ("ADBE", "Adobe Inc.", "Technology"),
    ("NOW", "ServiceNow, Inc.", "Technology"),
    ("BAC", "Bank of America Corporation", "Financials"),
    ("GS", "The Goldman Sachs Group, Inc.", "Financials"),
    ("SCHW", "The Charles Schwab Corporation", "Financials"),
    ("HD", "The Home Depot, Inc.", "Consumer Discretionary"),
    ("LOW", "Lowe's Companies, Inc.", "Consumer Discretionary"),
    ("DE", "Deere & Company", "Industrials"),
    ("PFE", "Pfizer Inc.", "Healthcare"),
    ("MRK", "Merck & Co., Inc.", "Healthcare"),
    ("ABT", "Abbott Laboratories", "Healthcare"),
    ("NEE", "NextEra Energy, Inc.", "Utilities"),
    ("MCD", "McDonald's Corporation", "Consumer Discretionary"),
)

ASSETS = (*LEGACY, *ADDITIONS)
REGISTRY = {
    s: {
        "symbol": s,
        "name": name,
        "sector": sector,
        "instrument_type": "BENCHMARK_ETF" if sector == "Benchmark" else "COMPANY_EQUITY",
        "strategies": () if sector == "Benchmark" else ("EOD_LONG", "INTRADAY_LONG", "SHORT"),
    }
    for s, name, sector in ASSETS
}
NEW = frozenset(s for s, _, _ in ADDITIONS)
BENCHMARKS = frozenset(s for s, v in REGISTRY.items() if v["instrument_type"] == "BENCHMARK_ETF")
