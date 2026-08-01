# ADR 0009: Separate the object-owning role from the roles that log in

- **Status**: Accepted
- **Date**: 2026-08-01

## Context

[DATABASE_CONVENTIONS.md §27.1](../DATABASE_CONVENTIONS.md#271-database-roles) originally specified five database roles, all of them login roles, with `migration_owner` doing double duty: it both owned every schema object *and* was the identity the migration runner authenticated as ([PLAN.md §29.6](../PLAN.md#296-migration-execution-mechanism)).

Deploying `dev` to a real AWS account for the first time showed that combination is not viable. Two PostgreSQL/RDS behaviors collide:

1. **Ownership transfer requires membership.** `ALTER SCHEMA … OWNER TO migration_owner` and `ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner` are rejected unless the connecting user is a member of `migration_owner`. The RDS master user is `rds_superuser`, not a true superuser, so it gets no implicit membership in roles it creates. The bootstrap revision failed with `must be member of role "migration_owner"`.
2. **`rds_iam` is inherited, and it disables password authentication.** On RDS, granting `rds_iam` to a role forces IAM authentication for that role and permanently disables password auth for it. Role membership is transitive.

Granting the membership that (1) demands therefore triggered (2): the master user became a transitive member of `rds_iam` through `migration_owner`, and every subsequent connection — including ones that had worked minutes earlier — failed with:

```
FATAL:  PAM authentication failed for user "dnd_admin"
```

The migration itself reported success, so the failure surfaced only afterward, as a database that had apparently locked out its own master user. Diagnosis was slowed by the error naming PAM (the mechanism behind RDS IAM auth) rather than passwords; a secret rotation and an instance reboot were both tried and neither helped, because the credential was never the problem. The instance was ultimately torn down.

A third, quieter problem sat underneath: PostgreSQL assigns object ownership from the **current role**, not from inherited membership. Even without the lockout, a session that merely inherited `migration_owner` would have created objects owned by itself, leaving every `ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner` entry inert and the application roles silently unable to read new tables.

## Decision

Split the owning role from the login roles. Six roles, one of which never authenticates:

| Role | Logs in | `rds_iam` | Purpose |
|---|---|---|---|
| `migration_owner` | No (`NOLOGIN`) | **Never** | Owns every schema object; ownership and default-privilege anchor only |
| `migration_runner` | Yes | Yes | Executes migrations as a member of `migration_owner` |
| `app_read_write` | Yes | Yes | Application runtime; DML only |
| `app_read_only` | Yes | Yes | Reporting and read models |
| `integration_worker` | Yes | Yes | Foundry/Discord/import-facing services |
| `admin_maintenance` | Yes | Yes | Break-glass, human use only |

Three rules make this work and must survive future edits:

- **`migration_owner` is `NOLOGIN` and never granted `rds_iam`.** With no authentication behavior attached, membership in it is safe to grant to anyone — including the RDS master user, which still needs it for ownership transfer. This is what defuses the collision.
- **Migrations `SET ROLE migration_owner` after connecting.** Ownership follows the current role, so becoming the role is the only way to get objects owned by it and to make the default-privilege entries fire. `env.py` does this on connect; `001_bootstrap` does it at the end of its own upgrade, covering the run that creates the role in the first place.
- **IAM policies scope `rds-db:connect` to a named login role**, never to `dbuser:…/*`, and never to `migration_owner`. The `rds_iam_connect_arns` Terraform output exposes one ARN per login role for exactly this; its `iam_auth_db_users` variable has a validation rule rejecting `migration_owner`.

## Consequences

**Easier**

- The master user keeps password authentication, so the documented `dev` workflow (fetch the managed master secret, connect, run `alembic upgrade head`) keeps working.
- Object ownership is deterministic and identical whether migrations run as the master user in `dev` or as `migration_runner` when deployed.
- Rotating, revoking, or compromising the migration runner identity never orphans object ownership — `migration_runner` owns nothing. This also brings the migration path in line with [§27.2](../DATABASE_CONVENTIONS.md#272-least-privilege), which already said roles that run things shouldn't own them.
- IAM policies get meaningfully narrower: one dbuser ARN per role instead of a wildcard.

**Harder**

- One more role to create, document, and grant, and a `SET ROLE` step that is easy to omit when writing tooling that connects outside Alembic. Anything that creates schema objects outside a migration must issue it too, or ownership silently drifts.
- `downgrade()` is more involved: it must `RESET ROLE`, hand `core` back, and clear `migration_owner`'s remaining grants with `REASSIGN OWNED` / `DROP OWNED` before the role can be dropped.
- The `iam_auth_db_users` Terraform variable duplicates the login-role list held in the bootstrap revision. They must be changed together; the validation rule catches only the one mistake that caused the outage, not general drift.

**Foreclosed**

- `migration_owner` can never be used to connect, so it cannot be the subject of an `rds-db:connect` grant, hold `CREATEDB` for the ephemeral test databases in [§29.9](../PLAN.md#299-aws-first-verification-mechanism), or serve as a break-glass login. Those all need login roles.

## Verification status

The role SQL was verified offline (`alembic upgrade head --sql`) and the Terraform validated, but **this has not been run against a live RDS instance** — the instance that produced the incident was destroyed before the fix existed. The specific behaviors this ADR depends on (`NOLOGIN` roles being exempt from the `rds_iam` interaction, `SET ROLE` producing the intended ownership, and the reworked `downgrade()` completing) still need confirming on real RDS the next time `dev` is stood up. Treat the design as reasoned rather than proven until then.

## References

- [DATABASE_CONVENTIONS.md §27.1](../DATABASE_CONVENTIONS.md#271-database-roles), [§27.2](../DATABASE_CONVENTIONS.md#272-least-privilege) — the role model
- [PLAN.md §29.5](../PLAN.md#295-database-role-schema-and-extension-bootstrap) — bootstrap requirements
- [PLAN.md §29.6](../PLAN.md#296-migration-execution-mechanism) — which role the migration runner connects as
- [PLAN.md §30.5](../PLAN.md#305-identity-and-secrets) — task roles and IAM database authentication
- [ADR 0008](0008-aws-first-deployment-and-verification.md) — the AWS-first policy that surfaced this
- `database/migrations/versions/001_bootstrap.py`, `database/migrations/env.py`
