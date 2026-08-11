# ADR 0012: Self-hosted Docker deployment, containerized-PostgreSQL CI verification

- **Status**: Accepted
- **Date**: 2026-08-11
- **Supersedes**: [ADR 0011](0011-local-first-development-aws-verified-delivery.md) in full; the deployment-target and merge-gate clauses of [ADR 0008](0008-aws-first-deployment-and-verification.md) that ADR 0011 had left standing

## Context

ADR 0008 made the deployed AWS `dev` RDS instance the target every phase deploys to and the target CI verifies migrations and the `tests/database`/`tests/scenario` suites against, on the reasoning that "what was verified was not what was deployed" and that RDS-specific defects (the ungated `GRANT rds_iam` in the bootstrap revision is the canonical example) survive a fully green local run. ADR 0011 kept that CI merge gate but moved the developer's *inner loop* to a local PostgreSQL 18 server, because paying a network round trip to shared RDS on every iteration was expensive and the failure modes it introduced (expired credentials, a changed public IP, an orphaned ephemeral database, a transient RDS connection fault) were operational, not domain.

Both ADRs assumed the project's deployment target was, and would remain, AWS: `.github/workflows/ci.yml`'s `aws-verification` job assumed an OIDC-federated IAM role, opened and closed a security-group ingress rule on the shared `dev` instance, created and dropped a per-run ephemeral database on it, and depended on repository secrets (`AWS_CI_ROLE_ARN`, `DEV_DB_ADMIN_URL`) and variables (`AWS_REGION`, `DEV_DB_SECURITY_GROUP_ID`) to do it. That mechanism worked — it is documented in [PLAN.md §30.9](../PLAN.md#309-shared-dev-verification-mechanism-ci) and ran successfully, including GitHub Actions run `30765722355` — but it bought RDS-fidelity verification at a real, ongoing cost: every CI run needed a live AWS account, a scoped IAM trust relationship, and cleanup steps robust enough to run on failure so a crashed job wouldn't leak an open ingress rule or an orphaned database. `src/dnd_ai/api` still has no committed source as of this ADR — nothing has ever actually been deployed to the ECS Fargate target ADR 0008 named — so the AWS deployment obligation had been entirely a database-verification cost, not a running-service cost, for every phase to date.

The project's intended deployment model is changing to self/local hosting with Docker: an operator runs `docker compose up`, not `terraform apply`. That makes the AWS CI mechanism verification of a target the project no longer deploys to by default, rather than verification of the thing that ships.

## Decision

**Self-hosted Docker Compose is the officially supported deployment topology.** `compose.yaml` at the repository root defines PostgreSQL 18 with persistent named-volume storage, health checks, and environment-variable-driven configuration — see [DEVELOPMENT.md §3](../DEVELOPMENT.md#3-local-setup) for start/stop/backup/upgrade operations. The application `Dockerfile` builds the one shared image the API, worker, adapter, and one-off jobs (migrations today; the rest once `src/dnd_ai/api` exists) all run from, per the "one image, many entrypoints" plan in [DEVELOPMENT.md §2](../DEVELOPMENT.md#2-repository-layout) and [PLAN.md §31.3](../PLAN.md#313-packaging-and-release). There is no committed application service to containerize yet beyond the database and the `migrate` job — `compose.yaml` says so directly rather than pretending otherwise.

**Containerized PostgreSQL 18 is the CI merge gate**, replacing AWS `dev` RDS. `.github/workflows/ci.yml`'s `postgres-verification` job runs the identical sequence the AWS job did — empty-to-head migration, `alembic current`, a full `downgrade base`/`upgrade head` round trip, seed idempotency, `alembic check`, and the complete `tests/unit`/`tests/database`/`tests/scenario` suite — against a disposable `postgres:18.4` GitHub Actions service container instead of an ephemeral database on shared RDS. A separate `docker-build` job validates `compose.yaml`, builds the application image, brings up the composed database, and runs the `migrate` service against it as an end-to-end smoke test of the self-hosted topology itself. Neither job authenticates to AWS, opens a security-group rule, or needs a repository secret.

**Why full-suite RDS verification was removed, not kept as a second gate:** running both would mean maintaining two merge-blocking database targets indefinitely for a deployment path (AWS RDS/ECS Fargate) the project is no longer building toward, doubling CI runtime and operational surface (IAM role, ingress automation, ephemeral-database cleanup) for a target with no current deployable. That is disproportionate to what it verifies once self-hosted Docker is the actual shipped topology. The OIDC role's only consumer, `terraform/modules/github_actions_ci`, is removed from configuration for the same reason — nothing else used it.

**Concretely:**

- `.github/workflows/ci.yml` has no AWS OIDC permission, no credential configuration, no security-group automation, no RDS secret, and no AWS cleanup step. Its lint/type-check job is unchanged; `postgres-verification` and `docker-build` are new.
- `scripts/ci_ephemeral_database.py` and `scripts/ci_cleanup.py` — built solely for the AWS job's shared-ephemeral-database and ingress-revocation mechanism — are removed, along with `tests/unit/test_ci_cleanup.py`, which existed solely to validate `ci_cleanup.py`'s combining logic.
- `terraform/modules/github_actions_ci` and its wiring in `terraform/environments/dev/main.tf` are removed from configuration. This does not touch live infrastructure (per this project's standing rule that AI assistants never run Terraform or destroy cloud resources) — a previously applied `dev` may still have the underlying IAM role and OIDC provider deployed; removing them is a deliberate, human-run `terraform apply`/`destroy`, not a side effect of this change.
- `terraform/modules/database` and `terraform/modules/secrets`, and the `dev` environment that wires them, are **retained**, undeleted and unrun — they remain a documented, optional path for anyone who chooses to host PostgreSQL on AWS RDS instead of self-hosted Docker. They are no longer required for development or CI, and [INFRASTRUCTURE.md](../INFRASTRUCTURE.md), [QUICKSTART.md](../QUICKSTART.md), and [CHECKLIST.md](../CHECKLIST.md) are marked accordingly.
- `scripts/aws-db-allow-my-ip.sh` is retained for the same reason: it remains useful for anyone who does point `DATABASE_URL` at AWS dev directly, but is no longer part of any required workflow.
- ADR 0011 is superseded in full — the two-tier local-inner-loop/AWS-verified-delivery model it described no longer exists as two tiers; there is one PostgreSQL 18 target, self-hosted, used both for development and CI. ADR 0008's deployment-target claim (ECS Fargate) and merge-gate claim (AWS `dev` RDS) — the parts ADR 0011 had left standing — are also superseded; ADR 0008's inner-loop clause was already superseded by ADR 0011 and remains so.

**The tradeoff, accepted deliberately:** RDS-specific behavior — IAM database authentication, `rds_superuser` boundaries, `rds.force_ssl`/`pg_hba.conf` SSL enforcement, parameter-group settings, and other managed-role behavior documented in [DATABASE_CONVENTIONS.md §27](../DATABASE_CONVENTIONS.md) — is **no longer continuously verified by CI**. The `GRANT rds_iam` defect ADR 0008 was written to catch is exactly the class of bug this change stops routinely catching. Anyone who deploys to AWS RDS going forward is responsible for verifying that path themselves before relying on it; this project's CI will not do it for them. This is accepted because the project is no longer building toward that target by default, and continuing to gate every merge on a deployment path with no current deployable was a cost with no corresponding benefit.

## Consequences

**Easier**

- CI runs with no AWS account, no OIDC trust relationship, no repository secrets, and no cloud blast radius from a compromised CI role or a botched cleanup step.
- CI is faster and more reliable: a same-runner service container has no network round trip to a shared, possibly contended `db.t3.micro`, and nothing to leak (no ingress rule, no orphaned remote database) if a job is cancelled or crashes.
- The thing CI verifies (containerized PostgreSQL 18, brought up via `compose.yaml`) is now the same thing a self-hosting operator runs, closing the "what was verified was not what was deployed" gap ADR 0008 identified — just for a different target than ADR 0008 chose.
- Contributing needs nothing beyond Docker (or a local PostgreSQL 18 install) and `uv` — no AWS account at all, optional or otherwise, for schema or application work.

**Harder**

- RDS-specific defects have no CI safety net anymore. A team that does deploy to AWS RDS needs its own verification step; this project does not provide one.
- Two previously-load-bearing pieces of automation (`scripts/ci_ephemeral_database.py`, `scripts/ci_cleanup.py`) and their test are gone; reintroducing AWS verification later means rebuilding them or an equivalent, not restoring a `git revert`-able state indefinitely.
- The retained `terraform/modules/database`/`secrets` and `dev` environment are now unexercised by anything automated. They can drift from what actually works without anyone noticing until someone tries to apply them.

**Foreclosed**

- "CI verified this against RDS" is no longer a claim any merged commit can make. A green run means containerized PostgreSQL 18 and (for the `docker-build` job) the self-hosted compose topology, nothing about AWS specifically.
- Treating AWS `dev`/ECS Fargate as the default place application services will run. [SYSTEM_ARCHITECTURE.md §17](../architecture/SYSTEM_ARCHITECTURE.md#17-deployment-topology) no longer states that as fact; self-hosted Docker Compose is the default, and an AWS deployment path remains only as documented, optional, unbuilt planning material in [PLAN.md §30](../PLAN.md#30-aws-terraform-deployment-plan-for-postgresql)–[§31](../PLAN.md#31-aws-deployment-plan-for-application-services).
- Historical verification records (`docs/PHASE1_VERIFICATION.md` through `docs/PHASE9_VERIFICATION.md`) are not rewritten by this ADR. They accurately record that Phases 1–9 were verified against AWS `dev` RDS at the time; that history stands as evidence of what happened, not as current policy.

## References

- [ADR 0008](0008-aws-first-deployment-and-verification.md) — the decision this ADR supersedes the standing portions of
- [ADR 0011](0011-local-first-development-aws-verified-delivery.md) — the decision this ADR supersedes in full
- [PLAN.md §24.0](../PLAN.md#240-verification-policy) — the verification policy this ADR sets
- [DEVELOPMENT.md §3](../DEVELOPMENT.md#3-local-setup), [§8](../DEVELOPMENT.md#8-continuous-integration) — self-hosted setup and the current CI mechanism
- [DATABASE_CONVENTIONS.md §2.1](../DATABASE_CONVENTIONS.md#21-supported-postgresql-version) — the PostgreSQL version pin, unchanged by this ADR
- `compose.yaml`, `compose.ci.yaml`, `Dockerfile` — the self-hosted deployment and CI topology itself
- `.github/workflows/ci.yml` — the CI implementation
