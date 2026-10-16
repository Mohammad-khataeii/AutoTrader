# V4.2 executed test evidence

Earlier candidate source `072c258fa3820975e493643da00dca779ff43446869c6a5ce268dd054b07d704`; its178-test native/Ubuntu results below remain historical evidence. **Final Stage A source 9f03passes183 native tests,0 failed/skipped,488.42s**, plus the1-test real React lifecycle and2browser flows. See V4_2_LOCAL_VALIDATION.md and evidence/v4_2-stage-a-validation.json for final provenance. Original V4.1 baseline:148passed,0 failed/skipped,412.66s. Final local native regression:178passed,0 failed/errors/skipped,481.08s. Ubuntu/AMD64 container regression:178passed,0 failed/errors/skipped,875.119s. Real PostgreSQL underlies financial/migration/API/process cases. One native warning concerns a Starlette/AnyIO deprecated alias; no test was skipped because of it.

## Reproduction commands

```sh
python3 .tools/with_pg.py python3 -m pytest tests -q -s --junitxml=docs/evidence/v4_2-final-regression.xml
# In the isolated Ubuntu verification image, with private disposable-DB environment:
python -m pytest tests -q -s -o cache_dir=/tmp/pytest-cache --junitxml=/evidence/regression.xml
# Existing and new dashboard flows, against the independent V4.2 Compose project:
cd frontend
AUTOTRADER_BROWSER_URL=http://127.0.0.1:13042 AUTOTRADER_BROWSER_ENV=../.tools/v42-test.env AUTOTRADER_BROWSER_REPORT=../docs/evidence/v4_2-playwright.json AUTOTRADER_EVIDENCE_VERSION=v4_2 npx playwright test
```

The private `.tools/with_pg.py` launcher merely supplies the local PostgreSQL admin URL. Use an equivalent private AUTOTRADER_TEST_PG_ADMIN_URL in another checkout. Never publish its password. Tests create disposable prefixed databases, not production money. The Ubuntu harness used source read-only, resource limits, no published ports and a separate test image. The production image remains UID10001, metadata-readable/unwritable, read-only and cap-drop ALL.

Browser flows verify login, every existing page, genuine historical research job completion, backtesting, persistent official controls, pilot state/CSV, mock-AI quotas, logout, new shadow creation/selection/pause/resume, official isolation, financial JSON/full journal NDJSON downloads, failure filtering/detail and market health. Screenshots preserve V4.1 evidence under separate V4.2 filenames. Final browser pass counts/timing are in [JSON](evidence/v4_2-playwright.json).

## Additional executed integration

- Independent fresh Compose installation migrates before first funding; final populated migration/backup/restore and all financial invariants pass. A seed attempt refused a conflicting interrupted-run artifact; old versions were preserved and only completed immutable canonical runs were selected for the release seed. No immutable conflict was overwritten to force success.
- A real Docker V4.1 database clone migrated0010→0011, downgraded safely with empty shadow registry, then upgraded again. All15 financial-table seals match. Original database stayed unchanged: [proof](evidence/v4_2-docker-v41-migration-rollback.json).
- Actual API/worker SIGKILL, partial TP2 recovery, five shadow fills, official isolation, multi-domain risk/fault containment and full export are described in [financial evidence](V4_2_SHADOW_FINANCIAL_INTEGRITY.md).
- A new physical PostgreSQL cluster restored official plus two shadow domains, then executed only the restored domain's next exit: [proof](evidence/v4_2-full-cluster-restore.json).
- Exact original twelve simulations reproduce every archived trade/fill/equity field: [proof](evidence/v4_2-original-reproduction.json). Final experimental study matches the first completed negative study numerically; no strategy retuning followed the observed results: [proof](evidence/v4_2-study-reproduction.json).
-128 real feature-context windows match before/after EMA aggregation optimization: [proof](evidence/v4_2-context-equivalence.json). Controlled old/new request comparison and genuine public data smoke are separately labeled.
- Backend600-file/700-directory build reproduction and AMD64 UID10001 runtime proof passed. Core ARM64/AMD64 security scans, Python and npm audits are recorded separately.

## Failure/correction history

Intermediate attempts are retained rather than presented as final passes. Early experimental feature optimization exposed real issues that were corrected before the source freeze. The first completed research report mislabeled experimental ensembles as V4/V4.1; canonical final fields now identify them as experimental, with unchanged numerical results. A bid-target spread double charge inflated preliminary diagnostic counts; the corrected report records177 fixed-fill cost sign crossings and retains the superseded320-count artifact.

The first Ubuntu verification exercised tests but failed writing JUnit to a private host-owned mount. The corrected harness runs tests under the mount owner's UID and verifies write access before dispatch; final sanitized JUnit proves178pass. A Docker Scout concurrent cache lock caused two scanner invocations to fail; serial retries completed. These are recorded harness failures, not counted as passed production gates.

Future30-day prospective outcomes remain unavailable. Production deployment is established only by the actual release evidence in [V4_2_VPS_UPGRADE.md](V4_2_VPS_UPGRADE.md), not by local, Docker or Ubuntu test success alone.

## Final Stage A reproduction additions

```sh
python3 scripts/verify_original_research.py --root .data/research --run research-20261016T044934 --output .tools/original-reproduction.json
python3 scripts/public_market_smoke.py --output .tools/public-market-smoke.json
AUTOTRADER_BROWSER_ACCEPTANCE=1 python3 -m pytest tests/test_v42_lifecycle.py -q -s
```

Final native183 tests passed. The React lifecycle initially exposed a test-harness relative-URL error; its corrected absolute request URL passed. A repeat legacy browser flow initially assumed any old pilot remained active; the source guard had correctly interrupted it. The corrected test preserves that record, starts a newly frozen pilot and checks its observations/CSV. Final2browser flows passed57.7s. Full exact12 original replays and833-position diagnostics also completed under the final source. The final genuine smoke saw one real429and recovered to6 GOODobservations/10 successfulrequests without orders.
