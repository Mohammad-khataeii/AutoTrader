"""Pure regression checks for crypto order cash reservation and clean candles."""
import unittest
import httpx
from unittest.mock import patch
from decimal import Decimal
from stockswatch.crypto_shared_orders import reserve, StockReservationError
from stockswatch.crypto_data_quality import quarantine_untraded_spikes
from stockswatch.crypto_recovery import assess, benchmark_stabilized

def order(symbol="AAPL",side="buy",qty="10",price="100",**kw):
    return dict(id=kw.pop("id","order1"),symbol=symbol,side=side,
        qty=qty,filled_qty=kw.pop("filled_qty","0"),status="new",
        type=kw.pop("type","limit"),limit_price=price,**kw)

def holding(symbol="AAPL",qty="10"):
    return dict(symbol=symbol,qty=qty,side="long",asset_class="us_equity")

def bar(i):
    price=100+i*.004
    return dict(ts=f"2026-11-01T{i%24:02d}:00:00+00:00",
                o=price,h=price+0.2,l=price-0.2,c=price,v=100)

class CashTests(unittest.TestCase):
    def test_pending_stock_buy_reserves_cash_instead_of_globally_blocking(self):
        r=reserve([order(qty="15",price="80")],[], "10000","30000")
        self.assertEqual(r["reserved_stock_buys_usd"],Decimal("1200"))
        self.assertEqual(r["available_cash_usd"],Decimal("8800"))
    def test_partially_filled_buy_only_reserves_remainder(self):
        r=reserve([order(qty="15",filled_qty="10",price="80")],[], "10000","10000")
        self.assertEqual(r["reserved_stock_buys_usd"],Decimal("400"))
    def test_uncapped_market_buy_blocks(self):
        with self.assertRaisesRegex(StockReservationError,"uncapped"):
            reserve([order(type="market")],[], "10000","10000")
    def test_unknown_stock_sell_fails_closed(self):
        with self.assertRaises(StockReservationError):
            reserve([order(side="sell")],[], "10000","10000")
    def test_oco_double_sell_is_not_a_double_reservation(self):
        parent=order(id="tp",side="sell",qty="10",price="120",
                     order_class="oco",type="limit")
        stop=order(id="sl",side="sell",qty="10",price=None,
                   order_class="oco",type="stop",stop_price="90")
        stop["status"]="held"  # Alpaca's normal contingent OCO stop-leg state
        self.assertEqual(reserve([parent,stop],[holding()],"10000","10000")["available_cash_usd"],Decimal("10000"))
    def test_two_unverified_sells_exceeding_inventory_block(self):
        a=order(id="a",side="sell",qty="10")
        b=order(id="b",side="sell",qty="10")
        with self.assertRaises(StockReservationError):
            reserve([a,b],[holding()],"10000","10000")
    def test_no_credit_from_stock_sell(self):
        r=reserve([order(side="sell")],[holding()],"10000","20000")
        self.assertEqual(r["available_cash_usd"],Decimal("10000"))

class BrokerReadTests(unittest.TestCase):
    def test_broker_get_transport_recovers_without_post(self):
        from stockswatch.alpaca_crypto_paper import CryptoPaperClient
        calls=[]
        def service(req):
            calls.append(req.method)
            if len(calls)==1:
                raise httpx.ConnectError("mock-disconnect",request=req)
            return httpx.Response(200,json=[])
        with patch.dict("os.environ",{"STOCKSWATCH_ALPACA_PAPER_KEY":"mock-key",
                                     "STOCKSWATCH_ALPACA_PAPER_SECRET":"mock-secret"}):
            with CryptoPaperClient(transport=httpx.MockTransport(service)) as client:
                value=client.request("GET","/v2/orders")
        self.assertEqual(value,[])
        self.assertEqual(calls,["GET","GET"])

    def test_broker_post_network_uncertain_not_retried(self):
        from stockswatch.alpaca_crypto_paper import CryptoPaperClient, CryptoPaperError
        calls=[]
        def service(req):
            calls.append(req.method)
            raise httpx.ConnectError("mock-disconnect",request=req)
        with patch.dict("os.environ",{"STOCKSWATCH_ALPACA_PAPER_KEY":"mock-key",
                                     "STOCKSWATCH_ALPACA_PAPER_SECRET":"mock-secret"}):
            with CryptoPaperClient(transport=httpx.MockTransport(service)) as client:
                with self.assertRaisesRegex(CryptoPaperError,"crypto_paper_transport_uncertain"):
                    client.request("POST","/v2/orders",json={"symbol":"BTC/USD"})
        self.assertEqual(calls,["POST"])


class QualityTests(unittest.TestCase):
    def test_old_fake_close_quarantined_without_220_hour_freeze(self):
        rows=[bar(i) for i in range(250)]
        rows[10]=dict(rows[10],c=rows[10]["o"]*1.3,h=rows[10]["o"]*1.31,v=0)
        result,proof=quarantine_untraded_spikes(rows)
        self.assertEqual(len(result),249)
        self.assertEqual(proof["quarantined"],1)
    def test_new_fake_close_blocks(self):
        rows=[bar(i) for i in range(250)]
        rows[-1]=dict(rows[-1],c=rows[-1]["o"]*1.3,h=rows[-1]["o"]*1.31,v=0)
        self.assertEqual(quarantine_untraded_spikes(rows)[1]["reason"],"recent_untraded_close_spike")
    def test_new_fake_wick_blocks(self):
        rows=[bar(i) for i in range(250)]
        rows[-1]=dict(rows[-1],h=rows[-1]["o"]*1.3,v=0)
        self.assertEqual(quarantine_untraded_spikes(rows)[1]["reason"],"recent_untraded_wick_spike")
    def test_no_fabricated_history_when_too_few_valid(self):
        self.assertEqual(quarantine_untraded_spikes([bar(i) for i in range(100)])[1]["reason"],
                         "insufficient_clean_hourly_bars")

class RecoveryTests(unittest.TestCase):
    def test_benchmark_requires_correct_hour_and_real_volume(self):
        prices=[100,99.7,99.8,100]
        bars=[{"ts":str(i),"c":v,"v":20} for i,v in enumerate(prices)]
        self.assertTrue(benchmark_stabilized(bars,"3"))
        self.assertFalse(benchmark_stabilized(bars,"4"))
        bars[-1]["v"]=0
        self.assertFalse(benchmark_stabilized(bars,"3"))
    def test_candidate_requires_causal_volume_and_reversal(self):
        rows=[bar(i) for i in range(25)]
        self.assertFalse(assess(rows,atr=0.5,rsi=50)["passed"])
        self.assertFalse(assess(rows,atr=0.5,rsi=78)["passed"])

if __name__=="__main__":
    unittest.main()
