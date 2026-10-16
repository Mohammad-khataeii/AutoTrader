# V4.1 security disposition

Security clearance for the entire optional stack remains **BLOCKED** by quarantined Grafana. The selected core images now have zero high/critical findings in the recorded local scans. Scans requested high/critical findings; this is not a claim of zero findings at every severity or a remote penetration test. Counts below are distinct CVEs; one CVE can occur in several bundled packages.

| Component | Critical CVEs | High CVEs | Raw evidence |
|---|---:|---:|---|
| Backend | 0 | 0 | v4_1-backend-final.sarif |
| Frontend | 0 | 0 | v4_1-frontend-final.sarif |
| Redis | 0 | 0 | v4_1-redis-final.sarif |
| PostgreSQL selected backport | 0 | 0 | v4_1-postgres-final.sarif |
| Grafana quarantined | 2 | 19 | v4_1-grafana.sarif |

PostgreSQL stays major16 with its upstream entrypoint/data contract and SQL/XML capability. Updating current Alpine packages and replacing the outdated Go privilege helper with Alpine su-exec removed35 high/critical upstream result occurrences. The earlier selected library 2.13.9-r2 still had CVE-2026-86140 (CVSS8.0, xmlSnprintfElements stack buffer overflow), with no fixed package listed for this Alpine branch. Those failed scans are retained as superseded evidence, not hidden.

The fix is now backported from [GNOME commit d1686f91](https://github.com/GNOME/libxml2/commit/d1686f91dbda141a752200419d35639fd6b38340) into the exact Alpine 2.13.9 recipe, preserving both existing distro patches and the ABI. The [Debian advisory](https://security-tracker.debian.org/tracker/CVE-2026-86140) identifies that upstream fix; switching distributions alone would not clear its vulnerable stable packages. This repository builds a clearly identified **local 2.13.9-r3 package**, not an official Alpine release. Sources and patches have SHA512 checksums and pinned provenance. No library deletion, SQL/XML removal, CVE scan filter or scanner-only version relabeling was used.

The build executes upstream API checks (324,154 generated checks across 1,158 functions), 1,471 additional suite cases and the other upstream test programs. Missing optional external W3C/XSTC corpora are disclosed; three expected metadata errors are not reported as executed successful corpus tests. A new bounds test compiles the actual static function extracted from patched valid.c, checks every nonempty prefix for buffer sizes 64..256 with 32-byte canaries, and passes. Reversing only the upstream fix makes the same test abort with exit134. Build/provenance/bounds evidence is retained. The final runtime contains only the built package, not compiler/signing keys/build tools.

Candidate PostgreSQL 16.15 passes XMLPARSE/XPath/XMLSERIALIZE, hstore/pgcrypto/uuid-ossp loading, restoration of a real application backup into a separate database, populated-volume restart and empty financial reconciliation. The selected image is installed on the existing isolated Compose volume through a backup/restore-verified upgrade. Final health and runtime-image scan identify the actual selected image. The Dockerfile refuses to apply this package if the upgraded base library is no longer 2.13.9-r2; review/rebase rather than replacing newer vendor fixes. This local backport creates a maintenance obligation until an official fixed compatible package is available.

Grafana 13.2.4 was checked against the upstream registry and rebuilt/scanned. It contains 21 distinct CVEs (2 critical, 19 high), 53 affected-package result occurrences. It is absent from running core services and isolated under `quarantined-monitoring`. Do not enable that profile until affected bundled dependencies are rebuilt/replaced, rescanned and login/persistence/provisioning/query behavior is verified. Optional Prometheus is also stopped; earlier V4 evidence is historical, not a fresh V4.1 clearance.

| Grafana CVE | Severity | Affected package(s) |
|---|---|---|
| CVE-2026-100351 | HIGH | pkg:golang/github.com/getkin/kin-openapi@0.144.0 |
| CVE-2026-100352 | HIGH | pkg:golang/github.com/getkin/kin-openapi@0.144.0 |
| CVE-2026-100353 | HIGH | pkg:golang/github.com/getkin/kin-openapi@0.144.0 |
| CVE-2026-100354 | HIGH | pkg:golang/github.com/getkin/kin-openapi@0.144.0 |
| CVE-2026-21728 | HIGH | pkg:golang/github.com/grafana/tempo@1.5.1-0.20260910130453-bcfe9f230c1d |
| CVE-2026-28377 | HIGH | pkg:golang/github.com/grafana/tempo@1.5.1-0.20260910130453-bcfe9f230c1d |
| CVE-2026-56855 | HIGH | pkg:golang/golang.org/x/crypto@0.55.0 |
| CVE-2026-56866 | HIGH | pkg:golang/stdlib@1.26.6; pkg:golang/stdlib@1.26.7; pkg:golang/stdlib@1.27.1 |
| CVE-2026-78659 | HIGH | pkg:golang/golang.org/x/net@0.58.0; pkg:golang/golang.org/x/net@0.59.0; pkg:golang/stdlib@1.26.6; pkg:golang/stdlib@1.26.7; pkg:golang/stdlib@1.27.1 |
| CVE-2026-78660 | HIGH | pkg:golang/golang.org/x/net@0.58.0; pkg:golang/golang.org/x/net@0.59.0; pkg:golang/stdlib@1.26.6; pkg:golang/stdlib@1.26.7; pkg:golang/stdlib@1.27.1 |
| CVE-2026-78662 | HIGH | pkg:golang/golang.org/x/crypto@0.55.0 |
| CVE-2026-78667 | HIGH | pkg:golang/stdlib@1.26.6; pkg:golang/stdlib@1.26.7; pkg:golang/stdlib@1.27.1 |
| CVE-2026-78669 | HIGH | pkg:golang/golang.org/x/net@0.58.0; pkg:golang/golang.org/x/net@0.59.0; pkg:golang/stdlib@1.26.6; pkg:golang/stdlib@1.26.7; pkg:golang/stdlib@1.27.1 |
| CVE-2026-94439 | HIGH | pkg:golang/stdlib@1.26.6; pkg:golang/stdlib@1.26.7; pkg:golang/stdlib@1.27.1 |
| CVE-2026-94440 | HIGH | pkg:golang/stdlib@1.26.6; pkg:golang/stdlib@1.26.7; pkg:golang/stdlib@1.27.1 |
| CVE-2026-97031 | HIGH | pkg:golang/stdlib@1.26.6; pkg:golang/stdlib@1.26.7; pkg:golang/stdlib@1.27.1 |
| CVE-2026-97032 | HIGH | pkg:golang/golang.org/x/net@0.58.0; pkg:golang/golang.org/x/net@0.59.0; pkg:golang/stdlib@1.26.6; pkg:golang/stdlib@1.26.7; pkg:golang/stdlib@1.27.1 |
| CVE-2026-84304 | HIGH | pkg:golang/google.golang.org/grpc@1.83.0 |
| CVE-2026-84445 | HIGH | pkg:golang/google.golang.org/grpc@1.83.0 |
| CVE-2026-78663 | CRITICAL | pkg:golang/golang.org/x/net@0.58.0; pkg:golang/golang.org/x/net@0.59.0; pkg:golang/stdlib@1.26.6; pkg:golang/stdlib@1.26.7; pkg:golang/stdlib@1.27.1 |
| CVE-2026-56857 | CRITICAL | pkg:golang/stdlib@1.26.6; pkg:golang/stdlib@1.26.7; pkg:golang/stdlib@1.27.1 |

The initial stalled Grafana scan was terminated after the interrupted host session. A short diagnostic filtered probe was stopped; the retained final `v4_1-grafana.sarif` comes from the subsequent complete high/critical scan without a CVE filter. Its 21 rules and 53 results are authoritative.

Dependency audits: `v4_1-pip-audit.json` reports no known findings for the locked Python dependencies; `v4_1-npm-audit.json` reports zero dependency findings. Rebuilt backend/frontend/Redis images have no high/critical findings in the recorded scans. Existing patched dependency constraints and image hardening are retained.

Source/security verification checks tracked and new non-ignored text files for configured deployment secrets and key patterns; no findings. The Revolut market-data client exposes only GET/close HTTP calls. Anonymous overview/control/metrics requests are rejected, authenticated controls work, and throttling is durable across API instances. Only UI/API loopback ports are published; PostgreSQL and Redis have no host ports. Credentials, dumps and generated environment files remain ignored/private. The original tracked SQLite database is unchanged. Test flags cannot select the ordinary production PostgreSQL database. No ordinary application path submits real exchange orders.

Evidence: raw SARIF, `v4_1-source-security.json`, `v4_1-playwright.json`, final regression JUnit, backup/restore and deployment records. Stronger remote TLS/firewall/SSH, external exposure and host hardening need verification on the user's actual VPS. No real paid AI request or live exchange order was made.

Next security action: rebuild/replace the affected Grafana bundled Go/plugin dependencies with verified fixed versions, then rescan exact selected images and exercise login, persistence, provisioning and Prometheus queries before enabling monitoring. Track official libxml2 updates and retire the local backport only after equivalent compatibility/security checks.

`v4_1-core-scan.json` binds final scans to actual running image IDs. One concurrent index attempt failed; successful sequential scans followed. A retained Redis container was refreshed from its scanned rebuilt image with its persistent volume preserved. Final installed-Linux regression on the selected backported PostgreSQL image passes all 148 tests.
