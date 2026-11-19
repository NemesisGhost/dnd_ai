# Claude Code Instructions — D&D AI World Platform

This file is operating guidance for Claude Code (and other AI coding assistants) working in this repository. It summarizes and links to the authoritative documents rather than restating them — when this file and a linked document disagree, the linked document wins and this file should be corrected.

## Product and documentation

Start at the [documentation hub](docs/README.md). Load the affected topic, then its governing decisions. The [documentation standard](docs/standard.md) defines where tutorials, operations, references, explanations and evidence belong. The [roadmap](docs/delivery/roadmap.md) owns implementation order. The [work register](docs/delivery/work-register.md) owns current obligations.

Use SQLAlchemy Core, FastAPI, React and PostgreSQL 18 as described in [Development](docs/DEVELOPMENT.md). Use the [database model](docs/architecture/DATABASE_MODEL.md) and [table inventory](docs/reference/tables.md) together for schema work. For user-facing API behavior start with [access control](docs/api/ACCESS_CONTROL.md) and the [operation catalog](docs/api/operations.md).

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
9. **Persistent world entities are archived, not physically deleted.** Physical deletion is reserved for unreferenced drafts/test fixtures/legal removal, per [docs/ENTITY_LIFECYCLE.md §14](docs/ENTITY_LIFECYCLE.md#14-physical-deletion).
10. **No secrets in code or seed files.** Keep credentials in environment variables or host-mounted secrets, never in repository files.
11. **Develop and verify against PostgreSQL 18, self-hosted.** Migrations, `tests/database`, and `tests/scenario` run against a local or Compose PostgreSQL 18 server. CI repeats the suites against a disposable PostgreSQL 18 container and is the merge gate.

When any task seems to require breaking one of these, stop and flag it rather than quietly deviating — it usually means the domain model needs an explicit extension (see §37 of DATABASE_CONVENTIONS.md on the convention-change process), not a one-off exception.

## 6. Conventions quick-reference

Full rules are in the linked docs — don't treat this as complete.

- **Database:** `snake_case`, plural table names, `<entity>_id` primary keys (never a bare `id`), always schema-qualified references, `TEXT` over `VARCHAR(n)`, `TIMESTAMPTZ` for real-world time vs. `core.world_times` for fictional time, lookup tables over `ENUM`, no tables in `public`. Search [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md) and read the sections governing the affected tables, constraints, migrations, grants, and tests before writing schema.
- **Python services:** organize around the command/query and domain-service layering in [docs/architecture/SYSTEM_ARCHITECTURE.md §5](docs/architecture/SYSTEM_ARCHITECTURE.md#5-layering); business mutations use commands. The API owns bounded audit and reservation writes inside the request transaction (§6–7).
- **Terraform:** one module per bounded infrastructure concern (mirroring the existing `database` / `secrets` split), one directory per environment under `terraform/environments/`, no hardcoded credentials, state and variable naming should mirror what's already in `terraform/modules/`.
- **React:** standard component-based structure; the UI is a client like any other — it talks to the application API, not the database.
- **New documentation** always goes under `docs/` — component READMEs own component-specific entry points. The only Markdown files at the repository root are `README.md` and this file, and the only one under `terraform/` is a short pointer to `docs/operations/optional-aws.md`.
- **Tests and tooling:** `pytest` layers (`tests/unit` with no database; `tests/database` and `tests/scenario` against an ephemeral database — on your local PostgreSQL 18 server during development, in disposable containerized PostgreSQL 18 in CI, per rule 11), `ruff format`/`ruff check`/`mypy src` before committing. Test production behavior and credible failure modes. Do not recursively fault-inject failures of test-only cleanup machinery without a concrete false-pass, persistent-leak, or CI-instability risk. **Full-suite runs use the shard runner**, `uv run python scripts/run_sharded_tests.py` (four shards at once by default, each on its own throwaway PostgreSQL 18 cluster, about 17 minutes; CI groups the same suite eight ways), not one serial `pytest` process (about 47 minutes); it covers all of `tests/`, so the non-pytest checks (`ruff format --check`, `ruff check`, `mypy src`, `uv lock --check`, `alembic check`, `git diff --check`) complete full backend verification. Keep using plain `uv run pytest <path>` for focused runs. Report a runner failure and its rerun separately. See [docs/DEVELOPMENT.md §6](docs/DEVELOPMENT.md#6-testing) and [§6.3](docs/DEVELOPMENT.md#63-running-the-ci-shards-locally-four-by-default-ci-uses-eight).

## 7. Before implementing a feature

1. Search [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) and [docs/architecture/DATABASE_MODEL.md](docs/architecture/DATABASE_MODEL.md) for the concepts and tables named by the task. Don't invent vocabulary without checking for an existing term.
2. Confirm the requested behavior fits the documented domain and architecture boundaries.
3. If it creates, mutates, or removes an entity, follow the matching command/workflow in [docs/ENTITY_LIFECYCLE.md](docs/ENTITY_LIFECYCLE.md).
4. Search [docs/DATABASE_CONVENTIONS.md](docs/DATABASE_CONVENTIONS.md) by mechanism (for example: foreign keys, ranges, triggers, concurrency, comments, migrations, or grants), read those sections, and check the applicable §34 anti-patterns before finishing.
5. For application code, read the affected layer and transaction sections in [docs/architecture/SYSTEM_ARCHITECTURE.md](docs/architecture/SYSTEM_ARCHITECTURE.md). For database-only work, do not preload unrelated API/service sections.
6. Read the relevant workflow plus [docs/DEVELOPMENT.md §10](docs/DEVELOPMENT.md#10-definition-of-done); do not load setup/walkthrough sections unless the task concerns setup or CI mechanics.
7. If the change introduces a new cross-cutting concept, update the relevant doc under `docs/` in the same change — these documents are meant to stay current, not drift from the implementation.
8. Record verification evidence when a delivery milestone closes. A bug caused by a convention being wrong is a documentation defect too — fix both.
9. Prefer the smallest test that proves a production invariant. Test-only work is blocking only when it can create a false result, persistent external-state leak, or repeatable CI instability.
