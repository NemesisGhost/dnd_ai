# Infrastructure Guide (optional AWS path)

**This document describes the optional, no-longer-required AWS RDS path.** Self-hosted Docker Compose (`compose.yaml`, `Dockerfile`) is the officially supported deployment topology, and CI verifies against containerized PostgreSQL rather than AWS — see [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md) and [DEVELOPMENT.md §3.6](DEVELOPMENT.md#36-self-hosted-docker-compose). Nothing here is needed for development, CI, or ordinary contribution; it remains accurate reference material for anyone who chooses to host on AWS RDS instead.

> **Planned production target:** the existing Ubuntu mini-PC, per the (not yet implemented) [ADR 0013](adr/0013-locally-host-production-on-existing-mini-pc.md) and [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md). The AWS material below is optional reference material, not a resource slated for teardown — see line 3 above.

Reference for the AWS infrastructure that hosts the platform — what exists, how it is configured, and how to operate it.

Today that is only the PostgreSQL database and its supporting resources, which is what this document describes. Compute for the application services on AWS is planned but unbuilt and optional: [PLAN.md §31](README.md) sketches ECS Fargate/Lambda paths, and this document gains those sections when and if the modules exist.

**Which document do you want?**

| You want to… | Read |
|---|---|
| Set up your environment for the first time | [Development setup](DEVELOPMENT.md) |
| Deploy quickly, having done it before | [Deploying](#3-deploying) |
| Confirm you're ready to apply | [AWS preflight](#12-optional-aws-preflight) |
| Look up a variable, output, or error | **This document** |
| Set up your everyday dev/test database (local, not AWS) | [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup) |
| Reach the `dev` database directly | [DEVELOPMENT.md §3.5](DEVELOPMENT.md#35-connecting-to-aws-dev-optional-no-longer-required) |
| Know what the infrastructure *should* become | [PLAN.md §29](README.md) |

[PLAN.md §29](README.md) is the authoritative **plan**; this document describes **what exists today**. Where the two disagree about intent, §29 wins.

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
- [11. Known gaps and discrepancies](#11-known-gaps-and-historical-configuration)

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

Per [PLAN.md §29.1](README.md), still to be built:

- Remote Terraform state (currently **local state only** — see §29.2 of the plan).
- `staging/` and `prod/` environment directories.
- Database role, schema, and extension bootstrap. Terraform provisions the instance but cannot run SQL inside it; the RDS instance boots with only the master role and an empty database.
- A migration runner (`terraform/modules/db_migration_runner/`) able to reach a private RDS instance to run `alembic upgrade head` — used for `staging`/`prod`, which stay non-public.
- A `multi_az` variable on the `database` module.
- CloudWatch alarms.
- **All application compute.** Per [PLAN.md §30](README.md), the API, background worker, and Discord adapter run on ECS Fargate from a shared image in ECR, behind an ALB. None of `ecr`, `ecs_cluster`, `ecs_service`, or `alb` modules exist. Note that pulling images into the private subnets requires either ECR/S3 VPC endpoints or a NAT Gateway — the current design has neither ([PLAN.md §30.9](README.md)).

### What was removed

The pre-restart deployment tooling — the `db_runner`, `lambda-api`, and `lambda-with-build` modules, the `db-schema-introspect`/`query-runner` environments, and the Lambda that applied a directory of raw SQL files — has been **deleted**. Do not rebuild it from git history. Schema changes go through Alembic per [DATABASE_CONVENTIONS.md §25](DATABASE_CONVENTIONS.md#25-migration-conventions), executed by the migration runner described in [PLAN.md §29.6](README.md).

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

Select the intended AWS CLI profile and region before using Terraform. Verify the active identity with `aws sts get-caller-identity`; credentials belong in the local CLI/identity provider configuration, not source control. The permissions table below describes the deployment operations.

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

The deployment identity needs the relevant scoped actions above, including permission to create/pass the enhanced-monitoring role. Do not assume a broad managed policy supplies IAM permissions. Runtime-role policies are described in [§6](#6-secrets).

The pre-flight checklist is [AWS preflight](#12-optional-aws-preflight).

---

## 3. Deploying

The step-by-step path is [Deploying](#3-deploying); the pre-flight is [AWS preflight](#12-optional-aws-preflight). In brief:

```powershell
Copy-Item terraform/environments/dev/terraform.tfvars.example terraform/environments/dev/terraform.tfvars
# set owner_name, enable_public_access = true, and my_ip_cidr to something narrow
./build.ps1 -Environment dev -Action apply -AutoApprove
```

> **Set `my_ip_cidr` explicitly, and set it narrow.** Its declared default is `0.0.0.0/0` — never leave that in place. Per [PLAN.md §29.9](README.md), `dev` needs `enable_public_access = true` so contributors and CI can reach it day to day, but the actual per-caller allowlisting happens out-of-band via short-lived security-group rules added and removed with the AWS CLI (`scripts/aws-db-allow-my-ip.sh`, the CI workflow), not through this variable. Treat `my_ip_cidr` as a narrow, static baseline (e.g. your own IP, for the initial verification in [§7](#7-verification)) — it is not the mechanism day-to-day access relies on, and a `terraform apply` will not affect rules added out-of-band by that mechanism (see the note on drift in §29.9).

Terraform directly, if you prefer:

```powershell
terraform -chdir=terraform/environments/dev init
terraform -chdir=terraform/environments/dev plan -out tfplan
terraform -chdir=terraform/environments/dev apply tfplan
```

Initial apply takes roughly 10–15 minutes, dominated by RDS instance creation. `build.ps1` also runs the secrets upsert afterward if `terraform/environments/dev/secrets.local.json` exists (see [§6](#6-secrets)); pass `-SkipSecrets` to suppress it.

**The result is an empty database.** No schemas, roles, or extensions — that bootstrap is the first Alembic revision, run by the migration runner, and neither exists yet ([PLAN.md §29.5–§29.6](README.md)).

---

## 4. Configuration reference

### Environment variables (`terraform/environments/dev/variables.tf`)

| Variable | Default | Purpose |
|---|---|---|
| `aws_region` | `us-east-1` | Deployment region |
| `owner_name` | `developer` | Applied as an `Owner` tag to all resources |
| `my_ip_cidr` | `0.0.0.0/0` | Static baseline ingress CIDR; **always override, narrowly**. Per-session access is layered on top out-of-band ([§3](#3-deploying), [PLAN.md §29.9](README.md)), not driven through this variable |
| `enable_public_access` | `false` | Makes the RDS instance publicly accessible; dev only. Set `true` — required for the day-to-day AWS-verification workflow, not just occasional manual access |
| `vpc_id` | `""` | Override to deploy into a specific VPC instead of the default one |
| `private_subnet_ids` | `[]` | Override subnet selection |
| `additional_tags` | `{}` | Extra tags merged into `default_tags` |

### Module variables worth knowing (`terraform/modules/database/variables.tf`)

| Variable | Default | Notes |
|---|---|---|
| `database_name` | `dnd_ai` | Not `dnd_ai_dev` |
| `master_username` | `dnd_admin` | Not `postgres` |
| `postgres_version` | `18.4` | Matches [DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version)'s pin and the local development server. `dev` was replaced onto this version 2026-08-08 — see [POSTGRES18_UPGRADE_PLAN.md](DELIVERY_HISTORY.md). The RDS parameter group family (e.g. `postgres18`) is derived from this automatically (`local.parameter_group_family` in `rds.tf`) — there is no separate variable for it, so the two can't be set inconsistently |
| `instance_class` | `db.t3.micro` | |
| `allocated_storage` / `max_allocated_storage` | `20` / `100` | GB, gp3, autoscaling |
| `backup_retention_period` | `7` | Days |
| `deletion_protection` | `true` | Module default — meant for `staging`/`prod`. **`dev` overrides this to `false`** in `terraform/environments/dev/main.tf`, per [PLAN.md §29.3](README.md) |
| `skip_final_snapshot` | `false` | Module default. **`dev` overrides this to `true`** — no final snapshot on delete, matching its disposable-by-design status |
| `iam_database_authentication_enabled` | `true` | Ready for the IAM-auth roles in [PLAN.md §29.5](README.md) |
| `enhanced_monitoring` / `performance_insights_enabled` | `true` | |
| `create_vpc_endpoints` | `true` | Secrets Manager + KMS interface endpoints |
| `use_nat_gateway` | `false` | Endpoints are used instead |

The `dev` environment overrides only networking, `publicly_accessible`, `create_vpc_endpoints`, and tags. Everything else uses the module defaults above.

### Per-environment targets

When `staging/` and `prod/` are created, follow the table in [PLAN.md §29.3](README.md). Copy `environments/dev/` rather than adding conditionals to a single environment — per-environment tfvars keep blast radius explicit.

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

This only works from a network that can reach the instance — `enable_public_access = true` plus a current, open ingress rule for your IP (`scripts/aws-db-allow-my-ip.sh open`, per [PLAN.md §29.9](README.md)), or from inside the VPC.

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

`secrets.local.json`, `terraform.tfvars`, `*.tfstate`, and `.env` are all gitignored. Application roles should prefer IAM database authentication over stored passwords once the roles in [PLAN.md §29.5](README.md) exist.

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

For a role connecting with IAM database authentication, scope `rds-db:connect` to the specific entry it needs from the `rds_iam_connect_arns` output — the migration task to `migration_runner`, the API and worker to `app_read_write`, and so on ([PLAN.md §30.5](README.md)). `migration_owner` deliberately has no entry: it is `NOLOGIN` and cannot authenticate ([ADR 0009](adr/0009-separate-owning-role-from-login-roles.md)).

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

Once the bootstrap revision from [PLAN.md §29.5](README.md) exists, verification also includes connecting as `app_read_only` via an IAM token and confirming all thirteen schemas plus the expected Alembic head revision — see [PLAN.md §29.7](README.md) step 5.

---

## 8. Teardown

```powershell
./build.ps1 -Environment dev -Action destroy -AutoApprove
```

This now works without extra steps: `dev` overrides `deletion_protection = false` and `skip_final_snapshot = true` explicitly in `terraform/environments/dev/main.tf`, resolved 2026-08-08 as part of [POSTGRES18_UPGRADE_PLAN.md](DELIVERY_HISTORY.md) (that plan needed exactly this to replace the RDS instance). If you ever hit `deletion_protection` blocking a destroy anyway — for example against an instance created before this override existed — disable it directly first:

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

`staging`/`prod` costs are not estimated here — measure once those environments exist rather than guessing, per [PLAN.md §29.8](README.md). Run `terraform destroy` on `dev` when not actively developing.

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

## 11. Known gaps and historical configuration

The 2026-08-08 replacement onto PostgreSQL 18.4 and the dev deletion-protection/final-snapshot
overrides are completed historical changes; details are indexed in [delivery history](DELIVERY_HISTORY.md).
The current Terraform configuration is the configuration reference, not a live AWS inventory.

Remote Terraform state and staging/prod environments are not supplied by this repository.
Reconcile the historical orphaned KMS resource and login-role-list drift before operating
that account. A narrower CREATEDB login is an optional-AWS test-provisioning concern;
`migration_owner` remains NOLOGIN. Current CI runs containerized PostgreSQL and does not
open AWS ingress. Old `ci_ephemeral_database.py`/`ci_cleanup.py` references and AWS CI run
records describe the retired verification path, not scripts to invoke today.

## 12. Optional AWS preflight

Use this path only when operating the retained Terraform/RDS target; normal development
and CI use local/containerized PostgreSQL. Before an apply, confirm the AWS account and
region, inspect existing state, configure narrow network access, keep credentials/tfvars
untracked, and review the plan for replacements/deletions. The current dev configuration
sets `deletion_protection = false` and `skip_final_snapshot = true`; these settings are
not proof of any live instance's state. Bootstrap is implemented by Alembic, not future work.
Follow §§3–7 for configuration, deployment and verification, and §8 for intentional teardown.

Historical operator questions still needing reconciliation if AWS is used: the orphaned
KMS resource reported by Phase 1, manual `iam_auth_db_users` alignment with login roles,
remote state, and a narrower CREATEDB login for test provisioning. Do not delete a cloud
resource on the assumption that a historical report still describes today's account.

## 13. Legacy GitHub Actions OIDC state

The following operator decision guidance was moved from terraform/README. It describes
the consequences of removing configuration, not evidence that any live resources were
changed. No AWS operation is part of this documentation consolidation.

### Removed from configuration: the `github_actions_ci` module

The `github_actions_ci` module (the OIDC role CI used to assume) was removed
from configuration — its only consumer was the AWS `aws-verification` CI
job, which no longer exists. See
[docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)
for the reasoning. **This was a configuration-only change; no live AWS
resource was created, modified, or destroyed by that commit** — nothing in
this repository ran `terraform apply`, `terraform destroy`, or any command
that touches a backend or provider.

Removing a module from *configuration* does not remove, retire, or delete
anything from AWS by itself — it only makes configuration and state
disagree. What happens next is a deliberate operator choice between three
different outcomes, below. Don't run any of them without reading the plan
they produce first.

**What a future `terraform plan`/`apply` against a previously applied `dev`
will show, if you do nothing else.** Terraform reconciles state against
configuration, and resources present in state but absent from config are
proposed for *destruction* by default — not left alone. If `dev` was ever
applied with this module present, the next plan run against that state
will propose destroying:

- `module.github_actions_ci.aws_iam_role.github_actions_ci` and its inline
  policy — scoped to this repository's CI.
- `module.github_actions_ci.aws_iam_openid_connect_provider.github[0]` —
  **only if** `create_github_oidc_provider`/`create_oidc_provider` was
  `true` when applied (the `dev` environment's default). This resource is
  **not scoped to this repository**: a GitHub Actions OIDC provider
  (`token.actions.githubusercontent.com`) is one-per-AWS-account, so if this
  module created it, any *other* GitHub Actions workflow in the same AWS
  account that assumes a role via OIDC may depend on that same provider
  existing. **Never let a plan destroy it reflexively.** Check for other
  consumers first, every time, regardless of which of the three choices
  below you're pursuing:

  ```powershell
  aws iam list-open-id-connect-providers
  aws iam list-roles --query "Roles[?AssumeRolePolicyDocument.Statement[?Principal.Federated!=null]]"
  ```

  If another role trusts the same provider ARN, none of the options below
  may destroy or delete it.

**Review any plan line by line before applying it, every time.** `terraform
plan` alone touches no live resource — read exactly what it proposes,
re-check the OIDC-provider question above, and only then decide whether to
`apply`. None of this runs automatically from any commit to this
repository.

#### A. Preserve the resources *and* keep them Terraform-managed

Configuration and state must agree for Terraform to manage something — since
the module block is gone from this repository's configuration, keeping the
role Terraform-managed means putting equivalent configuration back before
applying anything: restore the `module "github_actions_ci"` block (see git
history for its last committed form), or write a new configuration and
`terraform import` the existing role/policy/provider into it. Either way,
apply nothing until a `terraform plan` against that restored configuration
shows no unexpected changes — it should show none, since the real resource
hasn't moved.

#### B. Preserve the live resources but stop managing them

This leaves everything the module created exactly as it is in AWS — **live,
unretired, unmanaged** — with Terraform simply no longer tracking any of it.
`state rm` does not delete or retire anything; it only removes an entry from
Terraform's state file. But state and reality have to be dropped *together*:
if some of the module's resources stay in state while others don't, a future
plan reconciles state against configuration for whatever's left, and with the
module gone from configuration, anything still tracked is proposed for
*destruction* — silently turning a "stop managing" choice into a "delete"
outcome for whichever resource you forgot. Removing the entire module
address from state, in one operation, is generally the coherent way to
abandon management of it, rather than removing resources one at a time.

Start by finding out what's actually still tracked — don't assume; the OIDC
provider resource's `count` depended on configuration (`create_github_oidc_provider`/
`create_oidc_provider`), so whether it's in state at all depends on how `dev`
was applied:

```powershell
terraform -chdir=terraform/environments/dev state list
```

Look for `module.github_actions_ci` and everything nested under it in the
output. If the module doesn't appear at all, there's nothing to remove —
skip straight to whichever of A/B/C you actually need for other resources.
If it does appear, remove the whole module in one command:

```powershell
terraform -chdir=terraform/environments/dev state rm module.github_actions_ci
```

This is deliberately the module-wide form, not per-resource `state rm`
calls, because it can't leave a partial result: whatever the `state list`
output actually showed under `module.github_actions_ci` — role, inline
policy, and OIDC provider alike, if `state list` showed the provider as
present — comes out of state together. **The shared OIDC provider is
exactly the resource this matters most for**: it's one-per-AWS-account, not
scoped to this repository (see the dependency check above), so if it's in
state and gets left behind while the rest of the module is removed, the next
`plan` proposes destroying a resource other GitHub Actions workflows in the
same account may depend on. Leaving it tracked under absent configuration is
not a safe way to "preserve" it — removing it from state, so Terraform stops
proposing to touch it at all, is what actually preserves it here.

On Terraform 1.7+, a declarative alternative that leaves a reviewable record
of this same choice is a `removed` block scoped to the whole module (add
temporarily, apply once, then delete):

```hcl
removed {
  from = module.github_actions_ci
  lifecycle {
    destroy = false
  }
}
```

Either form stops here: the IAM role, its inline policy, and the OIDC
provider (if it was ever in state) keep existing in AWS, accruing no
Terraform drift warnings but also receiving no further review from anyone,
until a human deletes them directly or brings them back under management via
option A.

#### C. Actually retire the resources (delete them)

Only after confirming via the dependency check above that nothing else
trusts the OIDC provider (if it's in scope at all), pick one:

1. **Temporarily restore the module configuration** (as in option A) and run
   a normal, reviewed `terraform destroy -target=module.github_actions_ci`
   against it, reading the plan first — this uses Terraform's own
   understanding of the resource graph rather than a hand-assembled list of
   ARNs, so it's the safer of the two paths here.
2. **Delete the specific resources directly with AWS tooling**, after
   confirming their exact names/ARNs yourself (`aws iam get-role
   --role-name <name>`, `aws iam list-role-policies --role-name <name>`) —
   there is deliberately no ready-made deletion script in this repository
   for this, since a generic one is exactly the kind of broad,
   easy-to-misapply tool that risks taking out a shared resource. Delete the
   inline policy before the role, and only delete the OIDC provider
   (`aws iam delete-open-id-connect-provider`) as an explicit, separate,
   last step you've independently decided to take — never as a
   side effect of cleaning up this repository's role.

Whichever path, if anything was still tracked in Terraform state when you
delete it out-of-band, run the module-wide `state rm` from option B
afterward (after re-checking with `state list`) so state doesn't keep
referencing a resource that no longer exists.
