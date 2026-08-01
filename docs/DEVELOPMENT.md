# Development Guide

How to set up a working environment and make changes to this repository.

This document covers the **mechanics** — toolchain, layout, commands, workflow. It deliberately does not restate design rules; those live in [DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md), [architecture/SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md), and [ENTITY_LIFECYCLE.md](ENTITY_LIFECYCLE.md). Read [PLAN.md](PLAN.md) first to find the current phase.

---

## Table of Contents

- [1. Toolchain](#1-toolchain)
- [2. Repository layout](#2-repository-layout)
- [3. Local setup](#3-local-setup)
- [4. Database and migrations](#4-database-and-migrations)
- [5. Phase 1 walkthrough](#5-phase-1-walkthrough)
- [6. Testing](#6-testing)
- [7. Code quality](#7-code-quality)
- [8. Continuous integration](#8-continuous-integration)
- [9. Writing application code](#9-writing-application-code)
- [10. Definition of done](#10-definition-of-done)

---

## 1. Toolchain

These are the project defaults. They are decisions, not suggestions — an implementer should use them rather than introduce an alternative. Changing one follows the convention-change process in [DATABASE_CONVENTIONS.md §37](DATABASE_CONVENTIONS.md#37-convention-change-process): propose, record the rationale, update this document in the same change.

| Concern | Choice | Notes |
|---|---|---|
| Language | **Python 3.12+** | Pin the exact version in `pyproject.toml` via `requires-python` |
| Packaging / env | **uv** | `uv.lock` is committed; `uv sync` is reproducible. `pip install -r requirements.txt` is generated from it only where a runtime needs it (e.g. the migration runner, per [PLAN.md §29.6](PLAN.md#296-migration-execution-mechanism)) |
| Database driver | **psycopg 3** | Not psycopg2 |
| SQL toolkit | **SQLAlchemy 2.x Core** | Core, not the ORM. The domain model is class-table inheritance across bounded schemas with typed state tables; an ORM identity map fights that design more than it helps. Use `sqlalchemy.Table` metadata and explicit queries |
| Migrations | **Alembic** | Required by [DATABASE_CONVENTIONS.md §25.1](DATABASE_CONVENTIONS.md#251-migration-tool). Hand-written SQL inside revisions where a PostgreSQL feature is clearer than the DSL |
| Validation / DTOs | **Pydantic v2** | Command and query payloads at the API boundary |
| HTTP API | **FastAPI** | The API layer only ([SYSTEM_ARCHITECTURE.md §5.2](architecture/SYSTEM_ARCHITECTURE.md#52-api-layer)). The concrete REST shape is still deferred by [PLAN.md §27](PLAN.md#27-deferred-decisions) — this pins the framework, not the endpoint design |
| Tests | **pytest** against the deployed AWS `dev` RDS instance | Per [PLAN.md §23.0](PLAN.md#230-aws-verification-policy) and [§29.9](PLAN.md#299-aws-first-verification-mechanism) — not testcontainers. Constraint and trigger behavior cannot be tested against SQLite, and a local container is a different PostgreSQL than what's actually deployed |
| Property tests | **Hypothesis** | For the cases in [PLAN.md §25.4](PLAN.md#254-property-based-tests) |
| Lint + format | **ruff** | Both linting and formatting; no separate black/isort |
| Types | **mypy** | `strict` on `src/`; relaxed in tests |
| AWS access | **AWS CLI v2** | Required for all contributors, not just infrastructure work — see [§3](#3-local-setup). `curl` for IP lookup |
| Local database fallback | **Docker**, PostgreSQL pinned to the deployed major version | Only when AWS is genuinely unreachable, per [PLAN.md §23.0](PLAN.md#230-aws-verification-policy) — see the `testcontainers` fallback fixture in [§6](#6-testing) |
| UI | **React** | Not yet started; no build tooling chosen |

---

## 2. Repository layout

The tree below is the **target**. As of Phase 1, `database/`, `src/dnd_ai/`, and `tests/` exist with the scaffolding this phase requires (Alembic setup, the bootstrap and shared-domains revisions, seed infrastructure, the three test layers); the deeper `src/dnd_ai/` subpackages (`api/`, `commands/`, `queries/`, `domain/`, `ai/`, `integrations/`) do not — create each as the phase that needs it requires, not in advance.

```text
.
├── README.md                  # Project entry point
├── CLAUDE.md                  # AI assistant operating instructions
├── build.ps1                  # Terraform orchestration wrapper
├── pyproject.toml             # Python project + tool config (ruff, mypy, pytest)
├── uv.lock
├── .env.example
├── docs/                      # ALL documentation (see CLAUDE.md §6)
├── terraform/                 # Infrastructure (see docs/INFRASTRUCTURE.md)
├── scripts/
├── database/
│   ├── alembic.ini
│   ├── migrations/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/          # Revision files
│   ├── seeds/                 # Lookup-table seed data (§25.4 of conventions)
│   └── functions/             # SQL for stored functions, applied via revisions
├── src/
│   └── dnd_ai/
│       ├── api/               # FastAPI routers, request/response models
│       ├── commands/          # Command handlers — the only way to mutate state
│       ├── queries/           # Read models and query services
│       ├── domain/            # Domain services, invariants, entity logic
│       ├── persistence/       # Table metadata, repositories, effective-state functions
│       ├── ai/                # Context assembly, proposals, provider adapters
│       ├── integrations/      # FoundryVTT, Discord, MCP adapters
│       └── config.py
└── tests/
    ├── unit/                  # No database
    ├── database/              # Constraint, trigger, and invariant tests
    ├── scenario/              # Cross-domain flows (see PLAN.md §24)
    └── conftest.py
```

The directory names under `src/dnd_ai/` map onto the layers in [SYSTEM_ARCHITECTURE.md §5](architecture/SYSTEM_ARCHITECTURE.md#5-layering). Keep that mapping — it is how a reviewer checks that a handler didn't grow domain rules.

---

## 3. Local setup

Per [PLAN.md §23.0](PLAN.md#230-aws-verification-policy), development verifies against the deployed AWS `dev` RDS instance, not a local stand-in. Setting up means getting AWS access, not installing a local database.

```bash
# 1. Toolchain
#    Install uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync

# 2. AWS access — see CONTRIBUTING.md §2 for account setup and credential
#    configuration if you don't have these yet
aws sts get-caller-identity     # must succeed before anything else

# 3. Environment
cp .env.example .env    # then edit DATABASE_URL to point at the dev endpoint
```

Open a path to the shared `dev` RDS instance for the length of your session, per [PLAN.md §29.9](PLAN.md#299-aws-first-verification-mechanism) — `dev` is publicly reachable but gated by a security-group rule scoped to your current IP, opened and closed around your work rather than left standing:

```bash
scripts/aws-db-allow-my-ip.sh open    # authorizes your current IP on the dev security group
# ... do your work — alembic, pytest, psql ...
scripts/aws-db-allow-my-ip.sh close   # revokes it
```

Verify:

```bash
uv run alembic -c database/alembic.ini current
uv run pytest tests/unit          # no database, always runs
uv run pytest tests/database       # against dev RDS, needs the tunnel above open
```

**Fallback only** — if AWS is genuinely unreachable (no network, an account-wide outage), a local container is acceptable per [PLAN.md §23.0](PLAN.md#230-aws-verification-policy):

```bash
docker run -d --name dnd-ai-pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=dnd_ai \
  -p 5432:5432 \
  postgres:15
```

Point `DATABASE_URL` at it and set `DND_AI_USE_LOCAL_POSTGRES=1` so `tests/database`/`tests/scenario` use the local-container fixture instead of the AWS one (see [§6](#6-testing)). The container is disposable. Destructive reset tooling is allowed here and only here, per [DATABASE_CONVENTIONS.md §25.3](DATABASE_CONVENTIONS.md#253-no-destructive-initialization-scripts) — never write a `DROP ... CASCADE` reset script that could target a persistent environment.

---

## 4. Database and migrations

### Alembic configuration

Two settings are non-obvious and must be right, because this project puts **no tables in `public`** ([DATABASE_CONVENTIONS.md §3.1](DATABASE_CONVENTIONS.md#31-public-schema)):

- `version_table_schema` — put Alembic's own version table somewhere deliberate (`core` is reasonable), not `public`.
- `include_schemas=True` in `context.configure(...)`, so autogenerate sees all thirteen bounded schemas.

Autogenerate is a starting point, never the final artifact. It does not reliably produce partial unique indexes, check constraints, triggers, comments, or the class-table inheritance patterns this schema depends on. Always read and edit the generated revision.

### Writing a revision

```bash
uv run alembic -c database/alembic.ini revision -m "create core entities and entity types"
```

Every revision must contain what [DATABASE_CONVENTIONS.md §25.2](DATABASE_CONVENTIONS.md#252-migration-files) requires — purpose, forward migration, development rollback where feasible, data implications, locking considerations. Put those in the module docstring, not a commit message.

Additional rules that bite in this schema specifically:

- **Schema-qualify everything.** `REFERENCES core.entities(entity_id)`, never `REFERENCES entities(entity_id)` (§3.2).
- **Add table and column comments** in the same revision that creates the object (§31).
- **Index every foreign key** (§19.1) with the naming scheme in §19.2.
- **Subtype tables take the parent UUID as their primary key** — no new UUID per level (§7.3).

### Running

```bash
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini downgrade -1     # verify rollback before committing
uv run alembic -c database/alembic.ini history --verbose
```

Against a deployed environment, migrations do **not** run from a laptop — the instance is private. They run through the migration runner described in [PLAN.md §29.6](PLAN.md#296-migration-execution-mechanism), which does not exist yet.

---

## 5. Phase 1 walkthrough

[PLAN.md §23 Phase 1](PLAN.md#23-delivery-phases) is the current target. Its exit criteria are: an empty database can be created reproducibly, migrations run up and down in development, schema validation runs in CI, and a migration can be applied end-to-end against deployed AWS RDS using only Terraform-managed infrastructure.

Concretely, in order:

1. **Project skeleton** — `pyproject.toml` with the tools from §1, `uv.lock`, ruff/mypy/pytest configuration, `src/dnd_ai/` package root.
2. **Alembic scaffold** — `database/alembic.ini` and `database/migrations/`, configured per §4 above. Connection URL read from the environment, never hardcoded.
3. **The bootstrap revision** — the first revision, containing everything in [PLAN.md §29.5](PLAN.md#295-database-role-schema-and-extension-bootstrap):
   - `CREATE EXTENSION IF NOT EXISTS pgcrypto;` and `pg_trgm` (`vector` is deferred)
   - all thirteen schemas from [PLAN.md §3](PLAN.md#3-postgresql-schema-organization)
   - `REVOKE CREATE ON SCHEMA public FROM PUBLIC;`
   - the five database roles from [DATABASE_CONVENTIONS.md §27.1](DATABASE_CONVENTIONS.md#271-database-roles), each non-migration role created `WITH LOGIN` and granted `rds_iam`

   It must be idempotent and re-runnable. Treat it as a revision, not an untracked script, so it is versioned like everything else.
4. **Shared domains** — `core.rating_1_10`, `core.percentage_0_100`, `core.nonnegative_integer` per [PLAN.md §4.2](PLAN.md#42-shared-domains).
5. **Seed infrastructure** — the mechanism for idempotent lookup seeding (§25.4), not yet the seed content.
6. **CI workflow** — see §8 below.
7. **Migration runner** — `terraform/modules/db_migration_runner/`, per [PLAN.md §29.6](PLAN.md#296-migration-execution-mechanism). This is what closes the final exit criterion.

Steps 1–6 need no AWS access to *write*. Verifying them — actually running the migrations and the test suite — does, per [PLAN.md §23.0](PLAN.md#230-aws-verification-policy): both go against the deployed `dev` RDS instance, reached per [§3](#3-local-setup). Step 7 (the migration runner) is additionally what closes Phase 1's own AWS exit criterion for *deployed* migrations specifically — it's a distinct mechanism from the day-to-day test/dev reachability in §29.9, reserved for `staging`/`prod` where public access is never opened.

---

## 6. Testing

Three layers, matching [PLAN.md §25](PLAN.md#25-testing-strategy) and [DATABASE_CONVENTIONS.md §32](DATABASE_CONVENTIONS.md#32-testing-conventions):

| Layer | Location | Database | Purpose |
|---|---|---|---|
| Unit | `tests/unit/` | none | Pure logic — rules calculations, policy decisions, validation |
| Database | `tests/database/` | AWS `dev` RDS (ephemeral database per run) | Constraints, triggers, subtype consistency, same-world invariants, state uniqueness, branch behavior |
| Scenario | `tests/scenario/` | AWS `dev` RDS (ephemeral database per run) | Cross-domain flows, ultimately the full acceptance scenario in [PLAN.md §24](PLAN.md#24-vertical-slice-acceptance-scenario) |

Database and scenario tests connect to the `dev` endpoint (open the ingress rule per §3 first) and create a throwaway database per test session — `dnd_ai_test_<run-id>` — migrated to head and dropped afterward, per [PLAN.md §29.9](PLAN.md#299-aws-first-verification-mechanism). This gives per-run isolation on the one shared instance without needing a database-per-developer.

```bash
uv run pytest                    # everything
uv run pytest tests/unit         # fast loop, no AWS needed
uv run pytest tests/database -x  # needs the dev ingress rule open, see §3
```

**Fallback only**: set `DND_AI_USE_LOCAL_POSTGRES=1` with `DATABASE_URL` pointed at a local container to run `tests/database`/`tests/scenario` against testcontainers instead, when AWS is genuinely unreachable (§3). This is not the default path and should not be what CI or day-to-day development relies on.

Two rules that matter more here than in a typical project:

- **Every nontrivial constraint gets a positive *and* a negative test** (§32.1). The schema encodes domain invariants; an untested `CHECK` is an unverified rule.
- **Build test data through the same commands production uses** (§32.3). Inserting rows directly bypasses the subtype and state invariants that are the thing under test. Exception: a test whose subject *is* invalid data.

---

## 7. Code quality

```bash
uv run ruff format .
uv run ruff check . --fix
uv run mypy src
```

Run all three before committing. CI runs them without `--fix`.

---

## 8. Continuous integration

`.github/workflows/ci.yml` covers, per [PLAN.md Phase 1](PLAN.md#23-delivery-phases), [§23.0](PLAN.md#230-aws-verification-policy), and [DATABASE_CONVENTIONS.md §25.6](DATABASE_CONVENTIONS.md#256-migration-testing):

- `ruff format --check`, `ruff check`, `mypy src`
- authenticate to AWS (a scoped IAM identity, credentials from repository secrets) and open a short-lived ingress rule on the `dev` security group for the runner's own egress IP, per [PLAN.md §29.9](PLAN.md#299-aws-first-verification-mechanism)
- migration from an **empty** database (a fresh `dnd_ai_ci_<run-id>` database on the `dev` instance) through all revisions to head
- schema comparison — autogenerate against head must produce an empty diff, proving migrations and metadata agree
- downgrade of recent development migrations where supported
- the full pytest suite against that same ephemeral database
- drop the ephemeral database and revoke the ingress rule — in a step that always runs, including on job failure, so a broken run doesn't leave a stale allowlist entry or an orphaned database behind

Seed idempotency (seeding twice yields the same state) is not yet a CI step — `apply_seed()` in `src/dnd_ai/persistence/seeds.py` exists, but no revision calls it with real seed content yet. Add that check to the workflow in the same change that introduces the first seed file.

A pull request that changes schema without a green migration job should not merge.

---

## 9. Writing application code

Layer placement is the thing reviewers check first. From [SYSTEM_ARCHITECTURE.md §5](architecture/SYSTEM_ARCHITECTURE.md#5-layering):

- `api/` — authentication, authorization, input validation, routing, response shaping. **No domain rules.**
- `commands/` — the only path that mutates state. Each handler owns its transaction boundary and follows the ten steps in [SYSTEM_ARCHITECTURE.md §6](architecture/SYSTEM_ARCHITECTURE.md#6-command-and-query-separation).
- `queries/` — reads only. Never mutates.
- `domain/` — invariants, allowed transitions, event construction, knowledge visibility. No HTTP or framework types.
- `persistence/` — table metadata, repositories, effective-state functions. Timeline and branch resolution lives here and is called, not reimplemented, by other layers.

Recurring requirements when writing a command:

- One PostgreSQL transaction per world change ([§7](architecture/SYSTEM_ARCHITECTURE.md#7-transaction-boundary)). External calls to AI providers, Discord, or Foundry go **after** commit, never inside the transaction.
- A state change needs a causal event, and both commit atomically (rule 6 in [CLAUDE.md](../CLAUDE.md#5-non-negotiable-architectural-rules)).
- Entity creation, mutation, archival, and deletion follow the specific command in [ENTITY_LIFECYCLE.md](ENTITY_LIFECYCLE.md) — including its required transaction steps.
- Support idempotency keys on externally-triggered commands (§26.4).

---

## 10. Definition of done

Before opening a pull request:

- [ ] The work matches the current phase in [PLAN.md](PLAN.md), or the deviation is stated explicitly
- [ ] Schema changes follow [DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md), checked against the anti-patterns in §34
- [ ] New tables and important columns carry comments (§31)
- [ ] Migration runs up **and** down cleanly against a fresh ephemeral database on the AWS `dev` instance (§3, §6) — a local database only if AWS was genuinely unreachable, noted as such
- [ ] Constraints have positive and negative tests
- [ ] Code sits in the layer [SYSTEM_ARCHITECTURE.md §5](architecture/SYSTEM_ARCHITECTURE.md#5-layering) prescribes
- [ ] `ruff format --check`, `ruff check`, `mypy src`, and `pytest` all pass
- [ ] No secret, credential, or connection string is committed
- [ ] Any new cross-cutting concept is reflected in the relevant `docs/` file **in the same change** — these documents are meant to stay current, not be reconciled later
