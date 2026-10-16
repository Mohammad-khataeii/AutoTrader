# V4.1 unattended paper operation

The existing worker, scanner, broker, financial gateway, ledger, protective manager
and recovery remain. The coordinator now claims a durable 15-second PostgreSQL
lease and renews every five seconds. Competing workers wait. Every worker-owned
order admission and dispatch verifies the current owner and lease while holding the
account lock. A stale process cannot post economic changes after takeover. A killed
worker's replacement may wait up to the remaining lease interval; startup does not
create a new account or reset cash.

The position loop runs independently with a five-second target. Market scans target
60 seconds measured from cycle start. Cycles do not overlap. Duration, schedule
overrun, next scan, scanned markets, observations, failures, qualified/rejected
signals and execution outcomes persist. Public API rate reservations remain shared
in PostgreSQL. The scan loop catches provider/database failures, preserves financial
state and retries with bounded backoff up to 60 seconds. Shutdown cancels its tasks,
closes clients and releases only its own coordinator lease. Database unavailability
prevents financial execution; a lease cannot be assumed valid from memory.

Persistent operation states distinguish INITIALIZING, DATA_SYNCING, RESEARCH_ONLY,
PAPER_READY, PAPER_TRADING, ENTRY_SUSPENDED, RISK_HALTED, DATA_DEGRADED,
RECOVERY_REQUIRED and SYSTEM_ERROR. Financial runtime health remains independently
authoritative. Healthy scanning with no approved strategy is RESEARCH_ONLY. Zero
orders are not a malfunction. A valid fresh book and finite modeled depth are still
required for protective exits; stale books/outages preserve exit intentions and
record protection watches, never fabricated fills.

Redis remains optional to financial processing. The API checks it with bounded
connection/socket timeouts and reports unavailable status. Its absence does not
replace PostgreSQL or reset risk/AI/paper state. Research jobs retain durable claims,
leases and bounded queue capacity; crash recovery recomputes a job with old partial
artifacts retained. The research worker has separate memory/CPU constraints.

Evidence: `evidence/v4_1-lifecycle.xml` executed the actual worker/API processes on
PostgreSQL 16: cost rejection, entry, TP1, partial TP2, killed process/restart,
remaining TP2, protective gap exit, five unique fills, zero reserved cash and empty
reconciliation. `test_v41_promotion_operations.py` verifies single-owner claims and
fencing after expiry. The full process suites additionally cover crash boundaries,
partial accounting, simultaneous orders/targets/stops, risk-halt persistence and
recovery. Deployment restart/outage evidence is recorded separately.

Limitations: ordinary Docker health checks do not independently restart a merely
unhealthy but still-running container. The worker catches recoverable cycle errors
and Compose restarts exited processes. There is no external host supervisor,
remote alert delivery or guarantee that a five-second monitor meets its deadline
during provider rate limits. Long-lived observation/incident retention needs disk
monitoring and archival that preserves pending-intent references.
