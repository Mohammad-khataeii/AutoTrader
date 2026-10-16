"""Offline, read-only diagnostic over exported structured evaluation JSON."""

import argparse
import json
from pathlib import Path

from autotrader.shadow.diagnostics import counterfactual

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    rows = data if isinstance(data, list) else data.get("items", [])
    print(
        json.dumps(
            counterfactual([r.get("explanation", r) for r in rows if r.get("explanation", r)]),
            indent=2,
        )
    )
