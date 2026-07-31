# Claude Code Instructions — D&D AI World Platform

This file is operating guidance for Claude Code (and other AI coding assistants) working in this repository. It summarizes and links to the authoritative documents rather than restating them — when this file and a linked document disagree, the linked document wins and this file should be corrected.

## 1. What this project is

A persistent-world simulation platform for tabletop RPGs (initially D&D 5e 2024). A world with branching timelines hosts multiple campaigns; PostgreSQL is the single source of truth; AI agents portray NPCs and propose world changes but never own canon. Full vision: [README.md](README.md).

## 2. Current status

This is an architecture restart. See [README.md § Current Status](README.md#current-status).

- The pre-restart legacy code (`Database/` flat `public`-schema tables, `src/lambda-functions/`, `DirectAPICalls/`, `PDFChatBot/`, and the Lambda build scripts) has been **removed**, along with the Terraform modules and environment wiring built specifically for it (`db_runner`, `lambda-api`, `lambda-with-build`, and the `db-schema-introspect`/`query-runner` environment configs).
- What remains under `terraform/`: the generic `database` and `secrets` modules (RDS, VPC, KMS, Secrets Manager) — infrastructure organization that isn't tied to the old schema and is reasonable to build on.
- Any existing database content will be dropped. No legacy schema or API compatibility is required.
- Don't resurrect deleted patterns from git history as "existing convention" — the current docs under `docs/` are the source of truth for how new code should look.

## 3. Technology stack

- **Infrastructure / IaC:** AWS, provisioned and managed with **Terraform**. New environments follow the existing `terraform/modules/` + `terraform/environments/<env>/` pattern.
- **Database:** PostgreSQL on AWS RDS. Schema, conventions, and migration approach are defined in [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md) (migrations via **Alembic**, per §25.1).
- **API / backend services:** **Python**. Application/domain/command-handler code (see architecture layers in §5 below) is Python.
- **UI:** **React**. Any web/admin client is a React application talking to the REST/application API — never directly to PostgreSQL.
- **Other integrations:** FoundryVTT module, Discord bot, MCP interface — all clients, all going through the application API (§5).

When a doc below doesn't yet specify a technology choice, default to this stack rather than introducing a new one.

## 4. Documentation map

All project documentation lives under `docs/` (never the repo root, except `README.md` and this file). Read the relevant doc *before* implementing in that area — these are detailed and authoritative; this file is intentionally not a substitute.

| Document | Use it for |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | **Source of truth** for implementation phases, deliverables, and exit criteria. Check current phase before starting work. |
| [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) | Conceptual vocabulary — what a World/Timeline/Campaign/Entity/Event/Knowledge Item/etc. *is* and its boundaries. Read before naming or designing anything new. |
| [docs/architecture/DATABASE_MODEL.md](docs/architecture/DATABASE_MODEL.md) | Logical schema: tables per domain, ER diagrams, ownership rules. The concrete translation of DOMAIN_MODEL.md into schema. |
| [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md) | Hard rules for naming, types, keys, inheritance, JSONB use, migrations, indexing, anti-patterns (§34). Follow exactly — this is a convention document, not a style suggestion. |
| [docs/ENTITY_LIFECYCLE.md](docs/ENTITY_LIFECYCLE.md) | How entities are created, approved, mutated, branched, archived, deleted — including the exact command list and required transaction steps. |
| [docs/architecture/SYSTEM_ARCHITECTURE.md](docs/architecture/SYSTEM_ARCHITECTURE.md) | Service layering, command/query separation, transaction boundaries, AI orchestration flow, deployment topology (modular monolith initially). |
| [docs/architecture/DUNGEON_FLOW.md](docs/architecture/DUNGEON_FLOW.md) | The reference end-to-end vertical slice (dungeon/quest scenario) — the acceptance test any cross-domain design should be checked against. |

## 5. Non-negotiable architectural rules

These hold regardless of which feature is being implemented. Full rationale is in the docs above; this is the checklist.

1. **PostgreSQL is the only source of truth.** Embeddings, caches, search indexes, generated summaries, and derived documents are disposable and rebuildable — never authoritative.
2. **AI never writes canon directly.** Every AI-suggested world change is a `Proposed Change` that goes through validation and (for high-impact changes) approval before becoming a normal domain command. Low-risk/automatic-approval categories are explicitly enumerated in the docs — don't invent new ones ad hoc.
3. **Clients never write directly to the database.** FoundryVTT, Discord, the React UI, and MCP all go through the application API and its commands — never raw table access.
4. **Class-table inheritance for entity subtypes**, rooted at `core.entities`. A subtype's primary key is the parent entity's UUID (no new UUID generated per subtype level). Don't use `INHERITS` or EAV-style generic tables.
5. **Definition, timeline state, knowledge, and history are always four separate concerns.** Never collapse "what it is," "what's currently true in this timeline," "who knows/believes what," and "what happened" into one field or table.
6. **State changes need a causal event; events and their typed-state updates commit atomically** in one transaction. Don't update `campaign.*_state` tables without a corresponding event (or explicit administrative source).
7. **Timelines only inherit parent history up to their branch point.** Effective-state queries must never leak post-branch parent events into a branch.
8. **Knowledge is per-knower, never a global boolean.** No `is_player_known` / `is_discovered` flags on the object itself — discovery and belief live in the knowledge domain, scoped to who knows it.
9. **Persistent world entities are archived, not physically deleted.** Physical deletion is reserved for unreferenced drafts/test fixtures/legal removal, per [docs/ENTITY_LIFECYCLE.md §14](docs/ENTITY_LIFECYCLE.md).
10. **No secrets in code or seed files.** AWS Secrets Manager for credentials and API keys, consistent with the existing Terraform pattern.

When any task seems to require breaking one of these, stop and flag it rather than quietly deviating — it usually means the domain model needs an explicit extension (see §37 of DATABASE_CONVENTIONS.md on the convention-change process), not a one-off exception.

## 6. Conventions quick-reference

Full rules are in the linked docs — don't treat this as complete.

- **Database:** `snake_case`, plural table names, `<entity>_id` primary keys (never a bare `id`), always schema-qualified references, `TEXT` over `VARCHAR(n)`, `TIMESTAMPTZ` for real-world time vs. `core.world_times` for fictional time, lookup tables over `ENUM`, no tables in `public`. See [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md) in full before writing schema.
- **Python services:** organize around the command/query and domain-service layering in [docs/architecture/SYSTEM_ARCHITECTURE.md §5](docs/architecture/SYSTEM_ARCHITECTURE.md); commands are the only way to mutate state and must be transactional per §6–7 of that doc.
- **Terraform:** one module per bounded infrastructure concern (mirroring the existing `database` / `secrets` split), one directory per environment under `terraform/environments/`, no hardcoded credentials, state and variable naming should mirror what's already in `terraform/modules/`.
- **React:** standard component-based structure; the UI is a client like any other — it talks to the application API, not the database.
- **New documentation** always goes under `docs/` (see [docs/PLAN.md Phase 0](docs/PLAN.md#23-delivery-phases) for the planned ADR/domain-doc set). Keep `README.md`'s Development Roadmap and Documentation sections pointing at `docs/PLAN.md` rather than duplicating its content.

## 7. Before implementing a feature

1. Check [docs/PLAN.md](docs/PLAN.md) for the current phase and that feature's exit criteria.
2. Look up the relevant concepts in [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) and their schema in [docs/architecture/DATABASE_MODEL.md](docs/architecture/DATABASE_MODEL.md) — don't invent new domain vocabulary without checking it doesn't already exist under a different name.
3. If it creates, mutates, or removes an entity, follow the matching command/workflow in [docs/ENTITY_LIFECYCLE.md](docs/ENTITY_LIFECYCLE.md).
4. Write schema per [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md); check §34 (anti-patterns) before finishing.
5. Place the code in the correct architectural layer per [docs/architecture/SYSTEM_ARCHITECTURE.md](docs/architecture/SYSTEM_ARCHITECTURE.md) — don't let API handlers embed domain rules or let domain services bypass the command/transaction pattern.
6. If the change introduces a new cross-cutting concept, update the relevant doc under `docs/` in the same change — these documents are meant to stay current, not drift from the implementation.
