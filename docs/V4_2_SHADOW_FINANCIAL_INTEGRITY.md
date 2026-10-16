# V4.2 shadow financial integrity

Earlier fully tested source `072c258fa3820975e493643da00dca779ff43446869c6a5ce268dd054b07d704`; final Stage A source `9f03f481049165cba9b54082d6f45f6e06e76d4b0a1625832b5f8434f8ace23a` additionally passes183local tests and the real React lifecycle acceptance. Separate PostgreSQL databases enforce financial isolation while reusing the existing journal, risk reservations, execution gateway, IOC pricing, partial fills, target identity and protective position manager. Each domain has one immutable identity and EUR 500 funding once. Official paper equity is never aggregated with shadow equity.

## Executed financial proofs

The final native suite passed 178 tests with zero failures/errors/skips. Its real API/worker process proof recorded API PID91039 and worker91038→91049 after SIGKILL. A2's actual causal indicators and strategy produced an entry; real DecisionEngine, allocation and repository admission created a BUY. TP1, partial TP2, restart, remaining TP2 and protective gap exit produced five persisted fills. Official cash/equity stayed EUR 500 with zero orders/fills; every domain reconciled. This uses deterministic market replay and is explicitly SYNTHETIC_ACCEPTANCE; no live exchange fill or historical edge is inferred. The complete Ubuntu/AMD64 suite independently passed the same 178 tests against disposable databases in the existing owned PostgreSQL container.

Repository integration also verifies duplicate execution idempotency, immutable account/manifest/source checks, official-gateway rejection, foreign position/reservation rejection, per-domain risk halts, concurrent funding/provisioning, leases, candle claims, source-change entry refusal with protection retained, restart recovery and migration transaction rollback. A failing experiment is contained while the next healthy experiment's protection still runs. An ordinary repository cannot initialize the official account inside a marked shadow database. Foreign-position rejection no longer attempts an invalid order foreign key.

Authenticated full NDJSON exports for journal, orders, fills and equity stream in 500-row batches. A real PostgreSQL API test exports more than 500 rows and checks every account identity. The dashboard's recent 500-record window is disclosed; full-history fee totals and maximum drawdown are computed independently.

## Full isolated-cluster recovery

[evidence/v4_2-full-cluster-restore.json](evidence/v4_2-full-cluster-restore.json) records complete custom-format dumps of one official and two shadow databases. All mode0600 archives were checksum-verified and restored into a newly created PostgreSQL cluster with the same logical domain names. Cluster identities differ:7697201974464630813 versus7697221222442692643.

The first source shadow had one real admitted A2 BUY and quantity0.57800995. Only its restored counterpart received the subsequent partial protective target: two fills and quantity0.40460697. The original shadow remained at one fill and quantity0.57800995. Official and second-shadow equity remained EUR 500 in both clusters; all journals reconciled. There was no funding replay or volume deletion. The temporary restored-cluster container was stopped and its volume retained.

A registry restored under a new name in the original cluster is explicitly blocked from following original shadow pointers. This is a recovery boundary, not an invitation to remap live domains automatically. The deploy helper restores read-only verification clones and never activates their workers.

Production prospective activation and domain IDs are recorded separately in [V4_2_VPS_UPGRADE.md](V4_2_VPS_UPGRADE.md). Synthetic process/restore acceptance establishes engineering behavior; it cannot substitute for future live-market observations or a completed 30-day experiment.

Evidence: [native JUnit](evidence/v4_2-final-regression.xml), [Ubuntu JUnit](evidence/v4_2-ubuntu-regression.xml), [browser results](evidence/v4_2-playwright.json), `tests/test_v42_lifecycle.py`, `tests/test_v42_shadow.py`, `tests/test_v42_api.py`.

## Final Stage A frontend-integrated lifecycle

The new-source local API/worker/React test passed in24.40s. Worker15676→15685 recovered partialTP2; all 5 persisted fills and one closed position were visible in the built React dashboard. Synthetic net P&LEUR 0.273417762120,feesEUR 0.149796346379; officialcash/equityEUR 500,noorders. This fixture result is explicitly SYNTHETIC_ACCEPTANCE and conveys no trading advantage. Evidence: evidence/v4_2-frontend-lifecycle.json, evidence/v4_2-frontend-lifecycle.xml and evidence/shadow-lifecycle-v4_2.png. No production experiments have been activated following the local-first approval gate.
