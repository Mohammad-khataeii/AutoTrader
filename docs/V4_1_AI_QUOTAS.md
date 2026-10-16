# V4.1 durable paid AI quotas

The existing budget ledger was extended, not replaced. Alembic revision
`0010_v41_ai_quotas` adds request event/category identity, a UTC quota timestamp,
estimated/reserved token bounds, provider response ID, separately reported provider
cost and cache status. Existing billing holds and financial history remain intact.
Legacy `UNKNOWN` states become `OUTCOME_UNKNOWN`.

Defaults: mock provider, no key/model required, 30/day (UTC midnight), 6 per rolling
60 minutes, USD10/calendar month, 12-second timeout and mandatory persistent quota.
Configuration can reduce quotas, not exceed these maxima. Production paid mode also
requires nonnegative explicit token prices and a UTC pricing-verification timestamp
no older than 31 days. Model access is checked by read-only retrieval before each
billable request; no model entitlement or guessed Sol price is assumed.

`reserve_ai_budget` serializes on the existing PostgreSQL paper-account row. The
PostgreSQL clock defines reservation/submission windows consistently across worker
machines. In the same transaction it checks duplicate material events, daily and
rolling-hour counts, billing-review holds, and spent + reserved + conservative
maximum request cost. A reservation must exist before submission. Submission
rechecks the counters and refuses cross-month reservation reuse. Concurrent workers
cannot both claim the last slot. SQLite paid reservations are rejected.

Normal candidate analyses preserve 3 daily and 1 hourly slots for portfolio-risk
reviews. Total quotas still apply to every category. Stable event fingerprints,
persistent single-flight claims and a 15-minute result cache avoid repeated scans.
Numerical strategies remain local. Unverified news alone does not qualify for a
paid analysis. Cache reuse has zero new tokens/cost and a persistent hit count.

States distinguish `RESERVED`, `SENT`, `COMPLETED`, `OUTCOME_UNKNOWN`,
`FAILED_CONFIRMED_NO_CHARGE`, and `RECONCILED`. A timeout, lost response, missing usage
or unknown billing never frees a hold. Duplicate unknown events remain blocked.
`reconcile_ai_request` requires an actor and billing evidence; it records the
receipt amount and an audit event. Repeated settlement/reconciliation is idempotent.
A token/cost bound overrun records the actual estimated cost, blocks later paid
requests with a persistent pricing-review hold, and does not falsify a USD10 total.
This internal guardrail cannot guarantee external invoicing never exceeds USD10.

Responses token-derived `actual_cost` is an estimate, not a confirmed invoice.
`actual_reported_cost` remains null until billing reconciliation. The dashboard
shows estimated spend, confirmed spend, reserved/remaining budget, UTC reset times,
rolling release time, counts, cache hits, quota rejections, errors and last success.
No credential fields are exposed. AI cannot approve research or alter risk, capital,
orders, targets or financial postings.

Executed initial quota evidence: `evidence/v4_1-quotas.xml`, 17 passing cases on real
PostgreSQL16. It covers 30/31, 6/7, exact rolling expiry, concurrent reservations,
repository restart, leap/non-leap February and 30/31-day month boundaries, day/month
crossover, duplicate unknown requests, audited zero-charge reconciliation, cost
bound overruns, persistent review holds and usage detail. Portfolio capacity and
safe configuration cases were added to the final regression suites. Existing mock,
OFF, schema-invalid and timeout boundary tests remain. No real paid call was made.

Implementation: `config.py`, `ai.py`, `persistence/ai_budget.py`, `ai_events.py`,
`models.py`, the migration and `/api/ai`. Tests use a fake provider only at the paid
network boundary; reservations and PostgreSQL transactions remain real.

Official sources checked using OpenAI Docs: [Responses usage](https://developers.openai.com/api/reference/resources/responses/methods/create)
and [pricing](https://developers.openai.com/api/docs/pricing). Current account access
and real predictive contribution are unverified. Operator billing reconciliation and
pricing review are required for ambiguous charges; no automatic release job exists.
