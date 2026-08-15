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
| Self-hosted deployment | **Docker Compose** (`compose.yaml`, `Dockerfile`) | The supported deployment topology ([ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)). One shared image for migrations today, API/worker/adapter once they exist |
| UI | **React** | Not yet started; no build tooling chosen |

---

## 2. Repository layout

The tree below is the **target**. As of Phase 6, `database/` holds the migrations and seed files, `src/dnd_ai/persistence/` holds the table metadata and seed machinery, `src/dnd_ai/commands/` holds the first command handlers (`record_event`, `perform_interaction`, `resolve_check`), and `tests/` holds all three layers plus shared factories. As of Phase 10, `src/dnd_ai/domain/` holds `access.py` — the `security.*` effective-access resolver (docs/architecture/DATABASE_MODEL.md §19.7) — and `errors.py`, the framework-free `SafeMessageError`/`DomainAuthorizationError` classification a domain error opts into when it needs control over how it reaches an API client. `src/dnd_ai/api/` holds the portable FastAPI application (app factory, `/healthz` and `/readyz`, the error contract, correlation IDs, and per-request transaction management; see ADR 0013 and docs/LOCAL_DEPLOYMENT.md for why "portable" — no Lambda/AWS-specific code lives here or anywhere else in this package). The remaining `src/dnd_ai/` subpackages (`queries/`, `ai/`, `integrations/`) do not exist yet — create each as the phase that needs it requires, not in advance. `commands/` itself stayed thin: no `domain/` layer was needed yet because the invariants a command has to satisfy (world consistency, ruleset allow-lists, the conditional-route decision) already live in triggers and `world.conditional_route_requirement_satisfied()` — a command calls those rather than re-deriving them in Python.

```text
.
├── README.md                  # Project entry point
├── CLAUDE.md                  # AI assistant operating instructions
├── pyproject.toml             # Python project + tool config (ruff, mypy, pytest)
├── uv.lock
├── .env.example
├── Dockerfile                 # The one image all services run from (PLAN.md §31.3)
├── compose.yaml               # Self-hosted deployment topology (ADR 0012) — no default password, no default port
├── compose.override.yaml      # Auto-loaded local-dev convenience: 127.0.0.1-only port
├── compose.ci.yaml            # CI override: disposable tmpfs storage
├── .dockerignore
├── docs/                      # ALL documentation (see CLAUDE.md §4)
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

There is one `Dockerfile`, not one per service: the API, background worker, Discord adapter, and one-off jobs including migrations all run the same image with different entrypoints. It runs Alembic migrations by default (`compose.yaml`'s `migrate` job) and, since Phase 10, also runs the FastAPI application under Uvicorn (`compose.yaml`'s `api` service — `docker compose up -d api`, or plain `docker compose up`); the worker/Discord-adapter entrypoints are added when those modules exist. Role selection is entirely `compose.yaml`'s own per-service `command:` override — the image's `ENTRYPOINT` never changes.

### 2.1 Keep source and tests bounded by domain

Repository structure is also a context boundary. Do not keep adding unrelated domains or correction passes to a file merely because the file already exists.

**Done.** The monolithic `src/dnd_ai/persistence/tables.py` was replaced with a `src/dnd_ai/persistence/tables/` package organized by bounded schema/domain. The shape, kept as the ongoing convention for where a new table goes:

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

The bare `DATABASE_URL` above is what Alembic, pytest, and CI read directly. The application itself (`src/dnd_ai/api/`, via `src/dnd_ai/config.py`) has its own, separate configuration source rule, summarized here and stated in full in that module's docstring and in `.env.example`: locally/in tests it accepts `DND_AI_DATABASE_URL`, falls back to the same unprefixed `DATABASE_URL` as a compatibility alias, and finally a hardcoded local-dev default — but in production (`DND_AI_ENVIRONMENT=production`, selected *only* by the real process/deployment environment, checked before `.env` is even considered) it never loads `.env` at all and requires `DND_AI_DATABASE_URL` explicitly, as a real environment variable or a mounted secret file named `dnd_ai_database_url` (docs/LOCAL_DEPLOYMENT.md). `.env` cannot select production either: if the real environment doesn't already say `production`, `.env` does get loaded, but if it turns out to set `DND_AI_ENVIRONMENT=production` itself, that fails startup outright rather than silently promoting the process. Other `DND_AI_*`-prefixed variables — `DND_AI_TEST_DATABASE_URL`, `DND_AI_CI_DB_NAME` (§8, tests/conftest.py), `DND_AI_SEEDS_DIR` (seed loading) — share the namespace but belong to those other subsystems, not to `Settings`; `config.py` keeps an explicit allowlist for them rather than accepting every `DND_AI_*` name.

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

**Required setup — `compose.yaml` will not start (`up`), run migrations, or start the API without it:**

```bash
cp .env.example .env
# edit .env: uncomment POSTGRES_PASSWORD and set a real value, then set
# MIGRATION_DATABASE_URL, APP_READ_WRITE_PASSWORD, API_DATABASE_URL,
# API_OIDC_ISSUER/API_OIDC_AUDIENCE/API_OIDC_JWKS_URL, and DATABASE_URL's
# password segments to match it
```

There is deliberately **no fallback password or configuration value** anywhere in `compose.yaml` — not even for local development — so nothing in this repository ships a working default credential, and nothing lets the `api` service silently boot with authentication unconfigured (or, per the correction below, running as a database superuser). `docker compose up` fails immediately with a clear message if `POSTGRES_PASSWORD` isn't set, rather than silently starting with a guessable one; `docker compose --profile tools run --rm migrate` and `docker compose up -d api` likewise refuse to run without `MIGRATION_DATABASE_URL`/(`API_DATABASE_URL` and all three `API_OIDC_*` variables) respectively. Settings must be kept in sync by hand — nothing derives one from another:

- `POSTGRES_PASSWORD` — read by `docker compose` to initialize PostgreSQL.
- `MIGRATION_DATABASE_URL` — the complete SQLAlchemy URL the `migrate` service connects with, addressing `db` (the compose service name) over the compose-internal network.
- `APP_READ_WRITE_PASSWORD`/`API_DATABASE_URL` — `api` connects to PostgreSQL as **`app_read_write`**, the DML-only login role `001_bootstrap` creates (`docs/DATABASE_CONVENTIONS.md` §27.1, ADR 0009) — never `postgres`, `migration_runner`, or `migration_owner`. This is a production security boundary, not an interim convenience: `app_read_write` holds `SELECT`/`INSERT`/`UPDATE`/`DELETE` on application tables only — no schema DDL, no role management, no membership in `migration_owner`, not a superuser, not a schema owner, no `CREATEDB`/`CREATEROLE`/`BYPASSRLS`. `001_bootstrap` creates the role with no password, so it cannot authenticate until you provision one — see "Provisioning the `app_read_write` credential" below — then build `API_DATABASE_URL` from that password yourself, the same percent-encoding rule as `MIGRATION_DATABASE_URL`.
- `API_OIDC_ISSUER`/`API_OIDC_AUDIENCE`/`API_OIDC_JWKS_URL` — the `api` service's OIDC provider settings, required together with no fallback. `compose.yaml` runs `api` with `DND_AI_ENVIRONMENT=production` unconditionally (a fixed value in `compose.yaml` itself — this file is the self-hosted/production deployment topology, not a "local" convenience default), so `dnd_ai.config.Settings` additionally requires the issuer and JWKS URL to be absolute, credential-free, fragment-free **HTTPS** URLs with a host, and the audience to be non-empty with no leading/trailing whitespace — see `.env.example`'s OIDC section for the full rule and why running the API directly on the host (outside Docker) is different.
- `DATABASE_URL` — read by the application/tests running on the host, addressing `localhost` (reachable only via `compose.override.yaml`'s port — see below). This one still authenticates as `postgres` — it is the admin/test connection developers and CI use directly, unrelated to what the containerized `api` service connects as.

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
| `APP_READ_WRITE_PASSWORD` | *(none — required to provision `app_read_write`)* | Read only by `set-role-password` (below), from this shell's own environment — never by Compose or the application |
| `API_DATABASE_URL` | *(none — required for `api`)* | The complete SQLAlchemy URL the `api` service connects with (host `db`, not `localhost`) — MUST authenticate as `app_read_write`, never `postgres`/`migration_runner`/`migration_owner` |
| `API_OIDC_ISSUER` | *(none — required for `api`)* | The `api` service's OIDC issuer URL — must be absolute HTTPS with a host, no embedded credentials, no fragment (`api` always runs with `DND_AI_ENVIRONMENT=production`) |
| `API_OIDC_AUDIENCE` | *(none — required for `api`)* | The `api` service's expected token audience — non-empty, no leading/trailing whitespace |
| `API_OIDC_JWKS_URL` | *(none — required for `api`)* | The `api` service's JWKS endpoint — same HTTPS/host/no-credentials/no-fragment rule as `API_OIDC_ISSUER` |
| `API_PORT` | `8000` | Host port the API is published on — only takes effect via `compose.override.yaml` (local development); the base topology publishes nothing |

**Running migrations** against the composed database:

```bash
docker compose --profile tools run --rm migrate
```

This builds the same `Dockerfile` image the `api` service (and any future worker/adapter service) shares and runs `alembic -c database/alembic.ini upgrade head` against `db` over the compose-internal network — it needs no published host port. It is not started by plain `docker compose up` — `profiles: ["tools"]` keeps it a deliberate one-off action, not a standing service. This is also what creates all six roles from `001_bootstrap` (§27.1), including `app_read_write` — with no password set yet.

**Provisioning the `app_read_write` credential** — required after `migrate`, before `docker compose up -d api`:

```bash
export APP_READ_WRITE_PASSWORD=<a real value>   # never commit this; a shell export, not a file
uv run python scripts/operations/database_recovery.py set-role-password \
  --role app_read_write --password-env-var APP_READ_WRITE_PASSWORD \
  --project dnd_ai --env-file .env --compose-file compose.yaml
```

`app_read_write` is created with no password by `001_bootstrap` — password authentication is refused until this step runs. `set-role-password` reads the new password from `--password-env-var` (a variable already set in *this* process's own shell — never accepted as a `--password` flag, which would leave it visible in `ps`/`docker top`/shell history for as long as the command runs) or `--password-file` (a mounted secret), escapes it as a SQL literal in-process, and sends it to `psql` only over stdin — never a command-line argument, never printed by this script or by Compose. `--role` accepts only the five real LOGIN roles (never `migration_owner`, which is `NOLOGIN` by design). The `ALTER ROLE ... PASSWORD` this issues is idempotent: rerunning it with a new value simply rotates the password, so this is also the rotation path — migration and application credentials stay independently rotatable because they are always two different roles with two different passwords. Once it succeeds, build `API_DATABASE_URL` yourself from the same password (percent-encoded, the same rule `MIGRATION_DATABASE_URL` already follows) and set it in `.env`, then confirm the password actually took before starting `api`:

```bash
uv run python scripts/operations/database_recovery.py verify-roles \
  --project dnd_ai --env-file .env --compose-file compose.yaml
```

This needs only the already-running `db` container (no image build, no application database touched). Its report includes one line per LOGIN role confirming a password is actually set; confirm `app_read_write`'s before proceeding to `docker compose up -d api`. Running the API before this step doesn't create a security hole (password auth still fails closed — the container just can't reach the database at all, so every DB-touching request fails), but it is a functional footgun this sequence, and `verify-roles`' automated check, both exist to prevent.

**Running the API** under Uvicorn, in the same container image:

```bash
docker compose up -d api      # dev: also publishes 127.0.0.1:8000 via the override
```

Unlike `migrate`, `api` is a standing service with no `profiles:` restriction, so plain `docker compose up` (no service name) starts it alongside `db` — but see the required ordering above: `migrate` and `set-role-password` must both have already succeeded, since Compose's own `depends_on` has no equivalent mechanism for a `profiles: ["tools"]` one-off job or a step external to Compose entirely. It reaches `db` over the compose-internal network — no published host port in the base `compose.yaml`, same as `migrate` — authenticating as `app_read_write` (never `postgres`/`migration_runner`/`migration_owner` — see the `APP_READ_WRITE_PASSWORD`/`API_DATABASE_URL` note above; this is a production security boundary, not a documented "future hardening" item). Its container `HEALTHCHECK` polls `/healthz` (process liveness only, deliberately database-independent; see `dnd_ai.api.app`'s own docstring) so `docker compose up --wait`/`docker compose ps` report readiness accurately — it does not, and cannot, detect a missing `app_read_write` password, which is exactly why `verify-roles` is a separate, required step rather than something the healthcheck alone catches. `compose.override.yaml` additionally publishes `api` on `127.0.0.1:${API_PORT:-8000}` for local development, mirroring `db`'s own override; a real self-hosted deployment reaches it only through a reverse proxy instead (not yet built — [§32](PLAN.md#32-local-production-deployment-plan), Phase 14).

`api` always runs with `DND_AI_ENVIRONMENT=production` (a fixed value in `compose.yaml` itself, not read from `.env`) — this file is the self-hosted/production deployment topology, not a "local" convenience default, so it must never be possible to start this service without a real OIDC provider configured and have every authenticated route silently fail closed with a generic 500 instead of the intended 401. `API_OIDC_ISSUER`/`API_OIDC_AUDIENCE`/`API_OIDC_JWKS_URL` are therefore required with no fallback, exactly like `API_DATABASE_URL` — `dnd_ai.config.Settings` also additionally requires the issuer/JWKS URL to be HTTPS in this mode. To exercise an authenticated route locally without standing up a real OIDC provider, run the API directly on the host instead (`uv run uvicorn dnd_ai.api.app:app --reload`, `DND_AI_ENVIRONMENT` left at its "local" default) — see `.env.example`'s OIDC section for the two paths and how their requirements differ.

Running the test suite or `uv run alembic` from the host against the composed database works the same way it does against a native install — point `DATABASE_URL` at `postgresql+psycopg://postgres:<your POSTGRES_PASSWORD>@localhost:5432/dnd_ai` (this needs `compose.override.yaml`'s port, i.e. plain `docker compose up -d db` with no `-f` flags) and follow [§3.4](#34-verify).

**Backup and upgrade responsibilities.** Unlike the disposable local server described in [§3.4](#34-verify), a self-hosted deployment's `dnd_ai_pgdata` volume is expected to hold real, non-reproducible data, and nothing here backs it up automatically — that is the self-hosting operator's responsibility, unlike the AWS RDS path's automated backups ([INFRASTRUCTURE.md §1](INFRASTRUCTURE.md#1-current-state)).

Backup, restore, role bootstrap, verification, and teardown all run through one production tool, **`scripts/operations/database_recovery.py`**, rather than hand-duplicated Bash/PowerShell command blocks — that duplication is exactly what caused flags, environment files, and variable names to drift across past revisions of this section. The script distinguishes three safety levels rather than making a single blanket "read-only" claim:

- **static** — argument/file/Compose-configuration validation. No container needs to be running; nothing is created.
- **docker-ephemeral** — `exec`/`cp` against an already-running `db` container, or (for the migration-target check only) a genuinely new one-off `migrate` container, whose image must already be built — this script never lets that check silently trigger a build. None of this creates, drops, or modifies any PostgreSQL database, role, or volume.
- **destructive** — force-drop/recreate/restore, real migrations, or `down -v`. Always gated behind an explicit `--confirm-*` flag, checked before any subprocess runs — static or docker-ephemeral — so a missing flag leaves everything untouched.

`restore` and `bootstrap-roles` always run their static and docker-ephemeral preflight checks before anything destructive, and refuse to proceed — leaving the target application database untouched — if any check fails. The standalone `preflight` (with `--level static|docker`) and `validate-archive` commands expose those same checks independently of any mutation — except for `preflight --for bootstrap-roles`, which is necessarily an incomplete subset, since its active migration-target check needs a database that doesn't exist until `bootstrap-roles` itself creates it (see the dedicated guide). Published `db` host ports fail preflight by default (`compose.yaml` alone, without `compose.override.yaml`, publishes none); `--allow-published-db-port` acknowledges a deliberate exception and always reports a public (non-loopback) binding loudly.

`verify` has no `--confirm-*` flag and never runs migrations, unconditionally, and every check it runs stays within its own `--project`/`--compose-file` and its running `db` service: the cluster-wide role check queries that cluster's `postgres` maintenance database (roles aren't per-database), and every application-database check — including the migration-head check — queries `--db-name`; it never consults `MIGRATION_DATABASE_URL` or touches the `migrate` service. Its migration-head check proves the selected database's recorded revision(s) genuinely equal the migration scripts' current head(s), not merely that `core.alembic_version` is readable, and rejects a database with zero, duplicate, unknown, or malformed revision rows rather than risk a false pass. It deliberately does not shell out to `alembic current --check-heads`: that command loads `database/migrations/env.py`, whose `run_migrations_online()` unconditionally creates and commits the `core` schema — real mutation Alembic's own `dont_mutate=True` does not suppress. Instead it computes repository heads and known revisions entirely locally (Alembic's `ScriptDirectory`, no subprocess, no env.py) and reads the selected database's revisions as a single fixed JSON query, parsed exactly rather than reduced to a lossy set (see the dedicated guide).

**Full operator documentation — including every command invocation, the isolated restore drill, role bootstrap, major-version adoption/cutover, and cleanup/exit-status semantics — lives in [docs/operations/DATABASE_RECOVERY.md](operations/DATABASE_RECOVERY.md).** That document is authoritative for operational invocation; run `uv run python scripts/operations/database_recovery.py <command> --help` for the full flag reference. This section stays a summary so the two never diverge — do not duplicate full command blocks back into it.

**Delivery status:** the self-hosted database recovery implementation is accepted. Do not keep reopening it for hypothetical parser or wording edge cases. The remaining obligation is operational evidence: periodically run the documented disposable backup -> restore -> verify drill with representative business-data checks. Reopen the implementation only for a reproduced defect, a deployment-topology change, or a PostgreSQL/Compose major-version change.

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

- `api/` — authentication, authorization, input validation, routing, response shaping. **No domain rules.** Error responses and logs are non-disclosing by construction, not by convention: `dnd_ai.api.errors._API_ERROR_CONTRACTS` maps each *exact* recognized `ApiError` subclass (`UnauthorizedError`/`ForbiddenError`/`NotFoundError`/`ConflictError`) to its one fixed `(status_code, error_code, safe_message)` triple — an unrecognized subclass, or any mismatch between an exception's current attributes and its registered triple (a status paired with the wrong code, an altered message), falls back to the identical fixed internal-error contract; `dnd_ai.api.errors._SUPPORTED_HTTP_EXCEPTION_STATUSES` is the equally explicit, closed set of framework HTTP statuses this application forwards to a response (currently just FastAPI/Starlette's own routing 404 and 405) — any other status, however HTTP-shaped, gets the same fixed internal-error fallback rather than being forwarded verbatim; an unrecognized/missing database integrity SQLSTATE is an internal error (500), not a guessed 400/409; a generic unique/exclusion conflict (409) never promises retrying will help — only a command's own exception type may say that, for a demonstrated optimistic-concurrency/idempotency case; a generic request-validation response never carries a field *location* at all, and never a pydantic `type` string either — only a small, fixed public vocabulary (`missing`/`invalid_type`/`invalid_format`/`out_of_range`/`invalid`) this module owns, mapped by exact dict lookup, capped in count, with every unmapped or custom pydantic type — including an identifier-shaped one a `PydanticCustomError` could produce — falling back to `invalid`; validation failures are logged through the same sanitized, fixed-shape path every other handler uses, and every handler computes exactly one validated `(status, code, message)` triple reused for both the response and the log line; and an accepted client `X-Correlation-Id` must be a canonical UUID — anything else is replaced with a freshly generated one rather than trusted, echoed, or logged.
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
