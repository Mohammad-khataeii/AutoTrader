"""Offline signal parity against independent original Git packages and recorded inputs."""
from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from v45_analyze import decode_features, decode_signal

from autotrader.shadow.versions import convert, frozen_module, verify_legacy, verify_v44

BASELINE = "ab742ee56c4774fb9a7b111f1f1043575f1743c9"
CHILD = '''
import json,sys
from dataclasses import asdict,fields
from datetime import datetime
from decimal import Decimal
from autotrader.domain import MarketFeatures,DataQuality
from autotrader.research.strategies import StrategyParameters
from autotrader.research.experimental import ExperimentalStrategyEngine
def feature(raw):
    if raw is None:return None
    data=json.loads(raw)
    for f in fields(MarketFeatures):
        if f.name not in {'symbol','timestamp','timeframe','data_quality','metadata'}:
            data[f.name]=Decimal(data[f.name]) if data.get(f.name) is not None else None
    data['timestamp']=datetime.fromisoformat(data['timestamp'])
    data['data_quality']=DataQuality(data['data_quality'])
    return MarketFeatures(**data)
def default(v):
    return v.value if hasattr(v,'value') else v.isoformat() if hasattr(v,'isoformat') else str(v)
results=[]
for case in json.load(sys.stdin):
    engine=ExperimentalStrategyEngine(StrategyParameters(**{k:Decimal(v) for k,v in case['parameters'].items()}),{case['strategy']})
    signals=engine.generate(feature(case['features']),feature(case['btc']),feature(case['eth']))
    results.append([{k:v for k,v in asdict(s).items() if k!='signal_id'} for s in signals])
print(json.dumps(results,default=default))
'''


def default(value):
    return value.value if hasattr(value, "value") else value.isoformat() if hasattr(value, "isoformat") else str(value)


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "docs/evidence/v4_5_rc2"
    with gzip.open(root / "docs/evidence/v4_5/observations.jsonl.gz", "rt") as stream:
        records = [json.loads(line) for line in stream]
    for generation, package in (("v42", verify_legacy()), ("v44", verify_v44())):
        cases, expected, per_account = [], [], {}
        for record in records:
            if record.get("kind") != "account" or record["identity"] == "official":
                continue
            manifest, data = record["record"]["manifest"], record["data"]
            if bool(manifest.get("execution_fingerprint")) != (generation == "v44"):
                continue
            raw_features = {(f.symbol, f.timestamp): raw["payload_json"] for raw in data["features"]
                            for f in [decode_features(raw["payload_json"]) ]}
            signals = {s.signal_id: s for raw in data["signals"] for s in [decode_signal(raw["payload_json"]) ]}
            stats = {"recorded_evaluations_replayed": 0, "primary_eligibility_veto_regime_mismatches": [],
                     "nonprimary_benchmark_dependent_mismatches": []}
            module = lambda name, selected=generation: frozen_module(name, selected)
            engine = module("research.experimental").ExperimentalStrategyEngine(
                module("research.strategies").StrategyParameters(**{k: Decimal(v) for k, v in manifest["parameters"].items()}),
                {manifest["strategy_id"]})
            for raw in data["decisions"]:
                decision = json.loads(raw["payload_json"])
                selected = [signals[s] for s in decision["signal_ids"] if s in signals]
                if not selected:
                    continue
                stamp = selected[0].timestamp
                features = raw_features.get((decision["symbol"], stamp))
                if not features:
                    continue
                btc, eth = raw_features.get(("BTC-EUR", stamp)), raw_features.get(("ETH-EUR", stamp))
                replay = engine.generate(convert(decode_features(features), selected=generation),
                    convert(decode_features(btc), selected=generation) if btc else None,
                    convert(decode_features(eth), selected=generation) if eth else None)
                stable = [{k: v for k, v in asdict(s).items() if k != "signal_id"} for s in replay]
                expected.append(json.loads(json.dumps(stable, default=default)))
                cases.append({"strategy": manifest["strategy_id"], "parameters": manifest["parameters"],
                              "features": features, "btc": btc, "eth": eth})
                def eligibility(s):
                    return s.evidence["entry_eligible"], s.evidence["veto"], s.evidence["regime"]
                observed, actual = {s.strategy_id: eligibility(s) for s in selected}, {s.strategy_id: eligibility(s) for s in replay}
                if observed.get(manifest["strategy_id"]) != actual.get(manifest["strategy_id"]):
                    stats["primary_eligibility_veto_regime_mismatches"].append(decision["decision_id"])
                if observed != actual:
                    stats["nonprimary_benchmark_dependent_mismatches"].append(decision["decision_id"])
                stats["recorded_evaluations_replayed"] += 1
            per_account[record["identity"]] = stats
        with tempfile.TemporaryDirectory(prefix="autotrader-rc2-parity-") as directory:
            source = Path(directory) / "autotrader"
            for name in package:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                git_path = "src/autotrader/" + ("_frozen/v42/" if generation == "v42" else "") + name
                target.write_bytes(subprocess.check_output(["git", "show", ("08e9590e207f7113d66d2f072fce75551a05df2e" if generation == "v42" else BASELINE) + ":" + git_path], cwd=root))
            isolated = subprocess.run([sys.executable, "-c", CHILD], cwd=directory,
                env={**os.environ, "PYTHONPATH": directory, "PYTHONDONTWRITEBYTECODE": "1"},
                input=json.dumps(cases).encode(), capture_output=True, check=True)
            actual = json.loads(isolated.stdout)
        assert actual == expected and all(not s["primary_eligibility_veto_regime_mismatches"] for s in per_account.values())
        report = {"evidence_class": "REAL_PRODUCTION_READ_ONLY_RECORDED_INPUT_REPLAY", "engineering_status": "PASS",
            "generation": generation, "package_files": len(package), "independent_original_git_signal_comparisons": len(cases),
            "independent_original_git_full_signal_mismatches": 0, "accounts": per_account,
            "limits": ["Exact saved decimal features/context; does not reconstruct missing historical raw-candle scan batches.",
                "Historical benchmark batch membership was not retained. Nonprimary D2 differences remain unverified; no historical full decision/order replay claim.",
                "Stored execution books for rejected A2 orders are replayed separately in execution-cost-analysis.json.",
                "Synthetic raw-candle liveness and restart proofs are separate engineering evidence; no profitability claim."]}
        (output / (generation + "-runtime-parity.json")).write_text(json.dumps(report, indent=2) + "\n")
        print(generation, len(cases), "independent original signals match; primary recorded eligibility matches")


if __name__ == "__main__":
    main()
