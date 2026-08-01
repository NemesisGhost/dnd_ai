# Quick Start

The fast path to a deployed development database. Assumes AWS CLI and Terraform are already installed and configured — if not, start with [CONTRIBUTING.md](CONTRIBUTING.md#2-aws-account-setup).

> **You may not need this.** Implementation work through Phase 7 runs entirely against a local Docker PostgreSQL container and costs nothing. See [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup). Deploy AWS infrastructure only when you specifically need it.

---

## 1. Configure

```powershell
Copy-Item terraform/environments/dev/terraform.tfvars.example terraform/environments/dev/terraform.tfvars
```

Edit the three values that matter:

```hcl
owner_name           = "your-name"          # tags every resource
my_ip_cidr           = "203.0.113.42/32"    # YOUR ip — the default is 0.0.0.0/0
enable_public_access = true                  # dev only
```

Find your IP:

```powershell
(Invoke-RestMethod https://ifconfig.me/ip).Trim()   # PowerShell
curl ifconfig.me                                    # bash
```

Append `/32` to make it a CIDR block.

## 2. (Optional) Add API keys

Only needed for the OpenAI or Discord integrations, neither of which is built yet.

```powershell
Copy-Item terraform/environments/dev/secrets.local.json.example terraform/environments/dev/secrets.local.json
```

Keys come from [platform.openai.com/api-keys](https://platform.openai.com/api-keys) and [discord.com/developers/applications](https://discord.com/developers/applications). The file is gitignored; values are pushed to Secrets Manager after apply, never into Terraform state.

## 3. Deploy

```powershell
./build.ps1 -Environment dev -Action plan            # review this
./build.ps1 -Environment dev -Action apply -AutoApprove
```

Roughly 10–15 minutes, dominated by RDS creation. `build.ps1` runs the secrets upsert automatically afterward if `secrets.local.json` exists.

Working through [CHECKLIST.md](CHECKLIST.md) first is worth the two minutes on a first deployment.

## 4. Verify

```powershell
terraform -chdir=terraform/environments/dev output
aws rds describe-db-instances --db-instance-identifier dnd-ai-dev-db --query "DBInstances[0].DBInstanceStatus"
```

Expect `available`. Full verification steps are in [INFRASTRUCTURE.md §7](INFRASTRUCTURE.md#7-verification).

## 5. Tear down when finished

```powershell
./build.ps1 -Environment dev -Action destroy -AutoApprove
```

**This currently fails** — `deletion_protection` defaults to `true` and dev never overrides it. Disable it first:

```powershell
aws rds modify-db-instance --db-instance-identifier dnd-ai-dev-db --no-deletion-protection --apply-immediately
```

See [INFRASTRUCTURE.md §8](INFRASTRUCTURE.md#8-teardown).

---

## FAQ

**What did I just deploy?**
A VPC-attached PostgreSQL 15 RDS instance, a KMS key, a security group, VPC endpoints for Secrets Manager and KMS, and empty Secrets Manager entries. Full inventory: [INFRASTRUCTURE.md §1](INFRASTRUCTURE.md#1-current-state).

**Can I use the database yet?**
Not really. It is an **empty** PostgreSQL instance — no schemas, roles, or extensions. That bootstrap is the first Alembic revision and does not exist yet ([PLAN.md §29.5](PLAN.md#295-database-role-schema-and-extension-bootstrap)).

**How do I connect?**
`terraform output` gives the endpoint; credentials come from the AWS-managed master secret. The username is `dnd_admin` and the database is `dnd_ai` — not `postgres`/`dnd_ai_dev`. Commands: [INFRASTRUCTURE.md §5](INFRASTRUCTURE.md#5-outputs-and-connecting).

**How do I run migrations against it?**
You can't yet, and not from your laptop when you can — the instance is private. Migrations run through the runner in [PLAN.md §29.6](PLAN.md#296-migration-execution-mechanism), which is unbuilt. Local migration workflow: [DEVELOPMENT.md §4](DEVELOPMENT.md#4-database-and-migrations).

**What does it cost?**
~$25–35/month. Breakdown and how to reduce it: [INFRASTRUCTURE.md §9](INFRASTRUCTURE.md#9-cost) and [CONTRIBUTING.md §6](CONTRIBUTING.md#6-cost-management).

**How do I add a staging environment?**
Copy `terraform/environments/dev/` and adjust per the table in [PLAN.md §29.3](PLAN.md#293-environments-dev-staging-prod). Don't parameterize a single environment with conditionals.

**Something failed.**
[INFRASTRUCTURE.md §10](INFRASTRUCTURE.md#10-troubleshooting) has the common causes.
