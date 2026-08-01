# AI Assistant Operating Guide — D&D AI World Platform

**Purpose**: This is the primary operating manual for AI assistants (Claude, Copilot, etc.) working in this repository. It synthesizes the complete documentation set into actionable guidance.

**Scope**: Detailed examples, anti-patterns, and decision trees. For the short version, see [CLAUDE.md](../CLAUDE.md). Where the two disagree, the linked source document wins and both should be corrected.

---

## 📋 Table of Contents

1. [Quick Start: What You Need to Know First](#quick-start-what-you-need-to-know-first)
2. [Project Status and Context](#project-status-and-context)
3. [The 10 Non-Negotiable Architectural Rules](#the-10-non-negotiable-architectural-rules)
4. [Technology Stack Reference](#technology-stack-reference)
5. [Documentation Hierarchy](#documentation-hierarchy)
6. [Pre-Implementation Checklist](#pre-implementation-checklist)
7. [Database Design Quick Reference](#database-design-quick-reference)
8. [Domain Model Quick Reference](#domain-model-quick-reference)
9. [Entity Lifecycle Quick Reference](#entity-lifecycle-quick-reference)
10. [Common Anti-Patterns to Avoid](#common-anti-patterns-to-avoid)
11. [Development Workflow](#development-workflow)
12. [AI's Role in This System](#ais-role-in-this-system)

---

## Quick Start: What You Need to Know First

### What is this project?

A **persistent-world simulation platform** for tabletop RPGs (initially D&D 5e 2024). Key concept: worlds persist independently of campaigns, multiple campaigns can share timelines, and timelines can branch for alternate histories. PostgreSQL is the single source of truth.

### Critical: This is an architecture restart

⚠️ **DO NOT resurrect legacy patterns.** The repository previously contained code from a prior iteration (`Database/`, `src/lambda-functions/`, `DirectAPICalls/`, `PDFChatBot/`, and related build scripts) that predated the persistent-world model in this document set. It has been **removed**, along with the Terraform modules and environment wiring built specifically for it (`db_runner`, `lambda-api`, `lambda-with-build`).

- Legacy schema: flat `public`-schema tables, no timelines/worlds/knowledge model → removed, replaced by the design in `architecture/DATABASE_MODEL.md`
- Legacy Lambda functions → removed, will be rebuilt from scratch per current architecture
- Existing database content → will be dropped, no migration required
- What remains: the generic `terraform/modules/database` and `terraform/modules/secrets` modules (RDS, VPC, KMS, Secrets Manager) — not tied to the old schema, reasonable to build on

### Where to look when stuck

1. **Check current phase**: [docs/PLAN.md](PLAN.md) — are you working on something that's supposed to be implemented yet?
2. **Clarify concepts**: [docs/DOMAIN_MODEL.md](DOMAIN_MODEL.md) — what does this term actually mean?
3. **Schema design**: [docs/architecture/DATABASE_MODEL.md](architecture/DATABASE_MODEL.md) — how should this be modeled?
4. **Database rules**: [docs/DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md) — what naming/pattern should I use?
5. **Lifecycle operations**: [docs/ENTITY_LIFECYCLE.md](ENTITY_LIFECYCLE.md) — how do I create/modify/delete this?
6. **Architecture**: [docs/architecture/SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md) — where does this code belong?
7. **End-to-end flow**: [docs/architecture/DUNGEON_FLOW.md](architecture/DUNGEON_FLOW.md) — how does this fit into the vertical slice?

---

## Project Status and Context

### Vision

Persistent game worlds supporting:
- Multiple simultaneous campaigns
- Shared or branching timelines
- Persistent NPCs, locations, organizations, quests
- AI-assisted GM workflows and NPC portrayal
- FoundryVTT and Discord integration
- Long-term structured memory
- Future support for additional rulesets beyond D&D 5e

### Current Phase

**Architecture and domain-modeling stage**. See [docs/PLAN.md Phase 0-1](PLAN.md) for current deliverables.

### What's Being Built

The first major vertical slice: **dungeon exploration flow**
- Party navigates areas
- Discovers hidden information
- Changes persistent state (doors, traps, mechanisms)
- Advances quests
- Influences NPC knowledge
- Leaves consequences for other campaigns on the same timeline

See [docs/architecture/DUNGEON_FLOW.md](architecture/DUNGEON_FLOW.md) for the complete acceptance scenario.

---

## The 10 Non-Negotiable Architectural Rules

These hold for **every feature, every file, every migration**. If a task seems to require breaking one, **stop and flag it** — don't deviate quietly.

### 1. PostgreSQL is the only source of truth

✅ **Correct**: 
- Structured data in PostgreSQL tables
- Vector embeddings as derived/rebuildable indexes

❌ **Wrong**:
- "The embedding knows the NPC's personality, we can regenerate the DB from that"
- Storing canonical facts only in generated summaries or AI context

### 2. AI never writes canon directly

✅ **Correct**:
- AI generates `Proposed Change` → validation → (optional approval) → domain command → event → state update

❌ **Wrong**:
- AI agent directly updates `campaign.character_state` or `core.entities`
- "This is low-risk, let's skip the proposal step for this specific case"

Low-risk/automatic-approval categories must be **explicitly enumerated** in design docs, not invented ad hoc.

### 3. Clients never write directly to the database

✅ **Correct**:
- FoundryVTT/Discord/React UI → Application API → Command/Query Services → PostgreSQL

❌ **Wrong**:
- FoundryVTT module has database connection string and writes to `world.dungeons`
- "It's faster if Discord bot just updates this flag directly"

### 4. Class-table inheritance for entity subtypes

✅ **Correct**:
```sql
core.entities (entity_id PK)
  → character.characters (character_id PK = entity_id FK)
    → character.npcs (npc_id PK = character_id FK)
```
- Same UUID cascades through inheritance chain
- No new UUID per level

❌ **Wrong**:
- Using PostgreSQL `INHERITS`
- EAV (Entity-Attribute-Value) generic tables
- Generating new UUID at each subtype level

### 5. Definition, state, knowledge, and history are always separate

✅ **Correct**:
- `world.dungeons` (what it is) 
- `campaign.location_state` (current condition in timeline)
- `knowledge.entity_knowledge` (who knows what)
- `narrative.events` (what happened)

❌ **Wrong**:
- Adding `is_discovered` boolean to `world.dungeons`
- Storing "current HP" in `character.characters` instead of `campaign.character_state`
- Collapsing definition and state into one JSONB blob

### 6. State changes need causal events

✅ **Correct**:
- Event created → state updated → both committed atomically in one transaction

❌ **Wrong**:
- Update `campaign.area_connection_state` without a corresponding event
- "It's just a flag change, we don't need an event for this"

### 7. Timelines only inherit parent history up to branch point

✅ **Correct**:
- Timeline B branches from A at event #100
- Queries against Timeline B see events 1-100 from A, plus all B-specific events
- Timeline A events after #100 never appear in B

❌ **Wrong**:
- Querying all events from parent regardless of branch point
- "This quest was added to parent after the branch, but it's important so let's include it"

### 8. Knowledge is per-knower, never global

✅ **Correct**:
- `knowledge.entity_knowledge` (knower_id, knowledge_item_id, belief_strength)

❌ **Wrong**:
- `is_player_known` boolean on `world.area_features`
- "discovered" flag stored on the object itself

Discovery and belief live in the **knowledge domain**, scoped to who knows it.

### 9. Persistent world entities are archived, not deleted

✅ **Correct**:
- Set `archived_at` timestamp, keep the row
- Physical `DELETE` reserved for: unreferenced drafts, test fixtures, legal removal

❌ **Wrong**:
- `DELETE FROM character.npcs WHERE npc_id = 'some-important-character'`
- "They left the campaign, let's delete them"

See [docs/ENTITY_LIFECYCLE.md §14](ENTITY_LIFECYCLE.md) for complete rules.

### 10. No secrets in code or seed files

✅ **Correct**:
- AWS Secrets Manager for credentials and API keys
- Terraform reads secrets at apply-time (never hardcoded)
- Environment variables from secure sources

❌ **Wrong**:
- `DB_PASSWORD = "mypassword123"` in Python code
- API keys in seed SQL files or committed configs

---

## Technology Stack Reference

| Layer | Technology | Notes |
|-------|------------|-------|
| **Infrastructure** | AWS | RDS PostgreSQL, S3, Secrets Manager, KMS. Everything is deployed to and verified in AWS ([ADR 0008](adr/0008-aws-first-deployment-and-verification.md)); the pre-restart Lambda/API Gateway wiring was removed and is not coming back |
| **Compute** | ECS Fargate | API, background worker, Discord adapter, and one-off jobs (including migrations) run one shared image from ECR. Modular monolith, not Lambda-per-function. See [PLAN.md §30](PLAN.md#30-aws-deployment-plan-for-application-services) — planned, unbuilt |
| **IaC** | Terraform | Modules under `terraform/modules/`, environments under `terraform/environments/`. See [INFRASTRUCTURE.md](INFRASTRUCTURE.md) |
| **Database** | PostgreSQL 15.x | RDS, version pinned in Terraform; migrations via Alembic |
| **Backend** | Python 3.12+ | SQLAlchemy 2.x Core (not the ORM), psycopg 3, Pydantic v2 |
| **API** | FastAPI (REST) | Framework is pinned; the concrete endpoint shape is still deferred by [PLAN.md §27](PLAN.md#27-deferred-decisions) |
| **UI** | React | Web/admin client talking to REST API; not yet started |
| **Integrations** | FoundryVTT Module, Discord Bot, MCP Interface | All are clients, all go through application API |
| **Migrations** | Alembic | See [DATABASE_CONVENTIONS.md §25](DATABASE_CONVENTIONS.md#25-migration-conventions) |
| **Tooling** | uv, pytest against deployed AWS `dev` (testcontainers is a fallback only), ruff, mypy | Full rationale in [DEVELOPMENT.md §1](DEVELOPMENT.md#1-toolchain); AWS-verification policy in [PLAN.md §23.0](PLAN.md#230-aws-verification-policy) |

**Do not introduce new technologies** without explicit design review and documentation update.

---

## Documentation Hierarchy

All project documentation lives under `docs/` (except `README.md` and `CLAUDE.md` in repo root).

### Primary Documents (read these first)

| Document | Purpose | When to Read |
|----------|---------|--------------|
| [README.md](../README.md) | High-level project vision and architecture overview | First time in repo |
| [CLAUDE.md](../CLAUDE.md) | Concise operating instructions for Claude | Quick reference |
| [docs/PLAN.md](PLAN.md) | **Source of truth** for implementation phases and deliverables | Before starting any feature |
| [docs/DOMAIN_MODEL.md](DOMAIN_MODEL.md) | Conceptual vocabulary and domain boundaries | Before naming anything |
| [docs/DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md) | Hard rules for schema design | Before writing any schema |
| [docs/ENTITY_LIFECYCLE.md](ENTITY_LIFECYCLE.md) | Create/mutate/archive/delete workflows | Before implementing entity operations |
| [docs/DEVELOPMENT.md](DEVELOPMENT.md) | Toolchain, repo layout, migration and test workflow | Before writing any code |

### Architecture Documents

| Document | Purpose |
|----------|---------|
| [docs/architecture/SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md) | Service layering, command/query separation, transaction boundaries |
| [docs/architecture/DATABASE_MODEL.md](architecture/DATABASE_MODEL.md) | Logical schema: tables, ER diagrams, ownership rules |
| [docs/architecture/DUNGEON_FLOW.md](architecture/DUNGEON_FLOW.md) | End-to-end vertical slice (the acceptance test) |

### Supporting Documents

| Document | Purpose |
|----------|---------|
| [docs/INFRASTRUCTURE.md](INFRASTRUCTURE.md) | Deploying and operating the AWS infrastructure |
| [docs/adr/](adr/) | Architecture Decision Records — 0001–0007 are stubs whose decisions live in [PLAN.md §2](PLAN.md#2-architectural-decisions); [ADR 0008](adr/0008-aws-first-deployment-and-verification.md) (AWS-first deployment and verification) is written in full |
| [.github/copilot-instructions.md](../.github/copilot-instructions.md) | GitHub Copilot repository instructions |

---

## Pre-Implementation Checklist

**Before implementing ANY feature**, complete this checklist:

### Phase Check
- [ ] Check [docs/PLAN.md](PLAN.md) for current phase
- [ ] Verify this feature is in the current phase's deliverables
- [ ] Confirm exit criteria are clear

### Domain Understanding
- [ ] Look up concepts in [docs/DOMAIN_MODEL.md](DOMAIN_MODEL.md)
- [ ] Verify I'm not inventing new vocabulary that already exists
- [ ] Check if this crosses domain boundaries (requires coordination)

### Schema Design
- [ ] Review relevant sections in [docs/architecture/DATABASE_MODEL.md](architecture/DATABASE_MODEL.md)
- [ ] Confirm table placement in correct PostgreSQL schema
- [ ] Check [docs/DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md) for:
  - [ ] Naming conventions (snake_case, plural tables, entity-specific PK names)
  - [ ] Data types (TEXT vs VARCHAR, TIMESTAMPTZ, UUID, avoid JSONB for stable concepts)
  - [ ] Inheritance pattern (class-table, same UUID through chain)
  - [ ] Foreign key relationships
  - [ ] Index strategy

### Entity Lifecycle
- [ ] If creating/mutating/deleting entities: read [docs/ENTITY_LIFECYCLE.md](ENTITY_LIFECYCLE.md)
- [ ] Identify correct command/workflow
- [ ] Ensure atomic transaction for inheritance chain
- [ ] Plan event creation if state changes

### Architecture Placement
- [ ] Check [docs/architecture/SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md)
- [ ] Identify correct layer (API / Application / Domain / Data)
- [ ] Confirm not bypassing command/transaction pattern
- [ ] Ensure clients go through API, not direct to DB

### Vertical Slice Validation
- [ ] Review [docs/architecture/DUNGEON_FLOW.md](architecture/DUNGEON_FLOW.md)
- [ ] Confirm this feature supports the dungeon exploration flow
- [ ] Verify it doesn't break the acceptance scenario

### Final Checks
- [ ] Review [10 Non-Negotiable Rules](#the-10-non-negotiable-architectural-rules)
- [ ] Review [Anti-Patterns](#common-anti-patterns-to-avoid)
- [ ] Confirm no legacy code being extended
- [ ] Verify no secrets in code

---

## Database Design Quick Reference

### Naming Conventions

```
✅ CORRECT:
- lowercase snake_case everywhere
- Plural table names: core.entities, campaign.sessions
- Entity-specific PK: entity_id, character_id, timeline_id (NOT generic "id")
- FK columns use referenced PK name: world_id, entity_id
- Booleans: is_primary, has_been_triggered, can_share
- Timestamps: created_at, updated_at, archived_at
- Schema-qualified references: REFERENCES core.entities(entity_id)

❌ WRONG:
- CamelCase or PascalCase
- Singular table names: entity, session
- Generic "id" column
- Unqualified references: REFERENCES entities(entity_id)
- Ambiguous booleans: active, public
```

### PostgreSQL Schemas

```
core        → Worlds, entities, names, sources, tags, calendars, world time
security    → Users, roles, permissions, access control
rules       → Rulesets and reusable mechanical definitions
character   → Shared character mechanics, NPC and PC extensions
world       → Locations, organizations, items, relationships
campaign    → Timelines, campaigns, parties, sessions, mutable state
narrative   → Events, quests, objectives, encounters, story arcs
knowledge   → Facts, rumors, beliefs, discoveries
interaction → Actions, checks, resolutions
ai          → Agents, context, embeddings, proposals
audit       → Change history, approvals, validation
import      → Staging and review for imports
integration → External identifiers, sync state
```

**Never create application tables in `public`.**

### Data Type Rules

```sql
-- Primary keys
UUID PRIMARY KEY DEFAULT gen_random_uuid()

-- For class-table inheritance (reuse parent UUID)
character_id UUID PRIMARY KEY 
  REFERENCES core.entities(entity_id) ON DELETE CASCADE

-- Text
TEXT                          -- Prefer this
CHECK (char_length(code) <= 100)  -- Not VARCHAR(100)

-- Timestamps
TIMESTAMPTZ                   -- Real-world time
core.world_times             -- Fictional time (NOT TIMESTAMPTZ)

-- Numbers
SMALLINT                     -- Small bounded ratings (1-10)
INTEGER                      -- Counts, moderate values
BIGINT                       -- High-volume counters
NUMERIC                      -- Exact financial/fractional
DOUBLE PRECISION             -- Only when floating-point is acceptable

-- JSONB: use sparingly
-- ✅ Good: external API payload, ruleset-specific calculations, experimental features
-- ❌ Bad: all character stats, all NPC relationships, all quest objectives

-- Arrays: simple ordered scalars only
-- Don't use when elements need: identity, relationships, provenance, individual updates
```

### Lookup Tables vs ENUM

```sql
-- ✅ PREFERRED: Lookup table with stable codes
CREATE TABLE core.canon_statuses (
  canon_status_id UUID PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,  -- "draft", "proposed", "canon"
  display_name TEXT NOT NULL,
  sort_order INTEGER
);

-- ❌ AVOID: PostgreSQL ENUM (hard to evolve)
CREATE TYPE canon_status AS ENUM ('draft', 'proposed', 'canon');
```

### Class-Table Inheritance Pattern

```sql
-- Root: core.entities
CREATE TABLE core.entities (
  entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id UUID NOT NULL REFERENCES core.worlds(world_id),
  entity_type_id UUID NOT NULL REFERENCES core.entity_types(entity_type_id),
  canonical_name TEXT NOT NULL,
  canon_status_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Level 1: character.characters (reuses entity_id)
CREATE TABLE character.characters (
  character_id UUID PRIMARY KEY 
    REFERENCES core.entities(entity_id) ON DELETE CASCADE,
  species_id UUID,
  size_id UUID
);

-- Level 2: character.npcs (reuses character_id)
CREATE TABLE character.npcs (
  npc_id UUID PRIMARY KEY 
    REFERENCES character.characters(character_id) ON DELETE CASCADE,
  importance SMALLINT CHECK (importance BETWEEN 1 AND 10),
  simulation_level_id UUID
);

-- Same UUID flows through entire chain: entity_id = character_id = npc_id
```

### Definition vs State vs Knowledge vs History

```
┌─────────────────────────────────────────────────────┐
│ What it IS (definition)                             │
│ → world.dungeons, character.characters              │
│   Stable, shared across timelines                   │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ What's CURRENTLY TRUE (state)                       │
│ → campaign.location_state, campaign.character_state │
│   Mutable, per-timeline                             │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ Who KNOWS what (knowledge)                          │
│ → knowledge.entity_knowledge                        │
│   Per-knower, may be false/incomplete               │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│ What HAPPENED (history)                             │
│ → narrative.events                                  │
│   Causality and audit trail                         │
└─────────────────────────────────────────────────────┘
```

---

## Domain Model Quick Reference

### Top-Level Concepts

```
World
  ├─ Contains: Entities, Calendars, Rulesets, Timelines
  └─ Does NOT contain: Mutable campaign state (that's in Timelines)

Timeline
  ├─ One evolving history of a world
  ├─ Contains: Events, Mutable State, Campaigns
  ├─ May branch from another timeline at a specific event/time
  └─ Multiple campaigns can share one timeline

Campaign
  ├─ An organized game within a timeline
  ├─ Contains: Parties, Sessions, Participants, Permissions
  └─ Does NOT own: Separate copies of entities (references shared entities)

Entity
  ├─ Significant world object with stable UUID
  ├─ Types: Character, NPC, PC, Location, Organization, Item, Quest, Event, etc.
  └─ Participates in: Relationships, Events, Knowledge, Tags, Timeline State

Event
  ├─ Narratively meaningful occurrence
  ├─ Explains why timeline state changed
  └─ Examples: door opens, NPC dies, quest objective completed

Knowledge Item
  ├─ Structured statement (fact, rumor, secret, belief, prophecy)
  ├─ Separate from objective truth
  └─ Tracked per-knower (different entities have different beliefs)
```

### Entity Hierarchy Examples

```
core.entities
  ├─ character.characters
  │   ├─ character.npcs
  │   └─ character.player_characters
  ├─ world.locations
  │   ├─ world.settlements
  │   ├─ world.buildings
  │   ├─ world.dungeons
  │   └─ world.dungeon_areas
  ├─ world.organizations
  │   ├─ world.businesses
  │   ├─ world.governments
  │   └─ world.religious_organizations
  ├─ world.item_instances
  ├─ narrative.events
  ├─ narrative.quests
  └─ knowledge.knowledge_items
```

### Key Separations

| Concept | Belongs To | NOT In |
|---------|-----------|---------|
| Longsword (definition) | `rules.item_definitions` | `world.item_instances` |
| The Blade of Saint Orra (instance) | `world.item_instances` | `rules.item_definitions` |
| Goblin (species) | `rules.species` or `rules.creature_types` | `character.npcs` |
| Grik the Gatekeeper (NPC) | `character.npcs` | Rules tables |
| Door definition | `world.area_connections` | `campaign.area_connection_state` |
| Door is open | `campaign.area_connection_state` | `world.area_connections` |
| Party knows door exists | `knowledge.entity_knowledge` | `world.area_connections` |

---

## Entity Lifecycle Quick Reference

### Canon Status Flow

```
Draft → Proposed → Approved → Canon
  ↓         ↓          ↓         ↓
Rejected  Rejected   Draft    Superseded → Archived
  ↓
Deleted (rare)
```

### Lifecycle Status (operational)

- `pending` — Not yet usable
- `active` — Currently usable
- `inactive` — Temporarily disabled
- `archived` — Retired from active use (PREFERRED over deletion)
- `deleted` — Physically removed (rare: unreferenced drafts, test data, legal requirement)

### Creation Workflow

All entity creation goes through commands (never direct inserts).

Example: `CreateNpc` command

```
1. Validate world, entity type, permissions
2. Create provenance source
3. BEGIN TRANSACTION
4.   INSERT core.entities (entity_id, ...)
5.   INSERT character.characters (character_id = entity_id, ...)
6.   INSERT character.npcs (npc_id = character_id, ...)
7.   INSERT names, tags, relationships
8.   Optional: initial timeline state
9.   Record in audit.change_log
10. COMMIT
```

**Critical**: Same UUID flows through entire inheritance chain. No new UUID per level.

### Mutation Workflow

```
Command
  → Authorization
  → Validation
  → Interaction or administrative cause
  → Event (if persistent timeline consequence)
  → Typed state transition
  → Knowledge updates
  → Quest/objective evaluation
  → NPC goal/relationship reactions
  → Audit record
  → COMMIT atomically
```

State changes must reference a causal event or explicit administrative source.

### Archival vs Deletion

```
✅ ARCHIVAL (default for persistent entities):
SET archived_at = now()
Row remains, queryable with historical context

❌ DELETION (exceptional cases only):
DELETE FROM table WHERE ...
Reserved for:
  - Unreferenced drafts
  - Test fixtures
  - Legal/compliance removal
  - Rejected proposals that were never canonical
```

See [docs/ENTITY_LIFECYCLE.md §14](ENTITY_LIFECYCLE.md) for complete rules.

---

## Common Anti-Patterns to Avoid

### Database Anti-Patterns

❌ **Creating tables in `public` schema**
```sql
CREATE TABLE public.my_new_table ...  -- WRONG
```
✅ Use bounded schemas: `core.`, `character.`, `world.`, `campaign.`, etc.

---

❌ **Generic `id` column**
```sql
CREATE TABLE worlds (
  id UUID PRIMARY KEY ...  -- WRONG
)
```
✅ Entity-specific name:
```sql
CREATE TABLE core.worlds (
  world_id UUID PRIMARY KEY ...  -- CORRECT
)
```

---

❌ **Using `VARCHAR(n)` without reason**
```sql
description VARCHAR(255)  -- WRONG (why 255?)
```
✅ Use `TEXT` with optional constraint:
```sql
description TEXT
CHECK (char_length(description) <= 1000)  -- If limit is meaningful
```

---

❌ **Storing definition and state together**
```sql
CREATE TABLE dungeons (
  dungeon_id UUID,
  name TEXT,
  description TEXT,
  is_door_open BOOLEAN,      -- WRONG: this is timeline state
  current_power_level INT    -- WRONG: this is timeline state
)
```
✅ Separate definition and state:
```sql
-- Definition
CREATE TABLE world.dungeons (
  dungeon_id UUID PRIMARY KEY ...
  name TEXT,
  description TEXT
)

-- State (per timeline)
CREATE TABLE campaign.location_state (
  location_state_id UUID PRIMARY KEY,
  timeline_id UUID REFERENCES campaign.timelines,
  location_id UUID REFERENCES world.locations,
  state_data JSONB  -- or typed columns
)
```

---

❌ **Collapsing knowledge into object flags**
```sql
CREATE TABLE area_features (
  feature_id UUID,
  name TEXT,
  is_discovered BOOLEAN,     -- WRONG: discovered by whom?
  is_player_known BOOLEAN    -- WRONG: which player? which party?
)
```
✅ Knowledge in separate domain:
```sql
CREATE TABLE knowledge.entity_knowledge (
  knowledge_record_id UUID PRIMARY KEY,
  knower_entity_id UUID,      -- Who knows
  knowledge_item_id UUID,      -- What they know
  belief_strength SMALLINT,
  discovered_at TIMESTAMPTZ
)
```

---

❌ **State changes without events**
```sql
-- Just update state, no event
UPDATE campaign.area_connection_state 
SET is_open = true 
WHERE connection_id = '...';
```
✅ Event drives state change:
```sql
-- 1. Create event
INSERT INTO narrative.events (event_id, event_type_id, ...)
VALUES (...);

-- 2. Update state
UPDATE campaign.area_connection_state 
SET is_open = true, last_event_id = <event_id>
WHERE connection_id = '...';

-- Both in same transaction
```

---

❌ **AI directly mutating canonical state**
```python
# AI agent code
def on_npc_interaction(npc_id, message):
    db.execute(
        "UPDATE campaign.character_state SET mood = 'angry' WHERE character_id = ?",
        npc_id
    )  # WRONG
```
✅ AI creates proposals:
```python
def on_npc_interaction(npc_id, message):
    proposal = create_proposed_change(
        agent_id=self.agent_id,
        change_type='update_emotional_state',
        target_entity_id=npc_id,
        proposed_data={'mood': 'angry'},
        rationale="NPC insulted during conversation"
    )
    return proposal  # Goes through validation/approval
```

---

❌ **Using PostgreSQL `INHERITS`**
```sql
CREATE TABLE character.npcs (
  ...
) INHERITS (character.characters);  -- WRONG
```
✅ Class-table inheritance with FK:
```sql
CREATE TABLE character.npcs (
  npc_id UUID PRIMARY KEY 
    REFERENCES character.characters(character_id) ON DELETE CASCADE,
  ...
)
```

---

❌ **Clients writing directly to database**
```javascript
// FoundryVTT module
const result = await pg.query(
  "UPDATE world.dungeons SET description = $1 WHERE dungeon_id = $2",
  [newDesc, dungeonId]
);  // WRONG
```
✅ Clients call application API:
```javascript
const result = await fetch('/api/v1/dungeons/update', {
  method: 'POST',
  body: JSON.stringify({
    dungeonId: dungeonId,
    updates: { description: newDesc }
  })
});
```

---

### Code Anti-Patterns

❌ **Extending legacy code**
```python
# WRONG: adding to legacy lambda
with open('src/lambda-functions/old_npc_handler/app.py', 'a') as f:
    f.write("# New feature...")
```
✅ Create new implementation per current architecture

---

❌ **Hardcoding secrets**
```python
DB_PASSWORD = "mypassword123"  # WRONG
OPENAI_API_KEY = "sk-..."     # WRONG
```
✅ Use AWS Secrets Manager:
```python
import boto3
secrets = boto3.client('secretsmanager')
db_secret = secrets.get_secret_value(SecretId='prod/db/credentials')
```

---

❌ **Bypassing command pattern**
```python
# Direct state mutation in API handler
@app.route('/open-door', methods=['POST'])
def open_door():
    door_id = request.json['door_id']
    db.execute("UPDATE campaign.area_connection_state SET is_open = true WHERE ...")
    return "OK"  # WRONG
```
✅ Use command handlers:
```python
@app.route('/open-door', methods=['POST'])
def open_door():
    command = OpenDoorCommand(
        actor_id=request.json['character_id'],
        connection_id=request.json['door_id'],
        timeline_id=request.json['timeline_id']
    )
    result = command_handler.execute(command)
    return result
```

---

## Development Workflow

### Starting a New Feature

```
1. Check docs/PLAN.md
   ├─ Am I working on the right phase?
   └─ What are the exit criteria?

2. Review domain concepts
   ├─ docs/DOMAIN_MODEL.md for vocabulary
   └─ docs/architecture/DATABASE_MODEL.md for schema

3. Check lifecycle rules
   └─ docs/ENTITY_LIFECYCLE.md if creating/mutating entities

4. Design schema changes
   ├─ Follow docs/DATABASE_CONVENTIONS.md
   ├─ Place in correct PostgreSQL schema
   ├─ Use class-table inheritance if entity subtype
   └─ Separate definition/state/knowledge/history

5. Implement in correct layer
   ├─ docs/architecture/SYSTEM_ARCHITECTURE.md for layering
   ├─ Commands for mutations
   ├─ Queries for reads
   └─ Never let clients bypass API

6. Validate against vertical slice
   └─ docs/architecture/DUNGEON_FLOW.md acceptance scenario

7. Test and document
   ├─ Unit tests for domain logic
   ├─ Integration tests for commands
   └─ Update relevant docs if introducing new concepts
```

### Creating Database Migrations

```bash
# Using Alembic (per docs/DATABASE_CONVENTIONS.md §25)

# 1. Generate migration
alembic revision -m "create_character_npcs_table"

# 2. Edit migration file
# - Add schema-qualified table names
# - Follow naming conventions
# - Include constraints and indexes
# - Document purpose in docstring

# 3. Test migration
alembic upgrade head

# 4. Test rollback
alembic downgrade -1
alembic upgrade head

# 5. Commit migration file
git add database/migrations/versions/xxx_create_character_npcs_table.py
git commit -m "Add character.npcs table with class-table inheritance"
```

### Terraform Workflow

```bash
# Using existing module structure

# 1. Changes in modules
cd terraform/modules/<module_name>
# Edit main.tf, variables.tf, outputs.tf

# 2. Use in environment
cd ../../environments/dev
# Update main.tf to reference new module or variables

# 3. Plan
terraform plan -out=tfplan

# 4. Review
# - No hardcoded secrets
# - Resources in correct module
# - Variables properly propagated

# 5. Apply
terraform apply tfplan

# 6. Commit (never commit state or secrets)
git add terraform/modules/ terraform/environments/dev/*.tf
git commit -m "Add RDS configuration for character schema"
```

### Lambda Function Workflow

The pre-restart Lambda functions, build scripts (`scripts/build_lambda.ps1`, `scripts/build_layer.ps1`), and Terraform Lambda modules (`lambda-api`, `lambda-with-build`) have been removed along with the legacy code they packaged. There is currently no Lambda build tooling in the repo.

If/when Python services need to run as Lambda functions (per [docs/architecture/SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md) §17, the initial deployment target is a modular monolith, not Lambda-per-function), design fresh build/deploy tooling and a Terraform module against the current architecture rather than restoring the deleted ones from git history.

---

## AI's Role in This System

### What AI Agents Do

✅ **Allowed and Encouraged**:
- Read approved world data and assemble context
- Generate NPC dialogue and portrayal
- Summarize sessions
- Suggest consequences and world changes
- **Propose** new facts or state changes
- Detect inconsistencies
- Provide rules assistance
- Generate quest hooks and rumors

### What AI Agents Must NOT Do

❌ **Prohibited**:
- Directly mutate `core.entities` or any canonical world state
- Bypass the proposal → validation → approval flow
- Write to `campaign.*_state` tables without going through commands
- Create events without proper causality chain
- Declare generated content as canon without approval
- Store authoritative facts only in embeddings or prompts

### AI Mutation Flow (The Right Way)

```
Structured Context
    ↓
AI Output (proposal)
    ↓
Proposed Change Record (ai.proposed_changes)
    ↓
Validation (rules engine, consistency checks)
    ↓
Approval (automatic policy OR GM review)
    ↓
Domain Command (if approved)
    ↓
Event (if timeline change)
    ↓
Typed State Update (campaign.*_state)
    ↓
Audit Record (audit.change_log)
```

### Low-Risk Changes (May Auto-Approve)

Explicitly enumerated categories only:
- Adding conversational memory to NPC interaction log
- Revealing an **already-authored** hidden feature after successful check
- Updating objective progress (e.g., 3/3 → 2/3) when completion rule satisfied
- NPC emotional reaction within personality bounds

### High-Risk Changes (Require Approval)

- Killing major NPCs
- Destroying artifacts
- Changing city control
- Creating new deities
- Permanently failing major quests
- Declaring generated lore as canonical
- Adding new world entities not previously defined

---

## Quick Decision Tree

### "Should I extend this existing code?"

The pre-restart legacy directories have already been removed from the repo. For anything you do find:

```
Does it follow the current architecture docs (docs/, CLAUDE.md)?
    ├─ YES → OK to extend
    └─ NO → Refactor or rewrite per current architecture; don't restore
             deleted legacy patterns from git history
```

### "Where does this data belong?"

```
Is it about WHAT something is (stable definition)?
    └─ Definition tables: core.entities, world.dungeons, character.npcs

Is it about CURRENT STATE in a timeline?
    └─ State tables: campaign.character_state, campaign.location_state

Is it about WHO KNOWS what?
    └─ Knowledge tables: knowledge.entity_knowledge

Is it about WHAT HAPPENED?
    └─ Event tables: narrative.events

Is it a rules definition (reusable across worlds)?
    └─ Rules tables: rules.classes, rules.spells, rules.item_definitions
```

### "Can I add this flag to the entity table?"

```
Is it:
  - Timeline-specific state? → NO, use campaign.*_state
  - Knowledge/discovery? → NO, use knowledge.entity_knowledge
  - History/causality? → NO, use narrative.events
  - Stable definition? → YES, can add to entity definition table
```

### "Should I use JSONB for this?"

```
Is it:
  - External API payload snapshot? → YES
  - Ruleset-specific calculation details? → YES
  - Experimental feature structure? → MAYBE
  - Core domain concept (character stats, quest objectives, NPC relationships)? → NO, use proper tables
```

### "Should AI write this directly to the database?"

```
NO. AI always goes through:
  Proposal → Validation → (Approval if high-risk) → Command → Event → State Update
```

---

## Emergency "I'm Stuck" Guide

### Problem: "I don't know what this term means"

→ [docs/DOMAIN_MODEL.md](DOMAIN_MODEL.md) — search for the term

### Problem: "I don't know what phase we're in"

→ [docs/PLAN.md](PLAN.md) — check current deliverables

### Problem: "I don't know where this table should go"

→ [docs/architecture/DATABASE_MODEL.md](architecture/DATABASE_MODEL.md) — find similar table, check schema

### Problem: "I don't know what to name this column"

→ [docs/DATABASE_CONVENTIONS.md §4](DATABASE_CONVENTIONS.md) — naming conventions section

### Problem: "I don't know if I should use class-table inheritance"

→ Is it an entity subtype? YES → class-table inheritance
→ See [docs/DATABASE_CONVENTIONS.md §7](DATABASE_CONVENTIONS.md)

### Problem: "I don't know if this should be definition or state"

→ Ask: "Does this change per timeline?" 
   - YES → state (campaign schema)
   - NO → definition (core/world/character schema)

### Problem: "I don't know how to create/modify/delete this entity"

→ [docs/ENTITY_LIFECYCLE.md](ENTITY_LIFECYCLE.md) — find matching command

### Problem: "I don't know where this code belongs (API vs domain vs query)"

→ [docs/architecture/SYSTEM_ARCHITECTURE.md §5](architecture/SYSTEM_ARCHITECTURE.md) — layering section

### Problem: "I don't know if this breaks the vertical slice"

→ [docs/architecture/DUNGEON_FLOW.md](architecture/DUNGEON_FLOW.md) — validate against acceptance scenario

### Problem: "User asked me to extend legacy code"

→ Explain this is architecture restart, legacy code being replaced, create new per current docs

### Problem: "I'm about to break one of the 10 rules"

→ **STOP**. Flag it to user. Don't proceed without explicit design decision.

---

## Summary: Your Core Responsibilities

As an AI assistant working on this project:

1. ✅ **Always read the relevant docs before implementing**
   - This is not optional
   - The docs are detailed and authoritative
   - This guide points you to them

2. ✅ **Follow the 10 Non-Negotiable Rules**
   - No exceptions without explicit user approval
   - PostgreSQL is truth
   - AI proposes, doesn't own canon
   - Clients go through API
   - Class-table inheritance
   - Separate definition/state/knowledge/history
   - Events cause state changes
   - Timelines branch correctly
   - Knowledge is per-knower
   - Archive, don't delete
   - No secrets in code

3. ✅ **Check current phase before implementing**
   - docs/PLAN.md is the source of truth
   - Don't implement Phase 3 features when we're in Phase 1

4. ✅ **Don't extend legacy code**
   - This is an architecture restart
   - Legacy dirs are being replaced
   - Create new implementations per current architecture

5. ✅ **When uncertain, stop and ask**
   - Better to clarify than build wrong
   - Architecture changes need explicit decisions
   - User has full context, you don't need to guess

6. ✅ **Update docs when introducing new concepts**
   - These docs are meant to stay current
   - If you add a new domain concept, update the relevant doc
   - Keep this guide and CLAUDE.md in sync with architecture evolution

---

**End of AI Assistant Operating Guide**

For questions, clarifications, or architecture decisions not covered here, consult the user.
