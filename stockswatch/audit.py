"""Read-only Aruba StocksWatch audit. Run locally with python -m stockswatch.audit."""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def snapshot(path, sessions):
    def fingerprint():
        result = []
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                st = path.with_name(path.name + suffix).stat()
                result.append((st.st_ino, st.st_size, st.st_mtime_ns))
            except FileNotFoundError:
                result.append(None)
        return result

    before = fingerprint()
    if before[0] is None:
        raise RuntimeError("database_missing")
    if before[3] or bool(before[1]) != bool(before[2]):
        raise RuntimeError("unstable_sqlite_sidecars_retry")
    # If no sidecars exist, immutable prevents SQLite from creating any.
    # Reject a changing snapshot instead of returning stale/partial totals.
    opts = "mode=ro" if before[1] else "mode=ro&immutable=1"
    with sqlite3.connect(path.as_uri() + "?" + opts, uri=True) as c:
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA query_only=ON")
        c.execute("BEGIN")

        def read(sql, params=()):
            return [dict(r) for r in c.execute(sql, params)]

        def exists(table):
            return bool(read("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)))

        account = read("SELECT cash,initial_cash,realized,paused,high_water FROM portfolio")[0]
        totals = read("""SELECT COALESCE(SUM(CASE side WHEN 'BUY' THEN -qty*price-fee
            ELSE qty*price-fee END),0) cash_delta,COALESCE(SUM(realized),0) realized FROM fills""")[
            0
        ]
        shares = read("""SELECT symbol,SUM(CASE side WHEN 'BUY' THEN qty ELSE -qty END) qty
            FROM fills GROUP BY symbol HAVING qty!=0 ORDER BY symbol""")
        positions = read("SELECT symbol,qty FROM positions ORDER BY symbol")
        marks = read(
            "SELECT day,cash,equity,exposure,drawdown FROM equity_curve ORDER BY day DESC LIMIT 1"
        )
        matching_orders = read("""SELECT COUNT(*) n FROM pending_orders o LEFT JOIN fills f
            ON f.order_id=o.id WHERE o.state='FILLED' AND f.id IS NULL
            UNION ALL SELECT COUNT(*) n FROM fills f LEFT JOIN pending_orders o
            ON o.id=f.order_id WHERE o.id IS NULL OR o.state!='FILLED' OR f.symbol!=o.symbol
            OR f.side!=o.side OR o.fill_day IS NOT f.fill_day""")
        result = {
            "database": str(path),
            "schema": read("SELECT value FROM metadata WHERE key='schema_version'")[0]["value"],
            "integrity": read("PRAGMA quick_check")[0]["quick_check"],
            "account": account,
            "positions": positions,
            "latest_equity": marks[0] if marks else None,
            "cash_reconciles": abs(account["initial_cash"] + totals["cash_delta"] - account["cash"])
            < 0.005,
            "realized_reconciles": abs(totals["realized"] - account["realized"]) < 0.005,
            "shares_reconcile": positions == shares,
            "equity_identity": not marks
            or abs(marks[0]["cash"] + marks[0]["exposure"] - marks[0]["equity"]) < 0.011,
            "fills_match_orders": all(r["n"] == 0 for r in matching_orders),
            "coverage": read("""SELECT source,COUNT(*) bars,COUNT(DISTINCT symbol) symbols,
                MIN(day) first_day,MAX(day) last_day,MAX(observed_at) last_observed FROM bars GROUP BY source"""),
            "provider": read("""SELECT source,COUNT(*) symbols,SUM(error IS NOT NULL) failed,
                MAX(last_success) last_success,MAX(last_attempt) last_attempt FROM sources GROUP BY source"""),
            "orders": read("SELECT side,state,COUNT(*) n FROM pending_orders GROUP BY side,state"),
            "pending": read("""SELECT symbol,side,signal_day,created_at,
                MAX(0,CAST((julianday('now')-julianday(created_at))*86400 AS INTEGER)) age_seconds
                FROM pending_orders WHERE state='PENDING' ORDER BY created_at"""),
            "all_fills": {"BUY": 0, "SELL": 0},
            "fills_last_30_market_sessions": {"BUY": 0, "SELL": 0},
            "sessions": {"first": sessions[0], "last": sessions[-1]},
            "decisions": read("SELECT action,COUNT(*) n FROM decisions GROUP BY action"),
            "legacy_reasons": read(
                """SELECT action,reasons_json,COUNT(*) n FROM decisions
                WHERE signal_day>=? GROUP BY action,reasons_json ORDER BY n DESC LIMIT 15""",
                (sessions[0],),
            ),
            "worker": read("""SELECT started_at,ended_at,state,stage FROM sw_scan_runs
                ORDER BY started_at DESC LIMIT 1""")
            if exists("sw_scan_runs")
            else [],
            "outcomes": read("""SELECT reason,COUNT(*) n FROM sw_order_outcomes GROUP BY reason""")
            if exists("sw_order_outcomes")
            else "not_in_deployed_schema",
        }
        for r in read(
            "SELECT side,COUNT(*) n,MAX(created_at) last_fill_at FROM fills GROUP BY side"
        ):
            result["all_fills"][r["side"]] = r["n"]
            result.setdefault("last_fill_by_side", {})[r["side"]] = r["last_fill_at"]
        for r in read(
            "SELECT side,COUNT(*) n FROM fills WHERE fill_day IN ("
            + ",".join("?" * len(sessions))
            + ") GROUP BY side",
            sessions,
        ):
            result["fills_last_30_market_sessions"][r["side"]] = r["n"]
        gates = {}
        if exists("sw_trade_cycles"):
            for row in read(
                "SELECT report_json FROM sw_trade_cycles WHERE market_day>=?", (sessions[0],)
            ):
                for item in json.loads(row["report_json"]).get("why_no_trade", []):
                    key = item["reason"]
                    gates[key] = gates.get(key, 0) + 1
        result["cycle_gate_distribution"] = gates or "unavailable"
    if not before[1] and fingerprint() != before:
        raise RuntimeError("sqlite_changed_during_snapshot_retry")
    return result


def remote(sessions):
    from importlib.util import find_spec
    import hashlib

    package = Path(find_spec("stockswatch").origin).parent
    path = Path(os.environ.get("STOCKSWATCH_DB", "/stockswatch-data/stockswatch.sqlite3")).resolve()
    if path.parent != Path("/stockswatch-data"):
        raise RuntimeError("unexpected_database_path")
    result = snapshot(path, sessions)
    result["python_source_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.glob("*.py"))
    }
    return result


def run_ssh(args, source=None):
    return subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "aruba-vps", *args],
        input=source,
        text=True,
        capture_output=True,
        check=True,
        timeout=45,
    ).stdout


def main():
    from .sessions import calendar, completed_day

    day = completed_day(datetime.now(timezone.utc))
    sessions = [str(d.date()) for d in calendar().sessions_window(day, -30)]
    prefix = "autotrader-aruba-test-"
    sw = prefix + "stockswatch-1"
    # Inspect only whitelisted Docker fields. Never read Config.Env or logs.
    template = (
        r"'{{.Name}} {{.Image}} {{.State.Status}} {{.RestartCount}} "
        r'{{index .Config.Labels "com.docker.compose.project"}} '
        r'{{range .Mounts}}{{if eq .Destination "/stockswatch-data"}}'
        r"{{.Type}} {{.Source}} {{.Destination}} {{.RW}}{{end}}{{end}}" + "'"
    )
    images = run_ssh(
        ["docker", "inspect", "-f", template, sw, prefix + "frontend-1", prefix + "backend-1"]
    )
    identity = [line.split() for line in images.splitlines()]
    if len(identity) != 3 or any(
        r[2] != "running" or r[4] != "autotrader-aruba-test" for r in identity
    ):
        raise RuntimeError("unexpected_compose_identity")
    if identity[0][5:] != [
        "bind",
        "/opt/personal-plan/staging/integrations/stockswatch-20261105-v1-3/data",
        "/stockswatch-data",
        "true",
    ]:
        raise RuntimeError("unexpected_ledger_mount")
    source = Path(__file__).read_text()
    result = json.loads(
        run_ssh(["docker", "exec", "-i", sw, "python", "-B", "-", "--remote", *sessions], source)
    )
    result["images"] = [
        dict(zip(("container", "image_id", "state", "restarts", "project"), r[:5]))
        for r in identity
    ]
    result["persistence"] = {"type": "bind", "source": identity[0][6], "target": identity[0][7]}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--remote"]:
        print(json.dumps(remote(sys.argv[2:])))
    else:
        main()
