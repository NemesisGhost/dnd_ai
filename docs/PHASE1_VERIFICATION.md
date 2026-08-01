# Phase 1 Verification Checklist

This document verifies Phase 1 (Database bootstrap) exit criteria per [PLAN.md §23](PLAN.md#23-delivery-phases).

## Exit Criteria

- [x] Empty database can be created reproducibly
- [x] Migrations can run up and down in development
- [x] Schema validation runs in CI
- [x] A migration can be applied end-to-end against a deployed AWS RDS instance using only Terraform-managed infrastructure

All four verified against a live `dev` deployment, not just offline SQL generation — see "What Was Actually Verified" below. GitHub Actions run [30704528098](https://github.com/NemesisGhost/dnd_ai/actions/runs/30704528098) is the CI evidence for the third and fourth criteria together: both jobs green on a real push to `main`.

## What Was Actually Verified

Terraform (`terraform/environments/dev`) applied cleanly against a real AWS account: VPC discovery, KMS key, RDS PostgreSQL 15.18 (`db.t3.micro`), security group, VPC endpoints, the GitHub Actions OIDC role (`terraform/modules/github_actions_ci`), and the `secrets` module. 17 resources, 0 destroyed, reusing a KMS key orphaned by an earlier teardown.

Against that live instance, with `DATABASE_URL` built from the AWS-managed master secret plus `sslmode=require` (the parameter group sets `rds.force_ssl=1` — this doesn't come up against a local container, which has no SSL configured at all):

- `alembic upgrade head` — both revisions, clean.
- `alembic downgrade base` then `alembic upgrade head` again — the full round trip, including `001_bootstrap`'s `REASSIGN OWNED`/`DROP OWNED`/`DROP ROLE` cleanup path, which had never been exercised against real RDS before this.
- Schema/role/ownership state confirmed directly: all 13 schemas present, `core` owned by `migration_owner`, `migration_owner` shows `rolcanlogin = false` while the five login roles show `true`, `rds_iam` granted to exactly those five (not `migration_owner`), `core.alembic_version` still owned by the connecting user (untouched by the ownership split).
- `pytest tests/database` — the ephemeral-per-run database mechanism from [PLAN.md §29.9](PLAN.md#299-aws-first-verification-mechanism): creates `dnd_ai_test_<random>` on the shared instance, migrates it, runs the constraint tests, drops it. Confirmed no orphaned databases afterward.
- Full suite (`uv run pytest`, real `uv` environment, not an ad-hoc venv) — 15 passed.
- CI: pushed to `main`, both `lint-and-type-check` and `aws-verification` jobs passed on GitHub's own runners — OIDC auth, session-scoped security-group rule opened and revoked, ephemeral database created and dropped, migrations, downgrade, `alembic check`, full test suite.

## Bugs Found and Fixed By This Verification

Every one of these was invisible to offline SQL generation and would have been invisible to a local-container test run. This is the reason [ADR 0008](adr/0008-aws-first-deployment-and-verification.md) exists.

1. **Route table silently disabled public access.** `terraform/modules/database` unconditionally created a route-less "private" route table and associated it onto reused default-VPC subnets, stripping their existing internet-gateway route. `enable_public_access = true` had no effect. Fixed: only create/associate that table when the module creates its own VPC.
2. **`migration_owner` holding `rds_iam` locked out the RDS master user.** Granting the ownership-transfer membership made the master user a transitive member of `rds_iam`, which forces IAM auth and disables password auth for every inheriting role — including the master user itself. Fixed by [ADR 0009](adr/0009-separate-owning-role-from-login-roles.md): split into a `NOLOGIN` owning role (`migration_owner`, never granted `rds_iam`) and a login role (`migration_runner`) that runs migrations as a member of it.
3. **`SET ROLE migration_owner` broke Alembic's own bookkeeping write.** Persisting the role switch for the rest of the run meant Alembic's post-migration write to `core.alembic_version` — a table it created and owns as the original connecting user, before any of our migration code runs — failed with "permission denied for table alembic_version". Fixed by granting `migration_owner` explicit access to that one table.
4. **The same `SET ROLE` check broke the ephemeral-database mechanism outright.** Testing only "does `migration_owner` exist and am I a member" is true on *any* database once bootstrap has run anywhere on the instance, because roles are cluster-wide in PostgreSQL while schema grants are per-database. A fresh ephemeral test database would switch to `migration_owner` before that database had ever been bootstrapped, and `CREATE TABLE core.alembic_version` failed with "permission denied for schema core". Fixed by checking whether `core.alembic_version` already exists in the *current* database — a proxy for "bootstrap has actually run here" — before switching role.
5. **A failed migration orphaned its ephemeral database.** `tests/conftest.py`'s `try`/`finally` didn't wrap the database creation itself, so a migration failure (found while chasing bug 4) left the database behind permanently. Found four such orphans from this session's own debugging before the fix. Now everything after `CREATE DATABASE` is inside the guarded block.
6. **CI failed before AWS was even reached.** `uv.lock` was never committed — no environment doing Phase 1's work had `uv` installed to generate it. `astral-sh/setup-uv@v4`'s dependency-cache step globs for `**/uv.lock` and hard-fails when nothing matches. Fixed by installing `uv`, running `uv sync --all-extras` for real, and committing the result.

## Local Fallback (AWS Unreachable Only)

Per [PLAN.md §23.0](PLAN.md#230-aws-verification-policy), this is not the default path. Set `DND_AI_USE_LOCAL_POSTGRES=1` and point `DATABASE_URL` at a local container:

```bash
docker run -d --name dnd-ai-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=dnd_ai -p 5432:5432 postgres:15
```

Steps 3–6 below are unchanged against it. `rds_iam` doesn't exist locally, so the bootstrap migration's conditional grants are silently skipped — expected, not a failure.

### 3. Run migrations

```bash
uv run alembic -c database/alembic.ini current
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini current --verbose
```

### 4. Verify database structure

```bash
docker exec -it dnd-ai-pg psql -U postgres -d dnd_ai
```

```sql
\dn+  -- all 13 schemas, all owned by migration_owner
\dD core.*  -- three domain types
\du  -- six roles plus postgres; migration_owner shows "Cannot login"

SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname LIKE 'migration%';
SELECT nspname, pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'core';
```

Expected schemas: ai, audit, campaign, character, core, import, integration, interaction, knowledge, narrative, public, rules, security, world.

Expected roles ([DATABASE_CONVENTIONS.md §27.1](DATABASE_CONVENTIONS.md#271-database-roles)): admin_maintenance, app_read_only, app_read_write, integration_worker, migration_runner, migration_owner, postgres.

Expected domains in core: rating_1_10, percentage_0_100, nonnegative_integer.

### 5. Test downgrade

```bash
uv run alembic -c database/alembic.ini downgrade -1
uv run alembic -c database/alembic.ini current
uv run alembic -c database/alembic.ini downgrade base
uv run alembic -c database/alembic.ini upgrade head
```

`core` survives `downgrade base` deliberately — it holds Alembic's own version table (`version_table_schema = core`), so the revision that creates the schema can't also drop it. See the comment in `001_bootstrap.py::downgrade`.

### 6. Run quality checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

### 7. Clean up

```bash
docker stop dnd-ai-pg
docker rm dnd-ai-pg
```

## Known Follow-Ups

- **Orphaned KMS key** from an earlier teardown (`5a359a0a-4d30-4c00-925f-2dfad6e5820d`) — the deploying IAM user lacks `kms:ScheduleKeyDeletion`. Still enabled, no alias, unused. Needs either that permission or manual console deletion.
- **`iam_auth_db_users`** (the Terraform variable listing login roles for `rds_iam_connect_arns`) duplicates the role list in `001_bootstrap.py`. They must be kept in sync by hand; the variable's validation rule only catches `migration_owner` being added to it, not general drift.
- **Seed idempotency** is not yet a CI step — no revision calls `apply_seed()` with real content yet. Add the check when the first seed file lands.
- **`staging`/`prod`** remain unbuilt. The SSM-based migration runner in [PLAN.md §29.6](PLAN.md#296-migration-execution-mechanism) is what those will use; `dev`'s direct-reachability mechanism (§29.9) is dev-only by design.

## Implementation Status

Phase 1 deliverables completed:
- Project skeleton (pyproject.toml, toolchain configuration, committed uv.lock)
- Alembic scaffold (database/alembic.ini, env.py, script template)
- Bootstrap revision — six roles (one `NOLOGIN` owning role, five login roles), thirteen schemas, extensions, ownership transfer
- Shared domains (rating_1_10, percentage_0_100, nonnegative_integer), with positive and negative constraint tests per [DATABASE_CONVENTIONS.md §32.1](DATABASE_CONVENTIONS.md#321-constraint-tests)
- Seed infrastructure (seeds.py, database/seeds/)
- CI workflow, verified green against live AWS on GitHub's own runners
- AWS infrastructure: `dev` deployed, GitHub OIDC role for CI, all four exit criteria closed with real evidence

Next phase: Phase 2 (Core world platform) per [PLAN.md §23](PLAN.md#23-delivery-phases).
