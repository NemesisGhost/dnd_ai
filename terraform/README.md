# Terraform

Infrastructure code for the D&D AI World Platform.

```text
modules/
├── database/     # VPC/subnets, security group, KMS key, RDS PostgreSQL, VPC endpoints
└── secrets/      # Named (value-less) Secrets Manager entries
environments/
└── dev/          # The only environment that exists today
scripts/
└── upsert-secrets.ps1
```

**Documentation lives under [`docs/`](../docs/), not here:**

- [docs/CONTRIBUTING.md](../docs/CONTRIBUTING.md) — first-time setup: tools, AWS credentials, scoped IAM policy
- [docs/QUICKSTART.md](../docs/QUICKSTART.md) — the deployment path, step by step
- [docs/CHECKLIST.md](../docs/CHECKLIST.md) — pre-flight checks before applying
- [docs/INFRASTRUCTURE.md](../docs/INFRASTRUCTURE.md) — reference: variables, outputs, secrets, verification, teardown, known gaps
- [docs/PLAN.md §29](../docs/PLAN.md#29-aws-terraform-deployment-plan-for-postgresql) — the authoritative plan: remote state, staging/prod, database bootstrap, Alembic migration runner

Quick start, from the repository root:

```powershell
Copy-Item terraform/environments/dev/terraform.tfvars.example terraform/environments/dev/terraform.tfvars
# edit terraform.tfvars — set owner_name and my_ip_cidr
./build.ps1 -Environment dev -Action plan
```

`dev` overrides `deletion_protection = false` and `skip_final_snapshot = true` explicitly in `terraform/environments/dev/main.tf` (per [docs/PLAN.md §29.3](../docs/PLAN.md#293-environments-dev-staging-prod)), so `terraform destroy` works directly — no extra step needed. Details: [docs/INFRASTRUCTURE.md §11](../docs/INFRASTRUCTURE.md#11-known-gaps-and-discrepancies) gap 1 (resolved) and [§8](../docs/INFRASTRUCTURE.md#8-teardown).
