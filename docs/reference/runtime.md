# Runtime configuration and integrations

| Concern | Implemented behavior |
|---|---|
| Database | Local tools and Alembic use `DATABASE_URL`. The API reads `DND_AI_DATABASE_URL` and supports a local/test compatibility alias. In production it requires the runtime login `app_read_write`. Compose passes `API_DATABASE_URL` to the API and `MIGRATION_DATABASE_URL` to the migration job. |
| Browser sessions | The local login uses a server-side session and an HttpOnly cookie. Configure exact accepted browser origins with `DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS`. Production requires HTTPS origins. |
| OIDC | External bearer compatibility is optional. Configure issuer, audience and JWKS URL together. Local account login works independently. |
| Foundry | The module pairs a device to an authorized campaign connection. A separate Foundry origin needs an exact allowlist. The adapter's commands use the API. A licensed, live v13 run remains an acceptance obligation. |
| AI | NPC turns and synthesis use an OpenAI-compatible Chat Completions endpoint selected by `DND_AI_AI_PROVIDER_BASE_URL`, model and optional API key. The hosted default needs a key. The resolver returns 503 if it cannot provide a hosted client. An operator-selected compatible local endpoint can run without a key. Tests can inject a deterministic fake. |
| Proposed changes and corpus | AI operates on authorized context. Proposals go through review or an explicitly allowed approval policy before a domain command can affect canon. Rules/reference retrieval has campaign grants. Campaign import staging is future work. |
| Other clients | Discord, MCP, the outbox worker and campaign import workers are planned. The current Compose services are `db`, `migrate` and `api`. |

## What the feature settings control

`DND_AI_FEATURE_AI_NPC_DIALOGUE` causes production startup to require a key for the default hosted endpoint when true. `DND_AI_FEATURE_FOUNDRY_INTEGRATION` causes production startup to require configured Foundry origins when true. Neither flag guards the corresponding requests. The Discord flag is declared without a runtime consumer. Configured credentials, authorized principals and provider availability still determine what requests can do. The session bootstrap currently reports `ask`, `ai_summaries`, `gm_briefs` and `cited_rules` as false independently of provider configuration. [Outstanding C2/C3 packaging and feature-setting work](../delivery/work-register.md#documentation-drift-at-the-audited-head)

Set production values through the process environment or supported mounted secrets. Production mode is selected from the process environment and skips the local dotenv file. Keep credentials out of shared commands and logs. [Full environment template](../../.env.example) · [Settings and validation](../../src/dnd_ai/config.py) · [Deployment](../operations/deployment.md) · [Foundry pairing and live verification](../../foundry-module/README.md#manual-live-foundry-verification)
