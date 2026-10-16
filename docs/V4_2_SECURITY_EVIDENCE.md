# V4.2 security evidence

Scan date2026-10-16. The dual-architecture table below belongs to the earlier source 072candidate. Final Stage A source 9f03was built/scanned locally and is recorded separately in [final ARM64 binding](evidence/v4_2-stage-a-image-binding.json), [SARIF](evidence/v4_2-stage-a-backend-arm64.sarif) and [runtime proof](evidence/v4_2-stage-a-docker-runtime.json). It reports zero high/critical findings. The final target-native AMD64 build is an approval-gated Stage B step; no remote build was performed after the workflow change. Exact earlier image IDs, archive/config/layer verification and SARIF hashes are in [image bindings](evidence/v4_2-security-image-bindings.json). Docker Scout1.25.0 scanned high/critical severities. AMD64 images were exported directly from the VPS; each exported configuration, creation timestamp and every root filesystem layer matches its server image. Containerd image/manifest IDs and Docker-save configuration digests can differ; both are recorded rather than conflated.

| Component | Architecture | Image ID | High/critical findings |
|---|---|---|---:|
| backend | arm64 | `sha256:c19134b4187a532e6d30e259960ef65171da909dcd7873ae92b7c02a41723048` | 0 |
| frontend | arm64 | `sha256:295795d02a35f5de02536d1bd5fc51087f88a81240ecfc86977be88fea65eb24` | 0 |
| postgres | arm64 | `sha256:8b628fc88dddf37b8db60d800efb780039c1fe1ed6eec6d390a1cbbc2cebda7f` | 0 |
| redis | arm64 | `sha256:f91927c704ccdfedd85306cb1f8efdd3f0c29fa67098faaa87bd1023e745af4b` | 0 |
| backend | amd64 | `sha256:281fe009d19d75eeb43bacc783e04a9a27559c4e1d4e23f5c8a857b1d3da23b4` | 0 |
| frontend | amd64 | `sha256:a396928be43edac7c647bdffefa16fa2e3564c2bcdde8f98942e29211c16e1d3` | 0 |
| postgres | amd64 | `sha256:b0535a9b0c0ede347417619578881b08d085d2a09c10d999301545a6514e97f2` | 0 |
| redis | amd64 | `sha256:3af709197c180653b51850eaf76e7397c01c4ef646c515268895ba7f0f033715` | 0 |

These results cover core backend/frontend/PostgreSQL/Redis images only. Existing PostgreSQL16 libxml2 backport and Redis patched images remain intact. No database/cache service upgrade or restart is required. Grafana remains quarantined and inactive:2distinct critical plus19distinct high CVEs,53occurrences in its previously recorded scan. Monitoring is excluded from the clean core-image claim.

Python dependency audit reports no known findings in the locked environment; npm audit reports zero vulnerabilities. See [pip audit](evidence/v4_2-pip-audit.json) and [npm audit](evidence/v4_2-npm-audit.json). No dependency lock was relaxed to hide a finding.

The source audit checks all tracked/unignored release files against configured local secret values and private-key block signatures, prints only counts/paths, and confirms the original SQLite artifact hash is unchanged. See [source audit](evidence/v4_2-source-security.json). Private environments, dumps, exported images and SSH material stay ignored. SSH authentication uses the configured alias; the SSH private key was never opened, displayed, copied or transmitted.

Existing Basic authentication protects official and new APIs. Unauthenticated shadow requests return401. DTOs forbid arbitrary account IDs/database URLs/force-trade inputs; unknown IDs and cross-domain transactions fail closed. Full history exports require the same authentication. Application/database/cache ports remain loopback/private; TLS termination and Nginx configuration are preserved. Production runtime uses UID10001, read-only root, cap-drop ALL, no-new-privileges and resource limits. Metadata is readable and unwritable under the final AMD64 runtime proof.

Real-money trading remains disabled in Compose and runtime. Market clients remain public read-only GET; shadow orders use the existing virtual execution gateway. AI_PROVIDER remains mock, quota totals remain zero, and shadow evaluation makes no AI requests. Production verification is separately recorded in V4_2_VPS_UPGRADE.md.

A missing host deployment-helper dependency stopped the first rollout before backup/migration. A private `.tools/deploy-venv` with httpx0.28.1 supplies the host helper, without changing system Python or unrelated apps. A subsequent fresh-backup gate is required before any production migration.

Final Stage A locked dependency audits also pass: evidence/v4_2-stage-a-pip-audit.json and v4_2-stage-a-npm-audit.json. Source authentication/risk behavior is covered by the final183-test native suite. The production image remains the earlier locally authored source 072candidate; no claim is made that final local tooling/source 9f03has been deployed.
