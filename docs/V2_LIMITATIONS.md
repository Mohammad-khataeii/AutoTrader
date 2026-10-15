# V2 Limitations

This is a meaningful V2 runtime-reliability slice, not the full V2 acceptance-complete platform.

Still incomplete:

- Worker does not yet use live Revolut X market feeds by default.
- Redis queues are not yet used.
- No distributed lock for multiple worker replicas.
- Position management only has a basic persistent sell path; TP1/TP2/TP3 and trailing-stop state machines remain pending.
- Dashboard pages are not fully redesigned into the requested workstation.
- AI budget/caching/circuit-breaker state is not fully durable.
- Backtesting V2 research features remain pending.
- Production authentication/session hardening remains pending.

Safety boundary preserved: live trading remains disabled.

