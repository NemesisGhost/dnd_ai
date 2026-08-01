# Phase 1 Verification Checklist

This document verifies Phase 1 (Database bootstrap) exit criteria per [PLAN.md §23](PLAN.md#23-delivery-phases).

## Exit Criteria

- [x] Empty database can be created reproducibly
- [x] Migrations can run up and down in development
- [x] Schema validation runs in CI
- [ ] A migration can be applied end-to-end against deployed AWS RDS

The first three were verified with `alembic ... --sql` (offline mode, no database
required) plus `ruff`/`mypy`, not yet against a live PostgreSQL container — do
step 3 below before treating them as fully closed in a given environment.

## Verification Steps (Local)

### 1. Install toolchain

```bash
# Install uv (if not already installed)
# Windows: https://docs.astral.sh/uv/getting-started/installation/
# Or: pip install uv

# Install dependencies
uv sync --all-extras
```

### 2. Start local PostgreSQL

```bash
# Start Docker container
docker run -d --name dnd-ai-pg `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=dnd_ai `
  -p 5432:5432 `
  postgres:15

# Verify it's running
docker ps
```

### 3. Run migrations

Run these from the repository root — `database/alembic.ini` resolves
`script_location` relative to the ini file itself, not the working directory.

```bash
# Verify Alembic can connect
uv run alembic -c database/alembic.ini current

# Run migrations to head
uv run alembic -c database/alembic.ini upgrade head

# Verify state
uv run alembic -c database/alembic.ini current --verbose
uv run alembic -c database/alembic.ini history --verbose
```

### 4. Verify database structure

Connect to the database and verify:

```bash
# Connect
docker exec -it dnd-ai-pg psql -U postgres -d dnd_ai

# In psql:
\dn+  -- Should show all 13 schemas
\dD core.*  -- Should show three domain types
\du  -- Should show five roles plus postgres
SELECT schema_name FROM information_schema.schemata ORDER BY schema_name;
```

Expected schemas:
- ai, audit, campaign, character, core, import, integration, interaction, knowledge, narrative, public, rules, security, world

Expected roles:
- admin_maintenance, app_read_only, app_read_write, integration_worker, migration_owner, postgres

Expected domains in core:
- rating_1_10, percentage_0_100, nonnegative_integer

`rds_iam` does not exist on local/CI PostgreSQL, so the bootstrap migration
skips those grants there — this is expected, not a failure. It only grants
`rds_iam` when that role is present, i.e. on RDS.

### 5. Test downgrade

```bash
# Downgrade one revision
uv run alembic -c database/alembic.ini downgrade -1

# Verify (should be at 001_bootstrap)
uv run alembic -c database/alembic.ini current

# Downgrade to base
uv run alembic -c database/alembic.ini downgrade base

# Upgrade back to head
uv run alembic -c database/alembic.ini upgrade head
```

Note: downgrading 001_bootstrap to base intentionally leaves the empty `core`
schema behind — it holds Alembic's own version table
(`version_table_schema = core`), so the revision that creates the schema
cannot also drop it in its own downgrade. See the comment in
`001_bootstrap.py::downgrade`.

### 6. Run quality checks

```bash
# Format check
uv run ruff format --check .

# Lint
uv run ruff check .

# Type check
uv run mypy src

# Full test suite
uv run pytest tests/unit                       # no database needed
uv run pytest tests/database tests/scenario     # needs the container from step 2
```

### 7. Clean up

```bash
# Stop and remove container
docker stop dnd-ai-pg
docker rm dnd-ai-pg
```

## What's Not Yet Complete

**AWS RDS deployment verification** (Phase 1 final exit criterion):
- The migration runner module (`terraform/modules/db_migration_runner`) specified in [PLAN.md §29.6](PLAN.md#296-migration-execution-mechanism) has not been implemented yet
- Cannot verify end-to-end migration against RDS without it
- This is deferred to allow Phase 2+ work to proceed
- The migration runner should be implemented before standing up staging/prod environments

**`uv.lock`** is not committed — no environment with `uv` installed has run
`uv sync` against this `pyproject.toml` yet. Run it once and commit the lock
file before relying on `uv sync --all-extras` reproducing this dependency set
elsewhere.

## Implementation Status

Phase 1 deliverables completed:
- Project skeleton (pyproject.toml, toolchain configuration)
- Alembic scaffold (database/alembic.ini, env.py, script template)
- Bootstrap revision (extensions, schemas, roles)
- Shared domains (rating_1_10, percentage_0_100, nonnegative_integer), with
  positive and negative constraint tests per [DATABASE_CONVENTIONS.md §32.1](DATABASE_CONVENTIONS.md#321-constraint-tests)
- Seed infrastructure (seeds.py, database/seeds/)
- CI workflow (migration validation, linting, type checking, tests)

Next phase: Phase 2 (Core world platform) per [PLAN.md §23](PLAN.md#23-delivery-phases).
