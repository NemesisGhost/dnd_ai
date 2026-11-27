# HTTP API

At `881786c` the registered FastAPI handlers and OpenAPI described 348 distinct method/path operations on 333 distinct paths; P15-C02-S03 adds one read (`GET /campaigns/{campaign_id}/reveal-delegations`, on an existing path), so they described 349 distinct method/path operations on 333 distinct paths; P15-C11-S02-T01 adds the four control-assignment operations (three writes and one read, on three new paths), P15-C11-S02-T02 adds the three assign-control delegation operations (two writes and one read, on two new paths), so they now describe **356 distinct method/path operations on 338 distinct paths**. A GET and a POST on the same path count separately. The 192 writes in the bounded R01 inventory use a different scope. Paths below are backend paths. The portal's development proxy removes the leading `/api` from ordinary API requests and preserves `/auth`.

| Contract family | Catalog | Additional policy |
|---|---|---|
| Identity, invitations, membership, sharing, audit and profiles | [82 operations](identity-and-access.md) | [Access and account contracts](ACCESS_CONTROL.md) · [Audit history](../reference/audit-history.md) |
| World setup, lifecycle and typed content | [157 operations](world-and-authoring.md) | [Lifecycle and command rules](../ENTITY_LIFECYCLE.md) |
| Session operation, state, reads, AI, reference corpus and Foundry | [117 operations](play-and-integrations.md) | [Audience-filtered reads](READ_API.md) · [Character sheets](CHARACTER_SHEET.md) · [Runtime integrations](../reference/runtime.md) |

## Calling an operation

Use the model names in the catalog to find field names, required and nullable values, query parameters and success bodies in the running API's `/openapi.json`. A response model describes the wire shape. Where OpenAPI declares no named success schema, the catalog says `response` and links the router that constructs it. The handler and its query projection determine which records and fields the current principal can receive. Check the linked router for handler-specific checks on token, owner, group, archive state and resource identity. The catalog's entry gates are only the first checks.

Browser login uses an opaque server-side session. Cookie-authenticated writes require the accepted Origin and CSRF handling. Foundry pairing and optional OIDC bearer access have separate principal boundaries. Campaign reads scope membership, permissions and perspective before projection. Some inaccessible resources return the same 404 as a missing record. Never use a disabled control, a list result or a preview as authority for a later write. [Access control](ACCESS_CONTROL.md)

## Submitting a change

For a keyed command, retain the same idempotency key and payload across a retry of the same intent. A key used for a different request conflicts. Check each route for required versus optional keys and response redaction. In particular, an invitation or activation secret may be displayed only once. Edits that require an expected version return a conflict when the record has moved. Re-read before reconciling a stale edit. [Idempotency and concurrency](../ENTITY_LIFECYCLE.md#18-concurrency-and-idempotency)

The request transaction owns the receipt, durable change and associated audit records. On finalized routes the authorization plan defines where the protected decision occurs. Some AI and Foundry workflows span multiple transactions. Local success requires a committed transaction. A client losing the response can have an uncertain outcome. Use the keyed replay contract where supported. The API distinguishes unauthenticated, forbidden, concealed/missing, validation and conflict responses. Error bodies are sanitized and a database failure is not reported as success. [Authorization timing](ACCESS_CONTROL.md#authorization-timing-and-the-final-check-r01-s6) · [Failure handling](../architecture/SYSTEM_ARCHITECTURE.md#20-failure-handling)
