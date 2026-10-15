# V3.4 security

Live trading is rejected by configuration and has no exchange submission adapter or route. Revolut X credentials are not requested or stored. Production requires generated dashboard credentials and PostgreSQL. Mock/off AI works without keys. Frontend credentials live only in component memory, are cleared on sign-out and are never hard-coded into the bundle.

All data/control endpoints and metrics are authenticated. Readiness checks the actual schema. No WebSocket route is exposed. Browser polling reads persisted scanner state and does not silently initiate repeated paid AI or market scans. React renders external explanations as text.

Database triggers prevent ordinary UPDATE/DELETE of journal and fills. Unique keys, foreign keys, account locking, fill attribution and reconciliation protect normal execution. Projection mismatches halt entries. An authenticated, fingerprinted correction plan can restore proven projections and records a zero-economic audit event; it cannot rewrite immutable history or infer legacy attribution. Ambiguous legacy rows halt automation.

Structured logs redact configured credentials, Authorization values and database URI passwords. Environment files and dependency/build artifacts are excluded from Git and Docker contexts. Runtime dependency versions are pinned; local pip and npm audits were executed. Docker Scout findings and remediation are recorded separately in test evidence, including any remaining upstream OS advisories.

Internal database/cache networks and loopback service bindings limit default exposure. Generated deployment passwords are never included in committed evidence. Backups must be protected as financial/audit history even though all funds are virtual.
