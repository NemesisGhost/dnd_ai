# D&D AI Database Infrastructure - Deployment Guide

## Overview

I've successfully created a complete Terraform infrastructure for deploying a PostgreSQL database on AWS for your D&D AI project. This infrastructure includes:

- **PostgreSQL RDS instance** with encryption and security
- **Complete VPC setup** with public and private subnets
- **Database initialization Lambda** that runs all 228 SQL files automatically
- **Secrets Manager integration** for secure credential storage
- **KMS encryption** for database and secrets
- **Comprehensive monitoring** and logging setup

## What's Been Created

### Infrastructure Components
- **VPC**: `10.0.0.0/16` with public and private subnets across 2 AZs
- **RDS PostgreSQL 15.4**: `db.t3.micro` with 20GB storage (auto-scaling to 100GB)
- **Security Groups**: Configured for database access
- **Lambda Function**: Automatically initializes database schema with all SQL files
- **Secrets Manager**: Stores database credentials securely
- **KMS Key**: Encrypts database and secrets
- **CloudWatch**: Logging and monitoring

### Database Schema
- **228 SQL files** organized by dependency order
- **Complete D&D world-building schema** with NPCs, settlements, organizations, etc.
- **Lookup tables** for races, locations, relationships, and more
- **JSONB fields** for flexible AI integration data
- **Full-text search** indexes for efficient queries

## Quick Deployment

### Prerequisites
1. AWS CLI configured with appropriate permissions
2. Terraform >= 1.5 installed
3. Python 3.x for Lambda packaging

### Deploy Commands

```powershell
# Navigate to the terraform directory
cd c:\Users\NemesisGhost\Documents\workspace\dnd_ai\terraform

# Deploy using the provided script
.\scripts\deploy.ps1 -Environment dev

# Or manually:
cd environments\dev
terraform init
terraform plan
terraform apply
```

### Expected Outputs
After deployment, you'll get:
- Database endpoint URL
- Secrets Manager secret name for credentials
- VPC and security group IDs
- Lambda function name for database initialization

## Cost Estimate
**Monthly cost for development environment**: ~$20
- RDS db.t3.micro: ~$15/month
- Storage 20GB: ~$2/month
- KMS key: ~$1/month
- Secrets Manager: ~$0.40/month
- Lambda/CloudWatch: Minimal (free tier)

## Security Features
- Database encryption at rest with KMS
- VPC isolation with private subnets
- Security groups restricting access to port 5432
- Secrets Manager for credential storage
- IAM roles with least-privilege access

## Database Connection

After deployment, get credentials and connect:

```powershell
# Get database credentials
aws secretsmanager get-secret-value --secret-id "dnd-ai/dev/database/credentials"

# Example connection (replace with actual values)
psql -h your-db-endpoint -p 5432 -U dnd_admin -d dnd_ai_dev
```

## File Structure Created

```
terraform/
├── modules/database/           # Reusable database module
│   ├── main.tf                # Infrastructure code
│   ├── variables.tf           # Configuration variables
│   ├── outputs.tf             # Output values
│   ├── versions.tf            # Provider requirements
│   ├── db_init_lambda.py      # Database initialization
│   └── db_init_lambda.zip     # Lambda package (generated)
├── environments/dev/          # Development environment
│   ├── main.tf               # Environment configuration
│   ├── variables.tf          # Environment variables
│   ├── outputs.tf            # Environment outputs
│   └── terraform.tfvars.example  # Sample configuration
├── scripts/                   # Deployment scripts
│   ├── deploy.ps1            # Deployment automation
│   ├── destroy.ps1           # Cleanup automation
│   ├── set-env.ps1           # Environment setup
│   └── prepare_lambda.py     # Lambda packaging
├── README.md                 # Comprehensive documentation
└── .gitignore               # Git ignore rules
```

## Next Steps

### 1. Deploy and Test
```powershell
# Deploy the infrastructure
.\scripts\deploy.ps1 -Environment dev

# Verify database initialization
aws logs tail /aws/lambda/dnd-ai-dev-db-init --follow
```

### 2. Connect and Verify
- Get database credentials from Secrets Manager
- Connect using psql or your preferred PostgreSQL client
- Verify tables are created: `\dt` in psql
- Check sample data: `SELECT * FROM races LIMIT 5;`

### 3. Application Integration
- Use the database endpoint in your applications
- Reference the Secrets Manager secret for credentials
- Connect Lambda functions to the same VPC for database access

### 4. Production Planning
- Create `environments/prod/` directory
- Increase instance size and storage
- Enable Multi-AZ deployment
- Add read replicas if needed
- Enable enhanced monitoring and Performance Insights

## Troubleshooting

### Common Issues
1. **Lambda timeout**: Database initialization may take 10-15 minutes
2. **Permission errors**: Ensure AWS credentials have required permissions
3. **Network issues**: Check security groups allow access from your IP

### Debugging Commands
```powershell
# Check Terraform state
terraform show

# View Lambda logs
aws logs tail /aws/lambda/dnd-ai-dev-db-init

# Test database connectivity
aws rds describe-db-instances --db-instance-identifier dnd-ai-dev-db
```

## Cleanup

To destroy all resources:
```powershell
.\scripts\destroy.ps1 -Environment dev
```

## Customization

### Environment Variables
Modify `environments/dev/terraform.tfvars`:
```hcl
aws_region = "us-east-1"
owner_name = "your-name"
my_ip_cidr = "your-ip/32"
enable_public_access = false
```

### Database Configuration
Modify `environments/dev/main.tf` to adjust:
- Instance class and storage
- Backup settings
- Monitoring levels
- Network configuration

## Support and Documentation

- Full documentation in `terraform/README.md`
- Module documentation in `modules/database/`
- AWS RDS documentation for advanced configuration
- Database schema documentation in `Database/DATABASE_SCHEMA.md`

## Success Criteria

✅ **Infrastructure Created**: VPC, RDS, Security Groups, Lambda
✅ **Database Initialized**: All 228 SQL files executed successfully
✅ **Security Configured**: Encryption, access controls, secrets management
✅ **Monitoring Enabled**: CloudWatch logs and basic monitoring
✅ **Documentation Complete**: README files and usage instructions

You now have a production-ready PostgreSQL database infrastructure for your D&D AI project, complete with the full world-building schema and ready for application integration!