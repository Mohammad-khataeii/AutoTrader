"""Fail-closed cash reservation for mixed Alpaca STOCK / CRYPTO paper accounts.

Existing equity exit orders neither consume buying power nor grant additional
cash. Pending equity BUY limits reserve worst-case funds before a crypto BUY.
Unexpected order shapes block *new* crypto entry, never an existing crypto exit.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

class StockReservationError(ValueError):
    pass

D=Decimal
ACTIVE={"new","accepted","pending_new","partially_filled",
        "accepted_for_bidding","held","pending_cancel","pending_replace"}

def positive(value, *, zero=False):
    try:
        n=D(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise StockReservationError("shared_stock_invalid_quantity_or_price") from None
    if not n.is_finite() or n < 0 or (not zero and n==0):
        raise StockReservationError("shared_stock_invalid_quantity_or_price")
    return n

def reserve(stock_orders, stock_positions, cash, nonmarginable_buying_power):
    """Return conservative *additional* USD available to crypto BUY admission.

    Account cash may already include an order hold; reserving independently is
    intentionally conservative to prevent cross-strategy overspending.
    """
    if not isinstance(stock_orders,list) or not isinstance(stock_positions,list):
        raise StockReservationError("shared_stock_book_incomplete")
    available=min(positive(cash,zero=True),positive(nonmarginable_buying_power,zero=True))
    positions={}
    for item in stock_positions:
        symbol=item.get("symbol")
        if (not symbol or symbol in positions or item.get("asset_class")!="us_equity"
                or item.get("side")!="long"):
            raise StockReservationError("shared_stock_positions_unverifiable")
        positions[symbol]=positive(item.get("qty"))
    seen=set()
    buy_reserve=D(0)
    sell_by_symbol={}
    buy_count=0
    for order in stock_orders:
        oid=order.get("id")
        sym=order.get("symbol")
        side=order.get("side")
        if (not isinstance(oid,str) or not oid or oid in seen
                or not isinstance(sym,str) or not sym
                or side not in {"buy","sell"} or order.get("status") not in ACTIVE):
            raise StockReservationError("shared_stock_order_unverifiable")
        seen.add(oid)
        qty=positive(order.get("qty"))
        filled=positive(order.get("filled_qty",0),zero=True)
        if filled>qty:
            raise StockReservationError("shared_stock_order_overfilled")
        remaining=qty-filled
        if side=="buy":
            # Market or stop-market BUY has no finite cash cap: fail closed.
            if order.get("type") not in ("limit","stop_limit"):
                raise StockReservationError("shared_stock_buy_price_uncapped")
            limit=positive(order.get("limit_price"))
            buy_reserve+=remaining*limit
            buy_count+=1
        else:
            if sym not in positions:
                raise StockReservationError("shared_stock_sell_without_inventory")
            sell_by_symbol.setdefault(sym,[]).append((order,remaining))
    for symbol, sells in sell_by_symbol.items():
        total=sum((remaining for _,remaining in sells),D(0))
        if total<=positions[symbol]:
            continue
        # An OCO's conditional stop and take-profit are mutually exclusive.
        # Never assume an arbitrary pair of SELL orders is OCO. Both legs must
        # be explicitly broker-classified and match share quantities.
        if (len(sells)!=2
            or any(o.get("order_class")!="oco" for o,_ in sells)
            or {o.get("type") for o,_ in sells}!={"limit","stop"}
            or sells[0][1]!=sells[1][1]
            or sells[0][1]>positions[symbol]):
            raise StockReservationError("shared_stock_sell_inventory_exceeded")
        by_type={o.get("type"):o for o,_ in sells}
        if positive(by_type["stop"].get("stop_price"))>=positive(by_type["limit"].get("limit_price")):
            raise StockReservationError("shared_stock_oco_levels_unverifiable")
    return {"available_cash_usd":max(D(0),available-buy_reserve),
            "reserved_stock_buys_usd":buy_reserve,
            "pending_stock_buy_orders":buy_count,
            "stock_sell_symbols_verified":len(sell_by_symbol)}
