# Database Deployment Verification Checklist

## Overview
This guide verifies the current D&D AI infrastructure: Terraform-driven RDS deployment, Secrets Manager, and the SSM-based DB runner that applies SQL from S3. It reflects the latest state: no Lambda-based DB init and no Terraform-managed DB secret values.

## Prerequisites

### Required tools
- [ ] Terraform v1.5+ installed
- [ ] AWS CLI v2.0+ installed and configured
- [ ] jq (for parsing JSON in CLI examples)
- [ ] psql client (optional, for manual testing)

### Required AWS permissions
- [ ] RDS instance creation and management
- [ ] VPC, subnet, and security group management
- [ ] Secrets Manager read/write access (PutSecretValue, GetSecretValue)
- [ ] KMS key creation and usage (Encrypt/Decrypt)
- [ ] SSM send-command permissions and EC2 basic access
- [ ] CloudWatch logs access

Example IAM policy snippets for a compute role (EC2/SSM runner or Lambda) to read secrets and decrypt:

Secrets Manager access (scoped to your project secrets):

```json
{
     "Version": "2012-10-17",
     "Statement": [
          {
               "Effect": "Allow",
               "Action": [
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret"
               ],
               "Resource": [
                    "arn:aws:secretsmanager:REGION:ACCOUNT_ID:secret:dnd-ai/*"
               ]
          }
     ]
}
```

KMS decrypt on your Secrets KMS key (replace with your key ARN):

```json
{
     "Version": "2012-10-17",
     "Statement": [
          {
               "Effect": "Allow",
               "Action": [
                    "kms:Decrypt"
               ],
               "Resource": "arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID"
          }
     ]
}
```

## Deployment steps

### 1) Pre-deployment validation

PowerShell (Windows):
```powershell
terraform -chdir="./terraform/environments/dev" init
terraform -chdir="./terraform/environments/dev" validate
terraform -chdir="./terraform/environments/dev" fmt -recursive
```

Expected output:
- ✅ "Terraform has been successfully initialized!"
- ✅ "Success! The configuration is valid."

Check variables in `terraform/environments/dev/terraform.tfvars`:
- [ ] `my_ip_cidr` matches your IP (avoid 0.0.0.0/0 unless necessary in dev)
- [ ] `owner_name` is set
- [ ] `aws_region` is correct

### 2) Plan and apply

Use the root build script (recommended):
```powershell
./build.ps1 -Environment dev -Action apply -AutoApprove
```

Or run manually:
```powershell
terraform -chdir="./terraform/environments/dev" plan -out tfplan
terraform -chdir="./terraform/environments/dev" apply tfplan
```

Expected resources:
- [ ] VPC with private (and public if created) subnets
- [ ] RDS PostgreSQL instance (default db.t3.micro)
- [ ] Security group for PostgreSQL
- [ ] KMS key for encryption
- [ ] Secrets Manager secrets (names/metadata for OpenAI/Discord)
- [ ] SSM Document and EC2 runner for DB schema application

Estimated dev cost: ~$20/month (see README for breakdown)

### 3) Upsert secrets (local → AWS)

Secrets values are not in Terraform. Create and upsert from a local JSON file:
```powershell
# Use the example file and fill in your values
Copy-Item ./terraform/environments/dev/secrets.local.json.example ./terraform/environments/dev/secrets.local.json

# Upsert to AWS Secrets Manager
./terraform/scripts/upsert-secrets.ps1 -Environment dev -Region us-east-1 -File ./terraform/environments/dev/secrets.local.json
```

### 4) Check Terraform outputs

```powershell
terraform -chdir="./terraform/environments/dev" output
```

Expected outputs include:
- [ ] `database_endpoint`
- [ ] `database_port`
- [ ] `database_name`
- [ ] `rds_master_user_secret_arn`
- [ ] `vpc_id`
- [ ] `runner_instance_id`, `runner_sg_id`, `sql_bucket_name`

### 5) Verify RDS instance status

```powershell
aws rds describe-db-instances --db-instance-identifier dnd-ai-dev-db
```

Check:
- [ ] `DBInstanceStatus` is `available`
- [ ] `Engine` is `postgres`
- [ ] Version matches module default (e.g., 15.x)

### 6) Trigger the DB runner to apply schema

The module automatically syncs `Database/` SQL and sends an SSM command when content changes. To trigger manually:
```powershell
# Re-sync SQL and trigger command (from local-exec behavior) — re-run apply if needed
terraform -chdir="./terraform/environments/dev" apply -auto-approve

# Or send SSM command directly to the runner instance by tag (Role=db-runner-...)
# See the created SSM document name:
terraform -chdir="./terraform/environments/dev" output apply_postgres_sql_document
```

Look for successful execution in the SSM command result and/or instance logs. The document retrieves the DB secret at runtime and runs psql for each file in `Database/order.txt`.

### 7) Manual database connection test

Fetch the AWS-managed password and connect:
```powershell
$secretArn = (terraform -chdir="./terraform/environments/dev" output -raw rds_master_user_secret_arn)
$pw = aws secretsmanager get-secret-value --secret-id $secretArn --query SecretString --output text | jq -r .password

psql -h (terraform -chdir="./terraform/environments/dev" output -raw database_endpoint) `
     -p (terraform -chdir="./terraform/environments/dev" output -raw database_port) `
     -U (terraform -chdir="./terraform/environments/dev" output -raw database_username) `
     -d (terraform -chdir="./terraform/environments/dev" output -raw database_name) \
     -w
```

Sample queries:
```sql
-- Version and tables
SELECT version();
\dt public.*

-- Sample data checks (adjust to available lookups)
SELECT name FROM public.tag_categories LIMIT 5;
SELECT name FROM public.races LIMIT 5;
```

## Troubleshooting

### RDS not accessible
- Ensure the database SG allows your IP or your app SG.
- Verify RDS status is `available` and subnet routes are correct.

### Secrets access issues
- Confirm IAM permissions for Secrets Manager and KMS decrypt on the key used.
- Ensure the secret ARN is correct and exists in your account/region.

### DB runner didn’t apply SQL
- Check SSM command history and the runner instance system logs.
- Ensure S3 sync completed and `Database/order.txt` is present.
- Re-run `terraform apply` in dev to force the null_resource to trigger when hashes change.

### SQL errors
- Validate SQL ordering in `Database/order.txt`.
- Test a single file manually with `psql --set=ON_ERROR_STOP=1`.

## Success criteria

- [ ] Terraform resources created without errors
- [ ] RDS instance running and reachable
- [ ] RDS master user secret retrievable and valid
- [ ] DB runner applied schema without failures
- [ ] Expected core tables exist and basic queries succeed

## Cost management

Development environment costs (rough estimates):
- RDS db.t3.micro: ~$12–15/month
- Storage (20GB): ~$2–3/month
- KMS key: ~$1/month
- Secrets Manager: ~$0.40/month
- EC2 runner + minimal traffic: low

Important: Run `terraform destroy` when not developing to avoid ongoing costs.

## Next steps

1. Document any local changes and environment settings
2. Create sample data for testing
3. Set up monitoring/alerts
4. Configure automated backups
5. Plan staging environment deployment
6. Begin application development and integration