# V4.9.1-rc.2 correction and verification

The rc.1 deployment stopped at its mandatory final verification gate. The previous images recovered while every account was flat; entries remain PAUSED. Cash is €6,961.614219600281, with the original single €7,000 funding event, eighteen orders and sixteen fills. No database was restored over live history. The frozen primary profile is `4.9.1-paper.1`; its mismatch with the recovered older images correctly prevents new primary entries until a compatible release is approved. Position monitoring remains active.

## Failed attempt and financial preservation

Approved rc.1 commit `ed530bb87ad16f65c07eb7b19177b999a7bafe25` passed all 1,491 source-file hashes, 280 installed-module hashes, canonical image identities and both seventeen-account VPS backup/restore proofs. The first restore also rehearsed the primary profile upgrade without changing cash, funding, orders, fills or origin. All fifteen shadow manifests were preserved; no experiment was created or retired.

The final `/api/intelligence` request exceeded the 45-second verification timeout. The helper did not resume the primary or seven active comparisons. It recovered the previous images without restoring or rewinding a financial database, and recorded exit code 1 at 10:01:18 UTC on 29 October 2026. The failure marker and both complete backups remain retained. Existing PostgreSQL/Redis volumes and images, private Tailscale configuration, and rollback source/images are preserved. The old production server was not contacted.

A read-only comparison confirmed matching original financial-core hashes across all seventeen accounts. All seventeen original equity-history prefixes also match; appended valuation observations and refreshed market marks are the expected differences. Every account retains exactly one funding event and all actual orders remain simulated. Details and original rc.1 test provenance are retained in `docs/evidence/v4_9_1/rc1-deployment-failure.json` and `docs/evidence/v4_9_1/rc1/`.

## Cause and local correction

The opportunities endpoint loaded up to 10,000 **complete** historical event payloads to derive episode summaries. The retained live history had 7,719 events containing 202,582,252 payload bytes. Grouping needs seven small metadata fields, rather than the complete indicator, depth and trade-plan evidence. This load can delay the application event loop and exhaust its memory under concurrent requests. The observed VPS failure was a timeout; the concurrent-memory failure was reproduced locally, without stressing the live VPS.

`api/episode_history.py` now projects those fields inside PostgreSQL with `json_to_record`. The time filter and 10,000-row limit apply before expansion. The application receives compact rows, and the existing `episodes()` function remains unchanged. The same 48-hour window, ordering, optional holding-horizon values, grouping rules and truncation warning remain. The recent-event page still exposes full original evidence, with its existing bounded page size. No history is deleted or rewritten.

This correction changes API history loading and adds a mandatory resource gate. It changes no trading recipe, admission rule, numerical risk limit, cost model, exit, schema or control identity. The primary runtime fingerprint remains `bddd32eae4c72058c583cd55684622b86a12527067b7c6b8941613207c49535c`; the original shadow execution fingerprint remains `44264f01586fedbd62e949f142c8240bb2dd9bae86c454fb17d388e2f5d9559c`. The already-frozen primary profile is compatible with the corrected runtime. Frozen V4.2/V4.4 sources and the reviewed boundary remain verified.

## Resource and correctness proof

Fresh official and primary database exports from the successful post-cutover backup were checksum-verified and restored into a separate internal network with no host ports or external access. Both PostgreSQL and the application were capped at 512 MiB; the application was limited to one CPU. The same checked-in isolated probe was used for the old and corrected application images. It submits two concurrent history requests, checks readiness during the requests, and verifies unchanged cash, fill count and reconciliation afterward.

| Observation | Original full-history implementation | Corrected projection |
|---|---|---|
| One history request | 12.16 seconds in the initial local baseline | Two requests completed in 1.79 and 1.75 seconds |
| Two concurrent requests under 512 MiB | Container OOMKilled, exit 137 | Both HTTP 200; no OOM |
| Corrected peak process RSS | — | 160,395,264 bytes, about 153 MiB |
| Maximum readiness request during load | — | 0.0114 seconds |
| Episode coverage of restored data | 94 episodes / 7,677 signals | Same 94 episodes / 7,677 signals |
| Recent full-evidence page / radar rows | 30 / 15 | Same 30 / 15 |

The native PostgreSQL tests also compare the original complete-event episode outputs with projected outputs, preserve large opaque evidence unchanged, verify time filtering before the row limit, exclude unrelated non-JSON states, and cover legacy optional/string/numeric horizons and invalid windows. The SQL returns no whole-history JSON aggregate or full historical payload column to the application.

This is a local restored-data resource test: the application ran as Linux AMD64 under Docker Desktop emulation and PostgreSQL was ARM64. It does not establish live VPS latency, prospective market performance or profitability. The next deployment must repeat the real VPS feed, runtime, dashboard and reconciliation checks before entries resume. The original primary-report endpoint's earlier sub-second measurement concerned a different endpoint and was not the cause of this failure.

## Release verification and next activation

The corrected application contains 281 Python modules, source fingerprint `362e1c0f26720baa856e6c783418ac8e97e54a7eec7addf083a62ebd7133cdcf`. Package/API versions are `4.9.1.dev2` / `4.9.1-dev.2`; the primary trading profile remains `4.9.1-paper.1`. Application images are built directly from verified tar input to avoid directory-transfer metadata reuse, and every installed Python file must match the immutable manifest. The frontend bytes are unchanged and must match the browser-tested assets. Configuration and filesystem layer digests bind portable image identity to the full commit.

Fresh full-suite results: **451 native backend tests passed with zero failures/skips**, **446 installed Linux AMD64 tests passed with zero failures/skips** (five explicit host Docker cases passed natively), **19 frontend tests**, **24 native Chromium/Nginx browser cases**, TypeScript/Vite builds, Ruff and mypy on **133** modules. No merged recheck result is presented as a complete run. Ten source-bound gates, including the restored-history resource probe, are pinned by `staging-readiness.json`. The 17-account corrected-image financial rehearsal and installed API checks have passed, preserving all original accounts, funding, cash, fills and control manifests. The resource proof is a required source-bound release gate; raising live memory or extending the verification timeout does not bypass it.

The failed rc.1 is not retried. After local tests, commit, push and immutable packaging, `AGENTS.md` requires separate approval of the completed rc.2 commit. A subsequent approved deployment must take fresh seventeen-database backups, restore-verify them, preserve all original histories and control identities, and pass the bounded history endpoint, genuine market context, fresh protection, exact image/source, private HTTPS browser and financial reconciliation checks before resume. No forced paper trade, real-money execution, profitability or completed 30-day claim follows from these engineering checks.
