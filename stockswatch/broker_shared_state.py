"""Pure fail-closed validation of the shared Alpaca Paper account snapshot.

The broker GET /v2/positions and GET /v2/orders both include US equities
AND cryptocurrency; never compare that full response with stock-only lists.
"""
from __future__ import annotations


def shared_state_matches(snapshot, fresh_positions, fresh_orders):
    if not isinstance(fresh_positions,list) or not isinstance(fresh_orders,list):
        return False
    if not all(isinstance(x,dict) for x in fresh_positions+fresh_orders):
        return False
    prior_positions=snapshot.get("positions",[])+snapshot.get("other_positions",[])
    prior_orders=snapshot.get("open_orders",[])+snapshot.get("other_open_orders",[])
    if not all(isinstance(x,dict) for x in prior_positions+prior_orders):
        return False

    def keyed(rows,key,fields):
        result={}
        for item in rows:
            name=item.get(key)
            if not isinstance(name,str) or not name or name in result:
                return None
            result[name]=tuple(item.get(f) for f in fields)
        return result

    position_fields=("asset_id","qty","qty_available","side",
                     "avg_entry_price","asset_class")
    left=keyed(prior_positions,"symbol",position_fields)
    right=keyed(fresh_positions,"symbol",position_fields)
    if left is None or right is None or left!=right:
        return False
    left=keyed(prior_orders,"id",("client_order_id","symbol","side",
               "status","qty","filled_qty","type","limit_price","stop_price"))
    right=keyed(fresh_orders,"id",("client_order_id","symbol","side",
               "status","qty","filled_qty","type","limit_price","stop_price"))
    return left is not None and right is not None and left==right
