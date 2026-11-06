"""Additive evidence schema for the StocksWatch intraday strategy."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .direction import SHORT_PREFIX, fifo, intent_action
from .intraday_policy import ORDER_PREFIX, STRATEGY, phase_at
from .storage import connect, one, rows

SCHEMA = """
CREATE TABLE IF NOT EXISTS sw_intraday_cycles (
    id TEXT PRIMARY KEY, at TEXT NOT NULL, report_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sw_intraday_cycle_time ON sw_intraday_cycles(at);
CREATE TABLE IF NOT EXISTS sw_intraday_observations (
    cycle_id TEXT NOT NULL REFERENCES sw_intraday_cycles(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL, at TEXT NOT NULL, session TEXT NOT NULL,
    valid INTEGER NOT NULL, action TEXT NOT NULL, evidence_json TEXT NOT NULL,
    PRIMARY KEY(cycle_id,symbol)
);
CREATE INDEX IF NOT EXISTS sw_intraday_symbol_time ON sw_intraday_observations(symbol,at);
CREATE TABLE IF NOT EXISTS sw_intraday_followups (
    cycle_id TEXT NOT NULL, symbol TEXT NOT NULL, at TEXT NOT NULL, outcome_json TEXT NOT NULL,
    PRIMARY KEY(cycle_id,symbol),
    FOREIGN KEY(cycle_id,symbol) REFERENCES sw_intraday_observations(cycle_id,symbol) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS sw_intraday_risk (
    account_id TEXT NOT NULL, trade_date TEXT NOT NULL, paused_at TEXT NOT NULL,
    PRIMARY KEY(account_id,trade_date)
);
CREATE TABLE IF NOT EXISTS sw_intraday_fills (
    id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES sw_alpaca_intents(client_id),
    symbol TEXT NOT NULL, at TEXT NOT NULL, side TEXT NOT NULL, qty TEXT NOT NULL, price TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sw_intraday_fill_costs (
    fill_id TEXT NOT NULL REFERENCES sw_intraday_fills(id),
    component TEXT NOT NULL, usd TEXT NOT NULL,
    PRIMARY KEY(fill_id,component)
);
"""


def initialize():
    with connect() as c:
        c.executescript(SCHEMA)
        c.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('sw_intraday_schema','1')")


def save(report):
    at = datetime.fromisoformat(report["at"])
    key = at.isoformat()
    # Each observation receipt has one immutable timestamp and one decision per symbol.
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        result = c.execute(
            "INSERT OR IGNORE INTO sw_intraday_cycles VALUES(?,?,?)",
            (
                key,
                key,
                json.dumps({k: v for k, v in report.items() if k != "rows"}, allow_nan=False),
            ),
        )
        if result.rowcount:
            c.executemany(
                "INSERT INTO sw_intraday_observations VALUES(?,?,?,?,?,?,?)",
                [
                    (
                        key,
                        r["symbol"],
                        key,
                        r["session"],
                        int(r["valid"]),
                        r["action"],
                        json.dumps(r, allow_nan=False),
                    )
                    for r in report["rows"]
                ],
            )
            _followups(c, report, at)
            c.execute(
                "DELETE FROM sw_intraday_cycles WHERE at<?", ((at - timedelta(days=7)).isoformat(),)
            )
        c.commit()


def _followups(c, report, at):
    # Forward mark only the first current valid quote 30–33 minutes later.
    # Bid vs historical ask with stress is an observational price path, never a fill.
    for r in report["rows"]:
        if not r["valid"] or r["feed"] != "sip":
            continue
        start = (at - timedelta(minutes=33)).isoformat()
        end = (at - timedelta(minutes=30)).isoformat()
        previous = c.execute(
            """
            SELECT o.cycle_id,o.evidence_json FROM sw_intraday_observations o
            LEFT JOIN sw_intraday_followups f ON f.cycle_id=o.cycle_id AND f.symbol=o.symbol
            WHERE o.symbol=? AND o.session=? AND o.at BETWEEN ? AND ? AND o.valid=1
                AND o.action='WAIT' AND f.cycle_id IS NULL ORDER BY o.at LIMIT 8
            """,
            (r["symbol"], r["session"], start, end),
        ).fetchall()
        for old in previous:
            evidence = json.loads(old["evidence_json"])
            if evidence["feed"] != r["feed"] or not evidence.get("setup"):
                continue
            net = (
                Decimal(str(r["quote"]["bp"]))
                / Decimal(str(evidence["quote"]["ap"]))
                * Decimal(".999")
                - 1
            )
            c.execute(
                "INSERT OR IGNORE INTO sw_intraday_followups VALUES(?,?,?,?)",
                (
                    old["cycle_id"],
                    r["symbol"],
                    at.isoformat(),
                    json.dumps({"net_proxy_bps": str(net * 10000), "kind": "FORWARD_QUOTE_PROXY"}),
                ),
            )


def status(now=None):
    now = now or datetime.now(UTC)
    latest = one("SELECT * FROM sw_intraday_cycles ORDER BY at DESC LIMIT 1")
    current = phase_at(now)
    if not latest:
        return {"strategy": STRATEGY, "status": "STARTING", "phase": current.name, "rows": []}
    evidence = json.loads(latest["report_json"])
    age = (now - datetime.fromisoformat(latest["at"])).total_seconds()
    stale = not 0 <= age <= 100 or current.name != evidence["phase"]
    evidence.update(
        stale=stale, current_phase=current.name, valid=0 if stale else evidence["valid"]
    )
    evidence["rows"] = [
        json.loads(r["evidence_json"])
        for r in rows(
            "SELECT evidence_json FROM sw_intraday_observations WHERE cycle_id=? ORDER BY symbol",
            (latest["id"],),
        )
    ]
    return evidence


def order_history():
    result = rows(
        """
        SELECT client_id,symbol,side,qty,state,broker_status,created_at,updated_at,detail_json
        FROM sw_alpaca_intents WHERE client_id LIKE ? OR client_id LIKE ? ORDER BY created_at DESC LIMIT 24
    """,
        (ORDER_PREFIX + "%", SHORT_PREFIX + "%"),
    )
    for row in result:
        detail = json.loads(row.pop("detail_json"))
        row.update(
            reason=detail.get("reason"),
            limit_price=detail.get("limit_price"),
            session=detail.get("session"),
            filled_qty=detail.get("filled_qty"),
            action=intent_action(row["client_id"], row["side"]).value,
            risk=detail.get("risk"),
        )
    return result


def pnl(account_id, prefix=ORDER_PREFIX):
    """FIFO from confirmed own fill activities. Suppress if the order set is incomplete."""
    intents = rows(
        """
        SELECT client_id,state,broker_status,detail_json FROM sw_alpaca_intents
        WHERE account_id=? AND client_id LIKE ?
    """,
        (account_id, prefix + "%"),
    )
    if not intents:
        return {"status": "NO_CONFIRMED_INTRADAY_FILLS", "realized_usd": None}
    fills = rows(
        """
        SELECT f.* FROM sw_intraday_fills f JOIN sw_alpaca_intents i USING(client_id)
        WHERE i.account_id=? AND i.client_id LIKE ? ORDER BY f.at,f.id
    """,
        (account_id, prefix + "%"),
    )
    totals = {}
    tape = []
    try:
        for fill in fills:
            qty, price = (Decimal(fill[k]) for k in ("qty", "price"))
            cid = fill["client_id"]
            totals[cid] = totals.get(cid, Decimal(0)) + qty
            tape.append((intent_action(cid, fill["side"]), fill["symbol"], qty, price))
        realized, lots = fifo(tape)
    except ValueError:
        return {"status": "INCOMPLETE_FILL_LINEAGE", "realized_usd": None}
    for i in intents:
        detail = json.loads(i["detail_json"])
        if i["state"] in {"PREPARED", "UNKNOWN"} or (
            i["broker_status"]
            and (
                "filled_qty" not in detail
                or totals.get(i["client_id"], Decimal(0)) != Decimal(detail["filled_qty"])
            )
        ):
            return {"status": "INCOMPLETE_FILL_LINEAGE", "realized_usd": None}
    costs = rows(
        """SELECT x.usd FROM sw_intraday_fill_costs x JOIN sw_intraday_fills f ON f.id=x.fill_id
        JOIN sw_alpaca_intents i USING(client_id) WHERE i.account_id=? AND i.client_id LIKE ?""",
        (account_id, prefix + "%"),
    )
    known_costs = sum((Decimal(r["usd"]) for r in costs), Decimal(0))
    return {
        "status": "BROKER_FILL_FIFO_PRICE_PNL",
        "realized_usd": str(realized) if fills else None,
        "confirmed_fills": len(fills),
        "fees_and_financing": "UNVERIFIED_TOTAL",
        "known_broker_fill_costs_usd": str(known_costs) if costs else None,
        "pnl_after_known_costs_usd": str(realized - known_costs) if costs else None,
        "open_cost_basis_usd": str(sum(q * p for inv in lots.values() for _, q, p in inv)),
        "open_quantity": {s: str(sum(q for _, q, _ in inv)) for s, inv in lots.items() if inv},
    }


def missed_proxies():
    row = one("""SELECT COUNT(*) AS resolved,
        SUM(CASE WHEN CAST(json_extract(outcome_json,'$.net_proxy_bps') AS REAL)>0 THEN 1 ELSE 0 END) AS positive
        FROM sw_intraday_followups""")
    return {
        "resolved": row["resolved"],
        "positive": row["positive"] or 0,
        "kind": "FORWARD_QUOTE_PROXY",
    }


def daily_loss_paused(account_id, day, breached, now):
    with connect() as c:
        if breached:
            c.execute(
                "INSERT OR IGNORE INTO sw_intraday_risk VALUES(?,?,?)",
                (account_id, day, now.isoformat()),
            )
        return (
            c.execute(
                "SELECT 1 FROM sw_intraday_risk WHERE account_id=? AND trade_date=?",
                (account_id, day),
            ).fetchone()
            is not None
        )
