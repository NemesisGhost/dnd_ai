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

Initial deployment may be a modular monolith with separate workers.

Recommended initial deployables:

- application API
- background worker
- PostgreSQL
- object storage
- reverse proxy
- FoundryVTT module
- Discord bot or adapter

A modular monolith is preferred initially because the domains require strong transactional consistency and are still evolving. Service boundaries can become process boundaries later when operational evidence justifies it.

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
- Optimistic concurrency failures return a retriable conflict.
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
10. The initial implementation should remain a modular monolith unless evidence supports decomposition.
