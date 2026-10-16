# AutoTrader4.2.0 release notes

This release adds evidence-driven trade failure diagnostics, bounded versioned experimental strategies, durable physically isolated EUR 500 shadow accounts, shared market-data caching/pacing, frontend integration and permanent deployment repairs while retaining the existing financial engine.

All833original positions and2,204 fills were analyzed. Original strategies and all archived results remain reproducible. A2/B2/C2/E2/F2 use version 4.2.0-experimental.1; D2 is a veto-only momentum filter. The five experimental outcomes are negative or have zero trades. NO STRATEGY PASSED VALIDATION; official promotion gates remain strict.

Shadow domains reuse actual broker/journal/risk/position-manager behavior. Frozen manifests, PostgreSQL identity checks, per-domain orders/risk/leases, idempotent funding, restart recovery, protected exit monitoring, authenticated controls and full history exports are implemented. Synthetic acceptance generated five actual persisted fills and recovered partial TP2 after SIGKILL while official cash/equity stayed EUR 500 with no orders. Full isolated-cluster restore preserved all domains and executed only the restored shadow's next exit.

Market observations are shared across official and experimental strategies. Completed candles refresh by boundary/incremental overlap; protection has request priority; shared429cooldowns and bounded Retry-After millisecond handling preserve freshness. Controlled old/new application measurement reduced candle requests80% and downloaded records89.84%. A genuine public-feed smoke is separately recorded.

The existing React dashboard gains shadow portfolios/controls/charts, complete exports, failure filtering/details, experimental OOS comparison and data health. Long record tables scroll within bounded panels. Existing pages, research jobs, official controls, authentication and pilot export remain exercised.

Deployment changes repair restrictive-host-file Docker builds, fresh Alembic initialization and populated backup/restore/migration ordering. Stage A release packaging now reads an exact committed revision, excludes runtime/private files, creates a checksum/manifest and rejects modified or extra package source. Production source operations require an approved full commit plus verified manifest. AGENTS.md records the permanent local→test→commit→push→approval→backup→deploy→verify→cleanup workflow.

See V4_2_LOCAL_VALIDATION.md for actual tests, V4_2_BACKTEST_RESULTS.md for all outcomes, V4_2_KNOWN_LIMITATIONS.md for scientific/security limits and V4_2_VPS_DEPLOYMENT.md for the approval boundary. Thirty future days and profitable edge are not claimed.
