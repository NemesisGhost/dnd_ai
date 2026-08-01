# Quick Start

The fast path to a deployed development database. Assumes AWS CLI and Terraform are already installed and configured — if not, start with [CONTRIBUTING.md](CONTRIBUTING.md#1-aws-account-setup-start-here).

> **This is now a prerequisite for everyday development, not an occasional side quest.** Per [PLAN.md §23.0](PLAN.md#230-aws-verification-policy), migrations and the `tests/database`/`tests/scenario` suites verify against this deployed `dev` instance, not a local container. If `dev` is already deployed by someone else, skip this document and go straight to [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup).

---

## 1. Configure

```powershell
Copy-Item terraform/environments/dev/terraform.tfvars.example terraform/environments/dev/terraform.tfvars
```

Edit the three values that matter:

```hcl
owner_name           = "your-name"          # tags every resource
my_ip_cidr           = "203.0.113.42/32"    # narrow static baseline only — the default is 0.0.0.0/0
enable_public_access = true                  # required — see PLAN.md §29.9
```

Day-to-day access for yourself and CI is *not* this variable — it's a short-lived security-group rule opened and closed per session via `scripts/aws-db-allow-my-ip.sh` (see [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup)). `my_ip_cidr` just needs to be narrow, not `0.0.0.0/0`.

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

## 5. Connect to the database

### Connection details

Everything except the password comes from Terraform:

```powershell
terraform -chdir=terraform/environments/dev output database_endpoint   # host:port
terraform -chdir=terraform/environments/dev output database_name       # dnd_ai
```

| Field | Value |
|---|---|
| Host | `dnd-ai-dev-db.<hash>.<region>.rds.amazonaws.com` (from `database_endpoint`) |
| Port | `5432` |
| Database | `dnd_ai` — not `dnd_ai_dev` |
| User | `dnd_admin` — not `postgres` |
| SSL | **Required** |

`sslmode=require` is not optional. The parameter group sets `rds.force_ssl=1`, so a
non-SSL connection is rejected outright with a `pg_hba.conf` error that doesn't
mention SSL. A local Docker container has no SSL configured at all, so this is easy
to miss until the first time you connect to something real.

### Get the password

AWS manages the master password; it is never in the repository or in Terraform state.

```powershell
$secretArn = terraform -chdir=terraform/environments/dev output -raw database_secret_name
aws secretsmanager get-secret-value --secret-id $secretArn --query SecretString --output text
```

That returns JSON containing `username` and `password`. Treat it as a credential —
don't paste it into a file that isn't gitignored.

### Pick a client

**A GUI client** (DBeaver, pgAdmin, DataGrip) — enter the four fields above and set
SSL mode to `require`. Usually the most pleasant way to browse schema.

**`psql`**, if you want a terminal. It is not installed by default on Windows:

```powershell
winget install PostgreSQL.PostgreSQL.15

$env:PGPASSWORD = "<password>"
psql -h <endpoint-host> -U dnd_admin -d dnd_ai "sslmode=require"
$env:PGPASSWORD = $null
```

**The project's own environment**, which already has psycopg and SQLAlchemy — no
install needed:

```powershell
uv run python -c "import os; from sqlalchemy import create_engine, text; print(create_engine(os.environ['DATABASE_URL']).connect().execute(text('select code from core.canon_statuses order by sort_order')).fetchall())"
```

For that, and for `alembic`, set `DATABASE_URL`:

```text
postgresql+psycopg://dnd_admin:<password>@<endpoint-host>:5432/dnd_ai?sslmode=require
```

**URL-encode the password.** The AWS-generated one routinely contains characters
(`$`, `>`, `~`, `/`) that change the meaning of a connection URI. In Python:
`urllib.parse.quote(password, safe='')`. Putting `DATABASE_URL` in `.env` (gitignored,
shape documented in `.env.example`) saves rebuilding it each session — both Alembic
and the test suite read it from there.

### Network access

You need an ingress rule for your current IP on the database security group. The
`my_ip_cidr` you set in [§1](#1-configure) creates a baseline one, so immediately
after deploying you are usually already allowed.

ISP-assigned addresses move, though. When yours does, connections **hang rather than
refuse** — the security group drops the packets silently. Open a session rule:

```bash
scripts/aws-db-allow-my-ip.sh open
# ... work ...
scripts/aws-db-allow-my-ip.sh close
```

Two things to know about it. The rule is added outside Terraform, so a later
`terraform plan` reports it as drift and wants to remove it — expected, and explained
in [PLAN.md §29.9](PLAN.md#299-aws-first-verification-mechanism). And it does not touch
the `my_ip_cidr` baseline; if your address has changed for good, update
`terraform.tfvars` rather than accumulating session rules.

### What about IAM authentication?

The five login roles are granted `rds_iam`, so IAM token auth is the intended path for
deployed services ([PLAN.md §30.5](PLAN.md#305-identity-and-secrets)). It does **not**
work from a developer laptop yet: no IAM policy grants a human user `rds-db:connect`.
Master-password auth is the only option today. Note also that `migration_owner` can
never be used to connect — it is `NOLOGIN` by design
([ADR 0009](adr/0009-separate-owning-role-from-login-roles.md)).

## 6. Tear down when finished

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
Right after `terraform apply`, it's an **empty** PostgreSQL instance — no schemas, roles, or extensions. The bootstrap revision that creates them exists in `database/migrations/versions/001_bootstrap.py`; run `alembic upgrade head` against it (see the next question) to actually get there.

**How do I connect?**
See [§5](#5-connect-to-the-database) above — connection details, fetching the password, client options, and the `sslmode=require` requirement. The full output reference is [INFRASTRUCTURE.md §5](INFRASTRUCTURE.md#5-outputs-and-connecting).

**My connection just hangs.**
Almost always the security group: your IP changed and the rule no longer matches, so packets are dropped rather than refused. Run `scripts/aws-db-allow-my-ip.sh open` ([§5](#5-connect-to-the-database)). If it fails immediately instead of hanging with a `pg_hba.conf` error, you're missing `sslmode=require`.

**How do I run migrations against it?**
Open a session-scoped ingress rule for your IP (`scripts/aws-db-allow-my-ip.sh open`), then `uv run alembic -c database/alembic.ini upgrade head` with `DATABASE_URL` pointed at the `dev` endpoint, same as any other environment — see [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup) and [PLAN.md §29.9](PLAN.md#299-aws-first-verification-mechanism). This works because `dev` is deliberately reachable this way; `staging`/`prod` stay private and go through the SSM-based runner in [PLAN.md §29.6](PLAN.md#296-migration-execution-mechanism) instead, which is unbuilt.

**What does it cost?**
~$25–35/month. Breakdown and how to reduce it: [INFRASTRUCTURE.md §9](INFRASTRUCTURE.md#9-cost) and [CONTRIBUTING.md §6](CONTRIBUTING.md#6-cost-management).

**How do I add a staging environment?**
Copy `terraform/environments/dev/` and adjust per the table in [PLAN.md §29.3](PLAN.md#293-environments-dev-staging-prod). Don't parameterize a single environment with conditionals.

**Something failed.**
[INFRASTRUCTURE.md §10](INFRASTRUCTURE.md#10-troubleshooting) has the common causes.
