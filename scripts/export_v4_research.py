"""Export the completed full study matching current source; never invent results."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from autotrader.research.artifacts import source_fingerprint


def main() -> None:
    root = Path(".data/research")
    fingerprint = source_fingerprint()[0]
    candidates = []
    for path in root.glob("runs/*/summary.json"):
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("source_fingerprint") != fingerprint or set(report.get("timeframes", {})) != {"1d", "4h"}:
            continue
        if all(len(v["strategies"]) == 6 for v in report["timeframes"].values()):
            candidates.append((path, report))
    if not candidates:
        raise RuntimeError("No completed full study matches current source; finish research first")
    path, report = max(candidates, key=lambda pair: pair[0].parent.name)
    output = Path("docs/evidence")
    (output / "v4-research-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
    evidence = {k:v for k,v in manifest.items() if k != "datasets"}
    evidence["datasets"] = [{k:v for k,v in m.items() if k not in {"provenance", "gaps"}} for m in manifest["datasets"]]
    (output / "v4-research-manifest.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    lines = ["# V4 executed historical results", "", f"Run: `{report['run_id']}`. Source fingerprint: `{fingerprint}`.",
        f"Original complete artifacts: `{path.parent.as_posix()}`. Summary: `evidence/v4-research-results.json`.", "",
        f"**{report['verdict']}**. No candidate is approved. The validated ensemble stays in cash.",
        "All amounts below are observed historical simulation outcomes, not forecasts.", "",
        "| TF | Strategy | Net EUR | Closed positions | PF | Max DD | Passed |", "|---|---|---:|---:|---:|---:|---|"]
    trades, curves = [], []
    for timeframe, group in report["timeframes"].items():
        for strategy, result in group["strategies"].items():
            metric = result["out_of_sample"]
            pf = metric["profit_factor"]
            pf_text = f"{pf:.4f}" if pf is not None else "undefined"
            lines.append(f"| {timeframe} | {strategy} | {metric['net_profit']:.4f} | {metric['trades']} | {pf_text} | {metric['max_drawdown']:.4%} | {result['gates']['passed']} |")
            full = json.loads((path.parent / f"{timeframe}-{strategy}-test.json").read_text(encoding="utf-8"))
            trades.extend({"study":report["run_id"], "timeframe":timeframe, "strategy":strategy, **row} for row in full["fills"])
            drawdown = {row["timestamp"]:row["drawdown"] for row in full["drawdown_curve"]}
            curves.extend({"study":report["run_id"], "timeframe":timeframe, "strategy":strategy, **row,
                "drawdown":drawdown[row["timestamp"]]} for row in full["curve"])
    lines += ["", "## Frozen intervals", ""]
    for timeframe, group in report["timeframes"].items():
        frozen = group["frozen_parameters"]
        lines.append(f"- {timeframe}: validation {frozen['validation_start']} to {frozen['validation_end_exclusive']}; test {frozen['test_start']} to {frozen['test_end_exclusive']}. UTC, exclusive ends.")
    lines += ["", "## Benchmarks", "", "| TF | Reference | Net EUR | Return | Max DD |", "|---|---|---:|---:|---:|"]
    for timeframe, group in report["timeframes"].items():
        for name, metric in group["benchmarks"].items():
            lines.append(f"| {timeframe} | {name} | {metric['net_profit']:.4f} | {metric['total_return']:.4%} | {metric['max_drawdown']:.4%} |")
    lines += ["", "V3.4 denotes its signals on the common V4 historical execution/cost/risk model, not a replay of the original durable application over every historical bar. Passive EUR500 references have different exposure and estimated endpoint liquidation costs. Candidate residual positions are disclosed as marks.", "",
        "Full JSON retains frozen training choices, validation, four walk-forward windows, cost stress, sample uncertainty, regime/strategy contributions, closed positions and explicit failure reasons. No strategy is selected by test performance. No historical L2 is reconstructed.", "",
        f"CSV exports contain {len(trades)} simulated fills and {len(curves)} equity/drawdown rows across twelve separate strategy/timeframe simulations. They are not production account fills.", "",
        "Earlier diagnostic studies remain on disk. The suspicious-candle correction retains its open execution event and marks quality only after close; the legacy comparison uses the same known-data-quality gate. Reported historical test segments were reused during engineering; prospective never-seen validation is not claimed.", "",
        "## Comparison to V3.4", "",
        "Execution realism improves through bid-triggered protection, net target floors and finite shared depth. Costs are more explicit; reduced realized costs are not established. Eligibility and causal regimes replace score-only admission, but no validated signal/regime edge is established. Profiles/correlation add allocation controls without proving superior returns. Financial durability is separately verified. The deployment research gate keeps entries disabled."]
    Path("docs/V4_BACKTEST_RESULTS.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    for name, rows in (("v4-research-trades.csv", trades), ("v4-research-equity.csv", curves)):
        fields = list(dict.fromkeys(key for row in rows for key in row))
        with (output / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    print(report["run_id"], report["verdict"], len(trades), "simulated fills", len(curves), "curve rows")


if __name__ == "__main__":
    main()
