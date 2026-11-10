"""One-hunk, fail-closed crypto BUY admission patch for the live image.

Preserves every unrelated stock/crypto paper hotfix byte-for-byte.
"""
import argparse
import ast
from pathlib import Path

OLD = '''                signals=ac.scan(now)
                for s in sorted(signals,key=lambda x:x["symbol"]):
                    if s["action"]!="BUY" or s["symbol"] in pos:continue
                    asset=_fresh_asset(s["symbol"],now)
                    bid,ask,stamp=data.latest_bid(s["symbol"])
                    if ask > float(s["price"])*1.02 or (ask-bid)/ask>0.015:
                        continue
                    loss_per_unit=money(ask)-money(s["stop"])
                    if loss_per_unit<=0:
                        continue
                    stop_fraction=loss_per_unit/money(ask)
                    budget=min(equity*CAP_PER_SYMBOL,
                               equity*CAP_CRYPTO_TOTAL-crypto_exposure,
                               buying*Decimal(".75"),
                               equity*RISK_PER_TRADE/stop_fraction)
                    budget=budget.quantize(Decimal(".01"),rounding=ROUND_DOWN)
                    if budget<MIN_TRADE_USD:continue
                    outcome=_submit_intent(client,account,s["symbol"],"buy",s["bar_at"],
                            s["reason"],notional=str(budget))
                    if outcome=="paper_order_acknowledged":
                        with connect() as c:
                            c.execute("""INSERT INTO ac_managed
                                (symbol,account_id,entry_client_id,stop,target,entered_at)
                                VALUES(?,?,?,?,?,?)
                                ON CONFLICT(symbol) DO UPDATE SET account_id=excluded.account_id,
                                  entry_client_id=excluded.entry_client_id,stop=excluded.stop,
                                  target=excluded.target,entered_at=excluded.entered_at""",
                                (s["symbol"],account,_order_id(account,s["symbol"],s["bar_at"],"buy"),
                                 str(s["stop"]),str(s["target"]),utc()))
                    return outcome
                return "no_approved_spot_long_signal"'''
NEW = '''                signals=ac.scan(now)
                from .crypto_trade_safety import depth_limited_notional
                last_blocked = None
                for s in sorted(signals,key=lambda x:x["symbol"]):
                    if s["action"]!="BUY" or s["symbol"] in pos:continue
                    asset=_fresh_asset(s["symbol"],now)
                    try:
                        quote=data.latest_entry_quote(s["symbol"])
                    except ac.CryptoDataError as exc:
                        last_blocked = "crypto_entry_quote_missing_or_invalid"
                        ac.record_admission(s["symbol"],s["bar_at"],last_blocked,
                                            {"quote_status":str(exc)},now)
                        continue
                    bid,ask,stamp=quote["bid"],quote["ask"],quote["observed_at"]
                    quote_stats={"bid":bid,"ask":ask,
                                 "bid_size":quote["bid_size"],"ask_size":quote["ask_size"],
                                 "spread_pct":round(100*(ask-bid)/ask,4)}
                    if ask > float(s["price"])*1.02 or (ask-bid)/ask>0.015:
                        last_blocked="crypto_entry_spread_or_stale_signal"
                        ac.record_admission(s["symbol"],s["bar_at"],last_blocked,quote_stats,now)
                        continue
                    loss_per_unit=money(ask)-money(s["stop"])
                    if loss_per_unit<=0:
                        last_blocked="crypto_entry_stop_above_market"
                        ac.record_admission(s["symbol"],s["bar_at"],last_blocked,quote_stats,now)
                        continue
                    stop_fraction=loss_per_unit/money(ask)
                    budget=min(equity*CAP_PER_SYMBOL,
                               equity*CAP_CRYPTO_TOTAL-crypto_exposure,
                               buying*Decimal(".75"),
                               equity*RISK_PER_TRADE/stop_fraction)
                    budget=budget.quantize(Decimal(".01"),rounding=ROUND_DOWN)
                    if budget<MIN_TRADE_USD:
                        last_blocked="crypto_entry_portfolio_budget_below_minimum"
                        ac.record_admission(s["symbol"],s["bar_at"],last_blocked,quote_stats,now)
                        continue
                    # Prevent a paper market order larger than 20% of either
                    # currently displayed quote side. No synthetic order depth.
                    budget,depth_status=depth_limited_notional(
                        budget,ask,bid,quote["ask_size"],quote["bid_size"],
                        min_usd=str(MIN_TRADE_USD))
                    if budget is None:
                        last_blocked=depth_status
                        ac.record_admission(s["symbol"],s["bar_at"],last_blocked,quote_stats,now)
                        continue
                    quote_stats["approved_notional_usd"]=str(budget)
                    quote_stats["depth_decision"]=depth_status
                    ac.record_admission(s["symbol"],s["bar_at"],
                                        "crypto_entry_admitted",quote_stats,now)
                    outcome=_submit_intent(client,account,s["symbol"],"buy",s["bar_at"],
                            s["reason"],notional=str(budget))
                    try:
                        ac.record_admission(s["symbol"],s["bar_at"],outcome,quote_stats,now)
                    except Exception:
                        # An audit write after submission must never re-submit
                        # an otherwise acknowledged paper order.
                        log.warning("Crypto paper admission outcome not journaled")
                    if outcome=="paper_order_acknowledged":
                        with connect() as c:
                            c.execute("""INSERT INTO ac_managed
                                (symbol,account_id,entry_client_id,stop,target,entered_at)
                                VALUES(?,?,?,?,?,?)
                                ON CONFLICT(symbol) DO UPDATE SET account_id=excluded.account_id,
                                  entry_client_id=excluded.entry_client_id,stop=excluded.stop,
                                  target=excluded.target,entered_at=excluded.entered_at""",
                                (s["symbol"],account,_order_id(account,s["symbol"],s["bar_at"],"buy"),
                                 str(s["stop"]),str(s["target"]),utc()))
                    return outcome
                return (last_blocked or "no_approved_spot_long_signal")'''


def patch_source(source):
    if source.count(OLD) != 1:
        raise ValueError("crypto_paper_buy_hunk_changed_or_missing")
    t = ast.parse(source)
    target = [n for n in ast.walk(t) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_run_paper_cycle_once"]
    if len(target) != 1:
        raise ValueError("crypto_paper_cycle_structure_unexpected")
    lineno = source.count("\n", 0, source.index(OLD)) + 1
    if not target[0].lineno < lineno <= target[0].end_lineno:
        raise ValueError("crypto_paper_hunk_outside_cycle")
    changed = source.replace(OLD, NEW, 1)
    ast.parse(changed)
    if changed.replace(NEW, OLD, 1) != source:
        raise ValueError("crypto_paper_patch_not_isolated")
    return changed


def main():
    p = argparse.ArgumentParser()
    p.add_argument("source")
    p.add_argument("destination")
    a = p.parse_args()
    original = Path(a.source).read_bytes()
    result = patch_source(original.decode("utf-8")).encode("utf-8")
    if Path(a.source).resolve() == Path(a.destination).resolve():
        raise ValueError("input_and_output_must_differ")
    Path(a.destination).write_bytes(result)
    print("CRYPTO_PAPER_HUNK_OK: BUY quote/depth/audit updated; all unrelated code preserved")


if __name__ == "__main__":
    main()
