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

### Retired: the `github_actions_ci` module

The `github_actions_ci` module (the OIDC role CI used to assume) was removed
from configuration — its only consumer was the AWS `aws-verification` CI
job, which no longer exists. See
[docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md](../docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md)
for the reasoning. **This was a configuration-only change; no live AWS
resource was created, modified, or destroyed by that commit** — nothing in
this repository ran `terraform apply`, `terraform destroy`, or any command
that touches a backend or provider.

**What a future `terraform plan`/`apply` against a previously applied `dev`
will show.** Terraform reconciles state against configuration, and
resources present in state but absent from config are proposed for
*destruction* by default — not left alone. If `dev` was ever applied with
this module present, the next plan run against that state will propose
destroying:

- `module.github_actions_ci.aws_iam_role.github_actions_ci` and its inline
  policy — scoped to this repository's CI, safe to destroy once you've
  confirmed nothing else depends on it.
- `module.github_actions_ci.aws_iam_openid_connect_provider.github[0]` —
  **only if** `create_github_oidc_provider`/`create_oidc_provider` was
  `true` when applied (the `dev` environment's default). This resource is
  **not scoped to this repository**: a GitHub Actions OIDC provider
  (`token.actions.githubusercontent.com`) is one-per-AWS-account, so if this
  module created it, any *other* GitHub Actions workflow in the same AWS
  account that assumes a role via OIDC may depend on that same provider
  existing. **Do not destroy it reflexively.** Before applying a plan that
  includes it, check for other consumers first:

  ```powershell
  aws iam list-open-id-connect-providers
  aws iam list-roles --query "Roles[?AssumeRolePolicyDocument.Statement[?Principal.Federated!=null]]"
  ```

  If another role trusts the same provider ARN, do not let this plan
  destroy it — see the preservation options below instead.

**To intentionally retire just this repository's role** (leaving a
shared OIDC provider, if any, untouched), remove only the role from state
before applying, rather than letting a full-module plan run:

```powershell
terraform -chdir=terraform/environments/dev state rm module.github_actions_ci.aws_iam_role.github_actions_ci
terraform -chdir=terraform/environments/dev state rm module.github_actions_ci.aws_iam_role_policy.github_actions_permissions
```

`state rm` removes a resource from Terraform's tracking **without**
touching the real AWS resource — the role keeps existing, unmanaged, until
someone deletes it directly (`aws iam delete-role`) once satisfied nothing
uses it.

**To preserve the whole module's resources** (role and, if present, the
OIDC provider) as Terraform-unmanaged rather than destroying or deleting
anything:

```powershell
terraform -chdir=terraform/environments/dev state rm module.github_actions_ci
```

On Terraform 1.7+, a declarative alternative that leaves a reviewable
record of the removal is a `removed` block (add temporarily, apply once,
then delete):

```hcl
removed {
  from = module.github_actions_ci
  lifecycle {
    destroy = false
  }
}
```

**To let the plan actually destroy the role** (and, only after confirming
no other consumer, the provider), run `terraform plan` first, read it
carefully line by line — confirming which specific resources are proposed
for destruction and re-checking the OIDC-provider sharing question above —
before ever running `apply`. None of this is executed automatically by any
commit to this repository.

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
