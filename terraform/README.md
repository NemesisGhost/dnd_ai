# Terraform

**Optional, legacy AWS infrastructure.** Self-hosted Docker Compose (see the
repository root [`compose.yaml`](../compose.yaml)) is the officially
supported deployment topology, and CI no longer uses any of this — see
[docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md](../docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md).
This code is retained, undeleted and unrun, for anyone who chooses to host
the database on AWS RDS instead; it is not required for development, CI, or
ordinary contribution.

```text
modules/
├── database/     # VPC/subnets, security group, KMS key, RDS PostgreSQL, VPC endpoints
└── secrets/      # Named (value-less) Secrets Manager entries
environments/
└── dev/          # The only environment that exists today
scripts/
└── upsert-secrets.ps1
```

The `github_actions_ci` module (the OIDC role CI used to assume) was removed
— its only consumer was the AWS `aws-verification` CI job, which no longer
exists. A previously applied `dev` may still have that role deployed; this
change only removed it from configuration; nothing live was destroyed. See
[docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md](../docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md)
for the reasoning, and destroy it deliberately (`terraform destroy
-target=module.github_actions_ci`) when convenient — not automatically.

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
