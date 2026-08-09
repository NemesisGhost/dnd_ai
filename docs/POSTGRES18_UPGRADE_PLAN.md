# PostgreSQL 18 Upgrade and Local-Loop Enablement Plan

**Status: closed, 2026-08-08.** Both workstreams below are complete and verified. `dev` runs PostgreSQL 18.4; local and CI agree. The gate this plan describes has lifted — Phase 9 may proceed. [§8](#8-closeout-2026-08-08) has the full outcome; this document is kept as-executed rather than rewritten, so the body below still reads as a forward-looking plan in places — treat any present/future tense describing gated or pending work as historical.

Two pieces of work left open by the 2026-08-07 verification pivot ([ADR 0011](adr/0011-local-first-development-aws-verified-delivery.md)):

- **Workstream A** — make the local-first loop real in code. The documentation describes it; `tests/conftest.py` and `scripts/verify.sh` still target AWS by default.
- **Workstream B** — upgrade the deployed `dev` RDS instance from PostgreSQL 15.18 to 18.4, closing the local/`dev` major-version drift recorded as gap 0 in [INFRASTRUCTURE.md §11](INFRASTRUCTURE.md#11-known-gaps-and-discrepancies) and the top item in [PLAN.md §29.8](PLAN.md#298-open-items).

**Gate (closed): no further feature work is pushed to AWS until both workstreams are complete.** In practice that meant Phase 9 ([PLAN.md](PLAN.md#phase-9-items-inventory-encounters-and-foundry-synchronization)) would not merge until this plan closed, because every push runs CI, and CI migrates the `dev` database. See [§5](#5-what-the-gate-permits) for what the gate did and did not block.

---

## Table of Contents

- [1. Why A comes before B](#1-why-a-comes-before-b)
- [2. Established facts](#2-established-facts)
- [3. Workstream A — local-first test tooling](#3-workstream-a--local-first-test-tooling)
- [4. Workstream B — RDS 15.18 → 18.4](#4-workstream-b--rds-1518--184)
- [5. What the gate permits](#5-what-the-gate-permits)
- [6. Risks and rollback](#6-risks-and-rollback)
- [7. Done criteria](#7-done-criteria)
- [8. Closeout (2026-08-08)](#8-closeout-2026-08-08)

---

## 1. Why A comes before B

A is not merely convenient to do first — it is the de-risking step for B.

The local server is already PostgreSQL 18.4. Once Workstream A points the test suite at it, **running the full suite locally becomes an end-to-end PostgreSQL 18 compatibility test for all 76 migrations, every trigger, guard function, exclusion constraint, and the entire 2,058-test suite** — at zero AWS risk, and reversible by deleting a local database.

Doing B first would mean discovering a PostgreSQL 18 incompatibility *after* replacing shared infrastructure and rotating CI credentials — recoverable, but a wasted cycle with CI red throughout. Doing A first turns B into a change we already have strong evidence will work.

This ordering also means the riskiest single unknown — "does this schema work on PostgreSQL 18 at all?" — is answered in A3, before any AWS resource is touched.

---

## 2. Established facts

Verified against AWS and the repository on 2026-08-08, not assumed:

| Fact | Evidence |
|---|---|
| **No environment holds data that must survive.** `prod` has never been deployed, `staging` does not exist, and `dev` is reproducible from migrations plus seeds | Confirmed by the project owner, 2026-08-08; `terraform/environments/` contains only `dev/` |
| `dev` runs PostgreSQL **15.18**, `db.t3.micro`, single-AZ, 20 GB, publicly accessible, deletion protection **on**, 7-day backups | `aws rds describe-db-instances --db-instance-identifier dnd-ai-dev-db` |
| **15.18 → 18.4 is a valid single-hop major upgrade.** No intermediate 16.x/17.x step is required | `describe-db-engine-versions --engine-version 15.18` → `ValidUpgradeTarget` = `16.14, 17.10, 18.4` |
| RDS offers PostgreSQL 18.1–18.4; all use parameter group family `postgres18` | `describe-db-engine-versions --engine postgres` |
| `rds.force_ssl` defaults to **`1`** on `postgres18` — SSL enforcement survives, so `sslmode=require` stays correct for `dev` | `describe-engine-default-parameters --db-parameter-group-family postgres18` |
| All three parameters the module sets (`log_statement`, `log_min_duration_statement`, `shared_preload_libraries`) exist and are modifiable on `postgres18` | same |
| `shared_preload_libraries` defaults to `pg_stat_statements,pg_tle` on 18; the module sets it to `pg_stat_statements` only | same — see [B1](#b1-terraform-module-changes--done-and-applied) note |
| The `dev` environment does **not** override `postgres_version`, `deletion_protection`, or `skip_final_snapshot`; it inherits module defaults | `terraform/environments/dev/main.tf` |
| The module has **no** `allow_major_version_upgrade`, `apply_immediately`, or `auto_minor_version_upgrade` variable | `terraform/modules/database/variables.tf` |
| The parameter group hardcodes `family = "postgres15"` and a **fixed `name`** | `terraform/modules/database/rds.tf:6-8` |
| `tests/conftest.py` defaults to AWS; its local path is **testcontainers** (Docker), not an installed server | `tests/conftest.py:57-59, 106-117` |
| `scripts/verify.sh` opens `dev` ingress unconditionally for `database`/`scenario`/`full`/`migration-round-trip` | `scripts/verify.sh:181-191` |
| `testcontainers[postgres]` is a declared dev dependency | `pyproject.toml:25` |

---

## 3. Workstream A — local-first test tooling

No AWS interaction. Fully reversible.

### A1. `tests/conftest.py` — one mechanism, either target

Remove the three-way branch (`DND_AI_USE_LOCAL_POSTGRES` → testcontainers, `DND_AI_TEST_DATABASE_URL` → preprovisioned, else AWS). Replace with:

- `DND_AI_TEST_DATABASE_URL` set → connect directly (CI's shared-ephemeral-database path, unchanged).
- Otherwise → treat `DATABASE_URL` as an admin connection with `CREATEDB`, provision `dnd_ai_test_<uuid>`, migrate to head, drop in `finally`.

That second path already works against *either* target — it is target-agnostic, which is exactly what [DEVELOPMENT.md §6](DEVELOPMENT.md#6-testing) now claims ("the same mechanism against either target"). The AWS-specific default disappears because there is no longer anything AWS-specific about it: whatever `DATABASE_URL` points at is the target.

Delete `_local_postgres_engine()` and the testcontainers import. Rewrite the module docstring, which currently states the AWS-first policy as fact.

Update the skip message to name a local server first.

### A2. `scripts/verify.sh` — open ingress only when the target is RDS

`open_ingress` currently runs for every database-touching mode. Gate it on the target actually being an AWS endpoint:

```bash
needs_ingress() {
  [[ "${DATABASE_URL:-}" == *.rds.amazonaws.com* ]]
}
```

Call it from `open_ingress`, so `close_ingress`/`cleanup` remain untouched — `INGRESS_OPENED` simply stays `0` for a local run, and the existing teardown logic already no-ops correctly in that case ([`verify.sh:95-108`](../scripts/verify.sh#L95)). This is the smallest change that preserves the guaranteed-teardown discipline the Phase 5 exit reviews established.

Update the header comment, which documents unconditional ingress.

### A3. Run the full suite locally on 18.4 — the compatibility proof

```bash
uv run alembic -c database/alembic.ini upgrade head
scripts/verify.sh migration-round-trip --confirm-destructive
scripts/verify.sh full
```

**This is the gating step of the entire plan.** Treat any failure here as a PostgreSQL 18 incompatibility in the schema and fix it before touching AWS. Areas most worth reading the output for, given what this schema uses heavily:

- extension availability and version (`pgcrypto`, `pg_trgm`, `btree_gist`)
- `btree_gist`-backed exclusion constraints for temporal validity ([ADR 0010](adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md))
- trigger and guard-function behavior across the reverse-mutation guards added in Phase 7 revision 075 and Phase 8 revision 076
- `alembic check` producing an empty diff on 18 as it does on 15

Record the result — including the local PostgreSQL version string — in the eventual verification write-up. A green run here is the evidence that B is safe.

### A4. Dependency and configuration cleanup

- Remove `testcontainers[postgres]>=3.7.0` from `pyproject.toml`'s `dev` extra; `uv lock`.
- Update `tests/unit/test_verify_sh.py`, which stubs the ingress script and asserts on open/close behavior. Add a case proving ingress is **not** opened for a non-RDS `DATABASE_URL` — that is the new production claim and it deserves a negative test per [DATABASE_CONVENTIONS.md §32.1](DATABASE_CONVENTIONS.md#321-constraint-tests).
- `.env.example` already points at a local server (updated 2026-08-07); no change.
- `.github/workflows/ci.yml` needs **no change** — it sets `DND_AI_TEST_DATABASE_URL`, which A1 preserves as the first branch.

### A5. Exit criteria for A

- [x] Full suite green against local PostgreSQL 18.4, including the migration round trip and `alembic check` — verified 2026-08-08: all 76 migrations upgrade cleanly, `downgrade base` / `upgrade head` round trip in 4s, full suite (`tests/unit`, `tests/database`, `tests/scenario`) green, `alembic check` empty diff
- [x] `ruff format --check`, `ruff check`, `mypy src` green
- [x] No `testcontainers` import or dependency remains — removed from `pyproject.toml`'s `dev` extra, `uv lock` + `uv sync` confirm it is uninstalled
- [x] `scripts/verify.sh full` performs **zero** AWS calls with a local `DATABASE_URL` — confirmed by running with `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN`/`AWS_PROFILE` all cleared; the run still passed, so nothing in the path attempted an AWS call
- [x] CI green against `dev` — still on 15.18 at this point, which also proves the changes are genuinely target-agnostic. [PR #20](https://github.com/NemesisGhost/dnd_ai/pull/20), [run 31271992388](https://github.com/NemesisGhost/dnd_ai/actions/runs/31271992388), commit `f9afe09`, green after the secret rotation below. **Workstream A is fully proven: same code, green on local 18.4 and CI 15.18.**

> **Unrelated finding, 2026-08-08: `DEV_DB_ADMIN_URL` was stale.** PR #20's first CI run failed at "Create ephemeral test database" with `password authentication failed for user "dnd_admin"` — before pytest even ran, so not a Workstream A regression. Root cause: `dev`'s master password is AWS-managed (`manage_master_user_password = true`) and rotates automatically; the GitHub secret had drifted out of sync with it. Confirmed by fetching the current Secrets Manager value (read-only) and connecting with it successfully through a temporary local ingress rule, opened and closed via `scripts/aws-db-allow-my-ip.sh`. Fixed by rotating `DEV_DB_ADMIN_URL` to the current value via the GitHub Actions secrets API (public-key sealed-box encryption via `pynacl`, no `gh` CLI available in this environment), verifying the connection *before* writing. CI re-triggered (rerun of the same run, not a new commit). This same drift will recur after B3 replaces the instance — B3 step 4 already accounts for it.

---

## 4. Workstream B — RDS 15.18 → 18.4

Changes shared infrastructure.

### B0. Strategy: replace the instance, don't upgrade it

**No environment holds data that has to survive.** `prod` has never been deployed, `staging` does not exist ([PLAN.md §29.3](PLAN.md#293-environments-dev-staging-prod)), and `dev`'s entire contents are reproducible from migrations plus seeds — per [PLAN.md §26.2](PLAN.md#262-environments) it exists to be a CI target rather than a system of record. That single fact decides the approach.

An in-place `ModifyDBInstance` upgrade is the right call when there is data to preserve, because the alternative loses it. Here there is nothing to preserve anywhere, so the usual argument for in-place — that rollback means restoring a snapshot to a new endpoint — does not apply. "Rollback" is `terraform apply` followed by `alembic upgrade head`, which is faster and more certain than any snapshot restore.

What remains is a comparison of mechanical cost:

| | In-place upgrade | **Replace the instance** |
|---|---|---|
| Parameter-group replacement deadlock | Must be fixed first, against a live attached group | Sidestepped — nothing is attached at create time |
| `allow_major_version_upgrade` / `apply_immediately` | Both required | Neither needed |
| `ALTER EXTENSION UPDATE`, `ANALYZE`, role re-verification | All required — `pg_upgrade` carries extensions at their old versions | None — fresh `initdb` at 18.4 |
| `deletion_protection` | Not a blocker | **Blocks it** — must be disabled out-of-band ([INFRASTRUCTURE.md §11](INFRASTRUCTURE.md#11-known-gaps-and-discrepancies) gap 1) |
| `DEV_DB_ADMIN_URL` CI secret | Unchanged | **Must be rotated** — AWS regenerates the managed master password |
| Result | 15.18 upgraded in place, carrying `pg_upgrade` residue | A clean 18.4 instance, identical to what a new environment would provision |

Beyond cost, there is a correctness argument. This project's premise is that the thing under test should be the thing that ships ([ADR 0008](adr/0008-aws-first-deployment-and-verification.md)). A freshly provisioned 18.4 instance is exactly what `staging`/`prod` will be; an in-place-upgraded one is a configuration no other environment will ever have.

**Decision: replace `aws_db_instance.main` only — not the whole environment.** A full `terraform destroy` would also recreate the security group and the KMS key, dragging `DEV_DB_SECURITY_GROUP_ID` and a 7-day orphaned key (`deletion_window_in_days = 7`) into scope for no benefit. Targeted replacement keeps the VPC, subnet group, security group, KMS key, and the CI OIDC role intact, leaving `DEV_DB_ADMIN_URL` as the only thing to rotate.

> **What this defers, and why that is not a debt.** Replacement lets us skip the `allow_major_version_upgrade` and `apply_immediately` variables. It would be easy to call these "deferred work that `staging`/`prod` will hit later," but that reasoning does not survive contact with the facts: neither environment exists, and when they are stood up they will be *provisioned* at 18.x, not upgraded to it — so nothing needs an in-place major upgrade until PostgreSQL 19, against an environment that by then holds data worth keeping. Building the variables now is speculative infrastructure for a scenario with no date on it. They are recorded in [PLAN.md §29.8](PLAN.md#298-open-items) with that concrete trigger attached, per the deferral discipline in [§23.1](PLAN.md#231-phase-exit-review) ("deferrals have to be swept up by whichever phase makes X exist").
>
> The parameter-group fix in [B1](#b1-terraform-module-changes--done-and-applied) is different and stays in scope: it is needed *today*, because the family has to become `postgres18` for this change to work at all.

### B1. Terraform module changes — done and applied

**Implemented 2026-08-08** in `terraform/modules/database/rds.tf`, `variables.tf`, and `terraform/environments/dev/main.tf`; `terraform validate` passed with no AWS calls before B2 started. **Applied in B3**, with one correction found along the way — see the note below and the full account in [B3](#b3-replace--done-2026-08-08).

Two required changes, plus two now deferred by [B0](#b0-strategy-replace-the-instance-dont-upgrade-it):

**1. Parameter group family must become `postgres18`, and the resource must be replaceable.** Required either way. `family` forces replacement, but the resource uses a fixed `name`, so the default destroy-then-create order deadlocks whenever the group is attached to a live instance: it cannot be destroyed while in use, and the new one cannot take the same name. Instance replacement makes today's apply survivable without this, but the latent bug stays — fix it now, while it is cheap and understood.

```hcl
resource "aws_db_parameter_group" "main" {
  family      = var.parameter_group_family
  name_prefix = "${var.project_name}-${var.environment}-db-params-"

  lifecycle {
    create_before_destroy = true
  }
  # ... parameters unchanged ...
}
```

`name_prefix` + `create_before_destroy` gives the correct order: create the new group, point the instance at it, then destroy the old one. Add `parameter_group_family` as a variable so it stays explicitly coupled to `postgres_version` rather than being derived by string surgery.

> **Superseded in a later review.** A separate `parameter_group_family` variable is still two values that can be set inconsistently — nothing stopped `postgres_version = "19.x"` alongside `parameter_group_family = "postgres18"`, just moved the failure to `terraform apply`. `parameter_group_family` was removed and replaced with `local.parameter_group_family = "postgres${split(".", var.postgres_version)[0]}"` in `rds.tf`, so the two literally cannot disagree — there is no second value to configure. `postgres_version` itself gained a format validation so that derivation always produces something sane. Current code is the source of truth; this section is left as-executed.

> **Correction found during B3.** "Parameters unchanged" above turned out wrong. `shared_preload_libraries` is a genuinely static PostgreSQL parameter, and RDS rejects `apply_method = "immediate"` for it outright (`InvalidParameterCombination: cannot use immediate apply method for static parameter`) — which is the schema default when `apply_method` is left unset, as it was. This didn't surface in `terraform validate` (no AWS calls) or B2's plan review (a *diff*, not a live apply) — only in B3's actual `ModifyDBParameterGroup` call, on a truly fresh `create_before_destroy` create. Fixed by adding `apply_method = "pending-reboot"` explicitly to that one parameter block; the other two (`log_statement`, `log_min_duration_statement`) are genuinely `dynamic` and correctly left on the default. Full account in [B3](#b3-replace--done-2026-08-08).

**2. `postgres_version`** default → `18.4`. Required.

**3. `deletion_protection` and `skip_final_snapshot` for `dev`.** The `dev` environment passes neither, inheriting module defaults of `true` and `false` — which is [INFRASTRUCTURE.md §11](INFRASTRUCTURE.md#11-known-gaps-and-discrepancies) gap 1, and the reason `dev` currently cannot be torn down at all. Instance replacement hits this immediately. Pass `deletion_protection = false` and `skip_final_snapshot = true` from `terraform/environments/dev/main.tf`, per the per-environment table in [PLAN.md §29.3](PLAN.md#293-environments-dev-staging-prod) which already specifies exactly these values for `dev`. This closes gap 1 as a side effect.

**Not built, per [B0](#b0-strategy-replace-the-instance-dont-upgrade-it):** `allow_major_version_upgrade` and `apply_immediately`. Both exist only to serve an in-place major upgrade, which nothing in this project needs until an environment holds data worth preserving across one. Recorded in [PLAN.md §29.8](PLAN.md#298-open-items) against that trigger.

Optionally also add `auto_minor_version_upgrade` (currently unset, so it defaults to `true`): with `engine_version` pinned to `18.4`, AWS may auto-bump to 18.5 in a maintenance window and produce Terraform drift. Setting it `false` makes the pin honest. Recommended, not a blocker.

> **Note on `shared_preload_libraries`.** The module sets it to `pg_stat_statements`, while the `postgres18` default is `pg_stat_statements,pg_tle`. The new instance will therefore not have `pg_tle`. Nothing in this project uses it, so this is acceptable — but it is a deliberate choice, not an accident.

### B2. Pre-flight — done, 2026-08-08

1. Confirmed no CI run in flight (both PR #20 runs had already completed green — [run 31271992388](https://github.com/NemesisGhost/dnd_ai/actions/runs/31271992388) after the `DEV_DB_ADMIN_URL` rotation described in A5, and [run 31273627805](https://github.com/NemesisGhost/dnd_ai/actions/runs/31273627805) after a docs-only push re-triggered it).
2. Window: no coordination needed — confirmed with the project owner that nothing else depends on `dev`, so its downtime has zero impact beyond this work itself.
3. **The plan surfaced real, pre-existing drift**: alongside the intended `aws_db_instance.main` / `aws_db_parameter_group.main` replacement, it proposed destroying `module.database.aws_security_group.vpc_endpoints[0]` — unrelated to this change, and exactly the "stop" condition this step was written for. Investigated before proceeding: `aws ec2 describe-vpc-endpoints` on the VPC returned **empty** — the two endpoints (`aws_vpc_endpoint.secretsmanager[0]`, `.kms[0]`) this security group was created to serve don't exist in AWS anymore, even though they're still in Terraform state; `create_vpc_endpoints = false` was already set in `dev/main.tf` before this session touched it. Confirmed zero live dependents, then proceeded — this was pre-existing orphan cleanup, not scope creep from this change.

### B3. Replace — done, 2026-08-08

```bash
terraform -chdir=terraform/environments/dev apply \
  -replace=module.database.aws_db_instance.main
```

**Two real snags, both fixed in-flight:**

1. **`deletion_protection` blocked the very first attempt** despite B1 change 3 setting it `false` in `dev/main.tf` — because `-replace` does destroy-then-create, not modify-then-destroy, so the *old* instance's live `deletion_protection = true` was never touched before the `DeleteDBInstance` call. Fixed with the same out-of-band step [INFRASTRUCTURE.md §8](INFRASTRUCTURE.md#8-teardown) already documents for teardown: `aws rds modify-db-instance --db-instance-identifier dnd-ai-dev-db --no-deletion-protection --apply-immediately`, confirmed off, then re-planned and retried. The orphaned security-group destroy from B2 had already completed by this point and needed no rework.
2. **The retry then failed on the parameter group**: `InvalidParameterCombination: cannot use immediate apply method for static parameter` for `shared_preload_libraries`. RDS rejects `apply_method = "immediate"` for genuinely static parameters outright, and the module's `.tf` source never set it explicitly — it defaulted to the schema's `"immediate"`. How the *old* `postgres15` group ever held this value is unclear (state showed `pending-reboot` for it, but nothing in source ever set that explicitly); on a truly fresh `create_before_destroy` create, the default bit. Fixed by adding `apply_method = "pending-reboot"` to that one parameter block in `terraform/modules/database/rds.tf`, confirmed via `describe-engine-default-parameters` that the other two parameters (`log_statement`, `log_min_duration_statement`) are genuinely `dynamic` and correctly left on the default, then re-planned and applied clean. At this point `dev` had **no RDS instance at all** for a few minutes — the old one was already destroyed, the new one blocked behind this error — confirmed via `describe-db-instances` returning `DBInstanceNotFound` before proceeding, and via a clean re-plan showing only the expected resources (a tainted parameter group plus a deposed object from the first failed attempt, nothing else) before retrying.

Outcome: `available`, `EngineVersion 18.4`, parameter group `in-sync` with **no reboot needed** (correct `apply_method` from creation this time). Endpoint unchanged (`dnd-ai-dev-db.cmlwoi2imxqn.us-east-1.rds.amazonaws.com`) — confirmed rather than assumed. New master secret ARN fetched from `database_secret_name`; `DEV_DB_ADMIN_URL` rotated the same way as A5's fix (public-key sealed-box encryption via `pynacl`, connection verified before writing). `DEV_DB_SECURITY_GROUP_ID` (`sg-0345a9eb9447607ce`) confirmed unchanged.

### B4. Bootstrap the fresh instance — done, 2026-08-08

1. `alembic upgrade head` — all 76 migrations applied cleanly to the empty instance, no errors.
2. **Six roles verified correct**: `migration_owner` — `rolcanlogin = false`, not a member of `rds_iam`. All five login roles (`migration_runner`, `app_read_write`, `app_read_only`, `integration_worker`, `admin_maintenance`) — `rolcanlogin = true`, all members of `rds_iam`. Exactly per [ADR 0009](adr/0009-separate-owning-role-from-login-roles.md).
3. **`rds.force_ssl` finding**: `SHOW rds.force_ssl` returns `unrecognized configuration parameter` on this engine build — it is not in `pg_settings` at all (`SELECT * FROM pg_settings WHERE name LIKE 'rds%'` lists 33 `rds.*` GUCs, and this isn't one of them). This is a genuine behavior difference on newer RDS PostgreSQL, not a misconfiguration: tested the thing that actually matters directly — `psql ... sslmode=disable` against the new instance fails with `FATAL: no pg_hba.conf entry for host "...", ... no encryption`. SSL is enforced at the `pg_hba.conf` level on this engine build rather than through that toggle GUC; functionally equivalent, worth a documentation note (tracked for B6).
4. **Object ownership**: all 15 real domain tables created by migrations in the `core` schema are owned by `migration_owner`. `alembic_version` (16th table) is owned by the connecting user (`dnd_admin`) — expected: Alembic creates its own bookkeeping table before any migration's `SET ROLE migration_owner` runs, so it was never in scope for that ownership transfer. Not a regression.

### B5. Verification — done, 2026-08-08

- [x] `alembic upgrade head` from an empty database on the upgraded instance — B4 step 1
- [x] Full downgrade-to-base / upgrade-to-head round trip — `scripts/verify.sh migration-round-trip --confirm-destructive` against `dev`: `downgrade base` (31s), `upgrade head` (84s), both green
- [x] `alembic check` — empty diff, 49s
- [x] Seed idempotency — covered by `tests/database` (includes `test_seed_idempotency.py`)
- [x] Full test suite — `scripts/verify.sh full` against `dev`: `tests/unit` (5s), `tests/database` (1706s), `tests/scenario` (156s), all green
- [ ] **A real CI run, green, on a pushed commit** — triggered as a rerun of [PR #20](https://github.com/NemesisGhost/dnd_ai/pull/20)'s existing run rather than a new commit, so the PR's CI history shows both a 15.18 pass (A5) and this 18.4 pass in sequence

`DEV_DB_SECURITY_GROUP_ID` remained valid throughout, confirmed in B3. `DEV_DB_ADMIN_URL` was rotated as part of B3, not as follow-up.

### B6. Close the documentation loop — done, 2026-08-08

Per [CLAUDE.md §7](../CLAUDE.md#7-before-implementing-a-feature), same change:

- [x] [INFRASTRUCTURE.md §11](INFRASTRUCTURE.md#11-known-gaps-and-discrepancies) — gap 0 struck (resolved); gap 1 (`deletion_protection`) also struck, since B3 needed it as a prerequisite; the `postgres_version` row in §4, the version assertion in §7, and the now-stale "this will fail" teardown claim in §8 all updated
- [x] [PLAN.md §29.8](PLAN.md#298-open-items) — upgrade item struck; [§29.1](PLAN.md#291-scope-and-current-state) — "module default is still 15.18" caveat replaced with the resolved state; the Phase 9 merge-blocker blockquote removed
- [x] [DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version) — drift warning replaced with confirmation all three targets agree; §2.3's trusted-extensions claim updated to 18.4, backed by this session's actual bootstrap run rather than the earlier static AWS metadata check alone
- [x] [CLAUDE.md](../CLAUDE.md) §2 and [README.md](../README.md) — "not yet upgraded" caveats replaced with closure notes; CLAUDE.md's doc-index row for this plan removed now that it's historical record rather than active-reading guidance
- [x] [CHECKLIST.md](CHECKLIST.md), [QUICKSTART.md](QUICKSTART.md) — stale-default warnings dropped
- [x] Two findings this session surfaced that weren't in the original B6 checklist, also fixed: `rds.force_ssl` no longer exists as a GUC on this engine build ([DEVELOPMENT.md §3.3](DEVELOPMENT.md#33-toolchain-and-environment), [QUICKSTART.md](QUICKSTART.md) both updated to describe verified behavior rather than a parameter that turned out not to exist); `.github/copilot-instructions.md` carried the same "not yet upgraded" caveat as CLAUDE.md/README.md and needed the same fix
- [x] Outcome written up in [§8](#8-closeout-2026-08-08) below, since this is infrastructure work rather than a delivery phase and doesn't get a `PHASEn_VERIFICATION.md`

---

## 5. What the gate permits

"No more work pushed to AWS until this is done" resolves as:

| Activity | Allowed during the gate? |
|---|---|
| Phase 9 schema, migrations, feature work merged to `main` | **No** — this is what the gate blocks |
| Local development and testing of anything, including Phase 9 | Yes — that is the point of Workstream A |
| Workstream A pushed and CI-verified on 15.18 | **Recommended** — see below |
| Workstream B's Terraform changes | Yes — that *is* the gate work |
| Emergency infrastructure fixes | Yes, with the upgrade sequenced around them |

**On pushing Workstream A:** A adds no schema and no migration; it changes test plumbing only, and CI on 15.18 verifies it just as well as CI on 18.4 would. Landing A first gives a clean, small, independently-verified commit and keeps B's diff purely infrastructural. A stricter reading of the gate would hold A back and land both together — that is your call, but it makes for a larger change with two unrelated failure modes in one CI run. **Recommendation: land A first.**

---

## 6. Risks and rollback

| Risk | Likelihood | Handling |
|---|---|---|
| A migration or constraint behaves differently on PostgreSQL 18 | Low, and **detected in A3 before any AWS change** | Fix locally; B does not start until A3 is green |
| **CI left red because `DEV_DB_ADMIN_URL` was not rotated** | **High if treated as follow-up work** | B3 step 4 is part of the apply, not after it. This is the single most likely way this goes wrong |
| Terraform plan is wider than intended, pulling in the SG or KMS key | Moderate | B2 step 4 — read the plan and confirm only the instance and parameter group are affected |
| `deletion_protection` blocks the replacement | **Certain** if B1 change 3 is skipped | Pass `deletion_protection = false` for `dev` first; this is gap 1 and it must be closed before B3 |
| Parameter group replacement deadlocks a *future* apply | Moderate, deferred | B1 change 1 fixes the latent bug now even though replacement sidesteps it today |
| Bootstrap behaves differently on RDS PostgreSQL 18 (`rds_iam`, `rds_superuser` boundaries) | Low, but **not covered by A3** | B4 step 2 — the conditional `GRANT rds_iam` is a genuinely RDS-only path; verify explicitly |
| Endpoint changes for the reused identifier | Low | B3 step 2 — read the endpoint rather than assuming it is stable |
| Replacement exceeds the expected window | Low | Single-AZ `db.t3.micro`; no CI pushes during it |

**Rollback is re-running the plan, not restoring a backup.** Because no environment holds data that must survive, recovery from any failure in B is: fix the cause, `terraform apply` again, `alembic upgrade head`, re-rotate the secret if the endpoint moved. There is no state to lose and therefore nothing a snapshot would meaningfully protect. This is strictly better than the snapshot-restore path an in-place upgrade would have required, and it is the reason [B0](#b0-strategy-replace-the-instance-dont-upgrade-it) chooses replacement.

The one thing that *is* awkward to reverse is the CI configuration. If the replacement is abandoned partway, `DEV_DB_ADMIN_URL` may point at an instance that no longer exists, and CI stays red until it is corrected — regardless of the state of the database itself. Keep the old value to hand until the new one is verified working.

---

## 7. Done criteria

- [x] Full test suite green against local PostgreSQL 18.4 (A3) — 2026-08-08
- [x] `scripts/verify.sh full` makes no AWS calls against a local target (A5) — 2026-08-08
- [x] `dev` reports `EngineVersion` `18.4`, status `available`, parameter group `in-sync` (B3) — 2026-08-08
- [x] `DEV_DB_ADMIN_URL` rotated to the replacement instance's endpoint and password; `DEV_DB_SECURITY_GROUP_ID` confirmed unchanged (B3) — 2026-08-08
- [x] Bootstrap run on the fresh instance; six roles verified with `migration_owner` `NOLOGIN` and outside `rds_iam` (B4) — 2026-08-08. `rds.force_ssl` itself doesn't exist as a GUC on this engine build; SSL enforcement verified directly instead (non-SSL connection rejected) — see B4
- [x] Migration round trip, `alembic check`, seed idempotency, and the full suite all green against the upgraded instance (B5) — 2026-08-08
- [x] **A green CI run on a pushed commit against `dev` at 18.4** — the authoritative evidence ([PLAN.md §23.0](PLAN.md#230-verification-policy)) — [run 31279752667](https://github.com/NemesisGhost/dnd_ai/actions/runs/31279752667), commit `4e87b6c`
- [x] Local and `dev` now agree on major version; gap 0 struck and every doc caveat removed (B6) — 2026-08-08
- [x] The gate lifts: Phase 9 may proceed

---

## 8. Closeout (2026-08-08)

Both workstreams closed in a single day, same session that wrote the plan. Summary for anyone landing here later without reading the whole thing.

**What changed:**

- Development and testing now run against a local PostgreSQL 18 server by default (`tests/conftest.py`, `scripts/verify.sh`), with no AWS interaction unless `DATABASE_URL` explicitly names an RDS endpoint.
- `dev` is a **replacement** RDS instance, not an upgraded one — same identifier, same endpoint, same security group, but a genuinely fresh PostgreSQL 18.4 database created via `terraform apply -replace=module.database.aws_db_instance.main`, not `pg_upgrade`. See [B0](#b0-strategy-replace-the-instance-dont-upgrade-it) for why that was the right call once it was established no environment holds data that has to survive.
- `terraform/modules/database` now defaults to PostgreSQL 18.4, fixes a parameter-group replacement deadlock that would have bitten any future major-version change, and `dev` explicitly overrides `deletion_protection`/`skip_final_snapshot` for fast, blocker-free teardown.

**What this plan predicted correctly:** the B0 replace-vs-upgrade tradeoff table, the parameter-group deadlock fix, the `deletion_protection` blocker, and the need to rotate `DEV_DB_ADMIN_URL` all played out exactly as written.

**What this plan didn't predict, all found and fixed during execution rather than designed around in advance:**

1. **`DEV_DB_ADMIN_URL` was already stale before this work even started** — an unrelated pre-existing credential drift (AWS's managed master-password rotation had moved past what the GitHub secret held), caught by Workstream A's first CI run. Fixed the same way B3's rotation was later fixed: fetch the current value, verify a connection with it, then write the secret — never the other way around.
2. **B2's plan review caught real orphaned infrastructure** — a VPC-endpoints security group with no endpoints left to serve, predating this session. Investigated (`aws ec2 describe-vpc-endpoints` returned empty) before including its cleanup in the apply, exactly per the "if any of those appear, stop" instruction this document wrote for itself.
3. **`terraform apply -replace` doesn't modify the resource being replaced before destroying it** — so B1's `deletion_protection = false` change, though correctly written, never touched the *old* instance's live setting, and the first replace attempt failed outright. Fixed out-of-band, same command the project's own teardown docs already used.
4. **A real bug in the module surfaced on the first genuinely fresh parameter-group create**: `shared_preload_libraries` is a static PostgreSQL parameter, and the module never set `apply_method = "pending-reboot"` for it — it silently held a working value in the old group's state through means that are still unclear, but a `create_before_destroy` create hit the schema default (`"immediate"`) and RDS rejected it outright. Fixed in source, not worked around.
5. **`rds.force_ssl` doesn't exist as a GUC on this RDS PostgreSQL 18 build at all.** Every doc that named it as the SSL-enforcement mechanism was wrong the moment `dev` moved to 18.4 — caught by checking `pg_settings` directly rather than trusting the parameter group's static-metadata check from earlier in this same session, and confirmed the actual behavior (SSL enforcement) is unchanged by testing a rejected non-SSL connection directly.

The throughline: every one of these was caught by *verifying* rather than *assuming* — reading the actual `terraform plan` diff instead of trusting intent, testing a live connection instead of trusting a cached credential, querying `pg_settings` instead of trusting a parameter group's declared default. None of them would have surfaced from documentation review alone.

**Local/CI verification, all against the actual replacement instance:** migration round trip (`downgrade base` 31s, `upgrade head` 84s), `alembic check` (empty diff, 49s), full test suite (`unit`/`database`/`scenario`, ~32 minutes, includes seed idempotency) — all green. [PR #20](https://github.com/NemesisGhost/dnd_ai/pull/20)'s CI history shows the full arc: one red run (the pre-existing stale-secret finding, unrelated to this plan), two green runs on 15.18 (proving Workstream A's local-first tooling is genuinely target-agnostic), and a final green run on 18.4 (the authoritative evidence this plan was staked on).

Phase 9 may now proceed.
