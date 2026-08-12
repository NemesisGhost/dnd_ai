# Development Guide

How to set up a working environment and make changes to this repository.

This document covers the **mechanics** — toolchain, layout, commands, workflow. It deliberately does not restate design rules; those live in [DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md), [architecture/SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md), and [ENTITY_LIFECYCLE.md](ENTITY_LIFECYCLE.md). Start with [CLAUDE.md §4](../CLAUDE.md#4-documentation-map-and-context-loading-policy), then read [PLAN.md §23.0–23.1](PLAN.md#23-delivery-phases) and the current phase entry rather than loading the whole plan.

---

## Table of Contents

- [1. Toolchain](#1-toolchain)
- [2. Repository layout](#2-repository-layout)
- [3. Local setup](#3-local-setup) (including [§3.6 Self-hosted Docker Compose](#36-self-hosted-docker-compose))
- [4. Database and migrations](#4-database-and-migrations)
- [5. Phase 1 walkthrough (complete)](#5-phase-1-walkthrough-complete)
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
| Tests | **pytest** against a local/self-hosted PostgreSQL 18 server; CI repeats them against a disposable containerized PostgreSQL 18 instance | Per [PLAN.md §24.0](PLAN.md#240-verification-policy). Constraint and trigger behavior cannot be tested against SQLite or any other engine, so every layer below `tests/unit` needs a real PostgreSQL |
| Property tests | **Hypothesis** | For the cases in [PLAN.md §25.4](PLAN.md#254-property-based-tests) |
| Lint + format | **ruff** | Both linting and formatting; no separate black/isort |
| Types | **mypy** | `strict` on `src/`; relaxed in tests |
| Development database | **PostgreSQL 18.x**, local install or `compose.yaml` | The default development and test target ([PLAN.md §24.0](PLAN.md#240-verification-policy), [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)). The major version must match everywhere it runs — see [DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version). Setup: [§3](#3-local-setup) |
| Self-hosted deployment | **Docker Compose** (`compose.yaml`, `Dockerfile`) | The officially supported deployment topology ([ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)). One shared image for migrations today, API/worker/adapter once they exist |
| AWS access (optional) | **AWS CLI v2** | Only needed if you choose to deploy the optional AWS RDS path under `terraform/`, or to change that Terraform — **not** for routine schema or application work, and not for CI. `curl` for IP lookup |
| UI | **React** | Not yet started; no build tooling chosen |

---

## 2. Repository layout

The tree below is the **target**. As of Phase 6, `database/` holds the migrations and seed files, `src/dnd_ai/persistence/` holds the table metadata and seed machinery, `src/dnd_ai/commands/` holds the first command handlers (`record_event`, `perform_interaction`, `resolve_check`), and `tests/` holds all three layers plus shared factories. The remaining `src/dnd_ai/` subpackages (`api/`, `queries/`, `domain/`, `ai/`, `integrations/`) do not exist yet — create each as the phase that needs it requires, not in advance. `commands/` itself stayed thin: no `domain/` layer was needed yet because the invariants a command has to satisfy (world consistency, ruleset allow-lists, the conditional-route decision) already live in triggers and `world.conditional_route_requirement_satisfied()` — a command calls those rather than re-deriving them in Python.

```text
.
├── README.md                  # Project entry point
├── CLAUDE.md                  # AI assistant operating instructions
├── build.ps1                  # Terraform orchestration wrapper (optional AWS path)
├── pyproject.toml             # Python project + tool config (ruff, mypy, pytest)
├── uv.lock
├── .env.example
├── Dockerfile                 # The one image all services run from (PLAN.md §31.3)
├── compose.yaml               # Self-hosted deployment topology (ADR 0012) — no default password, no default port
├── compose.override.yaml      # Auto-loaded local-dev convenience: 127.0.0.1-only port
├── compose.ci.yaml            # CI override: disposable tmpfs storage
├── .dockerignore
├── docs/                      # ALL documentation (see CLAUDE.md §4)
├── terraform/                 # Optional AWS infrastructure (see docs/INFRASTRUCTURE.md)
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

There is one `Dockerfile`, not one per service: the API, background worker, Discord adapter, and one-off jobs including migrations all run the same image with different entrypoints ([PLAN.md §31.3](PLAN.md#313-packaging-and-release)). It exists today and runs Alembic migrations by default (`compose.yaml`'s `migrate` job); `src/dnd_ai/api` has no committed source yet, so the API/worker/adapter entrypoints are added when those modules exist.

### 2.1 Keep source and tests bounded by domain

Repository structure is also a context boundary. Do not keep adding unrelated domains or correction passes to a file merely because the file already exists.

**Done.** The monolithic `src/dnd_ai/persistence/tables.py` was replaced with a `src/dnd_ai/persistence/tables/` package organized by bounded schema/domain, verified against AWS `dev` (`alembic check` reported no diff; the full `tests/unit`/`tests/database` suites pass). The shape, kept as the ongoing convention for where a new table goes:

```text
src/dnd_ai/persistence/tables/
├── __init__.py       # imports every domain module; preserves public re-exports
├── _shared.py        # the one MetaData object and shared table helpers
├── security.py
├── core.py
├── audit.py
├── campaign.py
├── rules.py
├── characters.py
├── locations.py
└── knowledge.py
```

Requirements for that split:

- It is a mechanical refactor: no migration behavior, schema operation, revision identity, or chain topology changed, and no table/column name, constraint, comment, or server-default changed. One migration, `036_remaining_rule_content_immutability`, received a documentation-only fix as part of this split: its docstring's "See:" pointer to the test file covering it was updated from the deleted `test_phase4_remaining_issues.py` to its replacement, `test_immutable_identity.py` — no change to `upgrade()`, `downgrade()`, or any other migration behavior.
- All table declarations use the one `MetaData` instance from `_shared.py`. `tables/__init__.py` imports every domain module so Alembic still receives complete metadata, and it re-exports existing public names so current imports remain compatible.
- Cross-domain foreign keys remain schema-qualified strings. Domain modules must not import each other's table objects merely to declare a foreign key; this keeps import order acyclic.
- Add a focused metadata-completeness test that compares expected schema-qualified table names/public exports before and after the split, then require `alembic check` to prove no schema diff.
- Put a new table in the module that owns its PostgreSQL schema/domain. If a module becomes large enough that an unrelated task must scan past several separate concerns, split it again by a stable subdomain rather than by implementation phase.

Database tests follow the invariant they protect, not the phase or review pass that discovered them. **Done.** `test_phase4_corrections.py` and `test_phase4_remaining_issues.py` — the historical accretion points — were split without weakening any assertion into `test_session_chronology.py`, `test_ruleset_provenance.py`, `test_ruleset_version_consistency.py`, `test_immutable_identity.py`, `test_world_ruleset_dependency_and_concurrency.py`, `test_character_language_integrity.py`, and `test_metadata_server_defaults.py` (366 tests collected before and after). Two small cross-topic helpers (`make_bare_ruleset`, `current_ruleset_version_id`) moved to `tests/factories.py` rather than being copied into every file that needed them; per-file fixtures small enough not to be worth sharing (for example each topic file's own `world_id`) were duplicated instead, consistent with the "large fixture block" threshold below.

New closeout tests go directly into the stable topic file. A temporary phase-named test file is allowed while a register is open, but closing the register includes distributing those tests by invariant and removing the temporary file. Historical verification documents record why a test exists; the active test filename records what it protects.

---

## 3. Local setup

Per [PLAN.md §24.0](PLAN.md#240-verification-policy) and [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md), development runs against a **local or self-hosted PostgreSQL 18 server**. No AWS account, no credentials, and no network are needed for schema or application work — CI verifies the same work against a disposable containerized PostgreSQL 18 instance when you push ([§8](#8-continuous-integration)).

### 3.1 PostgreSQL

Install PostgreSQL **18.x** — the version this project pins everywhere ([DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version)). A different major version is a setup defect: it produces green local runs that fail CI.

Two ways to get it, pick one:

| Option | How |
|---|---|
| `compose.yaml` (recommended) | `docker compose up -d db` — starts PostgreSQL 18.4 with persistent storage, no local install needed. See [§3.6](#36-self-hosted-docker-compose) |
| Native install | Windows: [EDB installer](https://www.postgresql.org/download/windows/), or `winget install PostgreSQL.PostgreSQL.18` (installs as the `postgresql-x64-18` service, started automatically). macOS: `brew install postgresql@18 && brew services start postgresql@18`. Linux: [PGDG apt/yum repository](https://www.postgresql.org/download/), then `postgresql-18` |

Confirm the server is up and on the right version before going further:

```bash
psql --version                  # must report 18.x
pg_isready                      # must report "accepting connections"
```

### 3.2 Database and superuser

The project's own roles (`migration_owner`, `app_read_write`, and the rest) are created **by the `001_bootstrap` migration**, not by hand — that is what keeps local and `dev` in agreement ([PLAN.md §29.9](PLAN.md#299-shared-dev-verification-mechanism-ci)). All you create manually is the database and a connecting superuser for the migrations to run as, standing in for the RDS master user.

```bash
# `postgres` superuser already exists from the install; use it directly, or
# create a named one if you prefer not to.
createdb -U postgres dnd_ai
```

On Windows the client tools are not on `PATH` by default; either add `C:\Program Files\PostgreSQL\18\bin` to it or invoke them by full path.

> The bootstrap revision issues `GRANT rds_iam` only when that role exists, so it is a no-op locally — `rds_iam` is an RDS-managed role with no local equivalent. This is deliberate and is one of the few places the two targets legitimately differ; see [ADR 0009](adr/0009-separate-owning-role-from-login-roles.md) for why that grant is conditional at all.

### 3.3 Toolchain and environment

```bash
# Install uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync

cp .env.example .env    # defaults already point at a local server
```

`DATABASE_URL` should name the local superuser connection — the migrations `SET ROLE migration_owner` themselves:

```
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/dnd_ai
```

No `sslmode=require` locally: a stock local server has no TLS configured, whereas `dev` enforces SSL and rejects a plain connection outright (`FATAL: no pg_hba.conf entry for host "...", ... no encryption`) — that asymmetry is the single most common surprise when you do connect to `dev`. On earlier RDS PostgreSQL versions this showed up as an `rds.force_ssl` parameter; as of the PostgreSQL 18 replacement ([POSTGRES18_UPGRADE_PLAN.md](POSTGRES18_UPGRADE_PLAN.md)) that GUC no longer exists at all (confirmed absent from `pg_settings`) — enforcement moved to `pg_hba.conf`, verified directly rather than by parameter inspection.

### 3.4 Verify

```bash
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini current

uv run pytest tests/unit           # no database
uv run pytest tests/database       # against your local server
```

`tests/database` and `tests/scenario` create their own throwaway database per session and drop it afterward ([§6](#6-testing)), so the `dnd_ai` database you just created is for manual inspection with `psql`, not what the suite uses.

Your local server is **disposable** — it holds nothing that isn't reproducible from migrations plus seeds, and it is not backed up. Destructive reset tooling is allowed here and only here, per [DATABASE_CONVENTIONS.md §25.3](DATABASE_CONVENTIONS.md#253-no-destructive-initialization-scripts) — never write a `DROP ... CASCADE` reset script that could target a persistent environment.

### 3.5 Connecting to AWS `dev` (optional, no longer required)

AWS RDS is an optional, no-longer-CI-verified path ([ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)) — you need this only if you have deployed the Terraform under `terraform/` yourself and want to reproduce a failure against it or inspect it directly. Setup is [CONTRIBUTING.md §2](CONTRIBUTING.md#2-aws-access-optional). `dev`, if deployed, is publicly reachable but gated by a security-group rule scoped to your current IP, opened and closed around your work rather than left standing ([PLAN.md §30.9](PLAN.md#309-shared-dev-verification-mechanism-ci)):

```bash
scripts/aws-db-allow-my-ip.sh open    # authorizes your current IP on the dev security group
# ... point DATABASE_URL at the dev endpoint (note sslmode=require) and work ...
scripts/aws-db-allow-my-ip.sh close   # revokes it — nothing does this automatically
```

Leaving that rule open is the failure mode to watch for; close it in the same session you opened it.

### 3.6 Self-hosted Docker Compose

`compose.yaml` at the repository root is the officially supported way to run PostgreSQL for both everyday development and a real self-hosted deployment ([ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)). It needs only Docker — no PostgreSQL install, no AWS account.

**Required setup — `compose.yaml` will not start (`up`) or run migrations without it:**

```bash
cp .env.example .env
# edit .env: uncomment POSTGRES_PASSWORD and set a real value, then set
# MIGRATION_DATABASE_URL and DATABASE_URL's password segments to match it
```

There is deliberately **no fallback password** anywhere in `compose.yaml` — not even for local development — so nothing in this repository ships a working default credential. `docker compose up` fails immediately with a clear message if `POSTGRES_PASSWORD` isn't set, rather than silently starting with a guessable one; `docker compose --profile tools run --rm migrate` likewise refuses to run without `MIGRATION_DATABASE_URL`. Three separate settings must be kept in sync by hand — nothing derives one from another:

- `POSTGRES_PASSWORD` — read by `docker compose` to initialize PostgreSQL.
- `MIGRATION_DATABASE_URL` — the complete SQLAlchemy URL the `migrate` service connects with, addressing `db` (the compose service name) over the compose-internal network.
- `DATABASE_URL` — read by the application/tests running on the host, addressing `localhost` (reachable only via `compose.override.yaml`'s port — see below).

`MIGRATION_DATABASE_URL` and `DATABASE_URL` are not assembled from `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` by Compose interpolation — that would be plain string substitution, not a URL encoder, and would silently break for a password containing characters that are special in a URL (`@ : / ? # [ ] %` and similar). Build each URL yourself and percent-encode the password segment if it needs one (Python: `urllib.parse.quote(password, safe="")`) — see `.env.example` for a worked example.

**Start and stop:**

```bash
docker compose up -d db      # start PostgreSQL 18.4 in the background
docker compose ps            # check status/health
docker compose down          # stop; data persists in the dnd_ai_pgdata volume
docker compose down -v       # stop and delete the data volume — destructive, confirm first
```

Plain `docker compose` commands with no `-f` flags auto-load `compose.override.yaml` alongside `compose.yaml`, which publishes PostgreSQL on `127.0.0.1:5432` — convenient for connecting a local `psql`/GUI client. **The base `compose.yaml` alone publishes no host port at all**, by design: a self-hosted deployment run explicitly as `docker compose -f compose.yaml up -d db` (bypassing the override) exposes nothing beyond the Docker network, which is what `compose.ci.yaml`'s CI usage and any real external-facing deployment should build from. If you need real external access to a self-hosted database, add your own deliberate, reviewed port mapping (and firewall rules) rather than reusing `compose.override.yaml`'s convenience default.

**Configuration** is environment-variable driven, with no committed secrets — copy `.env.example` to `.env` and adjust, or export the variables directly:

| Variable | Default | Purpose |
|---|---|---|
| `POSTGRES_USER` | `postgres` | Superuser the migrations connect and `SET ROLE migration_owner` as |
| `POSTGRES_PASSWORD` | *(none — required)* | No fallback; `docker compose up` refuses to start without it. Any value is fine, including one containing URL-special characters — Compose passes it to PostgreSQL directly, it is not embedded in a URL here |
| `POSTGRES_DB` | `dnd_ai` | Database name |
| `POSTGRES_PORT` | `5432` | Host port PostgreSQL is published on — only takes effect via `compose.override.yaml` (local development); the base topology publishes nothing |
| `MIGRATION_DATABASE_URL` | *(none — required for `migrate`)* | The complete SQLAlchemy URL the `migrate` service connects with (host `db`, not `localhost`) — see the required-setup note above for why this is a separate variable, not derived from the three above |

**Running migrations** against the composed database:

```bash
docker compose --profile tools run --rm migrate
```

This builds the same `Dockerfile` image the future API/worker/adapter services will share and runs `alembic -c database/alembic.ini upgrade head` against `db` over the compose-internal network — it needs no published host port. It is not started by plain `docker compose up` — `profiles: ["tools"]` keeps it a deliberate one-off action, not a standing service.

Running the test suite or `uv run alembic` from the host against the composed database works the same way it does against a native install — point `DATABASE_URL` at `postgresql+psycopg://postgres:<your POSTGRES_PASSWORD>@localhost:5432/dnd_ai` (this needs `compose.override.yaml`'s port, i.e. plain `docker compose up -d db` with no `-f` flags) and follow [§3.4](#34-verify).

**Backup and upgrade responsibilities.** Unlike the disposable local server described in [§3.4](#34-verify), a self-hosted deployment's `dnd_ai_pgdata` volume is expected to hold real, non-reproducible data, and nothing here backs it up automatically — that is the self-hosting operator's responsibility, unlike the AWS RDS path's automated backups ([INFRASTRUCTURE.md §1](INFRASTRUCTURE.md#1-current-state)).

Every destructive operation below — backup, restore, role bootstrap, verification, and teardown — runs through one production tool, **`scripts/operations/database_recovery.py`**, instead of hand-duplicated Bash and PowerShell command blocks. That tool exists specifically because duplicated command blocks drift: flags, environment files, image overrides, and variable names have repeatedly gone out of sync between the Bash and PowerShell copies of this section in past revisions of this document. The script:

- Requires an explicit `--project`, `--env-file`, and at least one `--compose-file` on every invocation — never a default `.env`, never Compose's own project-name discovery.
- Builds every subprocess call from an explicit argument list (never a shell string), so a database name or file path can never be reinterpreted as a shell operator.
- Refuses to run if any of `--project`/`--env-file`/`--compose-file`/`--db-user`/`--db-name` still contains an unfilled placeholder like `<...>`.
- Prints the selected project, environment file, Compose files, and database before doing anything destructive.
- Never opens or reads an `--env-file` itself, and never prints a secret — it only ever passes `--env-file <path>` through to `docker compose`, which resolves `POSTGRES_PASSWORD`/`MIGRATION_DATABASE_URL` itself.
- Requires an explicit `--confirm-drop`, `--confirm-restore`, or `--confirm-teardown` flag before the corresponding destructive step runs.
- Never deletes a volume, and never deletes evidence (an in-container dump copy, a temporary bootstrap database) left behind by a failed operation — inspect it, then clean it up by hand once you're done.

It is cross-platform (Python 3.12, run the same way from Bash or PowerShell), so this section shows one command block per operation rather than two. The handful of steps that remain outside the script — starting the cluster, confirming which project you're pointed at, quiescing external consumers, creating a disposable environment file — are non-destructive or cannot be automated from outside, and stay as direct commands.

Run it with `uv run python scripts/operations/database_recovery.py <command> --help` for the full flag reference; every example below is a complete, runnable invocation. A few procedures below (the drill, and the major-version experiment/cutover) need a uniquely generated project name — those show both a Bash and a PowerShell block for *generating* the name, since the two shells' variable syntax genuinely differs, but only one command block afterward, in Bash style (`$DND_TEST_PROJECT` and similar, all-caps with underscores); PowerShell users substitute their own variable from the block above (e.g. `$DndTestProject`) everywhere the Bash block references it.

#### Concepts and state boundaries

**What a `pg_dump` backup does *not* cover.** `pg_dump` captures exactly one database's schemas, tables, data, and the grants recorded inside that database — nothing that lives outside it. PostgreSQL roles (`CREATE ROLE ...`) are **cluster-wide**, not database-local: they live in the cluster's shared catalog rather than inside any one database, so `pg_dump -d dnd_ai` never includes them. This project's six roles — `migration_owner`, `migration_runner`, `app_read_write`, `app_read_only`, `integration_worker`, `admin_maintenance` — are created once, cluster-wide, by the `001_bootstrap` Alembic revision ([DATABASE_CONVENTIONS.md §27.1](DATABASE_CONVENTIONS.md#271-database-roles)), and every schema object and default privilege throughout the database is owned by, or granted to, one of them. **A `dnd_ai.dump` file by itself is not a complete recovery artifact for a brand-new PostgreSQL cluster** — restoring it onto a fresh server with no roles yet created fails as soon as `pg_restore` reaches the first statement referencing `migration_owner` or any of the other five.

The repository-native fix is to let Alembic recreate the roles before restoring data — the same `001_bootstrap` revision that created them on the original server, applied to the fresh one. `restore` (below) does this for you, in the right order for whichever of fresh-cluster or existing-cluster mode applies. (`pg_dumpall --globals-only` is a built-in alternative for capturing roles; it's discussed, and why it isn't the default recommendation here, further down.)

**What role bootstrap does *not* recover.** Recreating the six *role definitions* — and the grants/ownership `001_bootstrap` assigns to them — is not the same as reproducing everything about the roles' live state on the server you backed up from:

- **`pg_dump` never includes cluster roles at all** — not their existence, not their passwords, not their attributes.
- **Alembic recreates the repository-defined roles and grants**, exactly as `001_bootstrap` defines them. That's schema-level structure, not credentials.
- **Not recovered by either the dump or the migration**: any password set on a login role after `001_bootstrap` created it, credentials issued by an external identity system, role memberships added by hand after bootstrap, `ALTER ROLE ... SET` session defaults, or any other post-deployment role change.
- **After restoring onto a new cluster, rotate or reapply runtime credentials yourself**, as a deliberate step — from your deployment's own secret-management process, never the dump file, this documentation, or the repository. `restore` (below) prints a reminder of this at the end; it does not and cannot do it for you.
- If your deployment currently connects to PostgreSQL as the bootstrap superuser (`POSTGRES_USER`, `postgres` by default) rather than one of the five login roles, that is acceptable only because today's topology runs nothing but `alembic upgrade head` against the database — not the intended eventual model once `src/dnd_ai/api` exists ([DATABASE_CONVENTIONS.md §27.1](DATABASE_CONVENTIONS.md#271-database-roles)).

Do not "solve" any of the above by indiscriminately restoring a `pg_dumpall --globals-only` capture — see why, further down.

**What dropping and recreating the database loses.** Recreating the target database is deliberate — it guarantees a clean target for `pg_restore` — but "roles survive it" is not the same claim as "everything is fine afterward." Three categories of state behave three different ways:

- **Cluster-wide state survives untouched**: the six roles, their attributes, and role-to-role memberships all live in the cluster's shared catalog, not any one database.
- **Database-local state is restored by `pg_restore`** from the dump: schema/table ownership, `ALTER DEFAULT PRIVILEGES` entries, schema- and table-level grants, and installed extensions.
- **One piece of database-local state is restored by neither, and must be reapplied explicitly**: `001_bootstrap` also runs `GRANT CREATE ON DATABASE <db> TO migration_owner` — a privilege on the *database object itself*, recorded in `pg_database.datacl`, not on anything inside it. A plain `pg_dump -Fc` (no `--create`) never captures this. Missing it doesn't fail loudly — a recovered deployment can look completely fine until a later migration needs `CREATE EXTENSION`, and only then fails with a permission error. **`restore` reapplies this grant automatically**, immediately after recreating the database and before restoring the dump, using the same safe psql-variable/`\gexec` mechanism documented in `_grant_create_on_database`'s docstring in the script itself — never raw string interpolation of the database name into SQL. `verify` checks for it directly afterward.

**Confirm the project before doing anything destructive.** `database_recovery.py` never guesses or defaults a project name — but you still have to know it. Compose defaults `COMPOSE_PROJECT_NAME` to the containing directory's name unless a deployment sets it explicitly:

```bash
docker compose -p "<your-project>" -f compose.yaml ps
```

If that doesn't show the deployment you intend to act on, stop — confirm the right project name before continuing. `-f compose.yaml` only (no other `-f`, and no auto-loaded `compose.override.yaml`) means this, and every command below, never publishes a host port.

The `db` service's health check (`pg_isready`) deliberately targets the always-present `postgres` maintenance database, not the application database — see `compose.yaml`'s `healthcheck:` comment. That matters here specifically because restoring drops and recreates the application database: a health check pointed at it would either hold a connection that blocks the drop, or report the container unhealthy for the window between drop and recreate.

#### Backup

Dumps a database to a host file, cleaning up its own temporary in-container copy:

```bash
uv run python scripts/operations/database_recovery.py backup \
  --project "<your-project>" \
  --env-file .env \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --output "./dnd_ai-$(date +%Y%m%d).dump"
```

`-Fc` (custom format, compressed) is always used — it's the only format `restore` accepts. The result is an ordinary host file, not scoped to any Compose project: back it up like any other file (off-host copy, versioned storage, whatever your deployment needs), and reuse it with the drill or a real restore below. Per "Concepts" above, it's a **database-only** artifact — recovering onto a brand-new cluster also needs the role-recreation step built into `restore`. Pass `--overwrite` to replace an existing output file; without it, `backup` refuses to clobber one.

#### Fresh-cluster restore

Use this when standing up a **brand-new PostgreSQL cluster** — a new self-hosted deployment, an isolated restore drill, or a project-wide-adopted major-version cutover (below). There is no existing application database to protect; the one PostgreSQL's container init creates from `POSTGRES_DB` is disposable, and `restore --mode fresh` treats it that way.

```bash
docker compose -p "<your-project>" -f compose.yaml up -d --wait db

uv run python scripts/operations/database_recovery.py restore \
  --project "<your-project>" \
  --env-file .env \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --dump-file ./dnd_ai-20260811.dump \
  --mode fresh \
  --confirm-drop \
  --confirm-restore
```

In fresh-cluster mode, `restore`:

1. Runs the `migrate` service directly against the database that PostgreSQL's own container init already created — this **is** the "temporary/bootstrap application database": on a genuinely fresh cluster it holds nothing yet, so migrating it to create the six roles, extensions, schemas, and current schema objects costs nothing.
2. Verifies all six roles exist (via the `postgres` maintenance database), stopping if they don't.
3. Force-drops and recreates that same database, reapplies the `CREATE ON DATABASE` grant `dropdb`/`createdb` just discarded, and restores your dump into it.

**Restoring a dump created by a newer application/schema revision into an older application image is unsupported** — make sure the `migrate` image you're running already knows about the dump's revision (or later) before proceeding.

After it finishes: reapply or rotate runtime credentials for `migration_runner`/`app_read_write`/`app_read_only`/`integration_worker`/`admin_maintenance` from your own secret-management process (`restore` prints this reminder; it can't do it for you — see "What role bootstrap does not recover" above), then run `verify` (below) before treating the deployment as authoritative.

#### Existing-cluster restore

Use this when the **cluster itself survives** but the application database is gone, corrupt, or otherwise unusable — an ordinary in-place recovery, not a new cluster. The key difference from fresh-cluster mode: migrations must never be asked to connect to a database that might not exist or might be the thing that's broken.

**Quiesce every other consumer first** — `dropdb --force` (step below) disconnects anything still connected, and discovering what was still connected *while* it happens is worse than confirming there's nothing left beforehand. Stop the future API service, background worker, Discord/FoundryVTT adapters, or any other process connected to the target database (none exist as committed services yet — `src/dnd_ai/api` has no source, per [§2](#2-repository-layout) — so this is a no-op today, but becomes **mandatory** once any of them does), and close any interactive `psql`/GUI session or scheduled job. Re-confirm the project immediately before continuing:

```bash
docker compose -p "<your-project>" -f compose.yaml ps
```

```bash
uv run python scripts/operations/database_recovery.py restore \
  --project "<your-project>" \
  --env-file .env \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --dump-file ./dnd_ai-20260811.dump \
  --mode existing \
  --confirm-drop \
  --confirm-restore
```

In existing-cluster mode, `restore` **verifies the six roles against the `postgres` maintenance database first, without ever connecting to the (possibly missing or corrupt) target database.** If all six check out, it proceeds straight to force-drop/recreate/regrant/restore, exactly as above, with no Alembic connection to the damaged database required beforehand. If any role or the `migration_runner` → `migration_owner` membership is missing, `restore` stops immediately and does not touch the target database at all — migrations normally target an application database, and they cannot bootstrap roles through a database that doesn't yet exist or isn't reachable.

**If roles are missing, bootstrap them into a deliberately named temporary database first** — never the real recovery target, so a partially-migrated attempt never overloads or gets confused with it:

```bash
cat > .env.bootstrap <<'EOF'
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<the same password this cluster's real POSTGRES_USER already has>
POSTGRES_DB=dnd_ai
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:<the same password>@db:5432/dnd_ai_bootstrap_tmp
EOF
```

```powershell
$envContent = @"
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<the same password this cluster's real POSTGRES_USER already has>
POSTGRES_DB=dnd_ai
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:<the same password>@db:5432/dnd_ai_bootstrap_tmp
"@
[System.IO.File]::WriteAllText("$PWD\.env.bootstrap", $envContent, [System.Text.UTF8Encoding]::new($false))
```

Note the URL's database name — `dnd_ai_bootstrap_tmp`, not the real target — is the only thing that needs to differ from your real deployment's own connection details; `POSTGRES_USER`/`POSTGRES_PASSWORD` are this cluster's actual superuser credentials, because bootstrap-roles is creating roles on your **real** cluster, just inside a throwaway database on it. `.env.bootstrap` is not committed (`.gitignore`'s `.env.*` pattern covers it); remove it once you're done, the same as any other short-lived credential file.

```bash
uv run python scripts/operations/database_recovery.py bootstrap-roles \
  --project "<your-project>" \
  --env-file .env.bootstrap \
  --compose-file compose.yaml \
  --connect-user postgres \
  --temp-db-name dnd_ai_bootstrap_tmp \
  --protect-db-name dnd_ai \
  --confirm-env-targets-temp-db
```

This creates `dnd_ai_bootstrap_tmp`, migrates it (creating the six roles), verifies them, and — only once verification passes — drops that temporary database again. `--protect-db-name` is a safety guard: `bootstrap-roles` refuses to run if `--temp-db-name` equals it. `--confirm-env-targets-temp-db` is a required acknowledgment that `.env.bootstrap`'s `MIGRATION_DATABASE_URL` actually points at the temporary database — the script never opens that file to check for you, since it never reads secrets. If role verification fails after migrating, the temporary database is left in place for inspection rather than silently dropped.

Once roles are confirmed, re-run the `restore --mode existing` command above — it will now find all six roles and proceed. After it finishes, reapply/rotate runtime credentials and run `verify`, the same as fresh-cluster mode.

#### Verification

Run this after any restore, before treating a deployment as authoritative:

```bash
uv run python scripts/operations/database_recovery.py verify \
  --project "<your-project>" \
  --env-file .env \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --check "SELECT count(*) FROM core.worlds" "3"
```

`verify` runs the complete acceptance battery in one command — nothing here is left as "adapt the query yourself":

- **Role verification**, repeated as part of acceptance (all six roles, correct LOGIN/NOLOGIN, `migration_runner` membership).
- **`migration_owner`'s `CREATE ON DATABASE` privilege** — direct, sufficient proof by itself; nothing else in this battery needs to attempt creating anything to re-confirm it.
- **Ownership**, one focused query per object kind so a defect in one kind can't hide behind another: schemas, tables/sequences/views/matviews, functions/procedures, domains/enums. Each expects a single `migration_owner` owner (`public` and `pg_%` schemas excluded throughout — extension-owned objects there are expected, not a defect).
- **`core.alembic_version`'s exceptional owner**, checked against `--connect-role` (defaults to `--db-user`) **by name**, not folded into the grouped relation-ownership count above. Alembic creates its own bookkeeping table before `001_bootstrap` can `SET ROLE migration_owner`, and `001_bootstrap` deliberately grants that table's DML to `migration_owner` without transferring ownership — so this table is legitimately owned by whichever role connected and bootstrapped the database, which is configurable (`POSTGRES_USER`, or whatever role your deployment's migration URL actually connects as), not hardcoded to `postgres`. Any *other* owner appearing among the relations query above is a real defect, not this expected exception.
- **Required extensions** (`pgcrypto`, `pg_trgm`) — hard failure if missing. `btree_gist` is checked too but only as a warning if absent, since it's installed by a later revision (009) and its absence is expected on a database that predates it.
- **The current Alembic revision**, and **a clean `alembic upgrade head` run** — this proves migration machinery works end-to-end (connecting, `SET ROLE migration_owner`, reading/writing `core.alembic_version`). It does **not**, by itself, prove `CREATE ON DATABASE` works: when the dump is already at head, nothing between the restored revision and head needs to create an extension. The privilege check above already proved that directly; nothing here adds a throwaway `CREATE EXTENSION` purely to re-prove it.
- **Structural table counts** — proves the expected schemas and tables exist. This is deliberately **not** the same claim as "the expected business data exists": a structurally valid deployment may legitimately contain zero rows in any given table (a brand-new deployment has zero worlds, and that's correct, not broken).
- **Your own data checks**, via repeatable `--check "<SELECT ...>" "<expected scalar>"` pairs — read-only, operator-controlled, and refused if a check isn't a single `SELECT`. This is how you verify the data you actually expect, rather than treating "nonzero" as a universal proxy for correctness. For a restore drill, record source-side counts (or checksums) before backing up, then pass them as `--check` expectations after restoring — comparing selected source and restored counts, not assuming either is right.

Any hard-failing check makes `verify` exit nonzero; `btree_gist`'s absence is reported but does not by itself fail the run.

#### Isolated restore drill

**An untested backup is not a recovery plan.** Periodically run backup → restore → verify against a real dump, but inside a project that cannot be confused with, reach, or delete your real deployment — or an earlier or concurrently running drill — **and using its own disposable credentials, never your real `.env`.** Never reuse one fixed project name: a leftover container from an interrupted earlier drill, or a second drill running at the same time, would make that name's final teardown delete a project that isn't the one you just ran.

**Create a disposable environment file first.** Compose auto-loads `.env` from the working directory for variable substitution on every command that doesn't say otherwise; without a separate file, a drill would still interpolate credentials from your **real** deployment's `.env`. `--env-file` replaces `.env` entirely for the command it's given on, rather than merging with it (verified live: with `--env-file` set, values from a same-named variable in `.env` do not leak through), so giving the drill its own file closes that gap completely:

```bash
cat > .env.restore-test <<'EOF'
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<a-fresh-disposable-password>
POSTGRES_DB=dnd_ai
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:<the-same-fresh-disposable-password>@db:5432/dnd_ai
EOF
```

PowerShell — **do not use `Set-Content -Encoding utf8`**: under Windows PowerShell 5.1 that writes a UTF-8 byte-order mark, which can become part of the first key in a dotenv file or behave inconsistently depending on the parser reading it. Write the file with `[System.IO.File]::WriteAllText` and an explicit BOM-less encoding instead — this behaves identically on Windows PowerShell 5.1 and PowerShell 7:

```powershell
$envContent = @"
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<a-fresh-disposable-password>
POSTGRES_DB=dnd_ai
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:<the-same-fresh-disposable-password>@db:5432/dnd_ai
"@
[System.IO.File]::WriteAllText("$PWD\.env.restore-test", $envContent, [System.Text.UTF8Encoding]::new($false))
```

Generate an actual fresh password yourself — do not paste a real credential into it, and do not reuse your real deployment's password here either. Both placeholders must resolve to the exact same credential, percent-encoded in the URL if it contains characters special to URLs (`@ : / ? # [ ] %`). `.env.restore-test` is not committed (`.gitignore`'s `.env.*` pattern, `!.env.example` the one exception); remove it once the drill is done, the same as any other short-lived secret.

Generate a unique project name every time:

```bash
DND_TEST_PROJECT="dnd-ai-restore-test-$(date +%Y%m%d%H%M%S)-$$"
echo "$DND_TEST_PROJECT"
```

```powershell
$DndTestProject = "dnd-ai-restore-test-$(Get-Date -Format 'yyyyMMddHHmmss')-$([guid]::NewGuid().ToString('N').Substring(0,8))"
Write-Host $DndTestProject
```

Confirm nothing already exists under it, then run the drill — fresh-cluster mode, since a disposable project always starts from an empty volume — through the same three commands as any fresh-cluster restore, pointed at the drill's project and environment file:

```bash
docker compose --env-file .env.restore-test -p "$DND_TEST_PROJECT" -f compose.yaml ps

docker compose --env-file .env.restore-test -p "$DND_TEST_PROJECT" -f compose.yaml up -d --wait db

uv run python scripts/operations/database_recovery.py restore \
  --project "$DND_TEST_PROJECT" \
  --env-file .env.restore-test \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --dump-file ./dnd_ai-20260811.dump \
  --mode fresh \
  --confirm-drop \
  --confirm-restore

uv run python scripts/operations/database_recovery.py verify \
  --project "$DND_TEST_PROJECT" \
  --env-file .env.restore-test \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --check "SELECT count(*) FROM core.worlds" "<the count you recorded on the source before backing up>"
```

`-f compose.yaml` only, so the drill never loads `compose.override.yaml` and never publishes a host port. A throwaway project never has any other consumer connected to begin with, so existing-cluster mode's quiesce step is trivially satisfied here — this is exactly why the drill always uses fresh-cluster mode instead, rather than adding a second code path just for drills.

**If anything fails, or `verify` reports something unexpected, stop before tearing anything down.** Inspect the throwaway project — logs, an interactive `psql` session, whatever the failure calls for — a disposable project is exactly the thing it's safe to leave running while you investigate:

```bash
docker compose --env-file .env.restore-test -p "$DND_TEST_PROJECT" -f compose.yaml logs db
```

Do not script this drill with automatic teardown-on-exit — that would delete the evidence a failed drill exists to surface. Once you're done, whether the drill succeeded or you've finished investigating a failure, tear down deliberately and remove the disposable environment file:

```bash
uv run python scripts/operations/database_recovery.py teardown \
  --project "$DND_TEST_PROJECT" \
  --env-file .env.restore-test \
  --compose-file compose.yaml \
  --confirm-teardown

rm .env.restore-test
```

Compose derives container, network, and (because `compose.yaml`'s `dnd_ai_pgdata` volume has no explicit top-level `name:`) volume names from the project name, so each uniquely-named drill gets entirely separate resources; only the built image is shared. Using the same host dump file for both the drill and a real recovery is fine — it's an ordinary file on the host filesystem, not scoped to any project.

#### Restore — exceptional path: in place, over an existing database

Recreating the database (above) is the normal recovery path — prefer it whenever you can afford the brief downtime. Restoring **in place**, without dropping the database first, is for the narrower case where you specifically cannot recreate it (for example, other services depend on it staying up) and are willing to accept the limitations below. This path is deliberately **not** wired into `database_recovery.py restore` — it has different semantics (`--clean --if-exists` rather than force-drop/recreate) and different failure modes, and folding both into one command would make the common path's behavior less obvious. Confirm the target project first, the same as before anything destructive above:

```bash
docker compose -p "<your-project>" -f compose.yaml cp ./dnd_ai-20260811.dump db:/tmp/restore.dump
docker compose -p "<your-project>" -f compose.yaml exec -T db pg_restore -U postgres -d dnd_ai --clean --if-exists /tmp/restore.dump
docker compose -p "<your-project>" -f compose.yaml exec -T db rm /tmp/restore.dump
```

Because this path never drops the database, the `GRANT CREATE ON DATABASE ... TO migration_owner` privilege from the original bootstrap is untouched — the reapplication `restore` does above only matters after a drop/recreate cycle, not here.

**What `--clean` actually guarantees, precisely:** for each object the dump *contains*, `pg_restore --clean` emits a `DROP` for that object immediately before recreating it from the dump; `--if-exists` just silences the error when an object it expects to drop isn't there. That is narrower than "resets the database to match the dump":

- **Anything not represented in the dump is left alone.** A table, role grant, or other object created after the backup was taken is untouched, so an in-place restore can leave stale or unrelated state behind rather than reproducing a clean copy of the backed-up database.
- **It can fail outright, rather than silently succeeding**, when another session holds a lock on an object being dropped, the dump's objects are owned by a role that doesn't match what's currently in place, or a dependency isn't in the state `--clean`'s drop order expects.

Treat in-place `--clean --if-exists` restoration as an exceptional, break-glass procedure, not the default.

#### Why `pg_dumpall --globals-only` is not the default recommendation

`pg_dumpall --globals-only` is PostgreSQL's built-in way to capture cluster-wide role definitions, and it would technically solve "the database dump doesn't include roles" too. It's deliberately not what this document leads with, because on a real (potentially shared) PostgreSQL cluster it captures more than this application's six roles: every role in the cluster, not just this project's; role **attributes and password hashes**, an unnecessary credential-hygiene risk to apply unreviewed; and it can silently change existing roles' attributes or passwords if applied blindly to a cluster that already has some of them.

If you need cluster-wide role parity for reasons beyond this project, treat `pg_dumpall --globals-only` output as sensitive, review it before applying, and scope it down rather than applying it wholesale. For this project specifically, `bootstrap-roles`/`restore` only ever create the exact six roles `001_bootstrap` defines, nothing from any other application on the cluster, and never touch a password hash.

#### Current minor upgrades

**Upgrading the PostgreSQL minor version** (e.g. `18.4` → a later `18.x`) is a routine restart, because minor versions share an on-disk format: bump the tag in `compose.yaml`'s `db.image` and `docker compose -p "<your-project>" -f compose.yaml up -d db`, using the same project and the same volume.

#### Future major-version adoption and cutover

**This repository currently supports PostgreSQL 18.x only** ([DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version)). No PostgreSQL 19 (or any other major-version) production procedure is executable today — documenting how the *mechanics* of a future cutover would work is not the same as this project having adopted, verified, or supporting that version, and it hasn't. A future major must go through a reviewed, project-wide adoption change before any production use, exactly as described below. There are two genuinely different phases, and they must not be conflated:

**Phase A — before adoption: an isolated compatibility experiment, never a production target.** Before proposing the project-wide change in Phase B, you can check whether the new major version actually works against this schema and this migration history, using a disposable Compose project that can never become authoritative and is always torn down afterward. This is the only place `compose.pg-experiment-image.yaml` — a scratch, never-committed Compose override — is used:

```yaml
# compose.pg-experiment-image.yaml — scratch file, not committed
services:
  db:
    image: postgres:<candidate-version>   # never latest, never an unbounded major tag
```

```bash
DND_EXPERIMENT_PROJECT="dnd-ai-pg-experiment-$(date +%Y%m%d%H%M%S)-$$"

docker compose --env-file .env.pg-experiment -p "$DND_EXPERIMENT_PROJECT" -f compose.yaml -f compose.pg-experiment-image.yaml up -d --wait db

uv run python scripts/operations/database_recovery.py restore \
  --project "$DND_EXPERIMENT_PROJECT" \
  --env-file .env.pg-experiment \
  --compose-file compose.yaml \
  --compose-file compose.pg-experiment-image.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --dump-file ./dnd_ai-20260811.dump \
  --mode fresh \
  --confirm-drop \
  --confirm-restore

uv run python scripts/operations/database_recovery.py verify \
  --project "$DND_EXPERIMENT_PROJECT" \
  --env-file .env.pg-experiment \
  --compose-file compose.yaml \
  --compose-file compose.pg-experiment-image.yaml \
  --db-user postgres \
  --db-name dnd_ai
```

`.env.pg-experiment` is created the same BOM-free way as `.env.restore-test` above, with its own fresh disposable password — never a real deployment's. Every command carries **both** `-f compose.yaml` and `-f compose.pg-experiment-image.yaml`, and `--compose-file` passed twice to the script for the same reason: omitting the override lets Compose reconcile the service back to `compose.yaml`'s own currently-pinned image, silently testing the wrong version. Run the project's full compatibility pass here too — migrations, `tests/database`/`tests/scenario` pointed at this project's connection details, and this document's own procedures — then tear the experiment project down with `teardown --confirm-teardown` regardless of outcome. **Nothing from this phase is ever cut over to** — its only output is a decision (adopt or don't) and evidence to support it.

**Phase B — adoption: one reviewed change, applied before any real deployment moves.** Once Phase A's evidence supports it, bump the version pin in tracked configuration: `compose.yaml`'s `db.image` tag, CI's PostgreSQL service-container version ([§8](#8-continuous-integration)), `REQUIRED_POSTGRES_MAJOR_VERSION` (`tests/conftest.py`), [DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version) and any other version-policy text naming `18.x`, and the optional AWS path's RDS `postgres_version` pin (`terraform/modules/database`) if that path is in use — in one commit, verified by the full test/CI pass this change implies. **From this point on, `compose.yaml` alone, with no override, already targets the new major version** — that is what makes it "adopted," not a scratch file naming the same tag.

**Phase C — cutover of a real deployment, using tracked configuration directly.** Because Phase B already moved the real pin, standing up the new-version project needs **no image override at all** — it is an ordinary fresh-cluster restore into a newly named project, using plain `-f compose.yaml`:

```bash
DND_PROJECT_NEW="<your-project>-pg-new"

docker compose -p "$DND_PROJECT_NEW" -f compose.yaml up -d --wait db

uv run python scripts/operations/database_recovery.py restore \
  --project "$DND_PROJECT_NEW" \
  --env-file .env.pg-new \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --dump-file ./dnd_ai-20260811.dump \
  --mode fresh \
  --confirm-drop \
  --confirm-restore

uv run python scripts/operations/database_recovery.py verify \
  --project "$DND_PROJECT_NEW" \
  --env-file .env.pg-new \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai
```

A **new project name is still required** — Compose project names determine the named-volume namespace (see `compose.yaml`'s comment on `dnd_ai_pgdata` having no explicit top-level `name:`), so a project that already has a `dnd_ai_pgdata` volume keeps reusing exactly that volume regardless of which image tag it's pointed at, and the on-disk format is **not** compatible across major versions — PostgreSQL refuses to even start against a data directory from a different major version. The only way to guarantee a genuinely fresh data directory is a genuinely different project. `.env.pg-new` is created the same BOM-free way as `.env.restore-test` above, with its own fresh password for the new cluster; never reuse the real deployment's or the drill's credentials here. **The old deployment keeps its own `.env` and its own credentials, completely untouched by any of this.**

**A scratch image override is unnecessary for an ordinary cutover once Phase B has happened** — `compose.yaml` already names the adopted version. It remains available, narrowly, for a rare follow-up case: testing a *different patch image within the already-adopted major version* before bumping the tracked patch pin (for example, validating `19.5` ahead of `18.4` → `19.5`'s own tracked bump) — use it exactly as in Phase A, on a disposable, never-cutover project, never as a substitute for actually moving the tracked pin before a real cutover.

Inspect both volumes before cutover, confirming there are genuinely two, not one reused:

```bash
docker volume ls --filter "name=<your-project>_dnd_ai_pgdata"
docker volume ls --filter "name=${DND_PROJECT_NEW}_dnd_ai_pgdata"
```

**Cutover is not automatic — something concrete has to change, deliberately**, only once `verify` has fully passed against the new project:

- Whatever currently decides that the old project/`.env` is the one in use — a deployment script, a systemd unit, a process supervisor, a CI/CD job, or simply which `-p`/`--env-file` pair you type by habit — has to be updated to point at `$DND_PROJECT_NEW`/`.env.pg-new` instead.
- In practice that usually means promoting `.env.pg-new` into the deployment's real `.env` (backed by a real, retained secret-management process), not continuing to reference a file named after a one-off upgrade indefinitely.

**Only after the new project is confirmed live and stable does the old one get retired, and only deliberately** — using the **old** project's own configuration:

```bash
uv run python scripts/operations/database_recovery.py teardown \
  --project "<your-project>" \
  --env-file .env \
  --compose-file compose.yaml \
  --confirm-teardown
```

Consider keeping the old volume around for a rollback window rather than deleting it in the same session as cutover, if your recovery-time tolerance allows it.

`pg_upgrade` is a documented alternative that avoids a full dump/restore for a large database, at the cost of more manual steps than this repository's `compose.yaml` currently automates — it remains an advanced, unautomated alternative, not covered here.

#### Cleanup and rollback

Every disposable environment file this section creates (`.env.restore-test`, `.env.pg-experiment`, `.env.pg-new`, `.env.bootstrap`) is `.gitignore`d by the `.env.*` pattern and contains a real, if throwaway, credential — remove each one once its procedure is done, the same as any other short-lived secret. `compose.pg-experiment-image.yaml` is likewise `.gitignore`d and scratch: remove it once the experiment project (Phase A) it was created for has been torn down. Neither file is ever load-bearing for a real, currently-authoritative deployment — Phase C's cutover uses `compose.yaml` directly, with nothing scratch left over to forget about.

If a `restore` or `bootstrap-roles` run fails partway through, it deliberately leaves evidence in place rather than cleaning up automatically — an in-container dump copy, a temporary bootstrap database, or (for `teardown`) nothing at all, since `teardown` only ever runs when you explicitly ask it to. Inspect the failure (`docker compose ... logs db`, an interactive `psql` session, whatever it calls for) before tearing anything down; only run `teardown --confirm-teardown` once you're done investigating, and only against the project the failure actually happened in.

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

The downgrade round trip is cheap now that it runs locally, so run it every time rather than saving it for a phase close — Phase 1's downgrade was broken for weeks while looking fine. `scripts/verify.sh migration-round-trip --confirm-destructive` wraps the full `downgrade base` / `upgrade head` cycle ([§7](#7-code-quality)).

Against a self-hosted `compose.yaml` database, run `docker compose --profile tools run --rm migrate` ([§3.6](#36-self-hosted-docker-compose)). Against the optional AWS `dev` path, migrations run against a disposable containerized database in CI on every push and are no longer routinely run against `dev` itself; to run them there by hand anyway, use the session-scoped ingress workflow in [§3.5](#35-connecting-to-aws-dev-optional-no-longer-required). `staging` and `prod`, if ever stood up, remain private and would use the one-off migration task described in [PLAN.md §30.6](PLAN.md#306-migration-execution-mechanism) — unbuilt, optional planning material.

---

## 5. Phase 1 walkthrough (complete)

**Phases 1 through 8 are done.** Phase 9 is next. Follow [PLAN.md §24.1](PLAN.md#241-phase-exit-review) when each phase closes and [§26.6](PLAN.md#266-proportional-test-infrastructure-policy) before expanding test-only infrastructure. Phase 9 was the first phase developed under the local-first loop in [§3](#3-local-setup) (originally [ADR 0011](adr/0011-local-first-development-aws-verified-delivery.md), now [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)); Phases 1–8 were developed directly against `dev` RDS, so their verification files record only that target — historical evidence, not current policy.

This section is kept as the reference for how the database bootstrap is put together, because every later phase builds on it.

Its exit criteria were: an empty database can be created reproducibly, migrations run up and down in development, schema validation runs in CI, and a migration can be applied end-to-end against deployed AWS RDS using only Terraform-managed infrastructure.

Concretely, in order:

1. **Project skeleton** — `pyproject.toml` with the tools from §1, `uv.lock`, ruff/mypy/pytest configuration, `src/dnd_ai/` package root.
2. **Alembic scaffold** — `database/alembic.ini` and `database/migrations/`, configured per §4 above. Connection URL read from the environment, never hardcoded.
3. **The bootstrap revision** — the first revision, containing everything in [PLAN.md §29.5](PLAN.md#295-database-role-schema-and-extension-bootstrap):
   - `CREATE EXTENSION IF NOT EXISTS pgcrypto;` and `pg_trgm` (`btree_gist` is added by the Phase 3 revision that first needs it; `vector` is deferred)
   - all thirteen schemas from [PLAN.md §3](PLAN.md#3-postgresql-schema-organization)
   - `REVOKE CREATE ON SCHEMA public FROM PUBLIC;`
   - the six database roles from [DATABASE_CONVENTIONS.md §27.1](DATABASE_CONVENTIONS.md#271-database-roles): `migration_owner` created `NOLOGIN` and never granted `rds_iam`, the five login roles created `WITH LOGIN` and granted `rds_iam`

   It must be idempotent and re-runnable. Treat it as a revision, not an untracked script, so it is versioned like everything else.
4. **Shared domains** — `core.rating_1_10`, `core.percentage_0_100`, `core.nonnegative_integer` per [PLAN.md §4.2](PLAN.md#42-shared-domains).
5. **Seed infrastructure** — the mechanism for idempotent lookup seeding (§25.4), not yet the seed content.
6. **CI workflow** — at the time, `.github/workflows/ci.yml`'s `aws-verification` job plus `terraform/modules/github_actions_ci` for the OIDC role it assumed. Both are historical: CI now verifies against containerized PostgreSQL (see §8 below), and that Terraform module was removed ([ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)).
7. **`dev` deployed and reachable** — `terraform/environments/dev` applied, with migrations run against the live instance per [PLAN.md §30.9](PLAN.md#309-shared-dev-verification-mechanism-ci).

Steps 1–6 needed no AWS access at all, and under [ADR 0011](adr/0011-local-first-development-aws-verified-delivery.md) (in effect at the time) neither did verifying them: migrations and the test suite ran against a local PostgreSQL 18 server ([§3](#3-local-setup)), with CI proving the same against `dev`. Step 7 was the exception and was inherently an AWS task at the time. *(When this walkthrough was written, every step's verification went directly against `dev`; see [PLAN.md §24.0](PLAN.md#240-verification-policy) for current policy — CI no longer touches AWS at all, per [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md).)*

> **What actually closed the AWS exit criterion (historical).** This step originally read "Migration runner — `terraform/modules/db_migration_runner/`". That module was never built and turned out not to be needed: `dev` was directly reachable via the session-scoped ingress mechanism in [§30.9](PLAN.md#309-shared-dev-verification-mechanism-ci), so migrations ran against it the same way they ran anywhere else, and CI did the same with an OIDC-assumed role. The SSM-based runner in [PLAN.md §30.6](PLAN.md#306-migration-execution-mechanism) remains documented, optional planning material for `staging`/`prod` on AWS, unbuilt and not on the critical path since self-hosted Docker Compose became the default deployment topology.

---

## 6. Testing

Three layers, matching [PLAN.md §25](PLAN.md#25-testing-strategy) and [DATABASE_CONVENTIONS.md §32](DATABASE_CONVENTIONS.md#32-testing-conventions):

| Layer | Location | Database | Purpose |
|---|---|---|---|
| Unit | `tests/unit/` | none | Pure logic — rules calculations, policy decisions, validation |
| Database | `tests/database/` | Local/self-hosted PostgreSQL 18 (ephemeral database per run); disposable containerized PostgreSQL 18 in CI | Constraints, triggers, subtype consistency, same-world invariants, state uniqueness, branch behavior |
| Scenario | `tests/scenario/` | Local/self-hosted PostgreSQL 18 (ephemeral database per run); disposable containerized PostgreSQL 18 in CI | Cross-domain flows, ultimately the full acceptance scenario in [PLAN.md §25](PLAN.md#25-vertical-slice-acceptance-scenario) |

Database and scenario tests create a throwaway database per test session — `dnd_ai_test_<run-id>` — migrate it to head, run, and drop it. That is the same mechanism against either target, which is what lets the identical suite run locally and in CI with nothing skipped or conditionally disabled on either ([PLAN.md §24.0](PLAN.md#240-verification-policy), [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)).

```bash
uv run pytest                    # everything, against your local server
uv run pytest tests/unit         # fast loop, no database at all
uv run pytest tests/database -x  # local server, see §3
```

**Your local/self-hosted server and CI's container must stay in agreement.** Same PostgreSQL major version, same extensions, same six bootstrap roles. When they drift, the symptom is a green local run and a red CI run — and per [PLAN.md §24.0](PLAN.md#240-verification-policy), CI is right. Investigate rather than re-run.

If you have deployed the optional AWS `dev` path and want to run the suite against it — normally only to reproduce a failure specific to that environment — open the ingress rule per [§3.5](#35-connecting-to-aws-dev-optional-no-longer-required) and point `DATABASE_URL` at the `dev` endpoint (with `sslmode=require`). The fixture provisions its ephemeral database there exactly as it does locally.

### 6.1 Keep test infrastructure proportional

Write the smallest test that makes the production claim falsifiable. For database concurrency, that normally means arranging a genuine blocking operation, proving the original waiter resumes, and querying final committed state from an independent connection. It does not mean proving every possible failure of Python's multiprocessing or IPC implementation.

A helper deserves focused regression coverage when it could realistically:

- let a worker failure appear as a passing test;
- leave a PostgreSQL backend, transaction, advisory lock, or other persistent external resource that contaminates later tests; or
- cause repeatable CI hangs or instability in a supported environment.

Cover ordinary startup, success, assertion failure, timeout/cancellation, and teardown as applicable. Beyond those paths, require an observed incident or a concrete, realistic failure chain before adding fault injection. Assume standard-library cleanup primitives honor their documented contracts unless there is contrary evidence. Do not build and exhaustively test a second teardown framework solely to test the first.

When production assertions are reliable and CI isolation contains any residual test-process state, document theoretical limitations and proceed. See [PLAN.md §25.6](PLAN.md#256-proportional-test-infrastructure-policy) for the blocking threshold and stop-loss rule.

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

`scripts/verify.sh` wraps the read-only form of these checks, plus the
pytest layers and `alembic check`, as a single command that prints one
PASS/FAIL line per stage instead of each tool's full output — `full` output
is only shown for a stage that actually fails:

```bash
scripts/verify.sh quality   # ruff format --check, ruff check, mypy src — no database
scripts/verify.sh full      # quality + tests/unit + tests/database + tests/scenario + alembic check
```

See the script's header comment for every mode, including the opt-in,
explicitly destructive `migration-round-trip` stage — cheap and safe against
your own local server, and the reason the downgrade round trip is now expected
every phase rather than only at close ([§4](#4-database-and-migrations)).

The script's `dev`-ingress handling applies only when `DATABASE_URL` points at
the optional AWS `dev` endpoint. Against a local/self-hosted server —
including `compose.yaml` — there is nothing to open or revoke.

---

## 8. Continuous integration

CI is the project's merge gate, not advisory, per [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md) — it verifies the same self-hosted PostgreSQL 18 target the project deploys, not AWS RDS.

`.github/workflows/ci.yml` has three jobs, none of which need AWS credentials or repository secrets:

**`lint-and-type-check`**: `ruff format --check`, `ruff check`, `mypy src`.

**`postgres-verification`** — a `postgres:18.4` GitHub Actions service container, health-checked before the job's steps run — covers, per [PLAN.md Phase 1](PLAN.md#phase-1-database-bootstrap), [§24.0](PLAN.md#240-verification-policy), and [DATABASE_CONVENTIONS.md §25.6](DATABASE_CONVENTIONS.md#256-migration-testing):

- migration from an **empty** database through all revisions to head
- migration state confirmation (`alembic current --verbose`)
- a full downgrade-to-base/upgrade-to-head round trip
- seed idempotency — apply the complete seed set twice and require byte-identical lookup rows
- schema comparison — autogenerate against head must produce an empty diff, proving migrations and metadata agree
- the full pytest suite (`tests/unit`, `tests/database`, `tests/scenario`) — `tests/conftest.py` provisions its own ephemeral database off the service container exactly as it does against a local server

**`docker-build`**: validates `compose.yaml`/`compose.ci.yaml`, builds the application image, brings up disposable PostgreSQL via compose, and runs the `migrate` service against it as an end-to-end smoke test of the self-hosted deployment topology itself.

Seed idempotency became a required CI step in Phase 2 when the first lookup content was added. Every later seed change participates in the same check; do not create a second seeding path outside `apply_seed()`.

A pull request that changes schema without a green `postgres-verification` job should not merge. Local results do not substitute for it — CI runs on a clean, disposable environment every time, which a long-lived local server does not guarantee ([PLAN.md §24.0](PLAN.md#240-verification-policy)).

AWS RDS is no longer part of CI. Anyone who deploys the optional Terraform under `terraform/` is responsible for verifying that path themselves — see [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md) for what that trades away.

`scripts/wait_for_ci.py` polls a pushed commit's GitHub Actions run to
completion and reports only pass/fail, fetching per-job/per-step detail only
when the run actually failed:

```bash
uv run python scripts/wait_for_ci.py   # current HEAD's most recent run
```

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
- [ ] Migration runs up **and** down cleanly against a fresh database on your local/self-hosted PostgreSQL 18 server (§3, §4)
- [ ] Your local/self-hosted server is PostgreSQL 18.x, matching what CI runs — a mismatch invalidates the local result ([DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version))
- [ ] Constraints have positive and negative tests
- [ ] Tests target production behavior or a credible regression; any new test-harness fault injection satisfies [PLAN.md §26.6](PLAN.md#266-proportional-test-infrastructure-policy)
- [ ] Code sits in the layer [SYSTEM_ARCHITECTURE.md §5](architecture/SYSTEM_ARCHITECTURE.md#5-layering) prescribes
- [ ] `ruff format --check`, `ruff check`, `mypy src`, and `pytest` all pass locally
- [ ] CI is green on the pushed commit — containerized PostgreSQL 18 verification ([§8](#8-continuous-integration), [PLAN.md §24.0](PLAN.md#240-verification-policy)). A green local run is not a substitute; a red CI run after a green local one is a real defect or local/CI drift, not flakiness to re-run away
- [ ] If the change adds or alters a deployable, it runs via `compose.yaml` and was exercised there; an AWS deployable additionally needs the (optional, no longer required) AWS verification described in [PLAN.md §31.8](PLAN.md#318-per-phase-deployment-expectations)
- [ ] No secret, credential, or connection string is committed
- [ ] Any new cross-cutting concept is reflected in the relevant `docs/` file **in the same change** — these documents are meant to stay current, not be reconciled later
- [ ] If this change completes a phase, the phase exit review in [PLAN.md §24.1](PLAN.md#241-phase-exit-review) is done: `docs/PHASEn_VERIFICATION.md` written, recurring obligations re-checked, next phase reviewed and amended
- [ ] Phase closure is not blocked solely by theoretical failures of test-only cleanup primitives; lower-risk limitations are documented and delivery continues
