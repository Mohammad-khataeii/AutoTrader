# V3.4 concurrency and recovery

Every economic transaction first locks the one `paper-eur` account row with PostgreSQL FOR UPDATE. All balance, order, position, target and intention changes occur within that shared lock scope. This serializes the single account across sessions, processes and containers. No financial path relies on an asyncio lock.

Admission checks current cash, marked exposure, reservations, existing positions, entry count, cooldown, reconciled history and loss state. It commits the order and reservation before dispatch. Dispatch checks persisted controls and risk again, including changes in marked exposure since admission. The simulated IOC fill transaction either commits every economic projection and journal event or rolls them all back.

Stable client keys and unique order/fill/journal constraints protect retries. A fill ID is derived from its order, and terminal orders return their existing result. Database disconnections and SQLSTATE 40001/40P01 receive bounded retries of idempotent operations. IOC remainders release their reservations. Protective exits cancel pending overlapping exits before reserving remaining quantity.

Startup and each worker cycle recover pending intentions. A sufficiently fresh original observation can be replayed; a stale intention is cancelled and released. A different observation cannot silently replace the durable risk-checked execution snapshot.

Tests use independent PostgreSQL sessions, actual row-lock deadlocks, duplicate keys/fills, terminated connections and worker crashes on both sides of commit. Literal exactly-once network delivery is not claimed; economic effects are transactional and idempotent.
