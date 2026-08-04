# Contributing

Onboarding for new contributors: getting a working environment, then the workflow for changing things.

**Start with §1.** Per [PLAN.md §23.0](PLAN.md#230-aws-verification-policy), every phase — migrations and their `tests/database`/`tests/scenario` suites — is verified against the deployed AWS `dev` environment, not a local stand-in. **You need AWS access to contribute**, not just to touch infrastructure.

---

## Table of Contents

- [1. AWS account setup (start here)](#1-aws-account-setup-start-here)
- [2. Toolchain and environment](#2-toolchain-and-environment)
- [3. External API keys](#3-external-api-keys)
- [4. Changing application code](#4-changing-application-code)
- [5. Changing infrastructure](#5-changing-infrastructure)
- [6. Cost management](#6-cost-management)
- [7. Git workflow](#7-git-workflow)
- [8. Getting help](#8-getting-help)

---

## 1. AWS account setup (start here)

Phases 1 through 5 are complete and CI-verified, including all three of Phase 4's closeout passes and Phase 5's five corrections passes ([PHASE4_REMAINING_ISSUES.md](PHASE4_REMAINING_ISSUES.md) and [PHASE5_REMAINING_ISSUES.md](PHASE5_REMAINING_ISSUES.md) are both closed historical records). Both [Phase 6 entry gates](PLAN.md#phase-6-events-and-interactions) (repository context modularization, Phase 5 correctness) are closed, confirmed by GitHub Actions run 30878624056 on PR #10. Every phase verifies against the deployed `dev` RDS instance (migrations, `tests/database`, `tests/scenario`) — see [PLAN.md §23.0](PLAN.md#230-aws-verification-policy) and [§29.9](PLAN.md#299-aws-first-verification-mechanism) for why and how. A local PostgreSQL container is a documented fallback for when AWS is genuinely unreachable, not the default path — see [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup).

### 1.1 Install and configure

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

### 1.2 Creating a deployment identity

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

### 1.3 Deploying `dev`, once

`dev` is now shared, always-on infrastructure that every contributor's tests run against — someone needs to have deployed it before anyone can do §2 onward. If it's already up (ask in the project's usual channel, or just try `terraform -chdir=terraform/environments/dev output` first), skip to §2.

Otherwise follow [QUICKSTART.md](QUICKSTART.md), with [CHECKLIST.md](CHECKLIST.md) as the pre-flight. Reference material is [INFRASTRUCTURE.md](INFRASTRUCTURE.md). Set `enable_public_access = true` — required for the reachability mechanism in [PLAN.md §29.9](PLAN.md#299-aws-first-verification-mechanism) — and do **not** narrow `my_ip_cidr` to a single IP the way an old single-developer setup would; per-session access is granted per §2 below, not baked into the Terraform variable.

---

## 2. Toolchain and environment

Required, beyond the AWS access from §1:

| Tool | Version | Notes |
|---|---|---|
| Git | any | |
| Python | 3.12+ | Pinned in [DEVELOPMENT.md §1](DEVELOPMENT.md#1-toolchain) |
| uv | latest | Dependency management — [install](https://docs.astral.sh/uv/getting-started/installation/) |
| `curl` | any | Used to look up your current IP when opening dev access |
| Docker | any | **Fallback only** — for the local-container path in [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup) when AWS is unreachable |

Recommended: VS Code or your preferred IDE. Node.js 18+ only if you start on the React UI, which has not begun.

Setup, in full, is [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup). The short version:

```bash
uv sync
cp .env.example .env              # then edit DATABASE_URL to point at the dev endpoint
scripts/aws-db-allow-my-ip.sh open # opens dev access for your current IP
uv run alembic -c database/alembic.ini current
```

Run `scripts/aws-db-allow-my-ip.sh close` when you're done for the session — it isn't automatic outside CI.

Then follow [CLAUDE.md §4](../CLAUDE.md#4-documentation-map-and-context-loading-policy): read [PLAN.md §23.0–23.1](PLAN.md#23-delivery-phases) plus the current phase entry, search [DOMAIN_MODEL.md](DOMAIN_MODEL.md) for the affected vocabulary, read only the [DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md) sections governing the mechanisms you will change, and consult [architecture/SYSTEM_ARCHITECTURE.md §5](architecture/SYSTEM_ARCHITECTURE.md#5-layering) when application-layer placement is in scope. Do not preload the complete documentation set.

Skip to §4 unless you specifically need to change infrastructure itself, rather than just using the deployed `dev` environment.

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

`dev` runs ~$25–35/month ([INFRASTRUCTURE.md §9](INFRASTRUCTURE.md#9-cost)). Per [PLAN.md §23.0](PLAN.md#230-aws-verification-policy) it's now shared, always-on infrastructure that every contributor's tests depend on — **do not destroy or stop it** as a cost-saving measure; that breaks everyone else's ability to run `tests/database`/`tests/scenario` until it's back. This is an accepted ongoing project cost, not per-developer spend to individually manage.

Set a billing alarm in AWS Budgets so a runaway cost (an oversized instance class, an accidentally-left-open ingress rule from a failed CI run, storage growth from real usage) gets noticed quickly rather than discovered a month later. If cost genuinely needs to come down, that's an infrastructure change (right-sizing `instance_class`, revisiting VPC endpoints) proposed and applied deliberately per §5 — not an ad hoc destroy/recreate cycle.

Tearing `dev` down is still appropriate when the project itself is paused for an extended period, not as routine idle-time hygiene:

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
| How do I create/archive an entity? | [ENTITY_LIFECYCLE.md](ENTITY_LIFECYCLE.md) |
| Terraform or AWS problem? | [INFRASTRUCTURE.md §10](INFRASTRUCTURE.md#10-troubleshooting) |

Still stuck: open an issue at [github.com/NemesisGhost/dnd_ai/issues](https://github.com/NemesisGhost/dnd_ai/issues) with what you tried, what you expected, what happened, sanitized error output, and your OS / Terraform version / AWS region.

External references: [Terraform AWS provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs), [AWS RDS](https://docs.aws.amazon.com/rds/), [PostgreSQL](https://www.postgresql.org/docs/), [Alembic](https://alembic.sqlalchemy.org/), [SQLAlchemy](https://docs.sqlalchemy.org/).
