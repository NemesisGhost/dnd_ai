# Database Deployment Verification Checklist

## Overview
This document provides a step-by-step verification process for the D&D AI database deployment using Terraform and SQL script execution.

## Prerequisites

### Required Tools
- [ ] Terraform v1.5+ installed
- [ ] AWS CLI v2.0+ installed and configured
- [ ] Python 3.8+ (for validation scripts)
- [ ] psql client (optional, for manual testing)

### Required AWS Permissions
- [ ] RDS instance creation and management
- [ ] VPC, subnet, and security group management
- [ ] Secrets Manager read/write access
- [ ] Lambda function creation and execution
- [ ] KMS key creation and usage
- [ ] CloudWatch logs access

### Required Python Packages (for validation)
```bash
pip install boto3 psycopg2-binary
```

## Deployment Steps

### 1. Pre-deployment Validation

#### Check Terraform Configuration
```bash
cd terraform/environments/dev
terraform init
terraform validate
terraform fmt -recursive
```

Expected output:
- ✅ "Terraform has been successfully initialized!"
- ✅ "Success! The configuration is valid."

#### Review Variables
```bash
cat terraform.tfvars
```

Verify:
- [ ] `my_ip_cidr` is set to your actual IP address (not 0.0.0.0/0)
- [ ] `owner_name` is set to your name
- [ ] `aws_region` is correct for your deployment

### 2. Generate Deployment Plan

```bash
terraform plan -out=tfplan
```

Expected resources to be created:
- [ ] 1 VPC with public and private subnets
- [ ] 1 RDS PostgreSQL instance (db.t3.micro)
- [ ] 1 Security group with PostgreSQL access
- [ ] 1 KMS key for encryption
- [ ] 1 Secrets Manager secret
- [ ] 1 Lambda function for database initialization
- [ ] Various IAM roles and policies

Estimated cost: ~$15-20/month for development

### 3. Deploy Infrastructure

```bash
terraform apply "tfplan"
```

Monitor the deployment progress:
- [ ] VPC and subnets created (~2 minutes)
- [ ] RDS instance creation started (~15-20 minutes)
- [ ] Lambda function deployed
- [ ] Secrets Manager secret created

### 4. Post-deployment Verification

#### Check Terraform Outputs
```bash
terraform output
```

Expected outputs:
- [ ] `database_endpoint` - RDS endpoint URL
- [ ] `database_port` - 5432
- [ ] `database_name` - "dnd_ai_dev"
- [ ] `secrets_manager_secret_name` - Secret name for credentials
- [ ] `vpc_id` - VPC ID where resources are deployed

#### Verify RDS Instance Status
```bash
aws rds describe-db-instances --db-instance-identifier dnd-ai-dev-db
```

Check that:
- [ ] `DBInstanceStatus` is "available"
- [ ] `Engine` is "postgres"
- [ ] `EngineVersion` is "15.4"

#### Check Lambda Function
```bash
aws lambda get-function --function-name dnd-ai-dev-db-init
```

Verify:
- [ ] Function exists
- [ ] Runtime is "python3.11"
- [ ] State is "Active"

### 5. Database Schema Validation

#### Run Automated Validation
```bash
cd terraform/scripts
python validate_database.py dnd-ai/dev/database/credentials
```

Expected validation results:
- [ ] ✅ Database connection successful
- [ ] ✅ update_timestamp() function exists
- [ ] ✅ All lookup tables have data
- [ ] ✅ Core entity tables exist
- [ ] ✅ Foreign key relationships established
- [ ] ✅ Database indexes created
- [ ] ✅ Update triggers configured

#### Manual Database Connection Test
```bash
# Get database password from Secrets Manager
aws secretsmanager get-secret-value \
  --secret-id "dnd-ai/dev/database/credentials" \
  --query SecretString --output text | jq -r .password

# Connect with psql (replace with actual endpoint and password)
PGPASSWORD="<password>" psql \
  -h <rds-endpoint> \
  -p 5432 \
  -U dnd_admin \
  -d dnd_ai_dev
```

Test queries:
```sql
-- Check database version
SELECT version();

-- Verify tables exist
\dt public.*

-- Check sample data
SELECT name FROM public.tag_categories;
SELECT name FROM public.races LIMIT 5;

-- Test relationships
SELECT n.name, r.name as race 
FROM public.npcs n 
JOIN public.races r ON n.race_id = r.race_id 
LIMIT 5;
```

### 6. Lambda Function Testing

#### Invoke Database Initialization Function
```bash
aws lambda invoke \
  --function-name dnd-ai-dev-db-init \
  --payload '{}' \
  response.json

cat response.json
```

Expected response:
```json
{
  "statusCode": 200,
  "body": "{\"message\": \"Database initialization completed\", \"executed_files\": 20, \"total_files\": 20, \"failed_files\": [], \"status\": \"success\"}"
}
```

#### Check Lambda Logs
```bash
aws logs describe-log-groups --log-group-name-prefix "/aws/lambda/dnd-ai-dev-db-init"

aws logs get-log-events \
  --log-group-name "/aws/lambda/dnd-ai-dev-db-init" \
  --log-stream-name "$(aws logs describe-log-streams \
    --log-group-name "/aws/lambda/dnd-ai-dev-db-init" \
    --order-by LastEventTime --descending \
    --max-items 1 --query 'logStreams[0].logStreamName' --output text)"
```

Look for:
- [ ] "Connected to database successfully"
- [ ] "Successfully executed" messages for each SQL file
- [ ] No error messages or failed files

## Troubleshooting

### Common Issues

#### RDS Instance Not Accessible
**Problem**: Cannot connect to database
**Solutions**:
- Check security group allows access from your IP
- Verify RDS instance is in "available" state
- Confirm VPC and subnet configuration

#### Lambda Function Timeout
**Problem**: Database initialization takes too long
**Solutions**:
- Check Lambda timeout setting (should be 900 seconds)
- Verify Lambda has VPC access to RDS
- Check CloudWatch logs for specific errors

#### SQL Script Execution Errors
**Problem**: Some tables not created
**Solutions**:
- Check dependency order in Lambda function
- Verify all required lookup tables exist
- Review Lambda execution logs for SQL errors

#### Permission Errors
**Problem**: Access denied errors
**Solutions**:
- Verify IAM roles have necessary permissions
- Check KMS key permissions for encryption
- Confirm Secrets Manager access

### Recovery Commands

#### Redeploy Lambda Function
```bash
cd terraform/modules/database
python build_lambda.py
cd ../../environments/dev
terraform apply -target=module.database.aws_lambda_function.db_init
```

#### Force Database Recreation
```bash
terraform taint module.database.aws_db_instance.main
terraform apply
```

#### Clean Up (Destroy Everything)
```bash
terraform destroy
```

## Success Criteria

The deployment is successful when:
- [ ] All Terraform resources created without errors
- [ ] RDS instance is running and accessible
- [ ] Database schema validation passes all tests
- [ ] Lambda function executes successfully
- [ ] All expected tables and relationships exist
- [ ] Sample queries return expected results

## Cost Management

Development environment costs:
- **RDS db.t3.micro**: ~$12-15/month
- **Storage (20GB)**: ~$2.30/month  
- **KMS key**: $1/month
- **Secrets Manager**: ~$0.40/month
- **Lambda/VPC**: Minimal

**Important**: Run `terraform destroy` when not actively developing to avoid ongoing costs.

## Next Steps

After successful verification:
1. Document any customizations made
2. Create sample data for testing
3. Set up monitoring and alerting
4. Configure automated backups
5. Plan staging environment deployment
6. Begin application development and testing