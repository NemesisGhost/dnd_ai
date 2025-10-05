# D&D AI Terraform Infrastructure

This directory contains the Terraform infrastructure code for the D&D AI project, focusing on the PostgreSQL database deployment on AWS.

## Project Structure

```
terraform/
├── modules/
│   ├── database/                 # RDS, networking, KMS
│   ├── db_runner/                # SSM-based SQL runner (S3 sync + psql)
│   └── secrets/                  # Secrets metadata (no values)
├── environments/
│   └── dev/                      # Development environment
│       ├── main.tf               # Environment-specific configuration
│       ├── variables.tf          # Environment variables
│       └── outputs.tf            # Environment outputs
└── scripts/
  └── upsert-secrets.ps1        # Upsert local secrets to AWS Secrets Manager
```

## Features

### Database Module (`modules/database/`)

- **RDS PostgreSQL** instance with encryption at rest
- **VPC and networking** setup (can use existing or create new)
- **Security groups** with configurable access rules
- **Secrets Manager** integration for credential storage (values populated post-deploy)
- **KMS encryption** for database and secrets
- **Database initialization** via SSM-based DB runner (no Lambda)
- **Monitoring and logging** with CloudWatch
- **Backup and maintenance** scheduling
- **Parameter groups** for PostgreSQL optimization

### Development Environment (`environments/dev/`)

- Configured for cost-effective development usage
- Small instance sizes (db.t3.micro)
- Minimal backup retention
- Optional public access for development
- Automatic database schema initialization

## Prerequisites

1. **AWS CLI** configured with appropriate credentials
2. **Terraform** >= 1.5 installed
3. **PowerShell** (Windows) for the root build script (or use Terraform manually)
4. **AWS IAM permissions** for:
   - RDS instance management
   - VPC and networking
   - Secrets Manager
   - KMS key management
  - SSM Run Command and EC2
  - IAM role creation

## Quick Start

### 1. Set Your IP Address (Optional)

If you want to connect to the database from your local machine:

```powershell
# The script will automatically detect your IP, or set manually:
$env:TF_VAR_my_ip_cidr = "YOUR_IP_ADDRESS/32"
```

### 2. Deploy Development Environment

Preferred (root build script):

```powershell
./build.ps1 -Environment dev -Action apply -AutoApprove
```

Manual alternative:

```powershell
terraform -chdir="./terraform/environments/dev" init
terraform -chdir="./terraform/environments/dev" plan -out tfplan
terraform -chdir="./terraform/environments/dev" apply tfplan
```

### 3. Connect to Database

After deployment, get connection details:

```powershell
# Get outputs
terraform output

# Use the provided connection command, or get credentials manually:
aws secretsmanager get-secret-value --secret-id dnd-ai/dev/database/credentials
```

### 4. Verify Database Initialization

Schema application is handled by the SSM-based DB runner. Re-run apply to trigger when SQL changes. See `docs/terraform/VERIFICATION_GUIDE.md` for end-to-end checks, connection tests, and how to find the SSM Document and command results.

## Configuration

### Environment Variables

Set these before deployment:

```powershell
$env:TF_VAR_owner_name = "your-name"          # Resource owner tag
$env:TF_VAR_aws_region = "us-east-1"          # AWS region
$env:TF_VAR_my_ip_cidr = "203.0.113.0/32"     # Your IP for DB access
$env:TF_VAR_enable_public_access = $false     # Public DB access (dev only)
```

### Database Configuration

Modify `environments/dev/main.tf` to adjust:

- Instance class and storage
- Backup and maintenance windows
- Monitoring and logging levels
- Network configuration
- Security settings

## Database Schema

The database initialization includes:

- **228 SQL files** with complete D&D world-building schema
- **Lookup tables** for races, locations, relationships, etc.
- **Core entities**: NPCs, businesses, organizations, settlements, nations
- **Relationship tables** for complex entity associations
- **JSONB fields** for flexible data storage
- **Full-text search** indexes for names and descriptions
- **Triggers** for automatic timestamp updates

### Execution Order

The Lambda function executes SQL files in dependency order:

1. **Lookup tables** (no dependencies)
2. **Core shared entities** (tags, resources, services)
3. **Geographic entities** (locations, nations)
4. **Settlements and religions**
5. **Business and NPC entities**
6. **Detail and relationship tables**

## Cost Considerations

### Development Environment

- **RDS**: db.t3.micro (~$15/month)
- **Storage**: 20GB GP3 (~$2/month)
- **KMS**: ~$1/month
- **Secrets Manager**: ~$0.40/month
- **CloudWatch/SSM**: Minimal logs

**Total estimated cost**: ~$20/month for development

### Production Considerations

For production deployment:

- Use larger instance classes (db.t3.medium or higher)
- Enable enhanced monitoring and Performance Insights
- Use Multi-AZ deployment for high availability
- Increase backup retention period
- Enable deletion protection
- Use read replicas if needed

## Security Features

- **Encryption at rest** using AWS KMS
- **VPC isolation** with private subnets
- **Security groups** with least-privilege access
- **Secrets Manager** for credential storage
- **IAM roles** with minimal permissions
- **CloudTrail integration** for audit logging

## Monitoring and Maintenance

- **CloudWatch logs** for database/runner
- **Performance Insights** (configurable)
- **Enhanced monitoring** (configurable)
- **Automated backups** with configurable retention
- **Maintenance windows** for minimal disruption
- **Parameter groups** for performance tuning

## Customization

### Using Existing VPC

To deploy into an existing VPC:

```hcl
module "database" {
  source = "../../modules/database"
  
  vpc_id = "vpc-12345678"
  private_subnet_cidrs = ["10.0.10.0/24", "10.0.11.0/24"]
  allowed_security_group_ids = ["sg-12345678"]
  
  # ... other configuration
}
```

### Adding Environments

Create new environment directories:

```
environments/
├── dev/
├── staging/        # Copy from dev and modify
└── prod/           # Production configuration
```

### Extending the Database Module

The module is designed for reusability. You can:

- Add additional RDS instances (read replicas)
- Integrate with other AWS services
- Add custom monitoring and alerting
- Implement automated backups to S3

## Troubleshooting

### Common Issues

1. **Runner issues**: Check SSM command history and runner instance logs
2. **Network connectivity**: Check security groups and VPC configuration
3. **Permission errors**: Verify IAM roles and policies (Secrets/KMS)
4. **SQL errors**: Validate SQL ordering; test individual files with psql

### Debugging

```powershell
# View Terraform plan
terraform -chdir="./terraform/environments/dev" plan

# Check AWS resources
aws rds describe-db-instances
aws secretsmanager list-secrets
aws ssm list-documents --filters Key=Name,Values="dnd-ai-*apply-postgres-sql*"
```

## Cleanup

To destroy all resources:

```powershell
./build.ps1 -Environment dev -Action destroy -AutoApprove
```

**Warning**: This will permanently delete the database and all data. Ensure you have backups if needed.

## Next Steps

After successful database deployment:

1. **Test connectivity** and verify schema initialization
2. **Add application servers** and Lambda functions
3. **Implement Discord bot** integration
4. **Set up API Gateway** for external access
5. **Configure monitoring** and alerting
6. **Plan production** deployment strategy

## Support

For issues with this infrastructure:

1. Check CloudWatch logs for detailed error messages
2. Verify AWS permissions and quotas
3. Review Terraform state for resource conflicts
4. Consult AWS documentation for service-specific issues