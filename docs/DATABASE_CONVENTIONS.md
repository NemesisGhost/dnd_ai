# PostgreSQL Database Conventions

## 1. Purpose

This document defines database conventions for the persistent world platform.

These conventions apply to:

- PostgreSQL schemas
- tables
- columns
- constraints
- indexes
- inheritance patterns
- temporal data
- migrations
- seed data
- audit data
- AI-generated changes
- integrations

The goals are consistency, maintainability, predictable querying, safe evolution, and clear support for timelines, world state, and AI-assisted game management.

---

## 2. PostgreSQL version and extensions

### 2.1 Supported PostgreSQL version

**PostgreSQL 18.x.** One major version, pinned everywhere it runs:

| Where | Pinned by |
|---|---|
| Local development server | Each developer's install — [DEVELOPMENT.md §3.1](DEVELOPMENT.md#31-postgresql) |
| Self-hosted deployment (official) | `postgres:18.4` image in `compose.yaml` |
| CI | `postgres:18.4` GitHub Actions service container ([DEVELOPMENT.md §8](DEVELOPMENT.md#8-continuous-integration)) |
| AWS `dev` / `staging` / `prod` (optional, legacy) | `postgres_version` in `terraform/modules/database`, if deployed |

The major version was 15.x until 2026-08-07, when the development loop moved to a local server ([ADR 0011](adr/0011-local-first-development-aws-verified-delivery.md), later superseded by [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)) and 18.x became the version every target could share. `dev` was replaced with a fresh PostgreSQL 18.4 instance on 2026-08-08 to close that gap ([POSTGRES18_UPGRADE_PLAN.md](POSTGRES18_UPGRADE_PLAN.md)); CI's containerized target and `compose.yaml` were both pinned to that same `18.4` when self-hosted Docker became the default deployment topology.

**A local server on a different major version than what CI runs is a defect, not a preference.** It produces green local runs that fail CI, and it reintroduces the divergence between what is verified and what is deployed that [ADR 0008](adr/0008-aws-first-deployment-and-verification.md) was originally written to eliminate — now addressed by [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md) verifying the same self-hosted target it deploys. Match the version; do not use whatever is already installed.

Do not rely on behavior that differs across PostgreSQL major versions without an automated compatibility test.

### 2.2 Required extensions

Foundation extensions:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

Required when Phase 3 introduces temporal exclusion constraints:

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
```

`btree_gist` supplies GiST operator classes for scalar keys such as UUID. It must be enabled in the same migration, before the first constraint combining UUID equality with range overlap. Do not assume it is present merely because the target PostgreSQL version supports range types.

Later optional extension:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

`vector` is used for derived embedding search. Core relational operations must continue to function when vector indexing is unavailable.

### 2.3 Extension ownership

Extensions are installed through migrations or infrastructure bootstrap under a controlled database owner. Application users must not have extension-management permissions.

`pgcrypto`, `pg_trgm`, and `btree_gist` are all **trusted** extensions on PostgreSQL 13+ (verified as trusted on the AWS `dev` instance, both on 15.18 originally and again on 18.4 after the [POSTGRES18_UPGRADE_PLAN.md](POSTGRES18_UPGRADE_PLAN.md) replacement — the full `001_bootstrap` migration and later extension-adding revisions all succeeded without `rds_superuser`). A non-superuser may therefore install them with only `CREATE` on the database — the roles never need `rds_superuser`.

The same extensions must be installable on a local development server, since the identical `001_bootstrap` revision runs there ([DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup)). A stock local install provides all three in `contrib`; a missing one shows up as a bootstrap failure on the first `alembic upgrade head`, not as a subtle divergence later.

That privilege belongs to **`migration_owner`**, not to the connecting login role. Revision `001_bootstrap` ends with `SET ROLE migration_owner`, and `env.py` issues the same `SET ROLE` on connect, so every later revision runs as `migration_owner`; a `CREATE EXTENSION` in one of them fails with `permission denied to create extension` unless that role holds database-level `CREATE`. The bootstrap grants it for exactly this reason. A migration that adds an extension must not assume the connecting user's privileges apply to it.

---

## 3. Schema conventions

Use PostgreSQL schemas to establish bounded domains.

Approved schemas:

```text
core
security
rules
character
world
campaign
narrative
knowledge
interaction
ai
audit
import
integration
```

### 3.1 Public schema

Do not create application tables in `public`.

Revoke unnecessary creation privileges on `public` in non-development environments.

### 3.2 Cross-schema references

Cross-schema foreign keys are allowed and expected. Always schema-qualify table, function, type, and sequence references in migrations and stored code.

Preferred:

```sql
REFERENCES core.entities(entity_id)
```

Avoid:

```sql
REFERENCES entities(entity_id)
```

### 3.3 Search path

Do not depend on a broad mutable `search_path` for application correctness.

Stored functions must either:

- use schema-qualified references, or
- set a restricted `search_path` explicitly.

---

## 4. Naming conventions

### 4.1 General naming

Use lowercase `snake_case` for all database identifiers.

Use full descriptive names unless an abbreviation is universally understood in the project.

Preferred:

```text
character_ability_scores
relationship_participants
world_time_id
```

Avoid:

```text
char_abs
rel_parts
wt_id
```

### 4.2 Table names

Use plural table names.

Examples:

```text
core.entities
character.characters
campaign.sessions
narrative.events
```

### 4.3 Primary keys

Use singular entity-specific primary-key names:

```text
worlds.world_id
entities.entity_id
characters.character_id
events.event_id
```

Do not use a generic `id` column.

### 4.4 Foreign keys

Foreign-key columns use the referenced primary-key name whenever practical.

Examples:

```text
world_id
entity_id
timeline_id
character_id
```

When a table references the same parent more than once, use a semantic prefix:

```text
parent_timeline_id
source_entity_id
target_entity_id
from_area_id
to_area_id
```

### 4.5 Boolean columns

Boolean columns begin with `is_`, `has_`, `can_`, or `should_`.

Examples:

```text
is_primary
is_public
has_been_triggered
can_share
```

Avoid ambiguous booleans such as `active` or `public`.

### 4.6 Timestamp columns

Use consistent names:

```text
created_at
updated_at
archived_at
recorded_at
approved_at
started_at
ended_at
```

Real-world timestamps use `TIMESTAMPTZ`.

### 4.7 World-time columns

Fictional time references use names such as:

```text
world_time_id
effective_from_world_time_id
effective_to_world_time_id
branch_world_time_id
```

Do not store fictional dates in `TIMESTAMPTZ`.

### 4.8 Codes

Lookup tables should contain a stable machine-readable `code`.

Examples:

```text
canon
proposed
active
completed
```

Codes are lowercase `snake_case`, unique, and treated as stable API values.

Display names may change; codes should not change after release without a migration and compatibility plan.

---

## 5. Data types

### 5.1 UUID primary keys

Use `UUID` primary keys for persistent domain records.

Default generation:

```sql
UUID PRIMARY KEY DEFAULT gen_random_uuid()
```

For class-table inheritance, subtype primary keys do not generate a new UUID. They reuse the parent identifier.

```sql
character_id UUID PRIMARY KEY
    REFERENCES core.entities(entity_id)
    ON DELETE CASCADE
```

### 5.2 Integer identity keys

Integer identity keys may be used for high-volume internal append-only records when they do not require globally portable identity.

Examples may include:

- audit detail rows
- embedding chunks
- telemetry

Use generated identity columns rather than serial:

```sql
BIGINT GENERATED ALWAYS AS IDENTITY
```

### 5.3 Text

Prefer `TEXT` over arbitrary `VARCHAR(n)` unless the maximum length is a real business rule.

Use constraints where a maximum is meaningful.

```sql
CHECK (char_length(code) <= 100)
```

Do not use `VARCHAR(50)` merely because a value is expected to be short.

### 5.4 Timestamps

Use `TIMESTAMPTZ` for real-world times.

Do not use `TIMESTAMP WITHOUT TIME ZONE` for operational records.

### 5.5 Dates

Use PostgreSQL `DATE` only for real-world calendar dates that do not require a time zone.

Use `core.world_times` for fictional dates.

### 5.6 Numeric values

Use:

- `SMALLINT` for small bounded ratings
- `INTEGER` for counts and moderate values
- `BIGINT` for high-volume counters
- `NUMERIC` for exact financial or fractional values
- `DOUBLE PRECISION` only where floating-point behavior is acceptable

### 5.7 JSONB

Use `JSONB` only when:

- the structure is genuinely variable
- properties are experimental or ruleset-specific
- the data is rarely queried by individual fields
- the JSON is a snapshot or external payload

Do not use JSONB to avoid modeling stable domain concepts.

Acceptable examples:

- external API payload snapshot
- ruleset-specific calculation details
- proposed AI command payload
- uncommon connection requirements

Poor examples:

- all character statistics
- all NPC relationships
- all quest objectives
- all current location state

### 5.8 Arrays

PostgreSQL arrays may be used for simple ordered scalar values when no metadata is needed.

Do not use arrays when elements require identity, relationships, provenance, visibility, or individual updates.

### 5.9 Enumerations

Prefer lookup tables with stable codes over PostgreSQL `ENUM` for domain values expected to evolve.

PostgreSQL `ENUM` may be used only for tightly constrained infrastructure states unlikely to change.

---

## 6. Shared domains and checks

Create reusable PostgreSQL domains for repeated constraints.

```sql
CREATE DOMAIN core.rating_1_10 AS smallint
CHECK (VALUE BETWEEN 1 AND 10);

CREATE DOMAIN core.percentage_0_100 AS smallint
CHECK (VALUE BETWEEN 0 AND 100);

CREATE DOMAIN core.nonnegative_integer AS integer
CHECK (VALUE >= 0);
```

Potential later domains:

- normalized code
- dice expression
- world-time sort value
- positive quantity

Domains must remain simple. Complex context-dependent validation belongs in constraints or service logic.

---

## 7. Table-inheritance conventions

### 7.1 Default strategy

Use class-table inheritance.

Example:

```sql
CREATE TABLE core.entities (
    entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    world_id UUID NOT NULL REFERENCES core.worlds(world_id),
    entity_type_id UUID NOT NULL REFERENCES core.entity_types(entity_type_id),
    canonical_name TEXT NOT NULL
);

CREATE TABLE character.characters (
    character_id UUID PRIMARY KEY
        REFERENCES core.entities(entity_id)
        ON DELETE CASCADE
);

CREATE TABLE character.npcs (
    npc_id UUID PRIMARY KEY
        REFERENCES character.characters(character_id)
        ON DELETE CASCADE
);
```

### 7.2 Native PostgreSQL inheritance

Do not use `INHERITS` for core domain tables without an approved architecture decision record.

Reasons:

- parent foreign keys do not provide normal polymorphic guarantees
- uniqueness does not automatically span descendants
- migrations and ORMs may behave inconsistently
- subtype enforcement becomes harder to understand

### 7.3 Subtype creation

Create inherited entities through commands, service-layer transactions, or stored functions.

Do not allow clients to independently insert parent and subtype rows through unrelated API calls.

### 7.4 Subtype consistency

The system must validate that `core.entities.entity_type_id` matches the subtype row.

This may be enforced through:

- creation functions
- deferred constraint triggers
- validation tests

The implementation should avoid one trigger per subtype when a maintainable centralized solution is possible.

This consistency check must hold from both directions: validating a subtype row against its entity's type when the subtype row is written (`core.enforce_entity_subtype()`) is not sufficient on its own, since nothing then stops `core.entities.entity_type_id` itself from being changed to a type that no longer requires an already-existing subtype row. `core.enforce_entity_type_change()` (revision 048) is the parent-side counterpart — a generic trigger driven by `core.entity_types.required_subtype_table`/`required_subtype_pk_column` metadata rather than a name per subtype. Any migration that sets `required_subtype_table` on a new `core.entity_types` row must set `required_subtype_pk_column` alongside it (a paired `CHECK` enforces this) so that trigger can find the subtype row without guessing its primary-key column name from the table name.

### 7.5 Delete behavior

Deleting a subtype may cascade to subtype-owned dependent rows.

Deleting the root entity is exceptional. Prefer archival for persistent world entities.

---

## 8. Primary keys, uniqueness, and natural keys

### 8.1 Primary keys

Every persistent table must have a primary key unless it is a deliberate pure junction table with a documented composite key.

### 8.2 Unique constraints

Use database uniqueness constraints for true invariants.

Examples:

```sql
UNIQUE (world_id, code)
UNIQUE (timeline_id, entity_id)
UNIQUE (ruleset_version_id, code)
```

### 8.3 Partial unique indexes

Use partial unique indexes for conditional uniqueness.

Example: one active primary portrayal profile per NPC.

```sql
CREATE UNIQUE INDEX ux_npc_portrayal_profiles_current
ON character.npc_portrayal_profiles (npc_id)
WHERE is_current;
```

### 8.4 Case-insensitive uniqueness

Use normalized values or expression indexes.

```sql
CREATE UNIQUE INDEX ux_entity_types_code_ci
ON core.entity_types (lower(code));
```

Do not assume application-side case normalization is sufficient.

### 8.5 Slugs and external identifiers

Slugs are user-facing locators, not primary keys.

External identifiers must be stored in integration mapping tables and must not replace internal UUIDs.

---

## 9. Foreign-key conventions

### 9.1 Foreign keys are required

Use foreign keys for relational integrity unless a documented reason prevents it.

### 9.2 Delete actions

Choose delete actions deliberately.

Use `ON DELETE CASCADE` for true dependent records, such as:

- subtype rows
- portrayal-profile fragments owned only by the profile
- current-state child resources

Use `ON DELETE RESTRICT` or default behavior for shared and historical records.

Use `ON DELETE SET NULL` only when the record remains meaningful without the reference.

### 9.3 Persistent entities

Avoid physically deleting important world entities after real data exists.

Use:

```text
lifecycle_status_id
archived_at
```

Historical events, relationships, knowledge, and imported sources should remain valid.

### 9.4 Polymorphic references

Prefer foreign keys to `core.entities` for universal relationships.

Avoid generic pairs such as:

```text
entity_type TEXT
entity_id UUID
```

when a direct foreign key to `core.entities(entity_id)` is possible.

### 9.5 Same-world consistency

A normal foreign key cannot always enforce that related entities belong to the same world. Enforce these invariants with:

- composite keys where practical
- constraint triggers
- command validation
- automated tests

---

## 10. Required common columns

### 10.1 Entity-root tables

Root entity tables should include:

```text
created_at
created_by
updated_at
updated_by
archived_at
source_id
canon_status_id
lifecycle_status_id
```

Exact ownership may vary where data is inherited from `core.entities`.

### 10.2 Mutable records

Mutable records generally include:

```text
created_at
created_by
updated_at
updated_by
```

### 10.3 Append-only records

Append-only records generally include:

```text
recorded_at
recorded_by
source_id
```

### 10.4 Updated timestamps

Use a shared trigger function to update `updated_at` where database-managed timestamps are desired.

Avoid copying slightly different timestamp trigger functions across domains.

---

## 11. Lookup-table conventions

Lookup tables generally contain:

```text
<lookup>_id
code
display_name
description
sort_order
is_active
```

### 11.1 Stable codes

Application logic may reference codes, but joins and foreign keys use IDs.

### 11.2 Seed data

Seed lookup data through idempotent migrations.

Do not use hard-coded numeric or UUID identifiers in application logic unless intentionally reserved and documented.

### 11.3 Extensible versus rules-owned lookups

Distinguish:

- platform lookups
- world-owned definitions
- ruleset-owned definitions

For example, quest statuses are platform lookups. Spells are ruleset definitions. Factions are world entities.

---

## 12. Temporal conventions

### 12.1 System time

Use `TIMESTAMPTZ` for:

- record creation
- record update
- approvals
- session real-world times
- external sync times

### 12.2 World time

Use references to `core.world_times` for fictional chronology.

### 12.3 Temporal validity

Use consistent pairs:

```text
effective_from_world_time_id
effective_to_world_time_id
```

or for real-world operational validity:

```text
valid_from
valid_to
```

Fictional-time intervals are half-open: the start is inclusive and the end is exclusive. In range notation this is `[start, end)`. Adjacent intervals therefore do not overlap.

The start of a persisted validity interval must be finite. A missing end represents an open-ended/current interval; do not use sentinel dates or maximum integers.

When overlap must be enforced by PostgreSQL, persist an `INT8RANGE` over the referenced `core.world_times.sort_key` values. Keep the endpoint foreign keys for identity, display, precision, and provenance; populate the range in a database trigger so callers cannot make the IDs and range disagree. The same trigger must reject endpoints from the wrong world and reject an end that is not strictly later than the start.

### 12.4 Current records

Use one of these patterns:

- `effective_to_world_time_id IS NULL`
- explicit `is_current`
- separate current-state table

Choose one pattern per domain and document it.

For frequently read timeline state, prefer a dedicated current-state row plus event history.

### 12.5 Overlap prevention

Use exclusion constraints where temporal intervals must not overlap.

Example use cases:

- active control assignments
- membership periods
- current portrayal profiles

For timeline-scoped party membership, the constraint shape is:

```sql
EXCLUDE USING gist (
    timeline_id WITH =,
    party_id WITH =,
    member_entity_id WITH =,
    effective_period WITH &&
)
```

This requires `btree_gist` for the UUID equality operators. The period uses the half-open `INT8RANGE` convention from §12.3, so leaving at the same world-time position another membership begins is valid, while two open-ended rows for the same timeline/party/member are not.

Real membership changes create or close periods. Editing an existing elapsed period is reserved for correcting erroneous data, must be audited with the old and new endpoints, and must re-run all world, ordering, and overlap validation. When `narrative.events` arrives in Phase 6, narrative join/leave changes also acquire causal event references; Phase 3 must not add unconstrained event UUIDs in anticipation.

---

## 13. Timeline-state conventions

### 13.1 Scope

Mutable world state references a `timeline_id`.

Campaign IDs may also be recorded for provenance, but campaign ownership must not replace timeline scope when effects are shared.

### 13.2 Typed state

Frequently queried state uses typed tables.

Examples:

```text
campaign.character_state
campaign.location_state
campaign.area_connection_state
campaign.hazard_state
campaign.item_state
campaign.quest_state
```

### 13.3 Current-state uniqueness

Enforce one current row per timeline and subject where required.

Example:

```sql
UNIQUE (timeline_id, character_id)
```

for a snapshot-style current-state table.

### 13.4 Causality

Current-state updates must reference the event, interaction, command, or import that established the state.

Recommended columns:

```text
last_event_id
last_interaction_id
updated_at
```

### 13.5 Generic overrides

A generic override table is an escape hatch, not a default model.

Generic overrides must contain:

- timeline
- entity
- property path
- typed JSON value
- effective period
- source event
- validation metadata

Properties promoted to frequent use should be migrated to typed state tables.

---

## 14. Event conventions

### 14.1 Event identifiers

Events are world entities and reuse the entity UUID.

### 14.2 Event scope

Every event has:

- timeline
- world time or approximate period
- type
- source
- status

A session-generated event may also reference campaign and session.

### 14.3 Event immutability

Applied events should be treated as append-only historical facts.

Corrections should normally create:

- a superseding event
- a reversal event
- corrected event metadata with audit history

Do not silently rewrite applied history.

### 14.4 Event effects

Event effects must be explicit and machine-readable where they change typed state.

### 14.5 Event granularity

Use events for meaningful persistent outcomes. Do not flood the event table with every UI click or attack roll.

High-volume detail belongs in interactions, encounter logs, or external systems.

---

## 15. Knowledge and visibility conventions

### 15.1 Knowledge is not a boolean

Do not use global `is_player_known` fields.

Knowledge is associated with a knower and may include confidence, interpretation, and source.

### 15.2 Canonical truth

Knowledge items must distinguish:

- true
- false
- partially true
- disputed
- unknown
- no objective truth

### 15.3 Secrets

Secrets are represented through knowledge and visibility policies, not through arbitrary secret-text columns scattered across tables.

### 15.4 Visibility policies

Records requiring restricted access reference a visibility policy or use a domain-specific grant table.

Avoid duplicating combinations of:

```text
is_public
is_player_known
is_gm_only
```

throughout the schema.

### 15.5 Database row-level security

PostgreSQL row-level security may be introduced after access patterns stabilize.

Initial application enforcement must still use explicit authorization checks. RLS should strengthen security, not substitute for a clear permission model.

---

## 16. Canon and provenance conventions

### 16.1 Canon status required

World-authored entities and facts require a canon status.

### 16.2 Source required where practical

AI-generated, imported, and integration-created content must always identify a source.

This is an **application-command obligation, not a database constraint** (resolved in the Phase 4 closeout recorded by [PHASE4_VERIFICATION.md](PHASE4_VERIFICATION.md#closeout-2026-08-02)): every `source_id UUID FK` column is nullable with `ON DELETE SET NULL`, because official/officially-seeded content legitimately has no single authored source row and there is no schema concept of content *origin* independent of `canon_status_id` to key a structural check off of. The command handler that creates AI-generated, imported, homebrew, or integration-created rule content is responsible for requiring and validating a source before that content is written, with its own tests at that boundary, once such a command exists. Do not describe nullable `source_id` as database-enforced provenance.

### 16.3 Proposed content

Proposed content must remain distinguishable from canon in queries and AI context assembly.

### 16.4 Supersession

When one record supersedes another, store an explicit link where possible.

```text
supersedes_id
superseded_by_id
```

Do not rely only on free-form notes.

---

## 17. AI-data conventions

### 17.1 Canonical tables are not agent scratch space

Agents must not place chain-of-thought, unvalidated speculation, or raw model output into canonical world tables.

### 17.2 Generated output retention

Store:

- model provider
- model name
- request metadata
- prompt or context reference
- generated output
- token usage
- status

Sensitive hidden reasoning should not be required or stored.

### 17.3 Proposed changes

Agent mutations use `ai.proposed_changes` or equivalent command proposals.

### 17.4 Approval

Applied proposals must reference:

- approval policy
- reviewer or automatic policy
- approval timestamp
- resulting command or event

### 17.5 Embeddings

Embeddings are derived and replaceable.

Each embedding record should identify:

- source record
- source version or content hash
- embedding model
- dimensions
- creation time

Do not foreign-key canonical data to an embedding record as though the embedding were authoritative.

---

## 18. JSONB conventions

### 18.1 Naming

JSONB columns should describe their purpose:

```text
configuration_jsonb
requirements_jsonb
payload_jsonb
metadata_jsonb
old_value_jsonb
new_value_jsonb
```

### 18.2 Validation

Use check constraints or application schemas for important JSON shapes.

### 18.3 Indexing

Do not create a generic GIN index on every JSONB column.

Index only fields demonstrated by query requirements.

### 18.4 Versioning

External payloads and configuration structures should include or reference a schema version.

---

## 19. Index conventions

### 19.1 Foreign-key indexes

PostgreSQL does not automatically index foreign-key columns. Add indexes for foreign keys used in joins, filtering, or deletes.

### 19.2 Index naming

Use:

```text
ix_<table>_<columns>
ux_<table>_<columns>
```

Examples:

```text
ix_events_timeline_world_time
ux_entity_types_code
```

### 19.3 Composite indexes

Order columns according to actual query patterns.

Common patterns:

```text
(timeline_id, entity_id)
(timeline_id, world_time_sort)
(campaign_id, session_number)
(npc_id, is_current)
```

### 19.4 Partial indexes

Use partial indexes for active, current, unresolved, or approved records.

### 19.5 Text search

Use `pg_trgm` or PostgreSQL full-text search based on query needs.

Names often benefit from trigram indexes. Documents and long descriptions may use generated `tsvector` columns.

### 19.6 Vector indexes

Create vector indexes only after selecting model dimensions and measuring retrieval needs.

---

## 20. Constraint conventions

### 20.1 Check constraints

Use check constraints for local rules.

Examples:

```sql
CHECK (progress_percentage BETWEEN 0 AND 100)
CHECK (ended_at IS NULL OR ended_at >= started_at)
CHECK (from_area_id <> to_area_id)
```

### 20.2 Constraint naming

Use explicit names:

```text
pk_<table>
fk_<table>_<column>
ck_<table>_<rule>
uq_<table>_<columns>
ex_<table>_<rule>
```

### 20.3 Deferred constraints

Use deferrable constraints for transactions that must temporarily pass through an incomplete state, particularly class-table creation and relationship participants.

### 20.4 Triggers

Use triggers sparingly for:

- timestamps
- audit capture
- complex local integrity
- subtype consistency

Do not hide major business workflows in large trigger chains.

---

## 21. Function and procedure conventions

### 21.1 Naming

Use action-oriented schema-qualified names:

```text
character.create_npc
campaign.branch_timeline
narrative.apply_event
knowledge.reveal_knowledge
```

### 21.2 Security mode

Prefer `SECURITY INVOKER`.

Use `SECURITY DEFINER` only when necessary, with a restricted search path and explicit privilege review.

### 21.3 Return values

Creation functions should return the created identifier or a documented result type.

### 21.4 Transactions

Application services normally control transactions. Stored functions used as atomic commands must avoid external side effects.

### 21.5 Error handling

Raise meaningful exceptions with stable application error codes where appropriate.

---

## 22. View conventions

### 22.1 Purpose

Views may provide:

- effective state
- common read models
- compatibility projections
- security-filtered projections

### 22.2 Naming

Use descriptive names. Prefixing with `v_` is not required when the schema and name are clear.

Examples:

```text
campaign.effective_character_state
knowledge.party_known_facts
```

### 22.3 Materialized views

Use materialized views only after profiling demonstrates need.

Every materialized view requires a refresh strategy and staleness expectation.

---

## 23. Partitioning conventions

Do not partition tables prematurely.

Likely future candidates:

- audit logs
- interaction logs
- AI requests and outputs
- embedding chunks
- high-volume event observations

Partitioning keys may include time, world, or timeline. Select only after usage and retention patterns are measured.

---

## 24. Audit conventions

### 24.1 What to audit

Audit:

- canon changes
- state changes
- permission changes
- AI proposal approvals
- imports
- integration writes
- destructive administrative operations

### 24.2 Audit immutability

Audit tables are append-only to normal application roles.

### 24.3 Actor identity

Audit records must identify:

- user
- service
- AI agent
- integration

where applicable.

### 24.4 Correlation IDs

Commands spanning multiple records should share a correlation ID.

Recommended fields:

```text
correlation_id
causation_id
request_id
```

---

## 25. Migration conventions

### 25.1 Migration tool

Use Alembic for migration orchestration, with explicit SQL where PostgreSQL-specific features are clearer.

### 25.2 Migration files

Each migration must include:

- purpose
- forward migration
- development rollback where feasible
- data implications
- locking considerations

### 25.3 No destructive initialization scripts

Do not use `DROP TABLE IF EXISTS ... CASCADE` in persistent environment migrations.

Destructive reset scripts may exist only under clearly labeled local test tooling. A developer's local PostgreSQL server is disposable by definition ([PLAN.md §26.2](PLAN.md#262-environments)) and is the one place such tooling is appropriate — never write a reset script that could resolve its target to `dev`, `staging`, or `prod`.

### 25.4 Seed data

Seed stable lookup data through migrations or versioned seed commands.

Once a migration applying a `database/seeds/*.yaml` file has been applied anywhere (including only to the deployed `dev` instance), that file is frozen: do not edit it. A migration's `upgrade()` reads the seed file at whatever content it has *when the migration runs* — on a fresh database provisioned after the edit, not the content that existed when the migration was written. Editing a consumed file therefore makes two environments that both report being at the same revision seed different data, silently. To change or add content, add a new `*.yaml` file and a new migration. `database/seeds/frozen_manifest.json` records a sha256 hash per already-consumed file and the revision that consumed it; `tests/database/test_seed_idempotency.py` fails loudly if a listed file's hash no longer matches, rather than letting the drift reach a fresh database unnoticed.

### 25.5 Backward compatibility

Before production, use expand-and-contract migrations for breaking changes:

1. add new structure
2. write both where necessary
3. backfill
4. switch reads
5. remove old structure later

### 25.6 Migration testing

CI must test, against a disposable containerized PostgreSQL 18 instance ([PLAN.md §24.0](PLAN.md#240-verification-policy), [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)):

- migration from empty database
- upgrade through all revisions
- schema comparison
- seed idempotency
- downgrade for recent development migrations where supported

All five also run locally, and should be run there first — they are cheap against a local/self-hosted server, where the full downgrade-to-base round trip costs seconds and destroys nothing shared. `scripts/verify.sh` wraps them. Local results are the expected first evidence; the CI run is what closes a phase.

### 25.7 Deferred constraint triggers across a multi-revision downgrade

`alembic downgrade <target>` runs every intervening revision's `downgrade()` inside one continuous transaction when more than one revision separates the current version from `<target>` — `database/migrations/env.py`'s `context.begin_transaction()` spans the whole invocation, not each individual revision. A revision whose `downgrade()` `DELETE`s or `UPDATE`s rows in a table governed by a `DEFERRABLE INITIALLY DEFERRED` constraint trigger queues a pending firing that is not resolved until something forces it — normally the transaction's own `COMMIT`. If a *later* revision's `downgrade()`, reached further down the same chain within that same transaction, then tries to `DROP TABLE` (or otherwise structurally alter) the table the trigger is attached to, PostgreSQL refuses with `cannot DROP TABLE "..." because it has pending trigger events`, even when the trigger function itself would have no-op'd had it actually run (revisions `085_campaign_owner_capabilities`/`086_system_role_capabilities` hit exactly this against `security.role_capabilities`' retention trigger from migration `080_security_identity_and_access`).

A revision whose `downgrade()` mutates such a table must drain its own pending firings before returning, with `SET CONSTRAINTS <schema>.<trigger_name> IMMEDIATE` immediately after the mutating statement(s) — never `SET CONSTRAINTS ALL IMMEDIATE` in a migration (that would also force-evaluate any *other* deferred constraint a different, unrelated revision's own `downgrade()` might still be relying on staying deferred later in the same transaction). This keeps the fix local to the revision that creates the pending state, so its `downgrade()` is correct regardless of what runs before or after it in a longer chain, rather than requiring an unrelated later revision to know about and compensate for what an earlier one left pending. A single-step downgrade of the revision in isolation needs no such statement — the deferred check simply runs at that command's own commit — so this only matters once the revision's `downgrade()` might share a transaction with a later one that structurally touches the same table.

---

## 26. Transaction conventions

### 26.1 Atomic commands

A gameplay command that changes multiple domains must be atomic.

Example:

```text
Activate pylon
    -> create interaction result
    -> create event
    -> update mechanism state
    -> update dungeon power state
    -> advance quest objective
    -> record audit data
```

All steps commit or roll back together.

### 26.2 Isolation

Use PostgreSQL's default `READ COMMITTED` initially.

Use explicit row locking or higher isolation for contention-sensitive operations such as:

- timeline branching
- current-state replacement
- initiative advancement
- resource consumption
- proposal approval

### 26.3 Optimistic concurrency

Mutable API-facing records should include a revision number or use `updated_at` for optimistic concurrency.

A numeric `row_version` is preferred for high-conflict records.

### 26.4 Idempotency

External commands and integration messages should support idempotency keys.

---

## 27. Security conventions

For local production, PostgreSQL runs on a private Docker network with no public host port. Application and migration roles remain separate and least-privileged; moving from RDS does not collapse bootstrap ownership, login-role, migration, extension, or backup responsibilities. Secrets are provided from outside the repository. Logical backups and uploaded-file backups must have an offsite copy and be restore-tested before AWS retirement.

### 27.1 Database roles

Separate the role that **owns** objects from the roles that **log in**. One owning role, five login roles:

| Role | Logs in | Purpose |
|---|---|---|
| `migration_owner` | **No** | Owns every schema object. Never authenticates; exists only as an ownership and default-privilege anchor |
| `migration_runner` | Yes | Executes migrations as a member of `migration_owner` |
| `app_read_write` | Yes | Application runtime; DML only, no DDL |
| `app_read_only` | Yes | Reporting and read-model queries |
| `integration_worker` | Yes | Scoped grants for Foundry/Discord/import-facing services |
| `admin_maintenance` | Yes | Break-glass, human use only |

Two rules follow from the split and must not be "simplified" away:

- **`migration_owner` is `NOLOGIN` and is never granted `rds_iam`.** On RDS, granting `rds_iam` to a role forces IAM authentication for it and permanently disables password authentication. Role membership is transitive, so an owning role carrying `rds_iam` silently disables password auth for everyone granted membership in it — including the RDS master user, which must be a member in order to transfer ownership. Keeping the owning role authentication-free makes it safe to grant to anyone.
- **Object ownership comes from `SET ROLE`, not from membership.** PostgreSQL assigns ownership from the current role, so a session that merely inherits `migration_owner` still creates objects owned by itself, and `ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner` never fires for them. Migrations issue `SET ROLE migration_owner` after connecting.

Rationale and the incident that produced it: [ADR 0009](adr/0009-separate-owning-role-from-login-roles.md).

### 27.2 Least privilege

Application roles should not own schemas or tables. Neither should the role that runs migrations — `migration_runner` executes DDL but `migration_owner` owns the result, so rotating or revoking the runner identity never orphans object ownership.

### 27.3 Secrets

Do not store database passwords, API keys, or model credentials in source code or database seed files.

For the self-hosted deployment topology, credentials come from environment variables (`.env`, gitignored — see `.env.example`) or `compose.yaml`'s environment interpolation, never committed. For anyone using the optional AWS path, use AWS Secrets Manager or equivalent runtime secret injection.

### 27.4 Sensitive content

GM-only notes, secrets, private messages, and source documents require explicit access control.

---

## 28. Integration conventions

### 28.1 External IDs

Store external references in `integration.external_identifiers` or domain-specific mapping tables.

Suggested uniqueness:

```text
(integration_type, external_scope, external_id)
```

### 28.2 Synchronization

Sync records should include:

- last observed external version
- last synchronized timestamp
- direction
- status
- conflict information

### 28.3 Raw payloads

Raw incoming payloads may be retained for troubleshooting with retention limits and sensitive-data controls.

### 28.4 Direct writes

FoundryVTT, Discord, and external integrations must invoke application commands. They must not receive broad direct table-write access.

---

## 29. Import conventions

### 29.1 Staging first

Imported records enter the `import` schema before canonical tables.

### 29.2 No automatic canon

Extraction results default to proposed status.

### 29.3 Deduplication

Entity matching must consider:

- names and aliases
- entity type
- world
- locations
- relationships
- source references

### 29.4 Traceability

Every canonical record created by import must reference the import job and staged source.

---

## 30. Query conventions

### 30.1 Schema qualification

All application SQL should schema-qualify objects.

### 30.2 Avoid `SELECT *`

Select explicit columns in application code and persistent views.

### 30.3 Effective-state services

Applications should use approved effective-state functions or repository queries rather than reimplementing timeline inheritance.

### 30.4 Pagination

Use keyset pagination for large tables where practical.

### 30.5 N+1 queries

Character-sheet and AI-context queries must be designed as deliberate read models to avoid excessive round trips.

---

## 31. Documentation conventions

Every table must have a table comment describing its domain responsibility.

Important columns require comments where meaning is not obvious.

Example:

```sql
COMMENT ON TABLE knowledge.entity_knowledge IS
'Records what a specific entity knows or believes about a knowledge item.';
```

Migrations introducing a new domain must update relevant architecture documentation.

---

## 32. Testing conventions

### 32.1 Constraint tests

Every nontrivial constraint requires an automated positive and negative test.

### 32.2 Scenario tests

Maintain database scenario tests for:

- shared timeline effects
- branch isolation
- dungeon discovery
- quest advancement
- NPC knowledge filtering
- AI proposal approval

Each becomes required in the phase that first makes it provable, not before. In particular, **branch isolation** — a timeline inherits parent history only up to its branch point — is a **Phase 6** scenario test, because there is no history to inherit until `narrative.events` exists. Phase 3 delivers branch *structure* (parent, branch world time, world agreement) and timeline-scoped membership rows; neither demonstrates isolation, and neither should be recorded as satisfying this item. See [PLAN.md Phase 3](PLAN.md#phase-3-timelines-and-campaigns) and [Phase 6](PLAN.md#phase-6-events-and-interactions).

### 32.3 Data builders

Use reusable test-data builders or fixtures that create valid inherited entities through the same commands used by production code.

Do not bypass subtype and state invariants in tests unless explicitly testing invalid data.

---

## 33. Performance conventions

### 33.1 Measure first

Do not denormalize, partition, or materialize without query measurements.

### 33.2 Query plans

Capture `EXPLAIN (ANALYZE, BUFFERS)` for critical queries during performance testing.

Critical query groups include:

- character sheet assembly
- effective timeline state
- dungeon map and state
- NPC AI context
- party knowledge
- session event retrieval

### 33.3 Caching

Caches must identify source version or invalidation keys.

Caches are never authoritative.

---

## 34. Anti-patterns

The following are prohibited without an approved exception:

- application tables in `public`
- generic `id` primary keys
- unbounded free-text categorical values where a lookup is required
- fictional dates stored as text only
- global `is_player_known` booleans
- all-purpose entity-attribute-value tables
- JSONB as a substitute for stable relational modeling
- reciprocal relationship duplication
- campaign-owned copies of persistent world entities
- AI agents writing directly to canon tables
- direct integration writes to arbitrary tables
- hard-coded credentials
- destructive schema files using `DROP TABLE ... CASCADE`
- relying on `search_path` for object resolution
- storing item definitions and item instances in the same row type
- overwriting significant state without an event or audit trail

---

## 35. Example inherited entity creation

```sql
BEGIN;

INSERT INTO core.entities (
    world_id,
    entity_type_id,
    canonical_name,
    canon_status_id,
    lifecycle_status_id,
    source_id
)
VALUES (
    :world_id,
    :npc_entity_type_id,
    :canonical_name,
    :canon_status_id,
    :active_status_id,
    :source_id
)
RETURNING entity_id;

INSERT INTO character.characters (
    character_id,
    species_id,
    size_id
)
VALUES (
    :entity_id,
    :species_id,
    :size_id
);

INSERT INTO character.npcs (
    npc_id,
    simulation_level_id,
    importance
)
VALUES (
    :entity_id,
    :simulation_level_id,
    :importance
);

COMMIT;
```

In production, this operation should be wrapped in a command service or stored function.

---

## 36. Example event-assisted state update

A character activates a dungeon pylon.

One transaction should:

1. Insert the resolved interaction.
2. Insert the event entity and event subtype.
3. Insert event participants and location.
4. Insert event effects.
5. Update `campaign.interactable_state`.
6. Update `campaign.location_state` if the facility power mode changes.
7. Update `campaign.objective_state` if a quest objective advances.
8. Insert discoveries or observations.
9. Write audit records.

The event provides history; the typed state tables provide fast reads.

---

## 37. Convention-change process

Database conventions may evolve, but changes require:

1. A documented reason.
2. Impact analysis.
3. Migration implications.
4. Updates to this document.
5. Automated validation or linting where practical.

New domains should follow these conventions unless an architecture decision record explicitly approves an exception.
