# System Architecture

## 1. Purpose

This document defines the application, service, data, AI, integration and operational architecture for the D&D AI World Platform.

The platform is a persistent-world system in which PostgreSQL is the source of truth, integrations communicate through application services, and AI produces controlled proposals rather than directly owning canonical state.

## 2. Architectural goals

The architecture must support:

- multiple worlds
- multiple timelines per world
- multiple campaigns sharing a timeline
- alternate timeline branches
- shared NPC and player-character mechanics
- event-assisted state management
- party-specific knowledge and discovery
- dungeon and quest progression
- FoundryVTT and Discord integrations
- AI-assisted NPC portrayal and world management
- future campaign-data imports
- auditability, validation and replayable history
- future rulesets beyond D&D 5e

## 3. Context diagram

```mermaid
flowchart LR
    GM[Game Master]
    PLAYER[Players]
    ADMIN[Platform Administrator]
    DEV[Developer or MCP Client]

    WEB[Web and Admin Client]
    FOUNDRY[FoundryVTT Module]
    DISCORD[Discord Bot]
    MCP[MCP Interface]

    PLATFORM[D&D AI World Platform]

    MODELS[AI Model Providers]
    POSTGRES[(PostgreSQL)]
    OBJECTS[(Document or Object Storage)]

    GM --> WEB
    GM --> FOUNDRY
    PLAYER --> FOUNDRY
    PLAYER --> DISCORD
    ADMIN --> WEB
    DEV --> MCP

    WEB --> PLATFORM
    FOUNDRY --> PLATFORM
    DISCORD --> PLATFORM
    MCP --> PLATFORM

    PLATFORM --> POSTGRES
    PLATFORM --> OBJECTS
    PLATFORM --> MODELS
```

## 4. Container diagram

```mermaid
flowchart TB
    subgraph Clients
        WEB[Web and Admin UI]
        FOUNDRY[FoundryVTT Module]
        DISCORD[Discord Bot]
        MCP[MCP Server or Adapter]
        CLI[Administrative CLI]
    end

    subgraph Edge
        GATEWAY[API Gateway or Reverse Proxy]
        AUTH[Authentication and Authorization]
    end

    subgraph Application
        API[REST Application API]
        COMMANDS[Command Handlers]
        QUERIES[Query Services]
        JOBS[Background Workers]
        EVENTS[Internal Event Dispatcher]
    end

    subgraph DomainServices[Domain Services]
        ENTITY[Entity Service]
        TIMELINE[Timeline and State Service]
        CHARACTER[Character and NPC Service]
        DUNGEON[Dungeon Service]
        QUEST[Quest Service]
        KNOWLEDGE[Knowledge Service]
        RULES[Rules and Check Service]
        INTERACTION[Interaction Service]
        AIORCH[AI Orchestration Service]
        IMPORT[Import Service]
        INTEGRATION[Integration Service]
    end

    subgraph Data
        DB[(PostgreSQL)]
        VECTOR[(pgvector or Vector Index)]
        OBJECTS[(Object Storage)]
        CACHE[(Optional Cache)]
    end

    subgraph External
        MODEL[AI Model Providers]
        FOUNDRYAPI[FoundryVTT Runtime]
        DISCORDAPI[Discord API]
    end

    WEB --> GATEWAY
    FOUNDRY --> GATEWAY
    DISCORD --> GATEWAY
    MCP --> GATEWAY
    CLI --> GATEWAY

    GATEWAY --> AUTH
    AUTH --> API
    API --> COMMANDS
    API --> QUERIES
    COMMANDS --> ENTITY
    COMMANDS --> TIMELINE
    COMMANDS --> CHARACTER
    COMMANDS --> DUNGEON
    COMMANDS --> QUEST
    COMMANDS --> KNOWLEDGE
    COMMANDS --> RULES
    COMMANDS --> INTERACTION
    COMMANDS --> AIORCH
    COMMANDS --> IMPORT
    COMMANDS --> INTEGRATION

    COMMANDS --> EVENTS
    EVENTS --> JOBS

    ENTITY --> DB
    TIMELINE --> DB
    CHARACTER --> DB
    DUNGEON --> DB
    QUEST --> DB
    KNOWLEDGE --> DB
    RULES --> DB
    INTERACTION --> DB
    AIORCH --> DB
    IMPORT --> DB
    INTEGRATION --> DB

    QUERIES --> DB
    QUERIES --> CACHE
    AIORCH --> VECTOR
    AIORCH --> MODEL
    IMPORT --> OBJECTS
    INTEGRATION --> FOUNDRYAPI
    INTEGRATION --> DISCORDAPI
```

## 5. Layering

### 5.1 Client and integration layer

Responsibilities:

- user interaction
- FoundryVTT scene and actor integration
- Discord commands and conversations
- administrative workflows
- MCP access for development and tooling

Clients may request commands and queries. They must not write directly to PostgreSQL.

### 5.2 API layer

Responsibilities:

- authentication
- authorization
- input validation
- command/query routing
- correlation and idempotency identifiers
- response shaping
- rate limiting and abuse protection

The API layer should avoid embedding domain rules.

### 5.3 Application layer

Responsibilities:

- coordinate use cases
- open transaction boundaries
- invoke domain services
- enforce command-level authorization
- publish post-commit work
- translate domain results into API responses

Recommended command examples:

- `CreateWorld`
- `CreateTimeline`
- `CreateNpc`
- `StartSession`
- `PerformInteraction`
- `ResolveCheck`
- `ApplyEvent`
- `AdvanceQuest`
- `RevealKnowledge`
- `CreateTimelineBranch`
- `ApproveAiProposal`

### 5.4 Domain layer

Responsibilities:

- enforce invariants
- calculate allowed transitions
- create events and state changes
- evaluate quest completion
- control knowledge visibility
- assemble NPC context
- validate timeline inheritance
- separate rules definitions from instances

### 5.5 Persistence layer

Responsibilities:

- PostgreSQL repositories and query objects
- migrations
- transactional stored procedures where beneficial
- typed state views
- effective timeline-state functions
- full-text and vector-search support

## 6. Command and query separation

The architecture uses pragmatic command/query separation.

Commands mutate state and should:

1. authenticate and authorize
2. validate the requested operation
3. acquire required locks
4. create interactions or administrative causes
5. create events when the mutation is narratively significant
6. close old typed state and insert new typed state
7. evaluate dependent quest, knowledge and relationship changes
8. record audit data
9. commit atomically
10. schedule non-transactional work after commit

Queries should use optimized views and read models without mutating domain state.

## 7. Transaction boundary

A persistent world change should generally use one PostgreSQL transaction.

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Service
    participant DB
    participant Worker

    Client->>API: Command with idempotency key
    API->>Service: Authorized command
    Service->>DB: Begin
    Service->>DB: Validate and lock current state
    Service->>DB: Insert interaction/event
    Service->>DB: Close old state
    Service->>DB: Insert new state
    Service->>DB: Update quest/knowledge reactions
    Service->>DB: Insert audit/outbox record
    Service->>DB: Commit
    Service-->>API: Domain result
    API-->>Client: Response
    DB-->>Worker: Outbox item available
```

External calls to AI providers, Discord or FoundryVTT should not normally occur inside the database transaction.

## 8. Event-assisted state architecture

The platform is not pure event sourcing.

```mermaid
flowchart LR
    ACTION[Interaction or Command] --> EVENT[Historical Event]
    EVENT --> STATE[Typed Current State]
    EVENT --> QUEST[Quest Progress]
    EVENT --> KNOW[Knowledge Changes]
    EVENT --> REL[Relationship and Goal Changes]

    STATE --> READ[Effective Read Model]
    QUEST --> READ
    KNOW --> READ
    REL --> READ
```

Events answer why and when. Typed state answers what is true now.

## 9. Effective timeline state

An effective read combines:

```text
world definition
+ parent timeline history through branch point
+ local timeline events and state
+ campaign participation and permissions
+ party or character knowledge
```

The Timeline and State Service owns this resolution logic. Individual clients and domain services should not independently reinvent it.

## 10. Internal event dispatcher and outbox

The platform should use a transactional outbox for post-commit work.

Typical outbox consumers:

- update embeddings
- refresh caches
- notify FoundryVTT
- send Discord notifications
- generate session summaries
- evaluate low-priority NPC routines
- update search indexes

Outbox consumers must be idempotent.

## 11. AI orchestration architecture

```mermaid
flowchart TD
    REQUEST[AI Request] --> POLICY[Agent and Permission Policy]
    POLICY --> CONTEXT[Structured Context Assembly]
    CONTEXT --> RETRIEVE[Approved Semantic Retrieval]
    RETRIEVE --> PROMPT[Prompt Assembly]
    PROMPT --> MODEL[AI Provider]
    MODEL --> OUTPUT[Generated Output]
    OUTPUT --> CLASSIFY{Output Type}
    CLASSIFY -->|Dialogue or Summary| RETURN[Return Derived Content]
    CLASSIFY -->|Suggested Mutation| PROPOSAL[Create Proposed Change]
    PROPOSAL --> VALIDATE[Validate Invariants and Impact]
    VALIDATE --> REVIEW{Approval Policy}
    REVIEW -->|Automatic low risk| APPLY[Execute Domain Command]
    REVIEW -->|GM review| QUEUE[Review Queue]
    REVIEW -->|Reject| REJECT[Record Rejection]
    QUEUE --> APPLY
    APPLY --> EVENT[Event and Typed State]
```

AI context must be constrained by:

- world
- timeline
- campaign
- portrayed entity
- entity knowledge and beliefs
- disclosure rules
- current location and state
- approved source material
- user permissions

AI outputs are derived content unless promoted through the proposal workflow.

## 12. Rules engine

The rules engine should be ruleset-aware and deterministic where possible.

Responsibilities:

- ability and skill checks
- saving throws
- attack and damage resolution
- conditions and durations
- resource consumption
- spell and feature validation
- movement and senses
- ruleset version selection

Random results should record their inputs, roll expression, outcome and source so that session history can be audited.

## 13. Dungeon and quest services

The Dungeon Service owns:

- area containment and connections
- feature, hazard and interactable definitions
- current connection and hazard state
- area discovery
- travel and entry validation

The Quest Service owns:

- quest availability
- stage transitions
- objective dependencies
- event-evaluable completion
- GM-confirmed progress
- outcomes and rewards

The two communicate through events and explicit application orchestration rather than by directly editing each other's tables.

## 14. Knowledge service

Responsibilities:

- claim creation and versioning
- objective truth status
- per-entity awareness and belief
- party discovery
- information transfer
- sharing and disclosure policy
- public knowledge
- knowledge-filtered AI context

Discovery changes the knower's state, not the existence of the underlying entity or feature.

## 15. Integration architecture

### 15.1 FoundryVTT

Foundry is a client and visualization surface, not the authoritative database.

Integration responsibilities:

- map Foundry actors, scenes, journals and tokens to internal UUIDs
- submit interactions and checks
- receive state updates
- synchronize selected character and scene fields
- tolerate offline or delayed synchronization

Delivered (Phase 11 workstream 7, revised by Phase 11R workstream 11R): `foundry-module/` — a real, installable FoundryVTT module (dnd5e-only; FoundryVTT minimum `13`, verified `13.351`) implementing the client half of this section, over the adapter-facing API contract [§19.1](../architecture/DATABASE_MODEL.md#191-identity-and-login) and [DATABASE_MODEL.md §19](../architecture/DATABASE_MODEL.md) already establish. Combat-turn/condition/resource submission is always an explicit GM/player action (its own "D&D AI Sync" panel), never inferred from FoundryVTT's dnd5e-system-specific chat-card/damage-application internals; HP synchronization alone is automatic, wired to Foundry's `updateActor` hook with a self-updating guard so the module's own confirmed write-back never re-triggers a second submission. Each browser/device pairs itself individually against the hybrid Foundry pairing model ([DATABASE_MODEL.md](../architecture/DATABASE_MODEL.md)'s Foundry hybrid pairing section) — superseding the single shared `FoundrySystem` credential the original workstream delivered — so any campaign member, not only the GM, can pair their own client. See `foundry-module/README.md` for the pairing flow (`scripts/foundry_provision.py`'s `register`/`pairing-code` subcommands, a diagnostic CLI over the same public pairing API standing in for the portal UI Phase 13 will eventually provide) and `tests/scenario/test_foundry_adapter_e2e.py` for the reproducible harness proving the exit criterion this integration exists to satisfy.

### 15.2 Discord

Discord integration may support:

- out-of-session NPC conversation
- campaign notifications
- quest reminders
- downtime actions
- session summaries

Discord messages should be stored with provenance when they create interactions or knowledge transfers.

### 15.3 MCP

MCP exposes controlled development and GM tooling. It must follow the same authorization and domain-command pathways as other clients.

## 16. Import architecture

```mermaid
flowchart LR
    DOC[Campaign Documents] --> STORE[Object Storage]
    STORE --> EXTRACT[Extraction Worker]
    EXTRACT --> STAGE[Import Staging]
    STAGE --> MATCH[Entity Matching]
    MATCH --> VALIDATE[Validation]
    VALIDATE --> REVIEW[GM Review]
    REVIEW --> PROMOTE[Promotion Commands]
    PROMOTE --> DB[(Canonical PostgreSQL Data)]
```

The import subsystem is intentionally isolated from canonical tables until promotion.

## 17. Deployment topology

**Self-hosted Docker Compose is the officially supported deployment topology** ([ADR 0012](../adr/0012-self-hosted-docker-deployment-and-ci-verification.md)), superseding the AWS-only model ADR 0008 originally described. A modular monolith is preferred initially because the domains require strong transactional consistency and are still evolving; service boundaries can become process boundaries later when operational evidence justifies it.

| Deployable | Self-hosted target | Notes |
|---|---|---|
| PostgreSQL | `db` service in `compose.yaml`, PostgreSQL 18, persistent named volume | Source of truth (§2) |
| Migrations and batch jobs | `migrate` service in `compose.yaml`, built from the shared `Dockerfile` | Runs today |
| Application API | `api` service in `compose.yaml`, FastAPI under Uvicorn, built from the shared `Dockerfile` | Runs today; publishes no host port by default (compose.override.yaml adds one for local development); production ingress still requires the reverse proxy described in PLAN.md §32 |
| Background worker | Not yet built | Drains the outbox (§10), delivers integrations, processes AI proposals, once built |
| Discord adapter | Not yet built | Outbound gateway connection, once built |
| Object storage | Not yet decided | Import source documents, exports, image layers |
| Secrets | Environment variables / `.env` (gitignored) | No credential in an image, compose file, or source control |
| FoundryVTT module | Runs in the user's Foundry instance | A client, not something this project deploys — built and packaged from `foundry-module/` (`node packaging/package.mjs`), installed manually into the GM's own FoundryVTT instance (§15.1, `foundry-module/README.md`) |

The API, worker, and adapter will share a single container image; the entrypoint selects the role, so there is one artifact to build and promote — see [DEVELOPMENT.md §2](../DEVELOPMENT.md#2-repository-layout) and [§3.6](../DEVELOPMENT.md#36-self-hosted-docker-compose).

**AWS remains an optional, no-longer-continuously-verified deployment path.** `terraform/modules/database`/`secrets` and `terraform/environments/dev` are retained for anyone who chooses to host PostgreSQL on AWS RDS instead; an ECS Fargate/Lambda compute path for the application services remains documented, unbuilt planning material in [PLAN.md §30](../PLAN.md#30-aws-terraform-deployment-plan-for-postgresql)–[§31](../PLAN.md#31-aws-deployment-plan-for-application-services), not something any phase currently deploys to. Nothing in this project's supported, CI-verified path requires AWS.

## 18. Security model

Required controls:

- user and service authentication
- role- and permission-based authorization
- world and campaign access checks
- GM-only approval policies
- secret management outside source control
- least-privilege database roles
- row-level security only where it provides clear value
- audit logging for privileged changes
- strict separation between model-provider credentials and client access
- `Secure`, `HttpOnly`, narrowly scoped authentication cookies and CSRF protection for cookie-authenticated mutations
- reverse-proxy and/or application rate limiting for login and expensive AI endpoints
- no direct public access to PostgreSQL or Uvicorn

## 19. Observability

Every request and background job should carry:

- correlation ID
- causation ID
- user or service identity
- world, timeline and campaign identifiers when applicable
- command or query name
- duration and outcome

Operational telemetry should include:

- API errors and latency
- database transaction failures
- outbox backlog
- integration delivery failures
- AI provider latency, cost and error rates
- proposal approval rates
- validation failures
- import extraction and matching quality

## 20. Failure handling

- Domain validation failures return structured errors without partial writes.
- A generic request-validation response never exposes a caller-controlled field *location* (a dynamic dictionary key, a rejected extra-field name, a discriminator value, an input-derived alias, an arbitrary index), and never a pydantic error-*type* string either — only a small, fixed, public vocabulary the API layer owns (`missing`/`invalid_type`/`invalid_format`/`out_of_range`/`invalid`), matched by exact lookup against a closed set of real pydantic type strings, never by regex or character shape; every unmapped or custom type — built-in or `PydanticCustomError`-supplied, however identifier-shaped — falls back to `invalid`. Validation failures are logged through the same sanitized, fixed-shape path as every other API error, never with raw errors, locations, per-error codes, or rejected input.
- Every `ApiError`'s status code, public error code, and public message are fixed, type-level properties of one of a small number of explicit, registered subclasses — never constructor-supplied. The complete `(status, code, message)` triple, not each field independently, is checked against that registry before reaching a response or a log line; an unrecognized subclass or any mismatched/altered field falls back to the fixed internal-error contract. A framework-raised `HTTPException`'s status code is bounded the same way: only a small, explicit set of supported statuses (at minimum routing 404/405) is ever forwarded to a response, and any other status — however HTTP-shaped — gets the identical fixed internal-error fallback rather than being forwarded verbatim. `HTTPException.headers` is never forwarded either — a directly raised instance can carry any header a caller or a careless call site chose — so a 405 response's `Allow` header is instead recomputed by the API layer itself, as the union of declared methods across every application route whose own framework-provided route-matching accepts the request's path (not merely the single route Starlette's router happens to remember on a method mismatch, which under-reports when the same path is registered as more than one route). Every unclassified/fallback path in the API layer (an unrecognized `ApiError`, an unsupported `HTTPException` status, an unclassified `IntegrityError`, an otherwise-unhandled exception) returns and logs the identical fixed 500/`internal_error` contract — one constant, not a separately worded copy per handler. Every handler computes exactly one validated classification and reuses it for both the response and the log line.
- A unique/exclusion-constraint conflict returns a fixed, non-disclosing 409 — a genuine conflict, but not a claim that retrying the same request will succeed; only a command that recognizes a specific, demonstrated optimistic-concurrency or idempotency case may say retrying/re-reading is appropriate, through its own exception type.
- An integrity failure the application layer cannot confidently classify (a missing or unrecognized SQLSTATE) is treated as an internal error (500), not guessed at as a 400 or 409 — that ambiguity itself is evidence of an application/schema/runtime defect.
- External integration failures are retried through durable queues.
- AI failures do not roll back already-committed world changes.
- Failed outbox deliveries remain visible and retryable.
- Import failures remain in staging.
- Administrative repair commands require provenance and audit entries.

## 21. Scalability approach

Scale in this order:

1. correct indexes and query plans
2. optimized effective-state views
3. connection pooling
4. background work and outbox processing
5. read caching for expensive derived views
6. partitioning of large append-only tables
7. read replicas if required
8. process-level service extraction only when justified

Do not prematurely split domains into distributed microservices while core invariants still require cross-domain transactions.

## 22. Testing strategy

### Unit tests

- domain transition rules
- quest objective evaluation
- knowledge visibility
- AI proposal impact classification
- timeline inheritance calculations

### Integration tests

Run against a local/self-hosted PostgreSQL 18 server during development and against a disposable containerized PostgreSQL 18 instance in CI — never against SQLite or a mock ([PLAN.md §24.0](../PLAN.md#240-verification-policy)):

- PostgreSQL constraints and functions
- transactional state/event updates
- idempotent commands
- outbox processing
- effective-state views

### Contract tests

- FoundryVTT adapter
- Discord adapter
- AI provider adapters
- MCP tools
- OIDC bearer-token verification (`dnd_ai.domain.tokens`, `dnd_ai.api.auth`)

No live external dependency is permitted in tests. OIDC verification demonstrates the pattern: rather than a live identity provider or JWKS server, the verifier resolves its signing key through an injected `kid -> key` callable, and tests supply a fake resolver backed by a locally generated keypair. Use the same injectable resolver/client seam for Foundry, Discord, and AI-provider contract tests.

### End-to-end tests

The primary end-to-end scenario is the dungeon/quest flow defined in `docs/architecture/DUNGEON_FLOW.md`.

## 23. Architecture constraints

1. No client writes directly to domain tables.
2. PostgreSQL remains authoritative.
3. AI cannot directly mutate canon.
4. Events and typed state changes commit atomically.
5. External calls occur after commit through durable work where possible.
6. Knowledge-filtered context is mandatory for NPC portrayal.
7. Timeline resolution is centralized.
8. Rules data is versioned and ruleset-scoped.
9. Integrations retain internal UUID mappings.
10. Self-hosted Docker Compose is the deployment topology, and CI verifies against containerized PostgreSQL 18 of the same major version development uses before anything ships. AWS remains an optional, no-longer-continuously-verified path ([ADR 0012](../adr/0012-self-hosted-docker-deployment-and-ci-verification.md), superseding [ADR 0008](../adr/0008-aws-first-deployment-and-verification.md) and [ADR 0011](../adr/0011-local-first-development-aws-verified-delivery.md)).
11. The initial implementation should remain a modular monolith unless evidence supports decomposition.
