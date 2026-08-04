# D&D AI World Platform — GitHub Copilot Instructions

**Purpose**: Concise coding and architecture rules for GitHub Copilot working in this repository.

**Operating instructions**: Start with [CLAUDE.md](../CLAUDE.md). Search the `docs/` folder by task and read only relevant sections. [docs/AI_ASSISTANT_GUIDE.md](../docs/AI_ASSISTANT_GUIDE.md) is an on-demand example catalog, not startup context.

---

## ⚠️ Critical: Architecture Restart

This repository underwent a **complete architecture restart**.

The pre-restart legacy code has already been **removed**: the old flat `Database/` schema, `src/lambda-functions/`, `DirectAPICalls/`, `PDFChatBot/`, the old Lambda build scripts, and the Terraform modules/environment wiring built specifically for them (`db_runner`, `lambda-api`, `lambda-with-build`, `db-schema-introspect`, `query-runner`). Don't restore any of this from git history as "existing convention" — build against the current docs instead.

Any existing database content will be dropped; no legacy schema or API compatibility is required.

**What remains**: the generic `terraform/modules/database` and `terraform/modules/secrets` modules (RDS, VPC, KMS, Secrets Manager) and `terraform/environments/` — infrastructure organization that isn't tied to the old schema.

**Current implementation status**: Phases 1 through 5 are complete ([../docs/PHASE4_REMAINING_ISSUES.md](../docs/PHASE4_REMAINING_ISSUES.md) and [../docs/PHASE5_REMAINING_ISSUES.md](../docs/PHASE5_REMAINING_ISSUES.md) are both closed historical records). Both [Phase 6](../docs/PLAN.md#phase-6-events-and-interactions) entry gates (repository context modularization, Phase 5 correctness) are closed, pending confirmation from the CI run for the pass that closed the second one — see [../docs/PHASE5_VERIFICATION.md § Fifth exit review corrections](../docs/PHASE5_VERIFICATION.md#fifth-exit-review-corrections-2026-08-03). No API or UI exists yet.

---

## Project Overview

**Persistent-world simulation platform** for tabletop RPGs (D&D 5e 2024 initially):
- Worlds persist independently of campaigns
- Multiple campaigns can share timelines
- Timelines can branch for alternate histories
- PostgreSQL is the single source of truth
- AI proposes changes but never owns canonical state
- FoundryVTT and Discord integrations

---

## 11 Non-Negotiable Architectural Rules

1. **PostgreSQL is the only source of truth** (not embeddings/caches)
2. **AI never writes canon directly** (proposes → validates → approves → commits)
3. **Clients never write directly to database** (always through application API)
4. **Class-table inheritance for entity subtypes** (same UUID through inheritance chain)
5. **Definition/state/knowledge/history are always separate** (different tables/schemas)
6. **State changes need causal events** (event + state update in same transaction)
7. **Timelines only inherit parent history up to branch point** (no leakage after branch)
8. **Knowledge is per-knower, never global** (no `is_discovered` flags on entities)
9. **Persistent entities are archived, not deleted** (set `archived_at`, keep row)
10. **No secrets in code or seed files** (AWS Secrets Manager only)
11. **Deploy and verify in AWS** (RDS for database tests; ECS Fargate for deployables; local containers are fallback only)

**If a task requires breaking a rule: STOP and flag it.**

---

## Technology Stack

- **Infrastructure**: AWS (RDS PostgreSQL, S3, Secrets Manager, KMS). Initial deployment target is a modular monolith — not Lambda-per-function
- **IaC**: Terraform (modules under `terraform/modules/`, environments under `terraform/environments/`)
- **Database**: PostgreSQL 15.x on RDS; migrations via Alembic
- **Backend**: Python 3.12+, SQLAlchemy 2.x **Core** (not the ORM), psycopg 3, Pydantic v2
- **API**: FastAPI (REST); endpoint shape still deferred by `docs/PLAN.md` §27
- **UI**: React (web/admin client)
- **Tooling**: uv, pytest against deployed AWS `dev`, ruff, mypy. Testcontainers is a fallback only when AWS is genuinely unreachable
- **Integrations**: FoundryVTT module, Discord bot, MCP interface (all clients, all through API)

Full rationale: [docs/DEVELOPMENT.md §1](../docs/DEVELOPMENT.md#1-toolchain). Do not introduce alternatives.

---

## Documentation Routing (Use Task-Scoped Context)

All docs live under `docs/`. Only `README.md` and `CLAUDE.md` belong in the repository root.

Do not load the whole documentation set before every feature. Start with `CLAUDE.md`, identify the phase/domain/change type, search headings or keywords, then read only:

1. **`docs/PLAN.md` §23.0–23.1 and the current phase entry** — deliverables and exit criteria.
2. **Affected sections of `docs/DOMAIN_MODEL.md` and `docs/architecture/DATABASE_MODEL.md`** — vocabulary and schema.
3. **Mechanism-specific sections of `docs/DATABASE_CONVENTIONS.md`** — for example ranges, triggers, migrations, grants, or tests.
4. **A matching workflow document only when applicable** — `ENTITY_LIFECYCLE.md` for entity operations, `SYSTEM_ARCHITECTURE.md` for application layers/transactions, `DUNGEON_FLOW.md` for cross-domain scenario work, and `DEVELOPMENT.md` for the relevant mechanics plus §10.

Expand to a full document only for a cross-cutting reconciliation or when targeted sections leave an unresolved conflict. Do not preload completed-phase history or `AI_ASSISTANT_GUIDE.md`.

**Onboarding**: `docs/CONTRIBUTING.md` — **Deploying**: `docs/QUICKSTART.md` + `docs/CHECKLIST.md` — **Reference**: `docs/INFRASTRUCTURE.md`

**For a specific worked example**: Search `docs/AI_ASSISTANT_GUIDE.md` and open only the matching section.

---

## PostgreSQL Schema Organization

**Never create tables in `public` schema.**

Use bounded schemas:
- **`core`**: worlds, entities, names, sources, tags, calendars, world time
- **`security`**: users, roles, permissions, access control
- **`rules`**: rulesets and reusable mechanical definitions
- **`character`**: shared character mechanics, NPC and PC extensions
- **`world`**: locations, organizations, items, relationships
- **`campaign`**: timelines, campaigns, parties, sessions, **mutable state**
- **`narrative`**: events, quests, objectives, encounters
- **`knowledge`**: facts, rumors, beliefs, discoveries
- **`interaction`**: actions, checks, resolutions
- **`ai`**: agents, context, embeddings, proposals
- **`audit`**: change history, approvals, validation
- **`import`**: staging and review
- **`integration`**: external identifiers, sync state

---

## Database Naming Conventions

```sql
-- ✅ CORRECT:
CREATE TABLE character.npcs (
  npc_id UUID PRIMARY KEY 
    REFERENCES character.characters(character_id) ON DELETE CASCADE,
  importance SMALLINT CHECK (importance BETWEEN 1 AND 10),
  simulation_level_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ❌ WRONG:
CREATE TABLE public.NPC (
  id UUID PRIMARY KEY,  -- Generic "id"
  importance VARCHAR(50),  -- Should be SMALLINT or lookup FK
  is_discovered BOOLEAN,  -- Knowledge belongs in knowledge schema
  current_location_id UUID  -- State belongs in campaign schema
);
```

**Key rules**:
- lowercase `snake_case` everywhere
- Plural table names: `core.entities`, `campaign.sessions`
- Entity-specific PK names: `entity_id`, `character_id`, `timeline_id` (NOT generic `id`)
- FK columns use referenced PK name: `world_id`, `entity_id`
- Booleans: `is_primary`, `has_been_triggered`, `can_share`
- Timestamps: `created_at`, `updated_at`, `archived_at`
- Always schema-qualified: `REFERENCES core.entities(entity_id)`
- TEXT over VARCHAR(n) unless max length is real business rule
- TIMESTAMPTZ for real-world time, `core.world_times` for fictional time
- Use lookup tables with stable codes, not PostgreSQL ENUM

---

## Class-Table Inheritance Pattern

```sql
-- Root entity
CREATE TABLE core.entities (
  entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id UUID NOT NULL REFERENCES core.worlds(world_id),
  entity_type_id UUID NOT NULL REFERENCES core.entity_types(entity_type_id),
  canonical_name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Subtype reuses parent UUID
CREATE TABLE character.characters (
  character_id UUID PRIMARY KEY 
    REFERENCES core.entities(entity_id) ON DELETE CASCADE,
  species_id UUID,
  size_id UUID
);

-- Further subtype reuses character UUID
CREATE TABLE character.npcs (
  npc_id UUID PRIMARY KEY 
    REFERENCES character.characters(character_id) ON DELETE CASCADE,
  importance SMALLINT CHECK (importance BETWEEN 1 AND 10),
  simulation_level_id UUID
);
```

**Same UUID flows through entire chain**: `entity_id = character_id = npc_id`

**Do NOT** use PostgreSQL `INHERITS` for core domain tables.

---

## Definition vs State vs Knowledge vs History

```
DEFINITION (what it IS)
  └─ world.dungeons, character.characters
     Stable, shared across timelines

STATE (what's CURRENTLY TRUE)
  └─ campaign.location_state, campaign.character_state
     Mutable, per-timeline

KNOWLEDGE (who KNOWS what)
  └─ knowledge.entity_knowledge
     Per-knower, may be false/incomplete

HISTORY (what HAPPENED)
  └─ narrative.events
     Causality and audit trail
```

**Never mix these.** No `is_discovered` on entity definitions. No `current_hp` on character definitions.

---

## Key Separations

| Concept | Belongs To | NOT In |
|---------|-----------|---------|
| Longsword (definition) | `rules.item_definitions` | `world.item_instances` |
| "Blade of Saint Orra" (instance) | `world.item_instances` | `rules.item_definitions` |
| Goblin (species) | `rules.species` or `rules.creature_types` | `character.npcs` |
| "Grik the Gatekeeper" (NPC) | `character.npcs` | Rules tables |
| Door definition | `world.area_connections` | `campaign.area_connection_state` |
| Door is currently open | `campaign.area_connection_state` | `world.area_connections` |
| Party discovered door | `knowledge.entity_knowledge` | Neither of above |

---

## Common Anti-Patterns to Avoid

### ❌ Storing state on definition
```sql
CREATE TABLE world.dungeons (
  dungeon_id UUID,
  name TEXT,
  is_door_open BOOLEAN  -- WRONG: timeline state
);
```
✅ Separate state table: `campaign.location_state`

### ❌ Knowledge as object flags
```sql
CREATE TABLE world.area_features (
  feature_id UUID,
  is_discovered BOOLEAN  -- WRONG: by whom?
);
```
✅ Knowledge in separate domain: `knowledge.entity_knowledge(knower_id, knowledge_item_id)`

### ❌ State changes without events
```sql
UPDATE campaign.area_connection_state SET is_open = true;  -- WRONG
```
✅ Create event first, then update state in same transaction

### ❌ AI directly mutating state
```python
db.execute("UPDATE campaign.character_state SET mood = 'angry' ...")  -- WRONG
```
✅ AI creates proposal → validation → approval → command → event → state update

### ❌ Clients writing to database
```javascript
await pg.query("UPDATE world.dungeons SET description = $1 ...")  -- WRONG
```
✅ Clients call application API

---

## Entity Lifecycle

**All entity creation goes through commands** (never direct inserts).

Example: `CreateNpc` command
```
1. BEGIN TRANSACTION
2. INSERT core.entities (entity_id, ...)
3. INSERT character.characters (character_id = entity_id, ...)
4. INSERT character.npcs (npc_id = character_id, ...)
5. INSERT names, tags, relationships
6. Record in audit.change_log
7. COMMIT
```

**Archival (default)**: `SET archived_at = now()`, keep row  
**Deletion (rare)**: Only for unreferenced drafts, test data, legal removal

See `docs/ENTITY_LIFECYCLE.md` for complete workflows.

---

## AI's Role

**AI agents do**:
- Read approved world data and assemble context
- Generate NPC dialogue and portrayal
- Suggest consequences and changes
- **Propose** new facts (never write directly)

**AI agents must NOT**:
- Directly mutate `core.entities` or canonical state
- Write to `campaign.*_state` without commands
- Bypass proposal → validation → approval flow

**Correct AI flow**:
```
Context → AI Output → Proposed Change → Validation → Approval (if high-risk) 
  → Command → Event → State Update → Audit
```

---

## Development Workflow

### Starting a feature
1. Check `docs/PLAN.md` for current phase
2. Review `docs/DOMAIN_MODEL.md` for concepts
3. Check `docs/architecture/DATABASE_MODEL.md` for schema
4. Follow `docs/DATABASE_CONVENTIONS.md` for design
5. Implement in correct layer per `docs/architecture/SYSTEM_ARCHITECTURE.md`
6. Validate against `docs/architecture/DUNGEON_FLOW.md` acceptance scenario

### Database migrations
```bash
uv run alembic -c database/alembic.ini revision -m "create character npcs table"
# Edit the revision: schema-qualified names, table/column comments, FK indexes.
# Autogenerate misses partial indexes, check constraints, triggers, and comments — always review.
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini downgrade -1   # verify rollback before committing
```

### Quality gate
```bash
uv run ruff format . && uv run ruff check . --fix && uv run mypy src && uv run pytest
```

### Terraform
```bash
cd terraform/environments/dev
terraform plan -out=tfplan
# Review: no hardcoded secrets, correct module
terraform apply tfplan
# Never commit state or secrets
```

---

## Quick Decision Tree

**"Where does this data belong?"**
- Stable definition? → `core`, `world`, `character` schema
- Current timeline state? → `campaign` schema
- Who knows what? → `knowledge` schema
- What happened? → `narrative.events`
- Rules definition? → `rules` schema

**"Should I use JSONB?"**
- External API payload? → YES
- Core domain concept (character stats, quest objectives)? → NO (use proper tables)

**"Can I add this flag to entity table?"**
- Timeline-specific state? → NO (use `campaign.*_state`)
- Knowledge/discovery? → NO (use `knowledge.entity_knowledge`)
- Stable definition? → YES

---

## Emergency Guide

- **Don't know term?** → `docs/DOMAIN_MODEL.md`
- **Don't know current phase?** → `docs/PLAN.md`
- **Don't know schema location?** → `docs/architecture/DATABASE_MODEL.md`
- **Don't know naming convention?** → `docs/DATABASE_CONVENTIONS.md` §4
- **Don't know entity workflow?** → `docs/ENTITY_LIFECYCLE.md`
- **Don't know code layer?** → `docs/architecture/SYSTEM_ARCHITECTURE.md` §5
- **Don't know which library/tool?** → `docs/DEVELOPMENT.md` §1
- **Don't know where a file goes?** → `docs/DEVELOPMENT.md` §2
- **Deploying or debugging AWS?** → `docs/INFRASTRUCTURE.md`
- **User asks to extend legacy code?** → Explain restart, create new per current architecture
- **About to break one of 11 rules?** → STOP, flag to user

---

## Summary

1. ✅ **Route context before implementing** (`CLAUDE.md`, then the current `docs/PLAN.md` phase and affected topic sections)
2. ✅ **Follow 11 Non-Negotiable Rules** (no exceptions without approval)
3. ✅ **Don't extend legacy code** (create new per current architecture)
4. ✅ **PostgreSQL is truth, AI proposes, clients use API**
5. ✅ **Class-table inheritance, same UUID through chain**
6. ✅ **Separate definition/state/knowledge/history**
7. ✅ **When uncertain: stop and consult docs or user**

**For a missing worked example only**: Search `docs/AI_ASSISTANT_GUIDE.md` and open the matching section.

---

**Current phase**: always check `docs/PLAN.md` §23 rather than trusting a note here.
**Repository**: github.com/NemesisGhost/dnd_ai
