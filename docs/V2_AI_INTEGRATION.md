# V2 AI Integration

Current state:

- `AI_PROVIDER=mock` remains default.
- OpenAI provider is configurable and disabled without an API key.
- Model identifier is configurable; no Sol model identifier is invented.
- AI output is schema-validated and treated as analytical input only.
- AI never places orders or bypasses risk.

Still pending:

- Persistent token/cost ledger.
- Response cache.
- AI circuit breaker persisted across restarts.
- Selective invocation policy based on novelty and opportunity significance.
- Stronger prompt-injection tests.

