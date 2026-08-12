# ADR 0011: Local-first development, AWS-verified delivery (historical verification policy)

- **Status**: Superseded by [ADR 0012](0012-self-hosted-docker-deployment-and-ci-verification.md)
- **Date**: 2026-08-07
- **Amends**: [ADR 0008](0008-aws-first-deployment-and-verification.md) — supersedes its inner-loop clause; leaves its deployment-target and merge-gate clauses intact

> **Superseded 2026-08-11.** [ADR 0012](0012-self-hosted-docker-deployment-and-ci-verification.md) replaces this ADR's two-tier model entirely: self-hosted Docker Compose is now the deployment topology, and containerized PostgreSQL 18 is the CI merge gate, not AWS `dev` RDS. This document is kept as the historical record of the local-inner-loop decision and its reasoning; it no longer describes current policy. Read ADR 0012 for what's current.

## Context

[ADR 0008](0008-aws-first-deployment-and-verification.md) made the deployed AWS `dev` RDS instance the default target for *all* database work: migrations, `tests/database`, and `tests/scenario` ran there, and a local container was a fallback for genuinely unreachable AWS. That decision fixed two real problems — what was verified was not what was deployed, and deployment was perpetually deferred — and both fixes are worth keeping.

What it also produced, over Phases 1–8, was an expensive inner loop:

1. **Every database test run is a network round trip.** A `tests/database` run opens a security-group rule scoped to the developer's current public IP, creates an ephemeral database on shared RDS, migrates it through 70-plus revisions, runs the suite, drops the database, and revokes the rule. The migration alone dominates, and it is paid again on every session. The `db.t3.micro` instance is the slowest part of the loop and is shared with CI.
2. **A schema-heavy project pays the cost hardest.** Phases 1–8 were almost entirely DDL, constraints, triggers, and guard functions. That work is iterative by nature — write a trigger, run the negative test, discover the guard misses a reverse-mutation path, repeat. Phase 7's revision 075 and Phase 8's correction pass were both exactly this shape. A loop measured in minutes rather than seconds changes how many iterations get run before something is called done.
3. **The failure modes are operational, not domain.** Expired credentials, a changed public IP, a leaked security-group rule, an orphaned `dnd_ai_test_*` database, an RDS connection fault (one of which forced a CI re-run during Phase 6). None of these are defects in the thing being built.
4. **A local PostgreSQL is now installed and is the same major version the project will deploy.** RDS offers PostgreSQL 18.1 through 18.4; the local server is 18.4. The original "a local container is a different PostgreSQL" objection weakens considerably when the local server and the deployment target are the same major version, and it was never a claim that local and RDS are identical — only that some defects are RDS-specific.

The RDS-specific defects ADR 0008 was written to catch (the ungated `GRANT rds_iam` in the bootstrap revision is the canonical one) are real. But catching them does not require every developer iteration to run on RDS. It requires that *nothing merges* without having run on RDS.

## Decision

Split the two concerns ADR 0008 fused together:

- **Development and iteration happen against a local PostgreSQL 18 server.** This is the default inner loop, not a fallback. `alembic upgrade head`, `tests/database`, and `tests/scenario` run locally, with no AWS credentials, no security-group rule, and no network dependency.
- **Delivery is still verified on AWS.** CI (`.github/workflows/ci.yml`) continues to run migrations and the full `tests/database`/`tests/scenario` suites against the deployed `dev` RDS instance, using the ephemeral-database and scoped-ingress mechanism in [PLAN.md §29.9](../PLAN.md#299-shared-dev-verification-mechanism-ci). A green run on RDS remains a merge requirement and remains the authoritative verification of a commit.

Concretely:

- The local server is **PostgreSQL 18.x**, matching the RDS engine version the project pins ([DATABASE_CONVENTIONS.md §2.1](../DATABASE_CONVENTIONS.md#21-supported-postgresql-version)). A local major version that differs from the deployment target is a defect, not a preference — it reintroduces exactly the class of divergence ADR 0008 identified.
- A developer needs **no AWS account** to contribute application or schema code. AWS access is needed to change infrastructure, to deploy, or to investigate a CI failure that does not reproduce locally.
- Application services still run only on **ECS Fargate in AWS** ([PLAN.md §30](../PLAN.md#30-aws-deployment-plan-for-application-services)). There is no local deployment topology and none is being added; this ADR changes where the *database* under test lives, not where services run.
- `staging` and `prod` are unaffected. They remain non-public and migrated through the mechanism in [§29.6](../PLAN.md#296-migration-execution-mechanism).

**"It passes locally" is still not a sufficient verification claim.** It is now the expected *first* claim, and the phase exit review ([PLAN.md §23.1](../PLAN.md#231-phase-exit-review)) records both: what passed locally and the CI run ID that proved it on RDS. A phase closes on the second, not the first.

## Consequences

**Easier**

- The inner loop is seconds instead of minutes, with no credentials, no ingress rule, and no network. Iteration count on constraint and trigger work goes up, which is where this project's defects have actually clustered.
- Contributing no longer requires an AWS account, reversing the hardest consequence ADR 0008 accepted.
- No leaked security-group rules or orphaned ephemeral databases from an interrupted local session — there is nothing external to leak.
- `dev` RDS carries CI load only, so a developer's test run can no longer contend with a CI run on a shared `db.t3.micro`.
- Local `alembic downgrade base` round trips stop being a destructive operation against shared infrastructure.

**Harder**

- **RDS-specific defects move later in the cycle.** A defect that only manifests on RDS — IAM authentication, `rds_superuser` boundaries, `rds.force_ssl`, parameter-group settings, managed-role behavior — is now found by CI on a pushed commit rather than by the developer before pushing. This is the real cost of this decision and it is accepted deliberately: the fix is to keep CI as a hard gate, not to move the inner loop back.
- Two environments must be kept in agreement. A local server on a different major version, missing an extension, or with different roles produces green local runs that fail CI. The setup in [DEVELOPMENT.md §3](../DEVELOPMENT.md#3-local-setup) exists to make the two match, and the version pin is enforced by the conventions rather than by convention.
- Anything genuinely AWS-shaped — IAM database authentication, Secrets Manager resolution, ECS task wiring — has no local equivalent and must still be exercised in `dev`.
- The local server is unmanaged: no automated backups, no monitoring, and its lifecycle is each developer's own problem. It holds nothing that isn't reproducible from migrations plus seeds, and it must never hold anything else.

**Foreclosed**

- Local PostgreSQL as a *deployment* topology. Services deploy to ECS Fargate; the database of record is RDS. This ADR does not reopen [SYSTEM_ARCHITECTURE.md §17](../architecture/SYSTEM_ARCHITECTURE.md#17-deployment-topology).
- Merging on local evidence alone. The AWS CI job is not optional, is not advisory, and is not skippable for schema changes.
- Reverting to a PostgreSQL major version that RDS does not offer, in order to use whatever is conveniently installed.

## References

- [ADR 0008](0008-aws-first-deployment-and-verification.md) — the decision this amends
- [PLAN.md §23.0](../PLAN.md#230-verification-policy) — the verification policy this ADR sets
- [PLAN.md §29.9](../PLAN.md#299-shared-dev-verification-mechanism-ci) — the CI mechanism that remains AWS-based
- [PLAN.md §30](../PLAN.md#30-aws-deployment-plan-for-application-services) — application deployment, unchanged
- [DEVELOPMENT.md §3](../DEVELOPMENT.md#3-local-setup) — local PostgreSQL setup
- [DATABASE_CONVENTIONS.md §2.1](../DATABASE_CONVENTIONS.md#21-supported-postgresql-version) — the version pin
