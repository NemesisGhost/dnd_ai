# Claude Code Instructions — D&D AI World Platform

This file is operating guidance for Claude Code (and other AI coding assistants) working in this repository. It summarizes and links to the authoritative documents rather than restating them — when this file and a linked document disagree, the linked document wins and this file should be corrected.

## 1. What this project is

A persistent-world simulation platform for tabletop RPGs (initially D&D 5e 2024). A world with branching timelines hosts multiple campaigns; PostgreSQL is the single source of truth; AI agents portray NPCs and propose world changes but never own canon. Full vision: [README.md](README.md).

## 2. Current status

This is an architecture restart whose first four implementation phases are complete. Phase 1 established the database/AWS bootstrap; Phase 2 delivered and verified the core world platform; Phase 3 delivered timelines and campaigns; Phase 4 delivered the initial ruleset and shared-character schema, including a corrections pass that closed several integrity gaps found in review. The current target is [Phase 5: locations and dungeon play](docs/PLAN.md#phase-5-locations-and-dungeon-play). See [README.md § Current Status](README.md#current-status).

- The pre-restart legacy code (`Database/` flat `public`-schema tables, `src/lambda-functions/`, `DirectAPICalls/`, `PDFChatBot/`, and the Lambda build scripts) has been **removed**, along with the Terraform modules and environment wiring built specifically for it (`db_runner`, `lambda-api`, `lambda-with-build`, and the `db-schema-introspect`/`query-runner` environment configs).
- What remains under `terraform/`: the generic `database` and `secrets` modules (RDS, VPC, KMS, Secrets Manager) — infrastructure organization that isn't tied to the old schema and is reasonable to build on.
- Any existing database content will be dropped. No legacy schema or API compatibility is required.
- Don't resurrect deleted patterns from git history as "existing convention" — the current docs under `docs/` are the source of truth for how new code should look.

## 3. Technology stack

- **Infrastructure / IaC:** AWS, provisioned and managed with **Terraform**. New environments follow the existing `terraform/modules/` + `terraform/environments/<env>/` pattern. Everything runs in AWS — see rule 11 in §5.
- **Database:** PostgreSQL 15.x on AWS RDS. Schema, conventions, and migration approach are defined in [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md) (migrations via **Alembic**, per §25.1).
- **API / backend services:** **Python 3.12+** with **SQLAlchemy 2.x Core** (not the ORM), **psycopg 3**, **Pydantic v2**, and **FastAPI** at the API layer. Dependencies via **uv**; **ruff** and **mypy** for quality. Tests are **pytest** run against the deployed AWS `dev` database (testcontainers is a fallback only, per [docs/PLAN.md §23.0](docs/PLAN.md#230-aws-verification-policy)).
- **Compute:** application services (API, background worker, Discord adapter) and one-off jobs including migrations run on **ECS Fargate** from a single shared container image in **ECR**, per [docs/PLAN.md §30](docs/PLAN.md#30-aws-deployment-plan-for-application-services).
- **UI:** **React**. Any web/admin client is a React application talking to the REST/application API — never directly to PostgreSQL.
- **Other integrations:** FoundryVTT module, Discord bot, MCP interface — all clients, all going through the application API (§5).

The full toolchain, with rationale and the process for changing any of it, is in [docs/DEVELOPMENT.md §1](docs/DEVELOPMENT.md#1-toolchain). When a doc doesn't specify a technology choice, default to this stack rather than introducing a new one.

## 4. Documentation map

All project documentation lives under `docs/` (never the repo root, except `README.md` and this file). Read the relevant doc *before* implementing in that area — these are detailed and authoritative; this file is intentionally not a substitute.

| Document | Use it for |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | **Source of truth** for implementation *phasing*: which phase delivers what, exit criteria, first-time obligations. Check current phase before starting work. Its per-phase "Implement" prose is a working sketch, not the schema record — where it names a table, defer to DATABASE_MODEL.md for that table's actual existence, schema, and shape. |
| [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) | Conceptual vocabulary — what a World/Timeline/Campaign/Entity/Event/Knowledge Item/etc. *is* and its boundaries. Read before naming or designing anything new. |
| [docs/architecture/DATABASE_MODEL.md](docs/architecture/DATABASE_MODEL.md) | **Source of truth** for database schema and table scope: every table, its schema, key columns, ER diagrams, ownership rules. If PLAN.md and this document disagree on whether a table exists, its name, or its shape, this document wins and PLAN.md should be corrected (§25 there records the last such reconciliation). |
| [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md) | Hard rules for naming, types, keys, inheritance, JSONB use, migrations, indexing, anti-patterns (§34). Follow exactly — this is a convention document, not a style suggestion. |
| [docs/ENTITY_LIFECYCLE.md](docs/ENTITY_LIFECYCLE.md) | How entities are created, approved, mutated, branched, archived, deleted — including the exact command list and required transaction steps. |
| [docs/architecture/SYSTEM_ARCHITECTURE.md](docs/architecture/SYSTEM_ARCHITECTURE.md) | Service layering, command/query separation, transaction boundaries, AI orchestration flow, deployment topology (modular monolith on ECS Fargate). |
| [docs/architecture/DUNGEON_FLOW.md](docs/architecture/DUNGEON_FLOW.md) | The reference end-to-end vertical slice (dungeon/quest scenario) — the acceptance test any cross-domain design should be checked against. |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Toolchain, repository layout, local setup, Alembic workflow, testing layers, CI requirements, definition of done. Read before writing code. |
| [docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md) | Infrastructure reference — variables, outputs, secrets, verification, teardown, and known gaps in the current Terraform. Deployment path is [docs/QUICKSTART.md](docs/QUICKSTART.md), pre-flight is [docs/CHECKLIST.md](docs/CHECKLIST.md), onboarding is [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md). The plan for what it should become is [docs/PLAN.md §29](docs/PLAN.md#29-aws-terraform-deployment-plan-for-postgresql). |
| [docs/AI_ASSISTANT_GUIDE.md](docs/AI_ASSISTANT_GUIDE.md) | Long-form version of this file: worked examples, anti-patterns, decision trees. This file is the summary; that one has the detail. |
| [docs/adr/](docs/adr/) | One record per architectural decision. Most are stubs pointing back at PLAN.md §2. [ADR 0008](docs/adr/0008-aws-first-deployment-and-verification.md) governs where code runs and is verified; [ADR 0009](docs/adr/0009-separate-owning-role-from-login-roles.md) governs the database role model — read it before touching roles, grants, or object ownership. |

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
11. **Everything is deployed to and verified in AWS.** Migrations, `tests/database`, and `tests/scenario` run against the deployed `dev` RDS instance; deployables run on ECS Fargate in `dev`. A local container is a fallback for genuinely unreachable AWS, never the default loop, and "it passes locally" is not a verification claim. See [docs/PLAN.md §23.0](docs/PLAN.md#230-aws-verification-policy) and [ADR 0008](docs/adr/0008-aws-first-deployment-and-verification.md).

When any task seems to require breaking one of these, stop and flag it rather than quietly deviating — it usually means the domain model needs an explicit extension (see §37 of DATABASE_CONVENTIONS.md on the convention-change process), not a one-off exception.

## 6. Conventions quick-reference

Full rules are in the linked docs — don't treat this as complete.

- **Database:** `snake_case`, plural table names, `<entity>_id` primary keys (never a bare `id`), always schema-qualified references, `TEXT` over `VARCHAR(n)`, `TIMESTAMPTZ` for real-world time vs. `core.world_times` for fictional time, lookup tables over `ENUM`, no tables in `public`. See [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md) in full before writing schema.
- **Python services:** organize around the command/query and domain-service layering in [docs/architecture/SYSTEM_ARCHITECTURE.md §5](docs/architecture/SYSTEM_ARCHITECTURE.md); commands are the only way to mutate state and must be transactional per §6–7 of that doc.
- **Terraform:** one module per bounded infrastructure concern (mirroring the existing `database` / `secrets` split), one directory per environment under `terraform/environments/`, no hardcoded credentials, state and variable naming should mirror what's already in `terraform/modules/`.
- **React:** standard component-based structure; the UI is a client like any other — it talks to the application API, not the database.
- **New documentation** always goes under `docs/` — the only markdown files that belong at the repository root are `README.md` and this file, and the only one under `terraform/` is a short pointer to `docs/INFRASTRUCTURE.md`. Keep `README.md`'s Development Roadmap and Documentation sections pointing at `docs/PLAN.md` rather than duplicating its content.
- **Tests and tooling:** `pytest` layers (`tests/unit` with no database; `tests/database` and `tests/scenario` against an ephemeral database on the deployed AWS `dev` instance, per rule 11), `ruff format`/`ruff check`/`mypy src` before committing. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## 7. Before implementing a feature

1. Check [docs/PLAN.md](docs/PLAN.md) for the current phase, that feature's exit criteria, and the phase's **first-time obligations** — the mechanisms a phase exercises for the first time are where defects cluster ([§23.1](docs/PLAN.md#231-phase-exit-review)).
2. Look up the relevant concepts in [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) and their schema in [docs/architecture/DATABASE_MODEL.md](docs/architecture/DATABASE_MODEL.md) — don't invent new domain vocabulary without checking it doesn't already exist under a different name.
3. If it creates, mutates, or removes an entity, follow the matching command/workflow in [docs/ENTITY_LIFECYCLE.md](docs/ENTITY_LIFECYCLE.md).
4. Write schema per [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md); check §34 (anti-patterns) before finishing.
5. Place the code in the correct architectural layer per [docs/architecture/SYSTEM_ARCHITECTURE.md](docs/architecture/SYSTEM_ARCHITECTURE.md) — don't let API handlers embed domain rules or let domain services bypass the command/transaction pattern.
6. Follow the mechanics in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — Alembic revision requirements, test layers, and the definition-of-done checklist in §10.
7. If the change introduces a new cross-cutting concept, update the relevant doc under `docs/` in the same change — these documents are meant to stay current, not drift from the implementation.
8. If the change **completes a phase**, run the phase exit review in [docs/PLAN.md §23.1](docs/PLAN.md#231-phase-exit-review): write `docs/PHASEn_VERIFICATION.md`, re-check the recurring obligations, and review the next phase against what this one taught before starting it. A bug caused by a convention being wrong is a documentation defect too — fix both.
