# ADR 0008: Everything deploys to and is verified in AWS

- **Status**: Accepted, partially superseded by [ADR 0011](0011-local-first-development-aws-verified-delivery.md)
- **Date**: 2026-07-31

> **Amended 2026-08-07.** [ADR 0011](0011-local-first-development-aws-verified-delivery.md) supersedes this ADR's **inner-loop** clause: development and iteration now run against a local PostgreSQL 18 server by default, not against `dev` RDS. Everything else here stands — CI still verifies migrations and the `tests/database`/`tests/scenario` suites against the deployed `dev` instance as a merge gate, application services still deploy only to ECS Fargate, and "it passes locally" is still not a sufficient claim to close a phase. Read the two together: this ADR explains *why AWS verification exists*; ADR 0011 changes *when in the cycle it happens*.

## Context

The project originally treated AWS as optional for most work. [CONTRIBUTING.md](../CONTRIBUTING.md) told contributors that everything through Phase 7 ran against a local Docker PostgreSQL container and that "you do not need AWS to contribute"; [DEVELOPMENT.md §3](../DEVELOPMENT.md#3-local-setup) said local development needed no AWS resources; the test layers ran on testcontainers; and CI used a `postgres:15` service container. AWS entered the picture only for the final Phase 1 exit criterion.

That split produced two problems:

1. **What was verified was not what was deployed.** A local container is a different PostgreSQL than the RDS instance, with different roles (`rds_iam` does not exist locally), different networking, different parameter groups, and different extension availability. Bugs that only appear on RDS — the ungated `GRANT rds_iam` in the bootstrap revision was exactly this — survive a fully green local test run.
2. **Deployment was perpetually deferred.** Only PostgreSQL had an AWS plan ([PLAN.md §29](../PLAN.md#29-aws-terraform-deployment-plan-for-postgresql)). The application services had none: [SYSTEM_ARCHITECTURE.md §17](../architecture/SYSTEM_ARCHITECTURE.md#17-deployment-topology) listed vendor-neutral deployables ("object storage", "reverse proxy"), and [PLAN.md §29.6](../PLAN.md#296-migration-execution-mechanism) explicitly recorded that the project "needs no container registry or CI/CD platform decision yet." Each phase could therefore be called done without anything running in the environment it targets.

## Decision

Every phase is deployed to and verified in AWS. Local execution is a fallback for when AWS is genuinely unreachable, not the default development loop.

> Superseded in part by [ADR 0011](0011-local-first-development-aws-verified-delivery.md): local PostgreSQL 18 is now the default development loop. The requirement that every phase be *verified* in AWS before it closes is unchanged; it moved from the developer's machine to CI.

Concretely:

- Migrations and the `tests/database` / `tests/scenario` suites run against the deployed `dev` RDS instance, not testcontainers ([PLAN.md §23.0](../PLAN.md#230-verification-policy)). `tests/unit` is unaffected — it uses no database. *(Per ADR 0011 this now describes CI, not the developer inner loop.)*
- `dev` is shared, always-on infrastructure. Reachability for CI and developers is a short-lived, IP-scoped security-group rule opened and revoked per session; isolation between concurrent runs is an ephemeral database per run ([PLAN.md §29.9](../PLAN.md#299-shared-dev-verification-mechanism-ci)). `staging` and `prod` stay non-public and are migrated through the SSM-based runner in [§29.6](../PLAN.md#296-migration-execution-mechanism).
- Application services (the FastAPI modular monolith, the background worker, and the Discord bot) run on **ECS Fargate**, with images in ECR, in the same VPC and private subnets as the database ([PLAN.md §30](../PLAN.md#30-aws-deployment-plan-for-application-services)). This also unifies the migration runner: the same image runs migrations as a one-off task, replacing the standing EC2 runner anticipated in §29.6.

ECS Fargate was chosen over EC2 + systemd and over App Runner. EC2 is cheaper and matches the SSM pattern already specified for the migration runner, but deploys become file-sync-and-restart rather than image swaps and the instances need patching. App Runner needs the least infrastructure code but gives the least control over networking and task scheduling, and offers no natural home for the background worker or for one-off jobs like migrations. Fargate keeps one artifact (a container image) and one execution model across the API, the worker, and migrations, at the cost of a container build step in CI and a per-service running cost.

## Consequences

**Easier**

- The thing under test is the thing that ships: real RDS, real IAM authentication, real networking, real parameter groups.
- One artifact and one execution model across API, worker, and migrations.
- Deployment stops being a deferred, end-of-project problem — each phase exercises it.
- The migration runner collapses into the same mechanism as everything else, rather than being a bespoke standing EC2 instance.

**Harder**

- ~~Contributing now requires AWS access. [CONTRIBUTING.md](../CONTRIBUTING.md) starts with account setup rather than `docker run`.~~ Reversed by [ADR 0011](0011-local-first-development-aws-verified-delivery.md): contributing requires a local PostgreSQL 18 server; AWS access is needed only to change infrastructure, deploy, or debug a CI-only failure.
- `dev` is an ongoing shared cost (~$25–35/month for the database alone, plus per-service Fargate cost) and must not be destroyed as routine idle-time hygiene — doing so breaks every other contributor's test run.
- The inner loop is slower than a local container, and depends on network reachability to AWS.
- CI needs AWS credentials (an OIDC-assumed IAM role), a container build step, and cleanup steps that must run even on failure so a crashed job does not leak an open security-group rule or an orphaned database.
- A compromised CI role or a botched cleanup has a blast radius in a real AWS account, which a local container did not.

**Foreclosed**

- "It passes locally" is no longer an acceptable verification claim for anything touching the database. *(Still true under [ADR 0011](0011-local-first-development-aws-verified-delivery.md) — local is now the expected first claim, but a phase closes on the CI run against `dev`, not on it.)*
- Lambda-per-function is not revisited for application services; the modular monolith on Fargate is the target, consistent with the removal of the pre-restart Lambda/API Gateway wiring.

## References

- [ADR 0011](0011-local-first-development-aws-verified-delivery.md) — the amendment that moves the inner loop local
- [PLAN.md §23.0](../PLAN.md#230-verification-policy) — the verification policy
- [PLAN.md §29.9](../PLAN.md#299-shared-dev-verification-mechanism-ci) — reachability and test isolation mechanism
- [PLAN.md §30](../PLAN.md#30-aws-deployment-plan-for-application-services) — application service deployment
- [SYSTEM_ARCHITECTURE.md §17](../architecture/SYSTEM_ARCHITECTURE.md#17-deployment-topology) — deployment topology
- [DEVELOPMENT.md §3](../DEVELOPMENT.md#3-local-setup), [§6](../DEVELOPMENT.md#6-testing), [§8](../DEVELOPMENT.md#8-continuous-integration)
- [CONTRIBUTING.md §2](../CONTRIBUTING.md#2-aws-access-optional)
