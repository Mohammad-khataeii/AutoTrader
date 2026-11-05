"""Read-only PostgreSQL acquisition into the shared, content-addressed research store."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from psycopg import sql

from autotrader.learning.features import stamp
from autotrader.research.data import TIMEFRAMES, canonical, digest

HORIZONS = (15, 60, 240, 1440)
SCHEMA = "cross-account-evidence/1"
EPOCH = "1970-01-01T00:00:00.000000+00:00"
# table: stable key, extraction ordering column, refresh current projections
TABLES = {
    "market_candles": ("id", "id", False),
    "market_features": ("feature_id", "created_at", False),
    "strategy_signals": ("signal_id", "created_at", False),
    "trading_decisions": ("decision_id", "created_at", False),
    "orders": ("order_id", "created_at", True),
    "fills": ("fill_id", "created_at", False),
    "positions": ("position_id", "created_at", True),
    "exit_plans": ("exit_plan_id", "created_at", True),
    "exit_targets": ("target_id", "updated_at", True),
    "exit_intents": ("exit_intent_id", "created_at", True),
    "financial_journal": ("ledger_event_id", "created_at", False),
    "order_transitions": ("transition_id", "created_at", False),
    "risk_evaluations": ("evaluation_id", "created_at", False),
    "equity_snapshots": ("snapshot_id", "created_at", False),
    "system_incidents": ("incident_id", "created_at", True),
    "paper_multi_signals": ("id", "cutoff", False),
    "paper_multi_events": ("id", "id", False),
}
REQUIRED = {"market_candles", "market_features", "strategy_signals", "trading_decisions",
            "orders", "fills", "positions", "financial_journal"}


def utc(value: str | datetime) -> str:
    moment = stamp(value) if isinstance(value, str) else value
    if moment.tzinfo is None:
        raise ValueError("source_timestamp_has_no_timezone")
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def now_utc() -> str:
    return utc(datetime.now(UTC))


@dataclass(frozen=True)
class Source:
    database: str
    role: str
    identity: str
    manifest: dict[str, Any]
    state: str
    archived: bool = False


def sources(connection, database: str) -> list[Source]:
    """Only the configured root and explicitly registered paper databases."""
    if not database or not re.fullmatch(r"[a-zA-Z0-9_]{1,63}", database) or re.match(r"autotrader_(paper|shadow)_", database):
        raise ValueError("operational_root_required")
    rows = [Source(database, "OPERATIONAL", "paper-eur", {}, "RETAINED")]
    origin = connection.execute(
        "SELECT payload_json FROM public.system_state WHERE key='personal_paper_v47'"
    ).fetchone()
    if origin:
        manifest = json.loads(origin["payload_json"])
        rows.append(Source(manifest["database_name"], "PERSONAL", manifest["account_id"], manifest, "RETAINED"))
    for row in connection.execute("""
        SELECT s.experiment_id,s.database_name,s.state,s.manifest_json,
          EXISTS(SELECT 1 FROM public.system_state a WHERE a.key='shadow_archive:'||s.experiment_id) AS archived
        FROM public.shadow_experiments s ORDER BY s.experiment_id
    """):
        manifest = json.loads(row["manifest_json"])
        if manifest["experiment_id"] != row["experiment_id"] or manifest["database_name"] != row["database_name"]:
            raise ValueError("shadow_registry_identity_mismatch")
        rows.append(Source(row["database_name"], "SHADOW", row["experiment_id"], manifest, row["state"], row["archived"]))
    if len({s.database for s in rows}) != len(rows):
        raise ValueError("duplicate_registered_database")
    for row in rows[1:]:
        prefix = "paper" if row.role == "PERSONAL" else "shadow"
        if (not re.fullmatch(rf"autotrader_{prefix}_[a-f0-9]{{32}}", row.database)
                or row.manifest.get("official_database") != database
                or row.manifest.get("live_authorized") is True):
            raise ValueError("unverified_research_source_scope")
    return rows


def assert_source(connection, source: Source) -> None:
    if connection.execute("SELECT current_database() AS name").fetchone()["name"] != source.database:
        raise ValueError("connected_database_identity_mismatch")
    if source.role == "OPERATIONAL":
        return
    marker = connection.execute("SELECT manifest_hash,manifest_json FROM public.shadow_identity WHERE singleton=1").fetchone()
    if (not marker or json.loads(marker["manifest_json"]) != source.manifest
            or marker["manifest_hash"] != digest(canonical(source.manifest))):
        raise ValueError("research_source_manifest_mismatch")


def connect_read_only(url):
    import psycopg
    from psycopg.rows import dict_row

    if url.get_backend_name() != "postgresql":
        raise ValueError("postgresql_read_only_source_required")
    sslmode = url.query.get("sslmode")
    if set(url.query)-{"sslmode"} or sslmode is not None and not isinstance(sslmode,str):
        raise ValueError("unsupported_research_source_connection_options")
    return psycopg.connect(dbname=url.database, user=url.username, password=url.password,
                           host=url.host, port=url.port or 5432, row_factory=dict_row,
                           options="-c default_transaction_read_only=on -c statement_timeout=20000 -c work_mem=4MB",
                           connect_timeout=5, **({"sslmode":sslmode} if sslmode else {}))


def json_row(raw: str) -> dict:
    row = json.loads(raw, parse_float=str)
    for name in ("payload_json", "execution_json", "settings_json"):
        if row.get(name) is not None:
            row[name] = json.loads(row[name], parse_float=str)
            if not isinstance(row[name], dict):
                raise ValueError("structured_source_payload_required")
    return row


def candle(row: dict) -> dict:
    row = {k: row[k] for k in ("symbol", "timeframe", "timestamp", "source", "open", "high", "low", "close", "volume")}
    row["timestamp"] = utc(row["timestamp"])
    seconds = TIMEFRAMES[row["timeframe"]]
    if stamp(row["timestamp"]).timestamp() % seconds or not row["source"]:
        raise ValueError("invalid_candle_provenance_or_grid")
    for k in ("open", "high", "low", "close", "volume"):
        value = Decimal(str(row[k]))
        if not value.is_finite() or value < 0 or (k != "volume" and value == 0):
            raise ValueError("invalid_candle_value")
        row[k] = format(value.normalize(), "f")
    o, h, low, c = (Decimal(row[k]) for k in ("open", "high", "low", "close"))
    if not low <= min(o, c) <= max(o, c) <= h:
        raise ValueError("contradictory_candle_geometry")
    return row


def retain(store, source: Source, kind: str, record_id: str, raw: str, collected_at: str,
           horizons=HORIZONS) -> bool:
    try:
        row = json_row(raw)
        known = utc(row["created_at"]) if row.get("created_at") else None
        if known and known > collected_at:
            raise ValueError("source_record_created_in_future")
        observed = utc(row["timestamp"]) if row.get("timestamp") else known or collected_at
        if kind == "market_candles":
            row = candle(row)
            if stamp(observed)+timedelta(seconds=TIMEFRAMES[row["timeframe"]]) > stamp(collected_at):
                raise ValueError("unclosed_candle_at_extraction")
        elif kind == "market_features":
            # Source row ID and creation time are retained in refs, not duplicated in content.
            row.pop("feature_id", None)
            row.pop("created_at", None)
            row["timestamp"] = observed
        payload = canonical(row)
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        store.db.execute("INSERT OR IGNORE INTO research_errors VALUES (?,?,?,?,?)",
                         (source.database, kind, record_id, digest(raw.encode()), type(error).__name__+":"+str(error)[:160]))
        return False
    identity = digest(payload)
    previous = store.db.execute("SELECT content_hash FROM research_refs WHERE source=? AND kind=? AND record_id=?",
                                (source.database,kind,record_id)).fetchone()
    store.db.execute("INSERT OR IGNORE INTO research_content VALUES (?,?)", (identity, payload.decode()))
    store.db.execute("INSERT OR IGNORE INTO research_versions VALUES (?,?,?,?,?,?)",
                     (source.database, kind, record_id, identity, collected_at, known))
    store.db.execute("""INSERT INTO research_refs VALUES (?,?,?,?,?,?,?,?,?,?,?)
       ON CONFLICT(source,kind,record_id) DO UPDATE SET content_hash=excluded.content_hash,
       known_at=excluded.known_at, observed_at=excluded.observed_at,symbol=excluded.symbol,
       timeframe=excluded.timeframe,position_id=excluded.position_id,order_id=excluded.order_id,
       decision_id=excluded.decision_id""",
       (source.database, kind, record_id, identity, known, observed, row.get("symbol"), row.get("timeframe"),
        row.get("position_id"), row.get("order_id"), row.get("decision_id")))
    if kind == "trading_decisions":
        links = row["payload_json"].get("signal_ids")
        if isinstance(links, list):
            store.db.executemany("INSERT OR IGNORE INTO research_links VALUES (?,?,?)",
                                 [(source.database, s, record_id) for s in links if isinstance(s, str)])
    if (kind == "strategy_signals" or kind == "trading_decisions" and row["action"] in {"WAIT", "BUY"}) and known:
        for horizon in horizons:
            due = utc(stamp(known)+timedelta(minutes=horizon))
            key = digest(canonical([SCHEMA, source.database, kind, record_id, identity, horizon]))
            store.db.execute("""INSERT OR IGNORE INTO research_tasks
                (id,source,kind,record_id,content_hash,symbol,observed_at,due_at,horizon,next_attempt_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (key, source.database, kind, record_id, identity, row["symbol"], known, due, horizon, due))
    if previous != (identity,) and kind in {"trading_decisions","orders","positions","fills","financial_journal","exit_targets","exit_intents"}:
        decision_ids = {row["decision_id"]} if row.get("decision_id") else set()
        if row.get("position_id"):
            decision_ids.update(r[0] for r in store.db.execute("""SELECT DISTINCT decision_id FROM research_refs
                WHERE source=? AND kind='orders' AND position_id=? AND decision_id IS NOT NULL""",
                (source.database,row["position_id"])))
        for decision_id in decision_ids:
            store.db.execute("""UPDATE research_tasks SET status='PENDING',next_attempt_at=due_at WHERE source=? AND
                (kind='trading_decisions' AND record_id=? OR kind='strategy_signals' AND record_id IN
                 (SELECT signal_id FROM research_links WHERE source=? AND decision_id=?))""",
                (source.database,decision_id,source.database,decision_id))
    return True


def acquire(store, connection, source: Source, *, batch=500, sweep=False, horizons=HORIZONS) -> dict:
    """One bounded page per table. Cursor + evidence commit together.

    The caller establishes a repeatable-read snapshot. A sweep refreshes old
    mutable projections and discovers historical rows inserted behind a cursor.
    """
    if not 1 <= batch <= 5000 or not horizons or any(h < 5 or h > 1440 or h % 5 for h in horizons):
        raise ValueError("invalid_collection_bounds")
    assert_source(connection, source)
    captured = utc(connection.execute("SELECT transaction_timestamp() AS at").fetchone()["at"])
    tables = {r["table_name"] for r in connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
    if not REQUIRED <= tables:
        raise ValueError("source_required_tables_missing")
    prior = store.db.execute("SELECT role,identity,payload FROM research_sources WHERE source=?", (source.database,)).fetchone()
    if prior and (prior[:2] != (source.role, source.identity) or json.loads(prior[2])["manifest_hash"] != digest(canonical(source.manifest))):
        raise ValueError("research_registry_identity_changed")
    report = {}
    with store.db:
        store.db.execute("""INSERT INTO research_sources VALUES (?,?,?,?) ON CONFLICT(source) DO UPDATE SET payload=excluded.payload""",
                         (source.database, source.role, source.identity, canonical({
                             "manifest":source.manifest, "manifest_hash":digest(canonical(source.manifest)),
                             "state":source.state,"archived":source.archived,"collected_at":captured}).decode()))
        for kind, (key, order, mutable) in TABLES.items():
            if kind not in tables or sweep and not mutable and sweep != "all":
                continue
            cursor_kind = kind+(":sweep" if sweep else "")
            saved = store.db.execute("SELECT payload FROM research_cursors WHERE source=? AND kind=?",
                                     (source.database,cursor_kind)).fetchone()
            numeric = order in {"id","cutoff"}
            default = [0, ""] if numeric else [EPOCH, ""]
            last = json.loads(saved[0]) if saved else default
            bound = sql.SQL("") if numeric else sql.SQL(" AND t.{} <= %s::timestamptz").format(sql.Identifier(order))
            query = sql.SQL("""SELECT t.{key}::text AS record_id,t.{order} AS cursor,to_jsonb(t)::text AS raw
                FROM public.{kind} t WHERE (t.{order},t.{key}::text)>(%s::{typ},%s){bound}
                ORDER BY t.{order},t.{key}::text LIMIT %s""").format(
                key=sql.Identifier(key),order=sql.Identifier(order),kind=sql.Identifier(kind),
                typ=sql.SQL("bigint" if numeric else "timestamptz"),bound=bound)
            rows = connection.execute(query, [*last, *([] if numeric else [captured]), batch]).fetchall()
            accepted = 0
            for row in rows:
                accepted += retain(store,source,kind,row["record_id"],row["raw"],captured,horizons)
                last = [row["cursor"] if numeric else utc(row["cursor"]),row["record_id"]]
            if sweep and len(rows)<batch:
                last = default
            store.db.execute("INSERT INTO research_cursors VALUES (?,?,?) ON CONFLICT(source,kind) DO UPDATE SET payload=excluded.payload",
                             (source.database,cursor_kind,canonical(last).decode()))
            report[kind] = {"read":len(rows),"retained":accepted,"more":len(rows)==batch}
    return report


def referenced(store, source: str, kind: str, *, column="record_id", value: str) -> list[dict]:
    if column not in {"record_id","position_id","decision_id","order_id"}:
        raise ValueError("invalid_reference_axis")
    return [json.loads(r[0]) for r in store.db.execute(f"""SELECT c.payload FROM research_refs r
        JOIN research_content c ON c.hash=r.content_hash WHERE r.source=? AND r.kind=? AND r.{column}=?
        ORDER BY r.observed_at,r.record_id""", (source,kind,value))]


def acquire_fresh_signals(store, connection, source: Source, captured: str) -> None:
    """Independent current-signal lane so backfill cannot delay scoring."""
    assert_source(connection, source)
    if not store.db.execute("SELECT 1 FROM research_sources WHERE source=? AND identity=?",
                            (source.database,source.identity)).fetchone():
        return
    since=stamp(captured)-timedelta(seconds=60)
    rows=connection.execute("""SELECT signal_id,to_jsonb(s)::text AS raw FROM public.strategy_signals s
        WHERE created_at BETWEEN %s AND %s ORDER BY created_at DESC,signal_id LIMIT 120""",
        (since,stamp(captured))).fetchall()
    with store.db:
        for row in rows:
            retain(store,source,"strategy_signals",row["signal_id"],row["raw"],captured)
