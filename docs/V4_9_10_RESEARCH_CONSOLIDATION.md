# Personal Plan research consolidation · 4.9.10-rc.1

The November 5 audit reports one winner among 15 personal positions, roughly
€99.33 in realized losses, and no filled profit target quantities. The €20.84 in
simulated fill fees is already in net P&L. Several positions risked about €697
with initial stops as close as 0.28%. These findings prompted a position trace
that joins actual fills, fees, stops, target quantities, transition reasons,
and journal postings. The audit omits the full paths and execution payloads
needed to assign causes. The sanitized design inputs are in
[diagnostic-input.json](evidence/v4_9_10/diagnostic-input.json).

A3's 68 frozen-source refusals are authority failures. The entry repository
compares the pinned execution fingerprint before checking strategy and cost
terms. A compatible read or monitoring runner does not by itself grant a
native entry permission. The inventory shows both runtime compatibility and
native fingerprint match where applicable. It preserves those refusals
separately from cooldowns and planned-loss limits. Only explicit boolean
`false` values in recorded gate maps are counted as failed gates. Other
reason tokens remain annotations.

## Data and evaluation

The existing research Store runs an additive SQLite migration in a separate
`reports/consolidation` directory. PostgreSQL keeps its existing schema.
The collector uses a dedicated role and database-enforced read-only
transactions. It accepts the configured operational root and its registered
personal and shadow identities after checking the corresponding origin
manifests. No sampled export is accepted as training input. The original
gzip export was absent from its supplied path during implementation.

| Research record | Contents |
| --- | --- |
| `research_sources` | Registry role, identity, manifest hash, state and collection time |
| `research_content`, `research_refs`, `research_versions` | Canonical content, source record IDs, time and financial links, and append-only content versions |
| `research_cursors`, `research_errors` | Transactional keyset checkpoints and quarantined source record identifiers |
| `research_tasks`, `research_postmortems` | Frozen input references, horizon, assessment provenance and revised reviews as distinct records |
| `research_holdouts`, Store artifacts | Consumed windows and content-addressed candidate models and evaluation reports |
| `research_forecasts`, `research_forecast_reviews` | Original paper advisory assumptions, model hash and later evidence |

Candle data is stored once per canonical content hash, with source row IDs
preserved in references. Standalone candle rows without ingestion clocks can
supply later price paths. Prediction features come from the source signal's
recorded causal snapshot and require a completed cutoff, consistent saved
context and an eligible timestamp. Conflicting candles or signal revisions
exclude the affected observation. Incremental checkpoints commit with their
data. Explicit sweeps revisit old mutable rows and late historical inserts.
A scheduled collection is a bounded page through the corpus.

BUY, WAIT and signal reviews default to 15 minutes, one hour, four hours and
24 hours. The modeled path excludes partial entry/exit bars, caps the modeled
holding window at the recorded limit, models bid-side spread and stop gaps,
and requires a complete path and known pricing assumptions. Same-bar stop
and target ambiguity resolves to the stop. Recorded net targets are
converted to cost-adjusted bid triggers. Fees are applied once. Order minima
and depth refusals remain in the evidence. The review distinguishes a modeled
miss from a reconciled fill and keeps unpriced or unobservable events
inconclusive. The saved book provides a conditional entry quote. It supplies
no later depth or proof of counterfactual execution. Actual fill and journal
reconciliation is reported separately from modeled training labels.

The regularized classifier and calibrator reuse existing model code. Training
groups shared symbol and cutoff episodes across accounts, purges overlapping
outcomes with a one-day embargo, runs two chronological validation folds, and
compares one-position-at-a-time modeled policies with deterministic selection
and a no-trade baseline. A final holdout is recorded as consumed before
evaluation. The operator must establish that the holdout is also untouched
outside this store. Reports include cost stress, calibration, drawdown,
tail risk, normalized turnover and segmented results. Smaller samples produce
`INSUFFICIENT_EVIDENCE`. Advisory scoring requires the exact validated hash,
explicit operator authorization, fresh quote evidence and the opt-in flags.
Feature drift, stale validation, or adverse recent reviewed forecasts cause
abstention. The scorer provides no order, allocation or exit authority.

## Commands for the validation session

Run these from a clean checkout of the pushed commit with its Python and
frontend dependencies installed. These are commands for later use.

```sh
python -m pytest tests/test_v4910_consolidation.py tests/test_staging_backup.py tests/test_v491_restore_startup.py tests/test_v499_evidence.py tests/test_v498_multi_perpetuals.py tests/test_v492_learning.py tests/test_v42_shadow.py tests/test_v493_regimes.py
npm --prefix frontend test
npm --prefix frontend run build
```

Set `AUTOTRADER_RESEARCH_SOURCE_URL` through private configuration to the
dedicated read-only PostgreSQL role. Prefer a verified restored cluster that
retains the original database names and registry identities. Give the role
SELECT only on the allowlisted research and financial audit tables. Confirm
it cannot write. Keep the SQLite root outside the repository, on a filesystem
with enough space and restrictive permissions.

```sh
export RESEARCH_STORE=/path/to/private/consolidation
autotrader-consolidation --store "$RESEARCH_STORE" migrate
autotrader-consolidation --store "$RESEARCH_STORE" inventory --cap 3
autotrader-consolidation --store "$RESEARCH_STORE" backfill --batch 1000
autotrader-consolidation --store "$RESEARCH_STORE" backfill --batch 1000 --sweep all
autotrader-consolidation --store "$RESEARCH_STORE" review --limit 500
autotrader-consolidation --store "$RESEARCH_STORE" status
autotrader-consolidation --store "$RESEARCH_STORE" audit-personal --output /path/to/private/personal-audit.json
autotrader-consolidation --store "$RESEARCH_STORE" trace "$SOURCE_DATABASE" decision "$DECISION_ID"
autotrader-consolidation --store "$RESEARCH_STORE" trace "$SOURCE_DATABASE" position "$POSITION_ID"
```

Repeat backfill until every required source and table reports exhausted
pages. A full sweep resets each sweep cursor after exhaustion. Collect all
sources before interpreting missing joins. Use `review --retry-missing-paths`
after recovering missing candles. Repeat review until the due queue drains.
Live tasks with incomplete coverage retry on a bounded schedule. Raw trace
and audit outputs contain private records.

Set `HOLDOUT_START` and `HOLDOUT_END` to the independently reserved UTC
interval. Perform offline training only after confirming its boundaries and
data coverage. Authorize scoring only after reviewing a validated candidate.

```sh
autotrader-consolidation --store "$RESEARCH_STORE" train --horizon 240 --holdout-start "$HOLDOUT_START" --holdout-end "$HOLDOUT_END" --attest-untouched
autotrader-consolidation --store "$RESEARCH_STORE" authorize-scorer "$VALIDATED_MODEL_SHA" --confirm "$VALIDATED_MODEL_SHA"
autotrader-consolidation --store "$RESEARCH_STORE" disable-scorer
```

For the optional dedicated research worker, its default store is
`/app/reports/consolidation`. Configure `PERSONAL_PLAN_CONSOLIDATION_ENABLED=true`
with the read-only URL. `PERSONAL_PLAN_RESEARCH_SCORING=true` additionally
enables advisory scoring after authorization in that same store. Both flags
default to false. Existing legacy research and the trading worker use their
own code paths.

## Shadow consolidation and recovery

API creation and resume serialize against the configurable active cap,
which defaults to three and counts provisioning slots. Existing excess
experiments remain in their recorded states until operators decide their
disposition. Paused and archived experiments retain recovery obligations.
Operational and personal accounts are outside this cap. The diagnostic trio
in the audit covers early recovery, execution and authority problems in A3,
and trend pullback protection. The inventory ranks distinct strategies by
observations and diagnostic value. Use explicit keep IDs to change the plan.

```sh
autotrader-consolidation --store "$RESEARCH_STORE" archive-plan --cap 3
autotrader-consolidation --store "$RESEARCH_STORE" archive-plan --cap 3 --keep "$EARLY_ID" --keep "$A3_ID" --keep "$PULLBACK_ID"
python deploy/capacity.py verify-backup "$EXTERNAL_BACKUP_MANIFEST" "$EXTERNAL_RESTORE_PROOF"
autotrader-consolidation --store "$RESEARCH_STORE" prepare-archive "$EXPERIMENT_ID" --confirm "$EXPERIMENT_ID" --backup "$EXTERNAL_BACKUP_MANIFEST" --restore-proof "$EXTERNAL_RESTORE_PROOF" --output "$EXTERNAL_RESEARCH_ARCHIVE"
autotrader-consolidation --store "$RECOVERED_RESEARCH_STORE" rehydrate "$EXTERNAL_RESEARCH_ARCHIVE" --sha256 "$ARCHIVE_SHA"
```

Prepare the copy after an approved operational pause, with zero positions,
orders, reservations, and exit intents, and a quiescent coordinator.
The command verifies external dump bytes, the hash-bound isolated restore
proof, source row coverage and fresh matching financial seals under the
registry lock. Its receipt marks the experiment eligible for manual retirement
review. It writes external research files and does not transition the live
registry. The existing separate explicit archive workflow retains financial
data. Confirm current seals and exposure again before any later registry
operation. A restored research store provides audit records. A full verified
PostgreSQL dump is required to recover financial execution.

Keep local and independently stored restore-tested backups for operational,
personal and active financial accounts. Keep immutable full dumps, matching
source and image identities, proofs and access to periodic isolated restore
drills for retired research. Verify byte copies and recovery before reviewing
redundant storage. A research archive cannot replace a financial dump.

## Capacity, packaging and deployment prerequisites

Before pausing entries or transferring images, run capacity planning with
measured unpacked image and transfer sizes. A zero budget means those bytes
are already on disk. The forecast combines reservations per filesystem and
credits no assumed compression or reclaimable Docker storage. Insufficient
space blocks the operation before dump creation. Actual restore still checks
clone space and verifies every retained financial seal.

```sh
python deploy/staging_backup.py --capacity-only --image-bytes "$UNPACKED_IMAGE_BYTES" --transfer-bytes "$TRANSFER_BYTES" > capacity.json
autotrader-consolidation --store "$RESEARCH_STORE" record-capacity capacity.json
python deploy/capacity.py retention "$STAGING_BACKUP_ROOT" --external "$EXTERNAL_BACKUP_MANIFEST" "$EXTERNAL_RESTORE_PROOF"
python deploy/capacity.py artifacts artifact-inventory.json --staging-root /opt/personal-plan/staging
```

The artifact inventory contains `references_complete`, `referenced_image_ids`,
`images` with canonical IDs, sizes and recovery verification, and `transfers`
with paths under staging incoming, reference flags and external copies.
Include all running and stopped container references, rollback and release
images. Output is a dry run. Keep the most recent local verified recovery set.

After local validation and a separate release approval, prepare and verify the
immutable source package. Build and bind both Linux/AMD64 images to that SHA
using the repository's release workflow. This candidate has no activation
authorization and older version-specific operators cannot authorize it.

```sh
RELEASE_SHA=$(git rev-parse HEAD)
python deploy/release.py prepare --ref "$RELEASE_SHA" --output "$RELEASE_ARCHIVE"
python deploy/release.py verify --root "$EXTRACTED_RELEASE" --manifest "$EXTRACTED_RELEASE/release-manifest.json" --commit "$RELEASE_SHA"
docker buildx build --platform linux/amd64 --load --build-arg RELEASE_COMMIT="$RELEASE_SHA" -t "personal-plan-candidate-app:$RELEASE_SHA" -f "$EXTRACTED_RELEASE/Dockerfile.backend" "$EXTRACTED_RELEASE"
docker buildx build --platform linux/amd64 --load --build-arg RELEASE_COMMIT="$RELEASE_SHA" -t "personal-plan-candidate-frontend:$RELEASE_SHA" "$EXTRACTED_RELEASE/frontend"
```

On the approved staging host, the backup command uses the existing scoped
Compose wrapper. If clone capacity is insufficient, plan the backup-only
allocation and use a separately resourced Docker host to restore the copied
set. The portable restore accepts the manifest SHA and image configuration ID
bound to its release. It writes evidence outside the backup set.

```sh
python deploy/staging_backup.py --restore-test --candidate-image "$BACKEND_IMAGE_ID"
python deploy/staging_backup.py --capacity-only --plan-offhost-restore --image-bytes "$UNPACKED_IMAGE_BYTES" --transfer-bytes "$TRANSFER_BYTES"
python deploy/staging_backup.py --candidate-image "$BACKEND_IMAGE_ID"
python deploy/staging_backup.py --restore-from "$COPIED_BACKUP_MANIFEST" --manifest-sha256 "$BACKUP_MANIFEST_SHA" --candidate-image "$BACKEND_IMAGE_ID" --restore-evidence "$NEW_EVIDENCE_DIR"
```

Require all existing ledger identities and reconciliations, flat exposure for
profile cutover, exact image binding, protection and funding verification,
loopback health, and a reviewed rollback route before activation. Follow
`AGENTS.md` and the separately approved staging procedure for the actual
cutover. Preserve the pre-change control inventory. On a failed pre-cutover
check, inspect the running image and monitoring state, leave protection
running, and reconcile before an operator decides whether to restore the
previous control settings. Never restore an older dump over newer financial
postings. The additive research store can be retained offline during image
rollback. Existing financial schemas, V1 perpetual identities and strategy
profiles are untouched by this release's research changes.

**Implementation only.** Tests, builds, database migrations, training,
restore drills, deployment, and VPS access were not performed. Full source
coverage, historical execution feasibility and prospective ML edge remain
unverified. **NO AUTOMATIC MODEL PROMOTION.**
