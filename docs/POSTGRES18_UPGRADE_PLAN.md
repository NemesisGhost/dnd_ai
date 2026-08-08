# PostgreSQL 18 Upgrade and Local-Loop Enablement Plan

Two pieces of work left open by the 2026-08-07 verification pivot ([ADR 0011](adr/0011-local-first-development-aws-verified-delivery.md)):

- **Workstream A** — make the local-first loop real in code. The documentation describes it; `tests/conftest.py` and `scripts/verify.sh` still target AWS by default.
- **Workstream B** — upgrade the deployed `dev` RDS instance from PostgreSQL 15.18 to 18.4, closing the local/`dev` major-version drift recorded as gap 0 in [INFRASTRUCTURE.md §11](INFRASTRUCTURE.md#11-known-gaps-and-discrepancies) and the top item in [PLAN.md §29.8](PLAN.md#298-open-items).

**Gate: no further feature work is pushed to AWS until both workstreams are complete.** In practice that means Phase 9 ([PLAN.md](PLAN.md#phase-9-items-inventory-encounters-and-foundry-synchronization)) does not merge until this plan closes, because every push runs CI, and CI migrates the `dev` database. See [§5](#5-what-the-gate-permits) for what the gate does and does not block.

---

## Table of Contents

- [1. Why A comes before B](#1-why-a-comes-before-b)
- [2. Established facts](#2-established-facts)
- [3. Workstream A — local-first test tooling](#3-workstream-a--local-first-test-tooling)
- [4. Workstream B — RDS 15.18 → 18.4](#4-workstream-b--rds-1518--184)
- [5. What the gate permits](#5-what-the-gate-permits)
- [6. Risks and rollback](#6-risks-and-rollback)
- [7. Done criteria](#7-done-criteria)

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
| `shared_preload_libraries` defaults to `pg_stat_statements,pg_tle` on 18; the module sets it to `pg_stat_statements` only | same — see [B1](#b1-terraform-module-changes) note |
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
> The parameter-group fix in [B1](#b1-terraform-module-changes) is different and stays in scope: it is needed *today*, because the family has to become `postgres18` for this change to work at all.

### B1. Terraform module changes — done, not applied

**Implemented 2026-08-08** in `terraform/modules/database/rds.tf`, `variables.tf`, and `terraform/environments/dev/main.tf`. `terraform validate` passes (`terraform init -backend=false` + `validate`, no AWS calls, no state access). **Not yet run through `terraform plan`/`apply`** — B2 onward requires a live coordination window and is a separate step.

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

**2. `postgres_version`** default → `18.4`. Required.

**3. `deletion_protection` and `skip_final_snapshot` for `dev`.** The `dev` environment passes neither, inheriting module defaults of `true` and `false` — which is [INFRASTRUCTURE.md §11](INFRASTRUCTURE.md#11-known-gaps-and-discrepancies) gap 1, and the reason `dev` currently cannot be torn down at all. Instance replacement hits this immediately. Pass `deletion_protection = false` and `skip_final_snapshot = true` from `terraform/environments/dev/main.tf`, per the per-environment table in [PLAN.md §29.3](PLAN.md#293-environments-dev-staging-prod) which already specifies exactly these values for `dev`. This closes gap 1 as a side effect.

**Not built, per [B0](#b0-strategy-replace-the-instance-dont-upgrade-it):** `allow_major_version_upgrade` and `apply_immediately`. Both exist only to serve an in-place major upgrade, which nothing in this project needs until an environment holds data worth preserving across one. Recorded in [PLAN.md §29.8](PLAN.md#298-open-items) against that trigger.

Optionally also add `auto_minor_version_upgrade` (currently unset, so it defaults to `true`): with `engine_version` pinned to `18.4`, AWS may auto-bump to 18.5 in a maintenance window and produce Terraform drift. Setting it `false` makes the pin honest. Recommended, not a blocker.

> **Note on `shared_preload_libraries`.** The module sets it to `pg_stat_statements`, while the `postgres18` default is `pg_stat_statements,pg_tle`. The new instance will therefore not have `pg_tle`. Nothing in this project uses it, so this is acceptable — but it is a deliberate choice, not an accident.

### B2. Pre-flight

1. **Confirm no CI run is in flight.** Replacement mid-run fails that run and can leave an orphaned ephemeral database and an open security-group rule. This is the only pre-flight check with teeth — there is no data to back up, so no snapshot step ([B0](#b0-strategy-replace-the-instance-dont-upgrade-it)).
2. **Announce the window.** Expect roughly 10–20 minutes with no database. CI fails for anything pushed during it, and stays failing until step B3.4.
3. `terraform -chdir=terraform/environments/dev plan` and **read it carefully**. Confirm it shows exactly one `aws_db_instance` replacement plus the parameter-group create-before-destroy — and that it does **not** propose destroying the VPC, subnet group, security group, KMS key, or the `github_actions_ci` role. If any of those appear, stop: the change is wider than intended and `DEV_DB_SECURITY_GROUP_ID` is now in scope too.

### B3. Replace

```bash
terraform -chdir=terraform/environments/dev apply \
  -replace=module.database.aws_db_instance.main
```

1. Watch to completion rather than trusting the Terraform exit alone:
   ```bash
   aws rds describe-db-instances --db-instance-identifier dnd-ai-dev-db \
     --query "DBInstances[0].{Status:DBInstanceStatus,Ver:EngineVersion,PG:DBParameterGroups[0],Endpoint:Endpoint.Address}"
   ```
   Wait for `available`, `EngineVersion` = `18.4`, and the parameter group `in-sync` (it may report `pending-reboot` first, because `shared_preload_libraries` is static — reboot if so).
2. **Capture the new endpoint** from that output. It is usually stable for a reused identifier, but do not assume — read it.
3. **Fetch the new master password.** AWS generates a fresh one for the replacement instance:
   ```bash
   aws secretsmanager get-secret-value \
     --secret-id $(terraform -chdir=terraform/environments/dev output -raw database_secret_name) \
     --query SecretString --output text
   ```
4. **Rotate the `DEV_DB_ADMIN_URL` GitHub secret** to `postgresql+psycopg://dnd_admin:<url-encoded-password>@<endpoint>:5432/dnd_ai?sslmode=require`. URL-encode the password — AWS-generated ones routinely contain `$`, `>`, `~`, `/`. **CI stays red until this is done**, so treat it as part of the apply, not as follow-up.
5. Confirm `DEV_DB_SECURITY_GROUP_ID` is unchanged (`terraform output -raw database_security_group_id`). It should be — if it changed, B2 step 4 missed something.

### B4. Bootstrap the fresh instance

The replacement instance is **empty** — no schemas, roles, or extensions. This is the same state a newly deployed environment is in, and it is bootstrapped the same way. Connect through a session ingress rule ([DEVELOPMENT.md §3.5](DEVELOPMENT.md#35-connecting-to-aws-dev-occasional)) and:

1. `alembic upgrade head` — revision `001_bootstrap` creates the extensions, thirteen schemas, and six roles from scratch, at PostgreSQL 18 versions. Nothing needs `ALTER EXTENSION UPDATE` and nothing needs `ANALYZE`; that hygiene was `pg_upgrade`-specific and no longer applies.
2. **Verify the six roles** were created correctly on 18 — the one genuinely new thing here is that the bootstrap revision has never run against PostgreSQL 18 on RDS before:
   ```sql
   SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname LIKE 'migration_%' OR rolname LIKE 'app_%'
      OR rolname IN ('integration_worker','admin_maintenance');
   ```
   Confirm `migration_owner` is `NOLOGIN` and **not** a member of `rds_iam`, and that the five login roles are. This is the exact failure [ADR 0009](adr/0009-separate-owning-role-from-login-roles.md) exists for, and the conditional `GRANT rds_iam` is one of the few code paths that behaves differently on RDS than locally — so local success in A3 does **not** cover it.
3. **Confirm `rds.force_ssl` is `1`** on the new parameter group. The `postgres18` default is `1`, but the group is newly created — verify rather than assume. A plain non-SSL connection must still be rejected.
4. **Confirm object ownership** resolves to `migration_owner` ([PLAN.md §23.1](PLAN.md#231-phase-exit-review) recurring obligations).

### B5. Verification

- [ ] `alembic upgrade head` from an **empty** ephemeral database on the upgraded instance
- [ ] Full downgrade-to-base / upgrade-to-head round trip on that ephemeral database
- [ ] `alembic check` — empty diff
- [ ] Seed idempotency
- [ ] Full test suite
- [ ] **A real CI run, green, on a pushed commit** — this is the authoritative evidence, per [PLAN.md §23.0](PLAN.md#230-verification-policy)

`DEV_DB_SECURITY_GROUP_ID` remains valid because [B0](#b0-strategy-replace-the-instance-dont-upgrade-it) replaces only the instance, leaving the security group in place. `DEV_DB_ADMIN_URL` does not, and is rotated in B3 step 4 — CI cannot go green until it is.

### B6. Close the documentation loop

Per [CLAUDE.md §7](../CLAUDE.md#7-before-implementing-a-feature), same change:

- [INFRASTRUCTURE.md §11](INFRASTRUCTURE.md#11-known-gaps-and-discrepancies) — strike gap 0; update the `postgres_version` row in §4 and the version assertion in §7
- [PLAN.md §29.8](PLAN.md#298-open-items) — strike the upgrade item; [§29.1](PLAN.md#291-scope-and-current-state) — drop the "module default is still 15.18" caveat
- [DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version) — remove the drift warning; §2.3's "verified as trusted on the AWS `dev` instance, 15.18" becomes 18.4
- [CLAUDE.md](../CLAUDE.md) §2 and [README.md](../README.md) — remove the "not yet upgraded" caveats from both verification-pivot notes
- [CHECKLIST.md](CHECKLIST.md), [QUICKSTART.md](QUICKSTART.md) — drop the "stale default" warnings
- Write the outcome up. This is infrastructure work rather than a delivery phase, so it belongs in this document's own closeout section rather than a `PHASEn_VERIFICATION.md`.

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
- [ ] `dev` reports `EngineVersion` `18.4`, status `available`, parameter group `in-sync` (B3)
- [ ] `DEV_DB_ADMIN_URL` rotated to the replacement instance's endpoint and password; `DEV_DB_SECURITY_GROUP_ID` confirmed unchanged (B3)
- [ ] Bootstrap run on the fresh instance; six roles verified with `migration_owner` `NOLOGIN` and outside `rds_iam`; `rds.force_ssl` = `1` (B4)
- [ ] Migration round trip, `alembic check`, seed idempotency, and the full suite all green against the upgraded instance (B5)
- [ ] **A green CI run on a pushed commit against `dev` at 18.4** — the authoritative evidence ([PLAN.md §23.0](PLAN.md#230-verification-policy))
- [ ] Local and `dev` now agree on major version; gap 0 struck and every doc caveat removed (B6)
- [ ] The gate lifts: Phase 9 may proceed
