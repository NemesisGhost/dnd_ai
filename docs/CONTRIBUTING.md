# Contributing

Onboarding for new contributors: getting a working environment, then the workflow for changing things.

**Start with §1.** Most work on this project needs no AWS account at all.

---

## Table of Contents

- [1. Local development (start here)](#1-local-development-start-here)
- [2. AWS account setup](#2-aws-account-setup)
- [3. External API keys](#3-external-api-keys)
- [4. Changing application code](#4-changing-application-code)
- [5. Changing infrastructure](#5-changing-infrastructure)
- [6. Cost management](#6-cost-management)
- [7. Git workflow](#7-git-workflow)
- [8. Getting help](#8-getting-help)

---

## 1. Local development (start here)

The project is in [Phase 1](PLAN.md#23-delivery-phases) — database bootstrap. Everything through Phase 7 runs against a local PostgreSQL container. **You do not need AWS to contribute.**

Required:

| Tool | Version | Notes |
|---|---|---|
| Git | any | |
| Docker | any | Runs the local PostgreSQL |
| Python | 3.12+ | Pinned in [DEVELOPMENT.md §1](DEVELOPMENT.md#1-toolchain) |
| uv | latest | Dependency management — [install](https://docs.astral.sh/uv/getting-started/installation/) |

Recommended: VS Code or your preferred IDE. Node.js 18+ only if you start on the React UI, which has not begun.

Setup, in full, is [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup). The short version:

```bash
uv sync
docker run -d --name dnd-ai-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=dnd_ai -p 5432:5432 postgres:15
cp .env.example .env
```

Then read, in order: [PLAN.md](PLAN.md) for the current phase, [DOMAIN_MODEL.md](DOMAIN_MODEL.md) for vocabulary, [DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md) before writing schema, and [architecture/SYSTEM_ARCHITECTURE.md §5](architecture/SYSTEM_ARCHITECTURE.md#5-layering) for where code belongs.

Skip to §4 unless you specifically need deployed infrastructure.

---

## 2. AWS account setup

Only needed to deploy real infrastructure — closing the last [Phase 1 exit criterion](PLAN.md#23-delivery-phases), or working on the migration runner.

### 2.1 Install and configure

| Tool | Install |
|---|---|
| AWS CLI v2 | [aws.amazon.com/cli](https://aws.amazon.com/cli/) or `winget install Amazon.AWSCLI` |
| Terraform >= 1.5 | [developer.hashicorp.com/terraform/install](https://developer.hashicorp.com/terraform/install) or `winget install HashiCorp.Terraform` |

```powershell
aws configure --profile dnd-ai-dev
# Access Key ID, Secret Access Key, region (us-east-1), output format (json)

$env:AWS_PROFILE = "dnd-ai-dev"
aws sts get-caller-identity     # must succeed before anything else
```

`build.ps1` accepts the profile directly: `./build.ps1 -Environment dev -Action plan -AwsProfile dnd-ai-dev`.

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

### 2.3 Deploying

Follow [QUICKSTART.md](QUICKSTART.md), with [CHECKLIST.md](CHECKLIST.md) as the pre-flight. Reference material is [INFRASTRUCTURE.md](INFRASTRUCTURE.md).

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

All four must pass before opening a pull request. The full workflow — Alembic revision requirements, the three test layers, CI expectations — is [DEVELOPMENT.md §4–§8](DEVELOPMENT.md#4-database-and-migrations), and the definition of done is [§10](DEVELOPMENT.md#10-definition-of-done).

Before writing anything, confirm it belongs to the current phase in [PLAN.md](PLAN.md), and check the ten non-negotiable rules in [CLAUDE.md §5](../CLAUDE.md#5-non-negotiable-architectural-rules). If a task appears to require breaking one, stop and raise it rather than deviating quietly.

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

A dev environment runs ~$25–35/month ([INFRASTRUCTURE.md §9](INFRASTRUCTURE.md#9-cost)).

**Destroy it when you aren't using it.** That is the only reliable way to stop the spend:

```powershell
aws rds modify-db-instance --db-instance-identifier dnd-ai-dev-db --no-deletion-protection --apply-immediately
./build.ps1 -Environment dev -Action destroy -AutoApprove
```

Stopping rather than destroying is a partial measure — storage, KMS, VPC endpoints, and secrets keep billing, and **AWS automatically restarts a stopped RDS instance after 7 days**:

```powershell
aws rds stop-db-instance --db-instance-identifier dnd-ai-dev-db
aws rds start-db-instance --db-instance-identifier dnd-ai-dev-db
```

Set a billing alarm in AWS Budgets so an unnoticed instance doesn't run for a month. Remember that local development costs nothing — reach for §1 before §2.

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
| How do I create/archive an entity? | [ENTITY_LIFECYCLE.md](ENTITY_LIFECYCLE.md) |
| Terraform or AWS problem? | [INFRASTRUCTURE.md §10](INFRASTRUCTURE.md#10-troubleshooting) |

Still stuck: open an issue at [github.com/NemesisGhost/dnd_ai/issues](https://github.com/NemesisGhost/dnd_ai/issues) with what you tried, what you expected, what happened, sanitized error output, and your OS / Terraform version / AWS region.

External references: [Terraform AWS provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs), [AWS RDS](https://docs.aws.amazon.com/rds/), [PostgreSQL](https://www.postgresql.org/docs/), [Alembic](https://alembic.sqlalchemy.org/), [SQLAlchemy](https://docs.sqlalchemy.org/).
