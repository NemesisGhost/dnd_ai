# Pre-Deployment Checklist

Run through this before `terraform apply`. Explanations live elsewhere — this file is deliberately just the checks.

- Setting up for the first time? [CONTRIBUTING.md](CONTRIBUTING.md)
- Want the commands? [QUICKSTART.md](QUICKSTART.md)
- Want the reference? [INFRASTRUCTURE.md](INFRASTRUCTURE.md)

---

## Before you start

- [ ] You actually need this. Everyday development runs against a **local PostgreSQL 18 server** ([DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup)); this deploys the shared AWS environment CI verifies against ([PLAN.md §23.0](PLAN.md#230-verification-policy))
- [ ] This is a one-time deploy of shared, always-on infrastructure — confirm `dev` isn't already deployed by someone else first (`terraform -chdir=terraform/environments/dev output`)
- [ ] You accept ~$25–35/month as an ongoing cost, not a per-session toggle ([CONTRIBUTING.md §6](CONTRIBUTING.md#6-cost-management))

## Tooling

- [ ] `aws --version` reports v2
- [ ] `terraform version` reports >= 1.5
- [ ] `aws sts get-caller-identity` returns the expected account
- [ ] That identity has the permissions in [INFRASTRUCTURE.md §2.2](INFRASTRUCTURE.md#22-required-iam-permissions)

## Configuration

- [ ] `terraform/environments/dev/terraform.tfvars` exists (copied from `.example`)
- [ ] `owner_name` set — it tags every resource
- [ ] `my_ip_cidr` is a narrow static baseline (e.g. your address in `X.X.X.X/32` form), not the `0.0.0.0/0` default — day-to-day access is per-session via `scripts/aws-db-allow-my-ip.sh`, not this variable ([PLAN.md §29.9](PLAN.md#299-shared-dev-verification-mechanism-ci))
- [ ] `enable_public_access` is `true` — required, not optional, for the AWS-verification workflow
- [ ] `aws_region` matches your configured CLI region
- [ ] VPC approach decided: default VPC (simplest), module-created, or existing via `vpc_id` + `private_subnet_ids`

## Secrets (optional)

- [ ] `secrets.local.json` created from `.example`, if using OpenAI or Discord
- [ ] Real values filled in — no placeholders

## Not committed

- [ ] `git status` shows no `terraform.tfvars`, `secrets.local.json`, `*.tfstate`, `tfplan`, or `.terraform/`
- [ ] No credential, IP, or account ID in any file you are about to commit

## Plan review

- [ ] `terraform validate` passes
- [ ] `terraform plan` reviewed line by line
- [ ] Resource count looks right (~20 for a fresh dev apply)
- [ ] Nothing you expected to change in place is marked **destroy/replace** — on `aws_db_instance` that means data loss
- [ ] No unexpected deletions

---

## After deployment

- [ ] `terraform output` returns endpoint, port, and secret ARN
- [ ] `aws rds describe-db-instances --db-instance-identifier dnd-ai-dev-db` shows `available`
- [ ] Secrets populated, if you created `secrets.local.json`
- [ ] Outputs recorded wherever you need them for application config
- [ ] You understand the database is **empty** — no schemas, roles, or extensions until the bootstrap revision exists ([PLAN.md §29.5](PLAN.md#295-database-role-schema-and-extension-bootstrap))

Full verification: [INFRASTRUCTURE.md §7](INFRASTRUCTURE.md#7-verification).

## If it goes wrong

Common failures and causes: [INFRASTRUCTURE.md §10](INFRASTRUCTURE.md#10-troubleshooting).

To roll back, disable deletion protection first — `terraform destroy` alone **will fail**, because the module defaults `deletion_protection` to `true` and the dev environment does not override it:

```powershell
aws rds modify-db-instance --db-instance-identifier dnd-ai-dev-db --no-deletion-protection --apply-immediately
./build.ps1 -Environment dev -Action destroy -AutoApprove
```

Targeted teardown: `terraform -chdir=terraform/environments/dev destroy -target=module.database`.
