# V3.4 target attribution

Identity is account → position → exit plan → target or protective intention → order → fill → journal posting. A TAKE_PROFIT intention requires a target ID belonging to its exact position. STOP, TIME_EXIT, MARKET_RISK and EMERGENCY intentions have no target ID.

`dispatch_order` updates the linked target in the fill transaction. `sync_exit_plan_from_fills` can reconstruct progress solely from confirmed fills carrying that target and position identity. It never apportions position-wide SELL quantities. Original target prices and planned quantities remain stored after completion.

The default plan allocates 30% / 40% / the rounded remainder, using pair quantity precision. Available target quantity is original planned less confirmed fills less outstanding reservations. Position-wide exit reservations impose an additional bound.

Proof A (`test_proof_a_targets_survive_actual_worker_restart_and_stop`) opens 10 units through the gateway, fills TP1=3, fills TP2=1.5, kills the worker PID, starts a different PID against the same PostgreSQL database, completes TP2=4 and stops the remaining 3. TP3 remains zero. The test opens a fresh lifecycle for the same symbol after explicitly expiring the cooldown boundary and checks new targets remain untouched. Reconciliation reconstructs quantities and cash.

The former artificial step counter was removed. Actual assertions and process transitions determine pass/fail. See test evidence for executed results.
