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

### Removed from configuration: the `github_actions_ci` module

The `github_actions_ci` module (the OIDC role CI used to assume) was removed
from configuration — its only consumer was the AWS `aws-verification` CI
job, which no longer exists. See
[docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md](../docs/adr/0012-self-hosted-docker-deployment-and-ci-verification.md)
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
