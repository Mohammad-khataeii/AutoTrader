"""Regression: equities and crypto may share ONE Alpaca Paper account.

All broker responses are synthetic. Tests never make a network request,
modify a financial ledger, or submit any order.
"""
import httpx
import pytest

from stockswatch import alpaca_crypto_paper as crypto
from stockswatch import alpaca_paper as stocks


def _account():
    return {
        "id": "paper-account-1",
        "account_number": "paper-account-1",
        "currency": "USD",
        "status": "ACTIVE",
        "trading_blocked": False,
        "account_blocked": False,
    }


def _stock_position():
    return {"symbol": "AAPL", "asset_class": "us_equity", "side": "long",
            "qty": "34", "market_value": "6000"}


def _crypto_position():
    return {"symbol": "BTCUSD", "asset_class": "crypto", "side": "long",
            "qty": "0.01", "market_value": "1200"}


def _stock_order():
    return {"id": "so-1", "client_order_id": "manual-stock-exit",
            "symbol": "AAPL", "asset_class": "us_equity", "side": "sell",
            "status": "new", "qty": "34", "filled_qty": "0"}


def _crypto_order():
    return {"id": "co-1", "client_order_id": "acp1-" + "a" * 40,
            "symbol": "BTC/USD", "asset_class": "crypto", "side": "buy",
            "status": "new", "qty": "0.01", "filled_qty": "0"}


def test_crypto_reuses_existing_stock_paper_credentials(monkeypatch):
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_KEY", "STOCK-PAPER-KEY")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_SECRET", "STOCK-PAPER-SECRET")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID", "paper-account-1")
    monkeypatch.delenv("ALPACA_CRYPTO_PAPER_KEY", raising=False)
    monkeypatch.delenv("ALPACA_CRYPTO_PAPER_SECRET", raising=False)
    monkeypatch.delenv("ALPACA_CRYPTO_PAPER_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(crypto, "one", lambda *args, **kwargs: None)
    methods = []

    def transport(request):
        methods.append((request.method, request.url.path))
        assert request.headers["APCA-API-KEY-ID"] == "STOCK-PAPER-KEY"
        assert request.headers["APCA-API-SECRET-KEY"] == "STOCK-PAPER-SECRET"
        if request.url.path == "/v2/account":
            return httpx.Response(200, json=_account())
        if request.url.path == "/v2/positions":
            return httpx.Response(200, json=[_stock_position(), _crypto_position()])
        if request.url.path == "/v2/orders":
            return httpx.Response(200, json=[_stock_order(), _crypto_order()])
        raise AssertionError("Unexpected URL")

    with crypto.CryptoPaperClient(transport=httpx.MockTransport(transport)) as client:
        view = client.snapshot()
    assert [p["symbol"] for p in view["positions"]] == ["BTCUSD"]
    assert [o["symbol"] for o in view["orders"]] == ["BTC/USD"]
    assert [p["symbol"] for p in view["other_positions"]] == ["AAPL"]
    assert [o["symbol"] for o in view["other_open_orders"]] == ["AAPL"]
    assert len(methods) == 3
    assert all(method == "GET" for method, _ in methods)


def test_crypto_partial_override_fails_closed(monkeypatch):
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_KEY", "stock-key")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_SECRET", "stock-secret")
    monkeypatch.setenv("ALPACA_CRYPTO_PAPER_KEY", "half-configured")
    monkeypatch.delenv("ALPACA_CRYPTO_PAPER_SECRET", raising=False)
    with pytest.raises(crypto.CryptoPaperError, match="crypto_partial_paper_credentials"):
        crypto._credentials()


def test_stock_paper_filters_crypto_but_records_foreign_inventory(monkeypatch):
    client = object.__new__(stocks.PaperClient)
    monkeypatch.setattr(client, "account", lambda: _account())
    def get(path, params=None):
        if path == "/v2/orders":
            return [_stock_order(), _crypto_order()]
        if path == "/v2/positions":
            return [_stock_position(), _crypto_position()]
        raise AssertionError(path)
    monkeypatch.setattr(client, "get", get)
    monkeypatch.setattr(client, "_optional", lambda path, params, typ:
                        ({ } if typ is dict else [], None))
    view = client.snapshot()
    assert [p["symbol"] for p in view["positions"]] == ["AAPL"]
    assert [p["symbol"] for p in view["other_positions"]] == ["BTCUSD"]
    assert [o["symbol"] for o in view["open_orders"]] == ["AAPL"]
    assert [o["symbol"] for o in view["other_open_orders"]] == ["BTC/USD"]
    assert len(view["orders"]) == 1


def test_crypto_unknown_asset_class_fails_closed(monkeypatch):
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_KEY", "paper-key")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_SECRET", "paper-secret")
    monkeypatch.setenv("STOCKSWATCH_ALPACA_PAPER_ACCOUNT_ID", "paper-account-1")
    monkeypatch.delenv("ALPACA_CRYPTO_PAPER_KEY", raising=False)
    monkeypatch.delenv("ALPACA_CRYPTO_PAPER_SECRET", raising=False)
    monkeypatch.setattr(crypto, "one", lambda *args, **kwargs: None)
    def transport(request):
        if request.url.path == "/v2/account":
            return httpx.Response(200, json=_account())
        if request.url.path == "/v2/positions":
            return httpx.Response(200, json=[
                {"symbol": "UNRECOGNIZED", "side": "long", "qty": "1"}])
        if request.url.path == "/v2/orders":
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)
    with crypto.CryptoPaperClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(crypto.CryptoPaperError, match="crypto_shared_account_unknown_asset_class"):
            client.snapshot()
