# V3.4 AI integration

Default is `AI_PROVIDER=mock`; `off` also operates without credentials. Only explicit `openai` mode constructs a paid provider. AI never calls the execution gateway, changes capital policy or bypasses deterministic risk checks.

The provider validates structured JSON, supports uncertain/contradictory assessments and passes the result into the decision engine. Paid configuration requires an official model ID and explicit input/cache/output prices. The configured account's model identity is checked read-only before a billable request.

The official catalog documents `gpt-6.1-sol`. Account access was not tested because no API credentials or purchase were required. Source: [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol), checked 2026-10-15. Its documented standard token prices distinguish uncached input, cached input, cache writes and output; configuration deliberately has no assumed paid defaults.

PostgreSQL monthly budget rows are locked before reserving bounded request cost, with a hard USD 10 ceiling. Usage records preserve request ID, candidate, model, input/output/cache tokens, configured prices, reserved and actual cost, status and errors. Output tokens and prompt bytes are bounded; standard service tier and explicit cache mode are requested. SDK retries are disabled.

Ambiguous timeouts retain their reservation as UNKNOWN. Invalid output with reported usage is still charged in the local accounting. Completed settlement is idempotent. Legacy paid estimates create a disclosed hold pending billing review. Mock tests validate the external API boundary; no actual paid request was executed.

Authenticated `/api/news` intake persists timestamped article title/body/URL/source with an unverified context label. Up to three recent symbol articles enter the paid prompt as explicitly untrusted data; schema-validated catalyst interpretation reaches the decision engine. Prompt-injection text and invalid risk-override fields are tested at the external provider boundary. An autonomous external news feed is not configured.
