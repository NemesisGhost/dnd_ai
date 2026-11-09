# Terraform — optional AWS RDS

Self-hosted Compose is the supported topology. This retained optional RDS configuration
is not required by development or CI. See [INFRASTRUCTURE](../docs/INFRASTRUCTURE.md)
for prerequisites, configuration, deploy/verify/teardown and the legacy OIDC state decision.
Removing old documentation does not decommission cloud resources.

- `modules/database/`: networking, KMS and RDS.
- `modules/secrets/`: named Secrets Manager entries.
- `environments/dev/`: the existing environment configuration.

Review Terraform plans before applying them. Dev configuration explicitly disables
deletion protection and final snapshots; do not infer a live instance's settings from that.
