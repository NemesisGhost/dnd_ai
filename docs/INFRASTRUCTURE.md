# Infrastructure Guide

Reference for the AWS infrastructure that hosts the platform — what exists, how it is configured, and how to operate it.

Today that is only the PostgreSQL database and its supporting resources, which is what this document describes. Compute for the application services is planned but unbuilt: [PLAN.md §30](PLAN.md#30-aws-deployment-plan-for-application-services) specifies ECS Fargate, and this document gains those sections when the modules exist.

**Which document do you want?**

| You want to… | Read |
|---|---|
| Set up your environment for the first time | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Deploy quickly, having done it before | [QUICKSTART.md](QUICKSTART.md) |
| Confirm you're ready to apply | [CHECKLIST.md](CHECKLIST.md) |
| Look up a variable, output, or error | **This document** |
| Set up your everyday dev/test database (local, not AWS) | [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup) |
| Reach the `dev` database directly | [DEVELOPMENT.md §3.5](DEVELOPMENT.md#35-connecting-to-aws-dev-occasional) |
| Know what the infrastructure *should* become | [PLAN.md §29](PLAN.md#29-aws-terraform-deployment-plan-for-postgresql) |

[PLAN.md §29](PLAN.md#29-aws-terraform-deployment-plan-for-postgresql) is the authoritative **plan**; this document describes **what exists today**. Where the two disagree about intent, §29 wins.

---

## Table of Contents

- [1. Current state](#1-current-state)
- [2. Prerequisites](#2-prerequisites)
- [3. Deploying](#3-deploying)
- [4. Configuration reference](#4-configuration-reference)
- [5. Outputs and connecting](#5-outputs-and-connecting)
- [6. Secrets](#6-secrets)
- [7. Verification](#7-verification)
- [8. Teardown](#8-teardown)
- [9. Cost](#9-cost)
- [10. Troubleshooting](#10-troubleshooting)
- [11. Known gaps and discrepancies](#11-known-gaps-and-discrepancies)

---

## 1. Current state

### What exists

```text
terraform/
├── modules/
│   ├── database/        # VPC, subnets, security group, KMS key, RDS PostgreSQL, VPC endpoints
│   └── secrets/         # Named (value-less) Secrets Manager entries for OpenAI/Discord/API keys
├── environments/
│   └── dev/             # The only environment that exists today
└── scripts/
    └── upsert-secrets.ps1   # Populates secret values via AWS CLI, after apply
build.ps1                # Root orchestration wrapper: init/plan/apply/destroy + secrets upsert
```

A `terraform apply` in `terraform/environments/dev/` provisions, in dependency order:

1. Networking — by default the environment **discovers and reuses the account's default VPC and its subnets**; it does not create a new VPC unless you override `vpc_id`/`private_subnet_ids`. The `database` module can create its own VPC when given `vpc_cidr`/`private_subnet_cidrs` instead.
2. A KMS key, used for both the RDS instance and the Secrets Manager entries.
3. VPC interface endpoints for Secrets Manager and KMS (`create_vpc_endpoints = true`), so private subnets need no NAT Gateway.
4. The RDS PostgreSQL instance, with an **AWS-managed master user secret** (`manage_master_user_password = true`) — no master password ever enters Terraform state or source control.
5. Named Secrets Manager entries for external credentials, created empty.

### What does not exist yet

Per [PLAN.md §29.1](PLAN.md#291-scope-and-current-state), still to be built:

- Remote Terraform state (currently **local state only** — see §29.2 of the plan).
- `staging/` and `prod/` environment directories.
- Database role, schema, and extension bootstrap. Terraform provisions the instance but cannot run SQL inside it; the RDS instance boots with only the master role and an empty database.
- A migration runner (`terraform/modules/db_migration_runner/`) able to reach a private RDS instance to run `alembic upgrade head` — used for `staging`/`prod`, which stay non-public.
- A `multi_az` variable on the `database` module.
- CloudWatch alarms.
- **All application compute.** Per [PLAN.md §30](PLAN.md#30-aws-deployment-plan-for-application-services), the API, background worker, and Discord adapter run on ECS Fargate from a shared image in ECR, behind an ALB. None of `ecr`, `ecs_cluster`, `ecs_service`, or `alb` modules exist. Note that pulling images into the private subnets requires either ECR/S3 VPC endpoints or a NAT Gateway — the current design has neither ([PLAN.md §30.9](PLAN.md#309-open-items)).

### What was removed

The pre-restart deployment tooling — the `db_runner`, `lambda-api`, and `lambda-with-build` modules, the `db-schema-introspect`/`query-runner` environments, and the Lambda that applied a directory of raw SQL files — has been **deleted**. Do not rebuild it from git history. Schema changes go through Alembic per [DATABASE_CONVENTIONS.md §25](DATABASE_CONVENTIONS.md#25-migration-conventions), executed by the migration runner described in [PLAN.md §29.6](PLAN.md#296-migration-execution-mechanism).

---

## 2. Prerequisites

### 2.1 Tools

| Tool | Version | Install | Verify |
|---|---|---|---|
| AWS CLI | v2 | [aws.amazon.com/cli](https://aws.amazon.com/cli/) — or `winget install Amazon.AWSCLI` | `aws --version` |
| Terraform | >= 1.5 | [developer.hashicorp.com/terraform/install](https://developer.hashicorp.com/terraform/install) — or `winget install HashiCorp.Terraform` | `terraform version` |
| PowerShell | 5.1+ | Preinstalled on Windows | `$PSVersionTable.PSVersion` |
| `jq` | any | `winget install jqlang.jq` | `jq --version` |
| `psql` | 18.x | Already installed if you followed [DEVELOPMENT.md §3.1](DEVELOPMENT.md#31-postgresql); otherwise `winget install PostgreSQL.PostgreSQL.18` | `psql --version` |

`jq` and `psql` are only needed for the credential-retrieval and manual connection steps in [§5](#5-outputs-and-connecting). `build.ps1` and `upsert-secrets.ps1` need PowerShell; plain `terraform` commands work from any shell.

The AWS provider is pinned to `~> 5.0` in `terraform/environments/dev/main.tf`.

Credential configuration, named profiles, and creating a scoped deployment identity are covered in [CONTRIBUTING.md §2](CONTRIBUTING.md#2-aws-access-optional). Verify with `aws sts get-caller-identity` before anything else — a missing or expired credential is the most common cause of a failed first apply.

### 2.2 Required IAM permissions

The apply creates resources across six services. The identity running Terraform needs:

| Service | Why | Key actions |
|---|---|---|
| RDS | The database instance, subnet group, parameter group | `rds:CreateDBInstance`, `rds:CreateDBSubnetGroup`, `rds:CreateDBParameterGroup`, `rds:Describe*`, `rds:Modify*`, `rds:Delete*`, `rds:AddTagsToResource` |
| EC2 / VPC | Subnets, security groups, VPC interface endpoints | `ec2:CreateSubnet`, `ec2:CreateSecurityGroup`, `ec2:AuthorizeSecurityGroupIngress`, `ec2:CreateVpcEndpoint`, `ec2:Describe*`, `ec2:CreateTags`, matching `Delete*` |
| KMS | The customer-managed encryption key and its alias | `kms:CreateKey`, `kms:CreateAlias`, `kms:DescribeKey`, `kms:TagResource`, `kms:ScheduleKeyDeletion` |
| Secrets Manager | The named credential entries, plus reading the RDS-managed master secret | `secretsmanager:CreateSecret`, `secretsmanager:DescribeSecret`, `secretsmanager:GetSecretValue`, `secretsmanager:PutSecretValue`, `secretsmanager:TagResource`, `secretsmanager:DeleteSecret` |
| IAM | The RDS enhanced-monitoring service role | `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:PassRole`, `iam:GetRole`, `iam:DeleteRole` |
| CloudWatch Logs | PostgreSQL log export | `logs:CreateLogGroup`, `logs:PutRetentionPolicy`, `logs:DescribeLogGroups` |

`PowerUserAccess` covers everything except the IAM role creation; pair it with the narrow role policy in [CONTRIBUTING.md §2.2](CONTRIBUTING.md#22-creating-a-deployment-identity). Least-privilege policies for the *runtime* roles — as opposed to the deploying identity — are in [§6](#6-secrets).

The pre-flight checklist is [CHECKLIST.md](CHECKLIST.md).

---

## 3. Deploying

The step-by-step path is [QUICKSTART.md](QUICKSTART.md); the pre-flight is [CHECKLIST.md](CHECKLIST.md). In brief:

```powershell
Copy-Item terraform/environments/dev/terraform.tfvars.example terraform/environments/dev/terraform.tfvars
# set owner_name, enable_public_access = true, and my_ip_cidr to something narrow
./build.ps1 -Environment dev -Action apply -AutoApprove
```

> **Set `my_ip_cidr` explicitly, and set it narrow.** Its declared default is `0.0.0.0/0` — never leave that in place. Per [PLAN.md §29.9](PLAN.md#299-shared-dev-verification-mechanism-ci), `dev` needs `enable_public_access = true` so contributors and CI can reach it day to day, but the actual per-caller allowlisting happens out-of-band via short-lived security-group rules added and removed with the AWS CLI (`scripts/aws-db-allow-my-ip.sh`, the CI workflow), not through this variable. Treat `my_ip_cidr` as a narrow, static baseline (e.g. your own IP, for the initial verification in [§7](#7-verification)) — it is not the mechanism day-to-day access relies on, and a `terraform apply` will not affect rules added out-of-band by that mechanism (see the note on drift in §29.9).

Terraform directly, if you prefer:

```powershell
terraform -chdir=terraform/environments/dev init
terraform -chdir=terraform/environments/dev plan -out tfplan
terraform -chdir=terraform/environments/dev apply tfplan
```

Initial apply takes roughly 10–15 minutes, dominated by RDS instance creation. `build.ps1` also runs the secrets upsert afterward if `terraform/environments/dev/secrets.local.json` exists (see [§6](#6-secrets)); pass `-SkipSecrets` to suppress it.

**The result is an empty database.** No schemas, roles, or extensions — that bootstrap is the first Alembic revision, run by the migration runner, and neither exists yet ([PLAN.md §29.5–§29.6](PLAN.md#295-database-role-schema-and-extension-bootstrap)).

---

## 4. Configuration reference

### Environment variables (`terraform/environments/dev/variables.tf`)

| Variable | Default | Purpose |
|---|---|---|
| `aws_region` | `us-east-1` | Deployment region |
| `owner_name` | `developer` | Applied as an `Owner` tag to all resources |
| `my_ip_cidr` | `0.0.0.0/0` | Static baseline ingress CIDR; **always override, narrowly**. Per-session access is layered on top out-of-band ([§3](#3-deploying), [PLAN.md §29.9](PLAN.md#299-shared-dev-verification-mechanism-ci)), not driven through this variable |
| `enable_public_access` | `false` | Makes the RDS instance publicly accessible; dev only. Set `true` — required for the day-to-day AWS-verification workflow, not just occasional manual access |
| `vpc_id` | `""` | Override to deploy into a specific VPC instead of the default one |
| `private_subnet_ids` | `[]` | Override subnet selection |
| `additional_tags` | `{}` | Extra tags merged into `default_tags` |

### Module variables worth knowing (`terraform/modules/database/variables.tf`)

| Variable | Default | Notes |
|---|---|---|
| `database_name` | `dnd_ai` | Not `dnd_ai_dev` |
| `master_username` | `dnd_admin` | Not `postgres` |
| `postgres_version` | `18.4` | Matches [DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version)'s pin and the local development server. `dev` was replaced onto this version 2026-08-08 — see [POSTGRES18_UPGRADE_PLAN.md](POSTGRES18_UPGRADE_PLAN.md). The RDS parameter group family (e.g. `postgres18`) is derived from this automatically (`local.parameter_group_family` in `rds.tf`) — there is no separate variable for it, so the two can't be set inconsistently |
| `instance_class` | `db.t3.micro` | |
| `allocated_storage` / `max_allocated_storage` | `20` / `100` | GB, gp3, autoscaling |
| `backup_retention_period` | `7` | Days |
| `deletion_protection` | `true` | Module default — meant for `staging`/`prod`. **`dev` overrides this to `false`** in `terraform/environments/dev/main.tf`, per [PLAN.md §29.3](PLAN.md#293-environments-dev-staging-prod) |
| `skip_final_snapshot` | `false` | Module default. **`dev` overrides this to `true`** — no final snapshot on delete, matching its disposable-by-design status |
| `iam_database_authentication_enabled` | `true` | Ready for the IAM-auth roles in [PLAN.md §29.5](PLAN.md#295-database-role-schema-and-extension-bootstrap) |
| `enhanced_monitoring` / `performance_insights_enabled` | `true` | |
| `create_vpc_endpoints` | `true` | Secrets Manager + KMS interface endpoints |
| `use_nat_gateway` | `false` | Endpoints are used instead |

The `dev` environment overrides only networking, `publicly_accessible`, `create_vpc_endpoints`, and tags. Everything else uses the module defaults above.

### Per-environment targets

When `staging/` and `prod/` are created, follow the table in [PLAN.md §29.3](PLAN.md#293-environments-dev-staging-prod). Copy `environments/dev/` rather than adding conditionals to a single environment — per-environment tfvars keep blast radius explicit.

### Making infrastructure changes

```powershell
terraform -chdir=terraform/environments/dev fmt -recursive
terraform -chdir=terraform/environments/dev validate
./build.ps1 -Environment dev -Action plan
```

Read the plan before applying. Specifically check that:

- No resource you expected to change in place is marked **destroy/replace** — on an `aws_db_instance` that means data loss.
- No credential, IP address, or account ID appears in a value you are about to commit.
- New variables have descriptions and sensible defaults, matching the style already in `terraform/modules/`.
- A new bounded concern gets its own module, mirroring the existing `database` / `secrets` split, rather than growing an existing one.

Never commit `terraform.tfvars`, `secrets.local.json`, `*.tfstate`, `tfplan`, or `.terraform/`. All are gitignored; verify with `git status` anyway before committing.

---

## 5. Outputs and connecting

```powershell
terraform -chdir=terraform/environments/dev output
```

| Output | Contents |
|---|---|
| `database_endpoint` | RDS hostname |
| `database_port` | `5432` |
| `database_name` | Database name |
| `database_secret_name` | **The ARN** of the RDS-managed master user secret (the name is misleading; the value is an ARN, which `--secret-id` accepts) |
| `vpc_id` | VPC the instance lives in |
| `database_security_group_id` | For granting other services ingress |
| `openai_secret_name` / `discord_secret_name` | Names of the value-less secret entries |
| `rds_iam_connect_resource_arn` | The wildcard `dbuser` ARN pattern for `rds-db:connect` IAM policies — convenient for exploration, too broad for a real policy |
| `rds_iam_connect_arns` | Per-role `dbuser` ARNs keyed by database role name; prefer these when writing an actual policy |
| `connection_command` | A ready-made psql snippet (marked `sensitive`) |

Retrieving credentials and connecting:

```powershell
$secretArn = terraform -chdir=terraform/environments/dev output -raw database_secret_name
$pw = aws secretsmanager get-secret-value --secret-id $secretArn --query SecretString --output text | jq -r .password

$env:PGPASSWORD = $pw
psql -h (terraform -chdir=terraform/environments/dev output -raw database_endpoint) `
     -p (terraform -chdir=terraform/environments/dev output -raw database_port) `
     -U dnd_admin `
     -d dnd_ai
$env:PGPASSWORD = $null
```

This only works from a network that can reach the instance — `enable_public_access = true` plus a current, open ingress rule for your IP (`scripts/aws-db-allow-my-ip.sh open`, per [PLAN.md §29.9](PLAN.md#299-shared-dev-verification-mechanism-ci)), or from inside the VPC.

---

## 6. Secrets

Per [rule 10 in CLAUDE.md](../CLAUDE.md#5-non-negotiable-architectural-rules) and [DATABASE_CONVENTIONS.md §27.3](DATABASE_CONVENTIONS.md#273-secrets), no credential may live in source control or Terraform state.

Two mechanisms are in play:

1. **Database master credentials** — managed entirely by AWS (`manage_master_user_password = true`). Terraform never sees the password. Nothing to do.
2. **External API credentials** (OpenAI, Discord) — Terraform creates the Secrets Manager *entries* with no values; values are pushed afterward by AWS CLI:

```powershell
Copy-Item terraform/environments/dev/secrets.local.json.example terraform/environments/dev/secrets.local.json
# edit secrets.local.json with real values, then:
./terraform/scripts/upsert-secrets.ps1 -Environment dev -Region us-east-1 -File terraform/environments/dev/secrets.local.json
```

`secrets.local.json`, `terraform.tfvars`, `*.tfstate`, and `.env` are all gitignored. Application roles should prefer IAM database authentication over stored passwords once the roles in [PLAN.md §29.5](PLAN.md#295-database-role-schema-and-extension-bootstrap) exist.

### IAM policy snippets

For a compute role that needs to read project secrets:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
      "Resource": ["arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:dnd-ai/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["kms:Decrypt"],
      "Resource": "arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID"
    }
  ]
}
```

For a role connecting with IAM database authentication, scope `rds-db:connect` to the specific entry it needs from the `rds_iam_connect_arns` output — the migration task to `migration_runner`, the API and worker to `app_read_write`, and so on ([PLAN.md §30.5](PLAN.md#305-identity-and-secrets)). `migration_owner` deliberately has no entry: it is `NOLOGIN` and cannot authenticate ([ADR 0009](adr/0009-separate-owning-role-from-login-roles.md)).

---

## 7. Verification

```powershell
# Configuration is valid
terraform -chdir=terraform/environments/dev validate
terraform -chdir=terraform/environments/dev fmt -recursive -check

# Instance is up
aws rds describe-db-instances --db-instance-identifier dnd-ai-dev-db `
  --query "DBInstances[0].[DBInstanceStatus,Engine,EngineVersion,PubliclyAccessible]"

# Project resources exist
aws secretsmanager list-secrets --query "SecretList[?starts_with(Name,'dnd-ai')].Name"
```

Expected after a successful apply:

- RDS instance `DBInstanceStatus` is `available`, engine `postgres`, version `18.4`
- A KMS key and a database security group
- Secrets Manager entries for the RDS master user plus the named OpenAI/Discord entries
- VPC interface endpoints for Secrets Manager and KMS

Once the bootstrap revision from [PLAN.md §29.5](PLAN.md#295-database-role-schema-and-extension-bootstrap) exists, verification also includes connecting as `app_read_only` via an IAM token and confirming all thirteen schemas plus the expected Alembic head revision — see [PLAN.md §29.7](PLAN.md#297-deployment-runbook) step 5.

---

## 8. Teardown

```powershell
./build.ps1 -Environment dev -Action destroy -AutoApprove
```

This now works without extra steps: `dev` overrides `deletion_protection = false` and `skip_final_snapshot = true` explicitly in `terraform/environments/dev/main.tf`, resolved 2026-08-08 as part of [POSTGRES18_UPGRADE_PLAN.md](POSTGRES18_UPGRADE_PLAN.md) (that plan needed exactly this to replace the RDS instance). If you ever hit `deletion_protection` blocking a destroy anyway — for example against an instance created before this override existed — disable it directly first:

```powershell
aws rds modify-db-instance --db-instance-identifier dnd-ai-dev-db `
  --no-deletion-protection --apply-immediately
```

Destroying removes the RDS instance and its data, the security groups and any created networking, the Secrets Manager entries, and schedules the KMS key for deletion. There is no undo.

---

## 9. Cost

Approximate monthly `dev` cost with current defaults:

| Resource | Configuration | Cost |
|---|---|---|
| RDS | `db.t3.micro` | ~$15 |
| Storage | 20 GB gp3 | ~$2 |
| KMS | 1 key | ~$1 |
| Secrets Manager | ~3 entries | ~$1.20 |
| VPC interface endpoints | 2 endpoints | ~$7–15 |
| **Total** | | **~$25–35/month** |

VPC endpoints are the largest variable. They exist to avoid a NAT Gateway, which would cost more. Setting `create_vpc_endpoints = false` only makes sense if the instance sits in a subnet with another route to AWS APIs.

`staging`/`prod` costs are not estimated here — measure once those environments exist rather than guessing, per [PLAN.md §29.8](PLAN.md#298-open-items). Run `terraform destroy` on `dev` when not actively developing.

---

## 10. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Error: configuring Terraform AWS Provider` | Credentials not configured. Run `aws sts get-caller-identity`; reconfigure with `aws configure`. |
| `DBSubnetGroupNotFoundFault` | Fewer than two subnets in distinct AZs. Check the default VPC, or set `private_subnet_ids` explicitly. |
| `InvalidParameterValue: ... cannot be deleted ... deletion protection` | See [§8](#8-teardown). |
| Secrets Manager "already exists / scheduled for deletion" | A prior destroy left it in the 7-day recovery window: `aws secretsmanager delete-secret --secret-id <name> --force-delete-without-recovery`. |
| State locked after an interrupted run | `terraform force-unlock <lock-id>` using the ID from the error. |
| Cannot reach the database | Confirm `enable_public_access = true`, that the instance is `available`, and that you've actually opened a session rule for your *current* IP (`scripts/aws-db-allow-my-ip.sh open` — your ISP-assigned IP changes, and the rule from a previous session may have been revoked or belong to a stale IP). `my_ip_cidr` alone is not enough per [§3](#3-deploying). |
| A `terraform plan` on `dev` shows an unexpected security-group ingress rule to remove | Someone's session-scoped rule (§3, §29.9) wasn't revoked cleanly — a crashed CI job or a forgotten `aws-db-allow-my-ip.sh close`. Applying removes it, which is correct; if a session is genuinely still active, revoke and re-open it instead of blocking the apply. |

Verbose Terraform logging: `$env:TF_LOG = "DEBUG"` before the command; unset afterward.

---

## 11. Known gaps and discrepancies

Documented so they get fixed rather than rediscovered. These are **code** issues, not doc issues:

0. ~~PostgreSQL major version is behind the pin~~ — resolved 2026-08-08. `dev` was replaced with a fresh PostgreSQL 18.4 instance (targeted `terraform apply -replace=module.database.aws_db_instance.main`, not an in-place `pg_upgrade`), matching [DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version)'s pin and the local development server. Full account, including two real bugs this surfaced and fixed (`deletion_protection` blocking the first replace attempt, and a missing `apply_method = "pending-reboot"` on the `shared_preload_libraries` parameter), is [POSTGRES18_UPGRADE_PLAN.md](POSTGRES18_UPGRADE_PLAN.md). One residual finding worth knowing: `rds.force_ssl` is not a recognized GUC on this engine build at all (absent from `pg_settings`) — SSL is still enforced, verified empirically (a `sslmode=disable` connection is rejected), just not through that parameter anymore. Gap 1 below (`deletion_protection`/`skip_final_snapshot` for `dev`) was closed as a prerequisite for this replacement.

1. ~~`dev` cannot be destroyed.~~ — resolved 2026-08-08, as a prerequisite for the PostgreSQL 18 instance replacement in [POSTGRES18_UPGRADE_PLAN.md](POSTGRES18_UPGRADE_PLAN.md). `terraform/environments/dev/main.tf` now passes `deletion_protection = false` and `skip_final_snapshot = true` explicitly, matching [PLAN.md §29.3](PLAN.md#293-environments-dev-staging-prod). Verified live: the first replacement attempt failed against the *old* instance's still-`true` protection (a `-replace` destroy-then-create never modifies the resource being replaced first), fixed by disabling it out-of-band before retrying — see B3 in the plan doc for the full account.
2. **`my_ip_cidr` defaults to `0.0.0.0/0`.** A default of `null` with explicit validation would fail closed instead of open. Now that per-session access is meant to go through `scripts/aws-db-allow-my-ip.sh` and CI's own authorize/revoke step rather than this variable (§3, [PLAN.md §29.9](PLAN.md#299-shared-dev-verification-mechanism-ci)), consider dropping it to a single harmless placeholder CIDR rather than keeping it as a real access path at all.
3. **`database_secret_name` returns an ARN**, not a name. Either rename the output or change the value.
4. **`app_config_secret_name` is hardcoded to `""`**, and `deployment_summary.secrets.app_config` to `null`. Dead outputs — remove or implement.
5. **The `secrets` module exposes `api_gateway_api_key_secret_*` and `basic_auth_secret_*`** outputs that belong to the removed pre-restart Lambda API. Confirm whether the current architecture needs them; if not, remove.
6. **No remote state.** Local state blocks any second operator and risks loss. Bootstrap per [PLAN.md §29.2](PLAN.md#292-remote-terraform-state) before `staging` exists.
7. **No `multi_az` variable**, required before `prod` per [PLAN.md §29.8](PLAN.md#298-open-items).
8. **No `CREATEDB`-capable test role.** The ephemeral-per-run database mechanism in [PLAN.md §29.9](PLAN.md#299-shared-dev-verification-mechanism-ci) works today — `tests/conftest.py`, `scripts/ci_ephemeral_database.py`, and this session's Phase 4 corrections work have all exercised it successfully — but only because it connects as the RDS master user, which has `CREATEDB` incidentally rather than by design. The bootstrap revision's six roles are still scoped to schema-level DDL/DML only, none with `CREATEDB`. Add a dedicated, narrower **login** role for this before running the mechanism unattended in prod-adjacent environments — not by granting `CREATEDB` to `migration_owner`, which is `NOLOGIN` and nothing connects as ([ADR 0009](adr/0009-separate-owning-role-from-login-roles.md)).
9. ~~`scripts/aws-db-allow-my-ip.sh` and the CI IP-allowlist step don't exist yet~~ — resolved. Both exist (`scripts/aws-db-allow-my-ip.sh`; the "Open dev access for this runner"/cleanup steps in `.github/workflows/ci.yml`) and have been exercised against the deployed `dev` security group. The required GitHub configuration is present and the complete workflow passed in run [`30765722355`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30765722355). Cleanup no longer masks drop/revoke failures with `|| true`: `scripts/ci_cleanup.py` always attempts both, fails the step if either failed, and its combining logic is exercised against every failure combination by `tests/unit/test_ci_cleanup.py` without touching real AWS resources (see [PHASE4_VERIFICATION.md § Second closeout](PHASE4_VERIFICATION.md#second-closeout-2026-08-02)).
