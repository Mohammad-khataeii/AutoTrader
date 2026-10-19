"""Assemble release evidence from executed checks; refuse failed or missing inputs."""
from __future__ import annotations

import hashlib
import json
import platform
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from autotrader.shadow.versions import (
    LEGACY_SOURCE,
    V44_EXECUTION,
    V44_PACKAGE,
    compatibility,
    execution_fingerprint,
    verify_boundary,
    verify_legacy,
    verify_v44,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/v4_5_rc2"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((OUT / name).read_text())


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, default=str) + "\n")


def suite(name):
    node = ET.parse(OUT / name).getroot().find("testsuite")
    assert node is not None
    data = {k: int(node.attrib[k]) for k in ("tests", "errors", "failures", "skipped")}
    data["duration_seconds"] = float(node.attrib["time"])
    assert data["tests"] > 0 and not any(data[k] for k in ("errors", "failures", "skipped")), data
    return data


def main():
    verify_boundary()
    assert len(verify_legacy()) == 71 and len(verify_v44()) == 76
    app = {str(p.relative_to(ROOT / "src/autotrader")): sha(p)
           for p in sorted((ROOT / "src/autotrader").rglob("*.py"))}
    fingerprint = hashlib.sha256(json.dumps(app, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    before, intermediate, final = read("production-before.json"), read("production-current.json"), read("production-final.json")
    assert not final["live_trading_enabled"] and len(final["accounts"]) == 9
    prior = {r["identity"]: r for r in before["accounts"]}
    middle = {r["identity"]: r for r in intermediate["accounts"]}
    records, financial = [], []
    core = {"accounts", "balances", "financial_journal", "fills", "positions", "capital_reservations",
            "exit_intents", "exit_targets", "exit_plans", "cooldowns", "ai_budgets", "ai_usage"}
    for r in final["accounts"]:
        old = prior[r["identity"]]
        assert not r["reconciliation"] and not r["open_positions"] and not r["open_orders"]
        assert all(old["financial_seal"][t] == r["financial_seal"][t] for t in core)
        assert old["manifest"] == r["manifest"] and old["archive"] == r["archive"] and old["state"] == r["state"]
        assert len(r["funding"]) == 1 and float(r["funding"][0]["cash_delta"]) == 500
        changed = {k: {"before": old["financial_seal"][k], "after": v}
                   for k, v in r["financial_seal"].items() if k in old["financial_seal"] and old["financial_seal"][k] != v}
        if r["archive"]:
            assert not changed and middle[r["identity"]]["financial_seal"] == r["financial_seal"]
        financial.append({"identity": r["identity"], "database": r["database_name"], "core_financial_seals_unchanged": True,
            "manifest_unchanged": True, "archive_unchanged": True, "funding_count": 1, "funding_eur": 500,
            "reconciliation": [], "open_positions": 0, "open_orders": 0, "fills": r["financial_seal"]["fills"]["rows"],
            "concurrent_existing_worker_changes": changed, "final_financial_seal": r["financial_seal"]})
        if r["manifest"]:
            runtime = compatibility(r["manifest"])
            assert runtime["compatible"] and r["identity_matches"]
            records.append({"identity": r["identity"], "state": r["state"], "archive": r["archive"],
                "manifest": r["manifest"], "manifest_hash": r["manifest_hash"], "runtime": runtime,
                "manifest_and_database_marker_unchanged": True})
    old_orders = {o["order_id"]: o for a in intermediate["accounts"] for o in a.get("recent_orders", [])}
    final_orders = {o["order_id"]: o for a in final["accounts"] for o in a.get("recent_orders", [])}
    assert old_orders and all(final_orders[k] == v for k, v in old_orders.items())
    assert all(o["status"] == "REJECTED" and o["rejection_reason"] == "execution_quality:first_target_destroyed_by_execution_costs" for o in final_orders.values())
    save("eight-account-manifest-verification.json", {"engineering_status": "PASS", "evidence_class": "REAL_PRODUCTION_READ_ONLY_OBSERVATION_WITH_LOCAL_COMPATIBILITY_CHECK",
        "source_snapshots": ["production-before.json", "production-current.json", "production-final.json"],
        "manifest_count": 8, "active": 4, "archived_stopped": 4, "accounts": records})
    save("financial-integrity.json", {"engineering_status": "PASS", "evidence_class": "REAL_PRODUCTION_READ_ONLY_OBSERVATION",
        "start": before["captured_at"], "finish": final["captured_at"], "database_count": 9, "accounts": financial,
        "earlier_saved_orders_byte_equivalent_in_final_export": len(old_orders), "new_worker_rejected_orders": len(final_orders) - len(old_orders),
        "production_mutation_by_stage_a": False, "scope": "Dated live snapshots, not a coordinated cross-account cut. Existing workers continued valuations/risk-period rollovers and one rejected order. Initial snapshot seals cover 15 tables; final and isolated restore cover 19. No financial history overwrite claim from merely equal row counts."})
    backend, trace, compiled = suite("backend-tests.xml"), suite("trace-api-tests.xml"), suite("compiled-lifecycle-tests.xml")
    checks = read("local-checks.json")
    assert all(c["exit_code"] == 0 for c in checks["commands"])
    browser = read("browser-tests.json")["stats"]
    assert browser["expected"] == 25 and not any(browser[k] for k in ("unexpected", "skipped", "flaky"))
    image, lifecycle, restore = read("amd64-runtime-verification.json"), read("amd64-lifecycles.json"), read("nine-database-backup-restore.json")
    assert image["status"] == lifecycle["status"] == restore["status"] == "PASS"
    assert image["application_source_fingerprint"] == fingerprint and image["v45_execution"] == execution_fingerprint()
    assert lifecycle["candidate_execution"] == execution_fingerprint() and len(lifecycle["accounts"]) == 12
    assert restore["candidate_image_id"] == image["image_id"] and restore["database_count"] == 9
    assert restore["candidate"]["status"] == restore["rollback"]["status"] == restore["backup_discovery_exercise"]["status"] == "PASS"
    save("backend-tests.json", {"engineering_status": "PASS", "evidence_class": "SYNTHETIC_DETERMINISTIC_ENGINEERING_TEST",
        "environment": checks["environment"], "full_suite": backend, "supplemental_new_trace_api_case": trace,
        "distinct_tests_passed": backend["tests"] + trace["tests"], "compiled_three_generation_browser_lifecycles": compiled,
        "commands": ["AUTOTRADER_RC2_EVIDENCE=docs/evidence/v4_5_rc2/lifecycles python3 .tools/with_pg.py python3 -m pytest -q --junitxml=docs/evidence/v4_5_rc2/backend-tests.xml",
            "python3 .tools/with_pg.py python3 -m pytest -q tests/test_v45_trade_gates.py::test_durable_trace_api_authentication_scope_and_bounded_pagination --junitxml=docs/evidence/v4_5_rc2/trace-api-tests.xml"],
        "notes": ["The full run collected 235 cases; the new authenticated trace-pagination case was added and executed separately while that run was active.",
            "Initial 230-pass/2-failure evidence is retained. Fixed calendar-dependent test fixture and outdated gateway mock; unchanged financial risk rules.",
            "Starlette/AnyIO deprecation warning remains; PostgreSQL-dependent tests were executed, not skipped."]})
    save("frontend-tests.json", {"engineering_status": "PASS", "evidence_class": "SYNTHETIC_DETERMINISTIC_ENGINEERING_TEST",
        "unit_tests_passed": 12, "browser": browser, "typescript": "PASS", "production_build": "PASS",
        "commands": [c for c in checks["commands"] if c["kind"].startswith("frontend")],
        "build_warning": "Main JavaScript bundle exceeds the 500 kB advisory threshold; build passes.",
        "compiled_browser_lifecycles": {r: read(r + "-frontend-lifecycle.json") for r in ("legacy", "frozen-v44", "native")}})
    save("trade-gate-ui-tests.json", {"engineering_status": "PASS", "evidence_class": "SYNTHETIC_DETERMINISTIC_ENGINEERING_TEST",
        "browser": browser, "viewport_widths": [375, 768, 1024, 1440], "visual_review": "PASS desktop and mobile: critical red state, missing evidence, internal table scroll, durable refusal and runtime exception",
        "authenticated_real_local_api_cases": 2, "mock_api_interaction_cases": 23,
        "new_trace_api_case": trace, "production_browser_mutations": False,
        "screenshots": ["trade-gates-incompatible-desktop.png", "trade-gates-exception-mobile.png"],
        "limitations": "Controlled UI fixtures prove behavior, not production telemetry or market performance. Real financial lifecycle screenshots are independent isolated API/worker proofs."})
    save("amd64-container-tests.json", {"engineering_status": "PASS", "evidence_class": "SYNTHETIC_DETERMINISTIC_ENGINEERING_TEST",
        "runtime": image, "actual_candidate_lifecycle_count": 12, "lifecycle_evidence_sha256": sha(OUT / "amd64-lifecycles.json"),
        "restore_evidence_sha256": sha(OUT / "nine-database-backup-restore.json"),
        "commands": [c for c in checks["commands"] if c["kind"].startswith("amd64")],
        "integration_command": "python3 scripts/run_rc2_container_acceptance.py",
        "isolation": "Internal Docker networks, ephemeral PostgreSQL tmpfs, no exposed ports, read-only candidate, no production route or exchange orders"})
    accepted = []
    for r in records:
        if r["state"] != "SHADOW_ACTIVE":
            continue
        name = "lifecycles/" + r["identity"] + "-lifecycle.json"
        proof = read(name)
        assert proof["status"] == "PASS" and proof["manifest"] == r["manifest"] and len(proof["fills"]) == 2 and not proof["reconciliation"]
        accepted.append({"identity": r["identity"], "strategy": r["manifest"]["strategy_id"], "manifest_unchanged": True,
            "entry_fill_and_protective_exit_fills": 2, "evidence": name, "sha256": sha(OUT / name)})
    save("native-entry-acceptance.json", {"engineering_status": "PASS", "evidence_class": "SYNTHETIC_DETERMINISTIC_ENGINEERING_TEST_WITH_PRODUCTION_IDENTICAL_MANIFEST_FIXTURES",
        "accounts": accepted, "outbound_production_network_refused": True, "current_financial_implementations_poisoned_to_raise": True,
        "scope": "Original V44 raw-candle calculations, valid order/fill/protect/close, duplicate-candle suppression, reconstructed runner, original immutable parameters and funding isolation. Separate refused-cost/stale/risk tests retain exact reasons. No original financial database writes."})
    stage_proofs = [read(a["evidence"]) for a in accepted]
    events = [e for p in stage_proofs for trace_body in p["trace"] for e in trace_body["events"].values()]
    save("execution-gateway-traces.json", {"engineering_status": "PASS", "evidence_class": "SYNTHETIC_DETERMINISTIC_ENGINEERING_TEST",
        "successful_stage_names": sorted({e["stage"] for e in events if e["status"] == "SUCCEEDED"}),
        "event_count_in_four_identity_proofs": len(events), "historical_production_trace_status": "NOT_RECORDED",
        "historical_phrase": "Historical execution outcome not verified", "actual_historical_refusal_orders": len(final_orders),
        "durable_production_order_evidence": "execution-cost-analysis.json", "trace_api_pagination_authentication": trace,
        "dedup_failure_exception_cases": "tests/test_v45_rc2_safety.py",
        "scope": "Actual synthetic persisted events and separate real durable rejected-order records; historical traces are never fabricated."})
    restart = read("lifecycles/v44-worker-restart.json")
    assert restart["actual_worker_sigkill"] and restart["partial_target_survived"] and len(restart["fills"]) == 5
    save("isolated-restart-recovery.json", {"engineering_status": "PASS", "evidence_class": "SYNTHETIC_DETERMINISTIC_ENGINEERING_TEST",
        "generations": ["verified-v42", "verified-v44", "native-v45"], "actual_worker_sigkill_and_restart": True,
        "compiled_browser_cases": compiled, "fills_per_closed_partial_target_lifecycle": 5, "reconciliation": [],
        "evidence": ["compiled-lifecycle-tests.xml", "lifecycles/v44-worker-restart.json", "legacy-frontend-lifecycle.json", "frozen-v44-frontend-lifecycle.json", "native-frontend-lifecycle.json"],
        "limits": "SIGKILL uses real isolated host worker processes; actual AMD64 image separately proves runner reconstruction and 12 complete financial lifecycles. No production worker interruption."})
    save("v45-runtime-identity.json", {"engineering_status": "PASS", "evidence_class": "LOCAL_AND_ACTUAL_AMD64_CONTAINER_SOURCE_VERIFICATION",
        "execution_fingerprint": execution_fingerprint(), "application_source_fingerprint": fingerprint,
        "boundary_manifest_sha256": sha(ROOT / "src/autotrader/shadow/v45-boundary.json"),
        "new_accounts_created_in_production": False, "manifest_rebinding": False, "runtime": "native-v45",
        "unknown_or_tampered_generation": "BLOCKED; actual scan/monitor refusal tested"})
    market = final["market_data_health"]
    save("market-data-429-analysis.json", {"evidence_class": "REAL_PRODUCTION_READ_ONLY_OBSERVATION", "captured_at": final["captured_at"],
        "market_health": market, "retained_request_429_fraction": market.get("request_429", 0) / market["requests"],
        "causal_assessment": "Rate limits are real. No attribution of the stored A2 rejections to 429s: their actual durable reason is the execution-cost gate. Retained successful strategy inputs omit pre-strategy failures; request counters are not opportunities.",
        "policy": "Existing one-request/second/family scheduler, provider Retry-After, completed-candle cache and protective-book priority retained. No rate-limit thresholds weakened.",
        "measurement_limit": "Lifetime counters and four explicitly dated retained windows, not a complete 24-hour all-request export or proof that every market was fresh."})
    research = {}
    for name in ("universe-target-research.json", "timeframe-research.json"):
        report = read(name)["report"]
        assert not report["passed_strategies"]
        research[name] = {tf: {s: {k: v["out_of_sample"].get(k) for k in ("net_profit", "trades", "max_drawdown", "sharpe_ratio", "rejections")}
                              for s, v in data["strategies"].items()} for tf, data in report["timeframes"].items()}
    save("strategy-profitability-verdict.json", {"evidence_class": "HISTORICAL_PROXY_RESEARCH", "status": "NO_STRATEGY_PASSED", "studies": research,
        "untouched_holdout": False, "production_parameters_changed": False, "promotions": [],
        "verdict": "No strategy has positive validated out-of-sample support. Preserve existing unvalidated status and cost/risk refusals. No forced trading, new allocations, prospective-return or completed-30-day claim.",
        "limits": ["Current surviving Coinbase EUR universe and incomplete observations; no historical Revolut L2.",
            "Chronological splits, purge/embargo, four walk-forwards and conservative multiple-comparison handling do not create untouched holdout data.",
            "Reported rejection frequencies are historical simulation events; actual per-symbol full qualified opportunity census and all market regimes are not verified.",
            "No target-hit probability model; conditional target rewards and ATR-cost screens are not probability-weighted expected returns."]})
    save("rollback-readiness.json", {"engineering_status": "PASS", "evidence_class": "ISOLATED_PRODUCTION_DERIVED_CLONE",
        "known_good_image_id": restore["rollback_image_id"], "database_count": 9, "candidate_and_old_image_reconciliation": "PASS",
        "schema_change": False, "financial_seals_unchanged": True, "newer_transactions_restored_over": False,
        "production_container_rollback": "NOT_EXECUTED; separate Stage B approval required",
        "limits": "Proof covers the retained V42/V44 production identities and current schema. A future separately created V45 account requires a new rollback compatibility assessment. Retain latest financial history, never blindly restore prior dumps.",
        "plan": "docs/V4_5_RC2_RELEASE.md"})
    for name in ("v42-runtime-parity.json", "v44-runtime-parity.json"):
        assert read(name)["engineering_status"] == "PASS"
    required = ("backend-tests.json", "frontend-tests.json", "amd64-container-tests.json", "eight-account-manifest-verification.json",
        "v42-runtime-parity.json", "v44-runtime-parity.json", "v45-runtime-identity.json", "native-entry-acceptance.json",
        "financial-integrity.json", "nine-database-backup-restore.json", "isolated-restart-recovery.json", "rollback-readiness.json",
        "execution-gateway-traces.json", "trade-gate-ui-tests.json")
    save("release-identity.json", {"evidence_class": "LOCAL_COMMITTED_SOURCE_RELEASE_METADATA", "branch": "feature/autotrader-v45-trade-gate-recovery",
        "parent_commit": "08e9590e207f7113d66d2f072fce75551a05df2e", "intended_immutable_tag": "v4.5.0-rc.2",
        "commit_authority": "Post-commit release-manifest.json and delivery.json record full SHA and archive hash; a commit cannot embed its own SHA.",
        "application_source_fingerprint": fingerprint, "v42_source_fingerprint": LEGACY_SOURCE, "v44_execution_fingerprint": V44_EXECUTION,
        "v44_package_fingerprint": V44_PACKAGE, "v45_execution_fingerprint": execution_fingerprint(),
        "frozen_manifests": {n: sha(ROOT / "src/autotrader/_frozen" / n) for n in ("v42-manifest.json", "v44-manifest.json")},
        "prepared_at": datetime.now(UTC).isoformat(), "environment": platform.platform(), "deployment_performed": False})
    save("deployment-readiness.json", {"evidence_class": "HASH_BOUND_ENGINEERING_ACCEPTANCE_WITH_DISCLOSED_LIMITS", "recommendation": "READY",
        "scope": "Engineering release candidate ready for exact-commit Stage B review; no deployment authorization or profitability approval.",
        "application_source_fingerprint": fingerprint, "engineering_evidence": {n: sha(OUT / n) for n in required},
        "production_deployment": "NOT_EXECUTED", "approval_required": "Explicit approval naming the final full commit and archive hash, followed by fresh quiesced nine-database backup/restore verification.",
        "known_limits": ["Missing historical stage traces and exact benchmark batch membership remain unverified.",
            "Historical instrument minimum/price precision and full regime/untouched-holdout coverage are unavailable.",
            "No strategy passed validation; account creation, capital changes and promotion are not authorized.",
            "Actual production rollout/rollback and its final coordinated financial cut remain Stage B work."],
        "rollout_and_rollback_plan": "docs/V4_5_RC2_RELEASE.md"})
    print("PASS: named evidence assembled from executed checks; ready for immutable packaging and explicit Stage B review")


if __name__ == "__main__":
    main()
