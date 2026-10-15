# V3 Roadmap

1. Replace worker fixture data with scheduled Revolut X public feed ingestion.
2. Add Redis-backed queues and a single-writer execution lock.
3. Implement position state machines for TP1/TP2/TP3, trailing stops, break-even, cooldowns, and market-risk exits.
4. Add multi-timeframe feature persistence and strategy ensemble conflict resolution.
5. Build missed-opportunity and strategy evaluation pipelines.
6. Redesign dashboard into a full trading workstation with real persisted endpoints.
7. Add Grafana dashboards for worker, execution, risk, AI, and data freshness.
8. Add production auth/session controls and container hardening.
9. Add full Docker restart-recovery E2E tests.

