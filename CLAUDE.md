# Claude Code Instructions — D&D AI World Platform

This file is operating guidance for Claude Code (and other AI coding assistants) working in this repository. It summarizes and links to the authoritative documents rather than restating them — when this file and a linked document disagree, the linked document wins and this file should be corrected.

## 1. What this project is

A persistent-world simulation platform for tabletop RPGs (initially D&D 5e 2024). A world with branching timelines hosts multiple campaigns; PostgreSQL is the single source of truth; AI agents portray NPCs and propose world changes but never own canon. Full vision: [README.md](README.md).

## 2. Current status

This is an architecture restart. Phases 1 through 4 are complete, including Phase 4's initial ruleset/shared-character schema, its first corrections pass, and all three closeout passes (see [docs/PHASE4_VERIFICATION.md](docs/PHASE4_VERIFICATION.md); [docs/PHASE4_REMAINING_ISSUES.md](docs/PHASE4_REMAINING_ISSUES.md) is a closed historical record). Phase 5's location/dungeon schema, minimal knowledge-domain slice pulled forward from Phase 7, production invariants, resumed-waiter tests, and independent final-state assertions are complete, and formal verification is now also complete: a tenth review found that no Python thread can deliver the literal no-survivor guarantee the test-only `_BackgroundStatement` helper needs, a tenth pass replaced the worker thread with an independently terminable process, an eleventh review then found that process-based redesign could still report false success and silently discard cleanup failures, and an eleventh pass's fix is CI-confirmed by [PR #14](https://github.com/NemesisGhost/dnd_ai/pull/14)'s push-triggered run [`30964183959`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30964183959) (see [docs/PHASE5_VERIFICATION.md](docs/PHASE5_VERIFICATION.md); [docs/PHASE5_REMAINING_ISSUES.md](docs/PHASE5_REMAINING_ISSUES.md) is a closed historical record). Both the Phase 6 repository-context modularization gate and the Phase 5 formal-correctness gate are closed, so Phase 6 feature/schema work may begin. See [README.md § Current Status](README.md#current-status).

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

## 4. Documentation map and context-loading policy

All project documentation lives under `docs/` (never the repo root, except `README.md` and this file). The linked documents are authoritative, but **authoritative does not mean load every document in full for every task**. Use progressive, task-scoped retrieval:

1. Read this file, then identify the task's phase, domain, and change type.
2. Use a heading or keyword search (`rg -n '^#{1,4} |<term>' <candidate-docs>`) to locate the relevant sections before opening them.
3. Read only the current phase entry, the affected domain/schema sections, and the convention sections that govern the mechanism being changed. Expand to adjacent sections only when a dependency or conflict requires it.
4. Do not preload completed-phase verification/history, unrelated domains, or all of `PLAN.md`, `DOMAIN_MODEL.md`, `DATABASE_MODEL.md`, and `DATABASE_CONVENTIONS.md` together.
5. Read a whole authoritative document only for a cross-cutting design/reconciliation review, or when targeted sections do not resolve an ambiguity. State that reason in the work summary.

`docs/AI_ASSISTANT_GUIDE.md` is an **on-demand example catalog**, not part of normal startup context. Open a specific section only when this file and the authoritative topic document do not provide enough guidance. Never load it alongside this file merely because work is beginning.

| Document | Use it for |
|---|---|
| [docs/PLAN.md](docs/PLAN.md) | **Source of truth** for implementation *phasing*. Read §23.0–23.1 plus the current phase entry; use completed-phase history only for regression/archaeology work. Its per-phase "Implement" prose is a working sketch, not the schema record — where it names a table, defer to DATABASE_MODEL.md. |
| [docs/PLAN_PHASES_0_5_ARCHIVE.md](docs/PLAN_PHASES_0_5_ARCHIVE.md) | Completed Phase 0–5 deliverables, exit criteria, and first-time obligations. Read only for historical/regression work involving those phases. |
| [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) | Conceptual vocabulary and boundaries. Search for and read the affected concepts before naming or changing them; do not load unrelated domains. |
| [docs/architecture/DATABASE_MODEL.md](docs/architecture/DATABASE_MODEL.md) | **Source of truth** for database schema and table scope. Read the affected schema/domain section and its reconciliation notes. If PLAN.md disagrees on a table's existence, name, or shape, this document wins. |
| [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md) | Hard database rules. Read the sections governing the mechanisms being changed plus §34's relevant anti-patterns; follow them exactly. A full-document read is reserved for convention-wide reviews. |
| [docs/ENTITY_LIFECYCLE.md](docs/ENTITY_LIFECYCLE.md) | How entities are created, approved, mutated, branched, archived, deleted — including the exact command list and required transaction steps. |
| [docs/architecture/SYSTEM_ARCHITECTURE.md](docs/architecture/SYSTEM_ARCHITECTURE.md) | Service layering, command/query separation, transaction boundaries, AI orchestration flow, deployment topology (modular monolith on ECS Fargate). |
| [docs/architecture/DUNGEON_FLOW.md](docs/architecture/DUNGEON_FLOW.md) | The reference end-to-end vertical slice (dungeon/quest scenario) — the acceptance test any cross-domain design should be checked against. |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Toolchain, repository layout, local setup, Alembic workflow, testing layers, CI requirements, definition of done. Read the section matching the task plus §10. |
| [docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md) | Infrastructure reference — variables, outputs, secrets, verification, teardown, and known gaps in the current Terraform. Deployment path is [docs/QUICKSTART.md](docs/QUICKSTART.md), pre-flight is [docs/CHECKLIST.md](docs/CHECKLIST.md), onboarding is [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md). The plan for what it should become is [docs/PLAN.md §29](docs/PLAN.md#29-aws-terraform-deployment-plan-for-postgresql). |
| [docs/AI_ASSISTANT_GUIDE.md](docs/AI_ASSISTANT_GUIDE.md) | On-demand worked examples, anti-patterns, and decision trees. Not a startup read and not a second copy of required context. |
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

- **Database:** `snake_case`, plural table names, `<entity>_id` primary keys (never a bare `id`), always schema-qualified references, `TEXT` over `VARCHAR(n)`, `TIMESTAMPTZ` for real-world time vs. `core.world_times` for fictional time, lookup tables over `ENUM`, no tables in `public`. Search [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md) and read the sections governing the affected tables, constraints, migrations, grants, and tests before writing schema.
- **Python services:** organize around the command/query and domain-service layering in [docs/architecture/SYSTEM_ARCHITECTURE.md §5](docs/architecture/SYSTEM_ARCHITECTURE.md); commands are the only way to mutate state and must be transactional per §6–7 of that doc.
- **Terraform:** one module per bounded infrastructure concern (mirroring the existing `database` / `secrets` split), one directory per environment under `terraform/environments/`, no hardcoded credentials, state and variable naming should mirror what's already in `terraform/modules/`.
- **React:** standard component-based structure; the UI is a client like any other — it talks to the application API, not the database.
- **New documentation** always goes under `docs/` — the only markdown files that belong at the repository root are `README.md` and this file, and the only one under `terraform/` is a short pointer to `docs/INFRASTRUCTURE.md`. Keep `README.md`'s Development Roadmap and Documentation sections pointing at `docs/PLAN.md` rather than duplicating its content.
- **Tests and tooling:** `pytest` layers (`tests/unit` with no database; `tests/database` and `tests/scenario` against an ephemeral database on the deployed AWS `dev` instance, per rule 11), `ruff format`/`ruff check`/`mypy src` before committing. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## 7. Before implementing a feature

1. Read [docs/PLAN.md §23.0–23.1](docs/PLAN.md#23-delivery-phases) and the **current phase entry only** for its deliverables, exit criteria, and first-time obligations. Completed-phase detail is historical context, not routine input.
2. Search [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) and [docs/architecture/DATABASE_MODEL.md](docs/architecture/DATABASE_MODEL.md) for the concepts/tables named by the task, then read those sections and directly linked reconciliation notes. Don't invent vocabulary without checking for an existing term.
3. If it creates, mutates, or removes an entity, follow the matching command/workflow in [docs/ENTITY_LIFECYCLE.md](docs/ENTITY_LIFECYCLE.md).
4. Search [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md) by mechanism (for example: foreign keys, ranges, triggers, concurrency, comments, migrations, or grants), read those sections, and check the applicable §34 anti-patterns before finishing.
5. For application code, read the affected layer and transaction sections in [docs/architecture/SYSTEM_ARCHITECTURE.md](docs/architecture/SYSTEM_ARCHITECTURE.md). For database-only work, do not preload unrelated API/service sections.
6. Read the relevant workflow plus [docs/DEVELOPMENT.md §10](docs/DEVELOPMENT.md#10-definition-of-done); do not load setup/walkthrough sections unless the task concerns setup or CI mechanics.
7. If the change introduces a new cross-cutting concept, update the relevant doc under `docs/` in the same change — these documents are meant to stay current, not drift from the implementation.
8. If the change **completes a phase**, run the phase exit review in [docs/PLAN.md §23.1](docs/PLAN.md#231-phase-exit-review): write `docs/PHASEn_VERIFICATION.md`, re-check the recurring obligations, and review the next phase against what this one taught before starting it. A bug caused by a convention being wrong is a documentation defect too — fix both.
