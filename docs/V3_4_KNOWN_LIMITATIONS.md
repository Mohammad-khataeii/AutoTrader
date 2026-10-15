# V3.4 remaining blockers and verified limits

Final status:PARTIALLY_COMPLETE_WITH_BLOCKERS. Core financial and autonomous runtime proofs pass; full-stack security clearance does not.

## Outstanding mandatory security work

- PostgreSQL image:libxml2 2.13.9-r2, CVE-2026-86140,1HIGH, scanner reports no fixed Alpine package. PostgreSQL16/data compatibility and XML feature behavior must be preserved when selecting a fixed build. The obsolete Go helper and zlib findings were removed; they are not still shipped by the final filesystem.
- Prometheus v3.15.0:2CRITICAL/9HIGH unique CVEs in bundled Go1.27.1, x/net0.58.0 and the Prometheus pseudo-version module. Rebuild with a patched toolchain/dependencies and validate the application advisory's actual source applicability, or use a verified patched upstream release. Do not suppress a pseudo-version finding without commit evidence.
- Grafana13.2.4:2CRITICAL/14HIGH unique CVEs in Go1.26.6/1.26.7/1.27.1, x/net0.58/0.59, x/crypto0.55, grpc1.83.0 and Tempo's pseudo-version. OS zlib is upgraded, but embedded Go dependencies require rebuilt binaries or verified upstream patches. Latest published tags were checked against official release APIs; simply repeating the same image pull is insufficient.

Exact CVEs, packages, binary paths and available fixed versions are retained in docs/evidence/stack-security.json and per-image SARIF. These are unresolved scanner findings; exploitability is not assumed and no silent exceptions are applied. Backend/frontend image all-severity scans and Redis high/critical scan are clear.

## Explicit product/research limits

- Projection corrections are authenticated, fingerprinted and audited; they restore proven history and cannot invent economic funding or legacy attribution. Ambiguous V3.3 rows remain quarantined pending trusted source evidence. No actual user history was rewritten.
- External deposits/withdrawals are disabled under the fixed EUR500 policy; baseline cash-flow adjustments are therefore not applicable. A projection repair leaves the existing halt until explicit risk recovery checks pass.
- Historical execution supports MARKET/LIMIT IOC, next-bar latency and conservative intrabar assumptions. Resting queue priority is not assumed.
- Paid OpenAI access and real invoiced-cost comparison are NOT_RUN without credentials; mock/off operation is explicitly supported and no purchase/request occurred.
- Authenticated article intake/untrusted prompt context is implemented; an autonomous external news feed is not configured. No Telegram message was sent; persistent incidents/dashboard states provide local alerts.
- No profitable edge is established. Public replay and both walk-forward windows lost money.
- Linux deployment is local Docker Desktop; no remote VPS was supplied. Target-specific TLS exposure is not deployed; defaults are internal/loopback.

The earlier launcher-only Windows restart evidence is invalid. Corrected actual-interpreter and Linux process proofs supersede it. See the executed test evidence and continuation checkpoint for exact next implementation actions.
