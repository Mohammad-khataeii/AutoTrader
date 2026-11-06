"""Replay stored rank and cost decisions without broker access."""

import argparse
import json
from collections import Counter
from pathlib import Path

from .intraday import decide
from .intraday_policy import phase_at
from .sessions import instant


def replay(path):
    groups = {}
    with path.open() as stream:
        for line in stream:
            record = json.loads(line)
            if record.get("dataset", "intraday_observations") != "intraday_observations":
                continue
            row = record.get("row", record)
            evidence = json.loads(row["evidence_json"])
            at = instant(row["at"])
            if (
                instant(evidence["observed_at"]) != at
                or evidence["symbol"] != row["symbol"]
                or phase_at(at).name != evidence["session"]
                or row["cycle_id"] != row["at"]
            ):
                raise ValueError("replay_observation_identity_mismatch")
            group = groups.setdefault(at, {})
            if row["symbol"] in group:
                raise ValueError("replay_duplicate_symbol_observation")
            group[row["symbol"]] = evidence
    results = Counter()
    for _, group in sorted(groups.items()):
        saved = {symbol: row.get("rank") for symbol, row in group.items()}
        new = [
            {
                k: v
                for k, v in row.items()
                if k not in {"rank", "candidate", "setup", "score", "risk_decision"}
            }
            for row in group.values()
        ]
        macro, candidates = decide(new)
        for row in new:
            if row.get("rank") != saved[row["symbol"]]:
                results["rank_mismatches"] += 1
        results["cycles"] += 1
        results["observations"] += len(group)
        results["entry_candidates"] += len(candidates)
        results["risk_off_cycles"] += macro == "RISK_OFF"
    return {
        **results,
        "rank_mismatches": results["rank_mismatches"],
        "evidence_kind": "SAVED_RANK_REPLAY",
        "broker_calls": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    result = replay(parser.parse_args().export)
    print(json.dumps(result, indent=2))
    if result["rank_mismatches"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
