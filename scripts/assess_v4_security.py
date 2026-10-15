"""Preserve raw scanner findings and attach explicit, scoped applicability decisions."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote


def main() -> None:
    root = Path("docs/evidence")
    images = {"backend":"autotrader-v34-acceptance-backend", "frontend":"autotrader-v34-acceptance-frontend",
        "postgres":"autotrader-v34-postgres:16-alpine", "redis":"autotrader-v34-redis:7-alpine",
        "prometheus":"prom/prometheus:v3.15.0", "grafana":"autotrader-v34-grafana:13.2.4"}
    patched = subprocess.run(["docker","image","inspect","autotrader-v4-prometheus:3.15.0-patched"], check=False, capture_output=True)
    if patched.returncode == 0 and (root / "v4-prometheus-patched-cves.sarif").exists():
        images["prometheus_patched"] = "autotrader-v4-prometheus:3.15.0-patched"
    rows = {}
    for service, image in images.items():
        name = "v4-prometheus-patched-cves.sarif" if service == "prometheus_patched" else f"v4-{service}-container-cves.sarif"
        report = json.loads((root / name).read_text(encoding="utf-8"))
        identity = json.loads(subprocess.check_output(["docker","image","inspect",image]))[0]
        findings = []
        for run in report["runs"]:
            for finding in run.get("results", []):
                message = finding["message"]["text"]
                fields = {}
                for field in ("Severity", "Package", "Fixed version"):
                    match = re.search(r"^" + field + r"\s*:\s*(.+)$", message, re.MULTILINE)
                    fields[field] = match.group(1).strip() if match else "UNKNOWN"
                cve = finding["ruleId"]
                status = "UNRESOLVED_POTENTIALLY_APPLICABLE"
                reason = "Package/version match retained; symbol-level reachability is not established. Upgrade/rebuild and rescan before enabling optional monitoring."
                evidence = []
                if cve == "CVE-2026-56857" and identity["Os"] == "linux":
                    status = "NOT_APPLICABLE_PLATFORM"
                    reason = "The upstream advisory concerns Windows junction operations. These are Linux images/binaries. Raw finding is retained."
                    evidence = ["https://pkg.go.dev/vuln/GO-2026-6604"]
                elif service == "prometheus" and cve == "CVE-2026-42154":
                    status = "NOT_APPLICABLE_VERSION"
                    reason = "The verified binary is Prometheus3.15.0. The upstream advisory's affected ranges end before3.11.3; the Go pseudo-version is misleading. Raw finding is retained."
                    evidence = ["https://github.com/prometheus/prometheus/security/advisories/GHSA-8rm2-7qqf-34qm"]
                elif service == "grafana" and cve in {"CVE-2026-21728", "CVE-2026-28377"}:
                    status = "NOT_REACHABLE_CURRENT_CONFIGURATION"
                    reason = "These advisories concern Tempo server query/config endpoints. Compose does not deploy a Tempo server or configure its datasource. The client dependency remains present; reevaluate before enabling Tempo. Monitoring is stopped."
                    evidence = [f"https://grafana.com/security/security-advisories/{cve.lower()}/"]
                elif service == "postgres":
                    reason = "Affected libxml2 remains linked to PostgreSQL16. The app does not call SQL/XML; the database port is internal. No fixed package was supplied by the selected Alpine branch after a fresh rebuild. Do not substitute an unverified ABI-incompatible library or change database major version."
                    evidence = ["https://nvd.nist.gov/vuln/detail/CVE-2026-86140"]
                paths = [loc.get("physicalLocation", {}).get("artifactLocation", {}).get("uri", "") for loc in finding.get("locations", [])]
                findings.append({"cve":cve, "severity":fields["Severity"], "package":unquote(fields["Package"]),
                    "scanner_fixed_version":fields["Fixed version"], "affected_binary_or_library":paths,
                    "disposition":status, "reason":reason, "primary_evidence":evidence})
        rows[service] = {"image":image, "image_id":identity["Id"], "platform":identity["Os"]+"/"+identity["Architecture"],
            "selected_in_compose":service != "prometheus",
            "report":name, "scope":"all severities" if service in {"backend","frontend"} else "high/critical",
            "raw_unique_critical":len({f["cve"] for f in findings if f["severity"] == "CRITICAL"}),
            "raw_unique_high":len({f["cve"] for f in findings if f["severity"] == "HIGH"}),
            "unresolved_cves":sorted({f["cve"] for f in findings if f["disposition"].startswith("UNRESOLVED")}),
            "findings":findings}
    result = {"checked_at":datetime.now(UTC).isoformat(), "status":"BLOCKED" if any(r["unresolved_cves"] for r in rows.values() if r["selected_in_compose"]) else "ASSESSED",
        "policy":"No scanner findings are deleted or silently suppressed. Configuration exclusions are not patched versions. Monitoring remains disabled until unresolved findings are remediated.",
        "services":rows}
    (root / "v4-security-assessment.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["# V4 security remediation and dispositions", "", "Raw reports and exact image identities: `evidence/v4-security-assessment.json`.",
        "Fresh support builds used `--pull --no-cache`; original PostgreSQL16 volumes were retained. Application images were rebuilt and rescanned. These are package scans, not a penetration test.", "",
        "Authentication now limits failed guesses per client/process; missing and wrong credentials receive401, then429 with Retry-After. Cooldown is enforced before secret comparison, including otherwise-valid credentials from that client. Source review verifies GET-only exchange access, authenticated API/metrics and loopback-only published ports. No WebSocket was introduced.", "",
        "| Service | Selected image | Raw critical | Raw high | Unresolved unique CVEs |", "|---|---|---:|---:|---:|"]
    for service, row in rows.items():
        lines.append(f"| {service} | {row['selected_in_compose']} | {row['raw_unique_critical']} | {row['raw_unique_high']} | {len(row['unresolved_cves'])} |")
    lines += ["", "## Per-package and binary assessment", "", "| Service / CVE | Exact package/version | Binary/library | Scanner fixed version | Disposition |", "|---|---|---|---|---|"]
    for service, row in rows.items():
        for f in row["findings"]:
            lines.append(f"| {service} / {f['cve']} | {f['package']} | {'; '.join(f['affected_binary_or_library'])} | {f['scanner_fixed_version']} | {f['disposition']} |")
    lines += ["", "## Meaning and remaining work", "",
        "Prometheus3.15.0 is outside the affected ranges for [CVE-2026-42154](https://github.com/prometheus/prometheus/security/advisories/GHSA-8rm2-7qqf-34qm). The raw pseudo-version finding remains available. [CVE-2026-56857](https://pkg.go.dev/vuln/GO-2026-6604) concerns Windows junctions and does not apply to these Linux binaries. These exclusions do not clear the other Go findings.", "",
        "The [HTTP/2 advisory](https://pkg.go.dev/vuln/GO-2026-6612) supports upgrading Go to1.27.2 /1.26.9 and x/net to0.60.0. The custom Prometheus build pins the upstream commit, checksum-verified official UI, patched compiler and x/net. Its high/critical scan is clear and actual Compose configuration, embedded UI asset, API query and authenticated backend scrape passed (`v4-prometheus-functional.json`). Compose selects this rebuilt image. The superseded official-image findings remain in the table and raw report for audit; they are not active-image findings.", "",
        "Grafana's remaining bundled Go plugins require patched, functionally verified builds or upstream packages. No claim of whole-stack clearance is made. PostgreSQL's selected Alpine libxml2 package remains unresolved; application SQL/XML is unused and DB access is internal, but this is containment rather than a fix. Preserve PostgreSQL16 data compatibility when remediating.", "",
        "The optional monitoring profile remains disabled while unresolved findings remain. No risk acceptance on the user's behalf or automatic public exposure is implied."]
    Path("docs/V4_SECURITY_REMEDIATION.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({k:{key:r[key] for key in ("raw_unique_critical","raw_unique_high","unresolved_cves")} for k,r in rows.items()}, indent=2))


if __name__ == "__main__":
    main()
