# Contributing

Onboarding for new contributors: getting a working environment, then the workflow for changing things.

**Start with §1.** Per [PLAN.md §24.0](PLAN.md#240-verification-policy) and [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md), development runs against a **local or self-hosted (Docker Compose) PostgreSQL 18 server**, and self-hosted Docker Compose (`compose.yaml`) is the officially supported deployment topology. You do **not** need an AWS account to contribute schema or application code, or to deploy — CI verifies every push against a disposable containerized PostgreSQL 18 instance on your behalf. AWS access (§2) is now entirely optional, needed only if you choose to change or use the legacy Terraform under `terraform/`.

---

## Table of Contents

- [1. Local setup (start here)](#1-local-setup-start-here)
- [2. AWS access (optional)](#2-aws-access-optional)
- [3. External API keys](#3-external-api-keys)
- [4. Changing application code](#4-changing-application-code)
- [5. Changing infrastructure](#5-changing-infrastructure)
- [6. Cost management](#6-cost-management)
- [7. Git workflow](#7-git-workflow)
- [8. Getting help](#8-getting-help)

---

## 1. Local setup (start here)

Phases 1 through 8 are complete and CI-verified; Phase 9 is next. See [PLAN.md §23](PLAN.md#23-delivery-phases) for what each delivered and `docs/PHASEn_VERIFICATION.md` for the evidence.

Development runs against a **local or self-hosted PostgreSQL 18 server** ([PLAN.md §24.0](PLAN.md#240-verification-policy), [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)). Nothing in this section needs an AWS account. The fastest path is `docker compose up -d db` (see [DEVELOPMENT.md §3.6](DEVELOPMENT.md#36-self-hosted-docker-compose)) — a native PostgreSQL install works too.

### 1.1 Required tools

| Tool | Version | Notes |
|---|---|---|
| Git | any | |
| **Docker** (recommended) or **PostgreSQL 18.x** natively | | `compose.yaml` provides PostgreSQL 18.4 with no local install; native install options per platform: [DEVELOPMENT.md §3.1](DEVELOPMENT.md#31-postgresql) |
| Python | 3.12+ | Pinned in [DEVELOPMENT.md §1](DEVELOPMENT.md#1-toolchain) |
| uv | latest | Dependency management — [install](https://docs.astral.sh/uv/getting-started/installation/) |

Recommended: VS Code or your preferred IDE. Node.js 18+ only if you start on the React UI, which has not begun.

**Use PostgreSQL 18, not whatever version is convenient.** A server on a different major version produces green local runs that fail CI ([PLAN.md §24.0](PLAN.md#240-verification-policy)).

### 1.2 Setup

The full walkthrough is [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup). The short version, with Docker:

```bash
docker compose up -d db           # PostgreSQL 18.4, no local install needed

uv sync
cp .env.example .env              # defaults already point at the compose database

uv run alembic -c database/alembic.ini upgrade head
uv run pytest
```

Without Docker, install PostgreSQL 18 natively instead of the first step: `psql --version` must report 18.x, then `createdb -U postgres dnd_ai`.

The project's six database roles are created by the `001_bootstrap` migration, not by hand — that is what keeps your server in agreement with CI's containerized PostgreSQL.

### 1.3 Then read

Follow [CLAUDE.md §4](../CLAUDE.md#4-documentation-map-and-context-loading-policy): read [PLAN.md §24.0–24.1](PLAN.md#24-delivery-phases) plus the current phase entry, search [DOMAIN_MODEL.md](DOMAIN_MODEL.md) for the affected vocabulary, read only the [DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md) sections governing the mechanisms you will change, and consult [architecture/SYSTEM_ARCHITECTURE.md §5](architecture/SYSTEM_ARCHITECTURE.md#5-layering) when application-layer placement is in scope. Do not preload the complete documentation set.

Skip to §4 unless you need AWS access or are changing infrastructure.

---

## 2. AWS access (optional)

**You do not need this to contribute code, or to deploy.** CI needs no AWS credentials at all ([ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)), and self-hosted Docker Compose is the officially supported deployment topology. AWS RDS, under `terraform/`, is retained only as an optional alternative for anyone who prefers to host PostgreSQL on AWS instead.

You need AWS access only to:

- change or apply the legacy Terraform under `terraform/` (§5),
- deploy or operate an AWS `dev` environment you have chosen to stand up,
- reproduce a failure specific to that environment, by running the suite directly against it ([DEVELOPMENT.md §3.5](DEVELOPMENT.md#35-connecting-to-aws-dev-optional-no-longer-required)).

### 2.1 Install and configure

| Tool | Install |
|---|---|
| AWS CLI v2 | [aws.amazon.com/cli](https://aws.amazon.com/cli/) or `winget install Amazon.AWSCLI` |
| Terraform >= 1.5 | [developer.hashicorp.com/terraform/install](https://developer.hashicorp.com/terraform/install) or `winget install HashiCorp.Terraform` |
| `curl` | any | Used to look up your current IP when opening dev access |

```powershell
aws configure --profile dnd-ai-dev
# Access Key ID, Secret Access Key, region (us-east-1), output format (json)

$env:AWS_PROFILE = "dnd-ai-dev"
aws sts get-caller-identity     # must succeed before anything else
```

`build.ps1` accepts the profile directly: `./build.ps1 -Environment dev -Action plan -AwsProfile dnd-ai-dev`.

To reach the `dev` database, open a session-scoped ingress rule and close it when you're done — it isn't automatic outside CI:

```bash
scripts/aws-db-allow-my-ip.sh open
# ... work against the dev endpoint (DATABASE_URL needs sslmode=require) ...
scripts/aws-db-allow-my-ip.sh close
```

### 2.2 Creating a deployment identity

If your organization uses IAM Identity Center, use `aws configure sso` and skip this.

Otherwise create a dedicated user with a **scoped** policy. Do not attach `IAMFullAccess` — it is a path to account administrator, and it contradicts the least-privilege stance in [DATABASE_CONVENTIONS.md §27.2](DATABASE_CONVENTIONS.md#272-least-privilege).

```powershell
aws iam create-user --user-name dnd-ai-developer
aws iam create-access-key --user-name dnd-ai-developer   # record both values
```

Attach a customer-managed policy built from the per-service action list in [INFRASTRUCTURE.md §2.2](INFRASTRUCTURE.md#22-required-iam-permissions) — RDS, EC2/VPC, KMS, Secrets Manager, CloudWatch Logs, plus a narrow IAM grant.

The IAM portion needs only enough to manage the RDS enhanced-monitoring service role:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:PassRole",
      "iam:TagRole"
    ],
    "Resource": "arn:aws:iam::*:role/dnd-ai-*"
  }]
}
```

`PowerUserAccess` plus that policy is a reasonable shortcut. On a personal account where you are already the only user, `AdministratorAccess` is defensible — just don't do it on a shared account and call it least privilege.

### 2.3 Deploying `dev` (optional)

`dev` is no longer required for anything — CI does not depend on it, and nothing breaks for other contributors if it doesn't exist. Deploy it only if you personally want an AWS-hosted database to work against. If it's already up (try `terraform -chdir=terraform/environments/dev output` first), there is nothing to do here.

Otherwise follow [QUICKSTART.md](QUICKSTART.md), with [CHECKLIST.md](CHECKLIST.md) as the pre-flight. Reference material is [INFRASTRUCTURE.md](INFRASTRUCTURE.md). Set `enable_public_access = true` if you want the reachability mechanism in [PLAN.md §30.9](PLAN.md#309-shared-dev-verification-mechanism-ci) — and do **not** narrow `my_ip_cidr` to a single IP the way an old single-developer setup would; per-caller access is granted out-of-band per §2.1, not baked into the Terraform variable.

---

## 3. External API keys

Needed only for the OpenAI and Discord integrations, neither of which is implemented yet.

- **OpenAI**: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- **Discord bot**: [discord.com/developers/applications](https://discord.com/developers/applications) — create an application, add a bot, copy the token, application ID, and public key

Put them in `terraform/environments/dev/secrets.local.json` (copied from the `.example`). The file is gitignored, and values reach AWS through `upsert-secrets.ps1` rather than Terraform state — see [INFRASTRUCTURE.md §6](INFRASTRUCTURE.md#6-secrets).

Never put a real key in `.env`, a `.tf` file, a seed file, or a commit.

---

## 4. Changing application code

```bash
uv run ruff format .
uv run ruff check . --fix
uv run mypy src
uv run pytest
```

All four must pass locally before opening a pull request, and CI must then go green against containerized PostgreSQL 18 — that run is the merge gate, not your local result ([PLAN.md §24.0](PLAN.md#240-verification-policy)). If a green local run turns into a red CI run, treat it as a real defect or local/CI drift and investigate; do not re-run until it passes.

The full workflow — Alembic revision requirements, the three test layers, CI expectations — is [DEVELOPMENT.md §4–§8](DEVELOPMENT.md#4-database-and-migrations), and the definition of done is [§10](DEVELOPMENT.md#10-definition-of-done).

Before writing anything, confirm it belongs to the current phase entry in [PLAN.md](PLAN.md), and check the eleven non-negotiable rules in [CLAUDE.md §5](../CLAUDE.md#5-non-negotiable-architectural-rules). If a task appears to require breaking one, stop and raise it rather than deviating quietly.

---

## 5. Changing infrastructure

```powershell
terraform -chdir=terraform/environments/dev fmt -recursive
terraform -chdir=terraform/environments/dev validate
./build.ps1 -Environment dev -Action plan
```

What to check in the plan, and the module/variable conventions to follow, are in [INFRASTRUCTURE.md §4](INFRASTRUCTURE.md#4-configuration-reference) under "Making infrastructure changes."

A security scan is worth running on larger changes. Use [Trivy](https://trivy.dev/) (`trivy config terraform/`) — `tfsec` is deprecated and folded into it.

Known defects in the current Terraform are catalogued in [INFRASTRUCTURE.md §11](INFRASTRUCTURE.md#11-known-gaps-and-discrepancies). Fixing one of those is a good first contribution.

---

## 6. Cost management

This section only applies if you have chosen to deploy the optional AWS `dev` path. `dev` runs ~$25–35/month ([INFRASTRUCTURE.md §9](INFRASTRUCTURE.md#9-cost)). Since [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md), it is no longer shared, CI-critical infrastructure — nothing else depends on it, so destroying it affects only you.

Set a billing alarm in AWS Budgets so a runaway cost (an oversized instance class, an accidentally-left-open ingress rule, storage growth from real usage) gets noticed quickly rather than discovered a month later. If cost genuinely needs to come down, that's an infrastructure change (right-sizing `instance_class`, revisiting VPC endpoints) proposed and applied deliberately per §5 — not an ad hoc destroy/recreate cycle.

Tear `dev` down whenever you're done with it:

```powershell
aws rds modify-db-instance --db-instance-identifier dnd-ai-dev-db --no-deletion-protection --apply-immediately
./build.ps1 -Environment dev -Action destroy -AutoApprove
```

---

## 7. Git workflow

- Work on a feature branch; don't commit directly to `main`
- Commit messages explain what and why
- Review `git status` and `git diff` before every commit

**Never commit**: `terraform.tfvars`, `secrets.local.json`, `.env`, `*.tfstate`, `tfplan`, `.terraform/`

**Do commit**: `*.example` files, Terraform module code, `uv.lock`, documentation, scripts

Documentation is part of the change, not a follow-up. If a change introduces a new cross-cutting concept, update the relevant file under `docs/` in the same commit — these documents are meant to stay current rather than be reconciled later. All documentation belongs under `docs/`; only `README.md` and `CLAUDE.md` live at the repository root.

---

## 8. Getting help

| Question | Where |
|---|---|
| What does this term mean? | [DOMAIN_MODEL.md](DOMAIN_MODEL.md) |
| What should I be working on? | [PLAN.md §23](PLAN.md#23-delivery-phases) |
| How should this table look? | [DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md) + [architecture/DATABASE_MODEL.md](architecture/DATABASE_MODEL.md) |
| Where does this code go? | [architecture/SYSTEM_ARCHITECTURE.md §5](architecture/SYSTEM_ARCHITECTURE.md#5-layering) |
| Which library or tool? | [DEVELOPMENT.md §1](DEVELOPMENT.md#1-toolchain) |
| Local database won't connect? | [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup) |
| Green locally, red in CI? | [PLAN.md §24.0](PLAN.md#240-verification-policy) — check PostgreSQL major version and extensions first |
| Self-hosting with Docker? | [DEVELOPMENT.md §3.6](DEVELOPMENT.md#36-self-hosted-docker-compose) |
| How do I create/archive an entity? | [ENTITY_LIFECYCLE.md](ENTITY_LIFECYCLE.md) |
| Terraform or AWS problem? | [INFRASTRUCTURE.md §10](INFRASTRUCTURE.md#10-troubleshooting) |

Still stuck: open an issue at [github.com/NemesisGhost/dnd_ai/issues](https://github.com/NemesisGhost/dnd_ai/issues) with what you tried, what you expected, what happened, sanitized error output, and your OS / Terraform version / AWS region.

External references: [Terraform AWS provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs), [AWS RDS](https://docs.aws.amazon.com/rds/), [PostgreSQL](https://www.postgresql.org/docs/), [Alembic](https://alembic.sqlalchemy.org/), [SQLAlchemy](https://docs.sqlalchemy.org/).
