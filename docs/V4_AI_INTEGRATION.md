# Event-driven optional AI

Mock/off remain operational without credentials. Paid API behavior is optional and
was tested only at a mocked external boundary, never with a real paid request.
The configured model ID is preserved and checked using model retrieval per paid
event. Official [GPT-6 Sol documentation](https://developers.openai.com/api/docs/models/gpt-6-sol)
establishes the model's existence; account access is not inferred from that page.

The optional Responses request uses a strict JSON schema and validates the response
again locally. Prompt-byte bounds include schema overhead; token prices are explicit
configuration inputs. Persistent reservations and usage settlement preserve the
USD10 monthly ceiling, including ambiguous timeouts, cached-input/write charges
and invalid structured responses. Uncertain billable outcomes remain reserved.

The event wrapper skips low-value proposals. Qualified opportunities, material
price/RSI/momentum/regime changes or new supplied news create a context digest.
An account-locked durable claim prevents concurrent duplicate requests. Equivalent
results cache for15minutes; failures cache briefly. Model, strategy parameters,
version and news digest participate in cache identity. Cached reuse creates a new
assessment reference with zero additional token/cost accounting.

Untrusted news is explicitly data, never instructions. It cannot change risk limits
or submit orders. No autonomous authenticated news provider was added; ingestion
continues through the authenticated existing news endpoint.

Historical RULE_ONLY versus RULE_PLUS_AI_MOCK uses identical market data and the
same deterministic mock action logic as the runtime. It verifies integration only;
it provides no evidence of predictive AI value. See the actual matched reports.
The official [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and [prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
documentation informed the optional request format. OpenAI Docs skill was used;
no API key was provisioned or printed.
