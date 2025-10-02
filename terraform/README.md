# D&D AI Terraform Infrastructure

This directory contains the Infrastructure as Code (IaC) for the D&D AI project, organized into modular components for better maintainability and reusability.

## 🎯 Key Changes Made

### ✅ Removed Database Initialization Lambda
- Database schema deployment now handled separately via SQL migration scripts
- Eliminates complex Lambda packaging and dependency management
- Simpler, more maintainable approach for database setup

### ✅ Modular Component Architecture
- **Database Module**: PostgreSQL RDS with networking and security
- **Lambda Module**: AI query handlers and Discord bot functions  
- **Secrets Module**: Secure API key and configuration management

### ✅ Secure Configuration Management
- `secrets.tfvars.example` template for sensitive variables
- All API keys stored in AWS Secrets Manager with KMS encryption
- No sensitive data committed to Git

## 📁 Directory Structure

```
terraform/
├── modules/                    # Reusable Terraform modules
│   ├── database/              # PostgreSQL RDS with networking and security
│   │   ├── main.tf           # Module entry point and documentation
│   │   ├── networking.tf     # VPC, subnets, security groups, endpoints
│   │   ├── rds.tf           # RDS instance and parameter groups
│   │   ├── secrets.tf       # KMS encryption and database credentials
│   │   ├── variables.tf     # Module input variables
│   │   ├── outputs.tf       # Module outputs
│   │   └── versions.tf      # Terraform version constraints
│   ├── lambda/               # Lambda functions for AI and Discord bot
│   │   ├── main.tf          # Lambda functions and IAM roles
│   │   ├── variables.tf     # Module input variables
│   │   ├── outputs.tf       # Module outputs
│   │   └── versions.tf      # Terraform version constraints
│   └── secrets/              # API keys and sensitive configuration
│       ├── main.tf          # Secrets Manager resources
│       ├── variables.tf     # Module input variables
│       ├── outputs.tf       # Module outputs
│       └── versions.tf      # Terraform version constraints
└── environments/             # Environment-specific configurations
    └── dev/                 # Development environment
        ├── main.tf         # Environment configuration
        ├── variables.tf    # Environment variables
        ├── outputs.tf      # Environment outputs
        └── secrets.tfvars.example  # Template for sensitive variables
```

## 🚀 Quick Start

### 1. Setup Your Secure Configuration
```bash
cd environments/dev
cp secrets.tfvars.example secrets.tfvars
```

### 2. Configure Your Credentials
Edit `secrets.tfvars` with your actual values:
```hcl
# AWS Configuration
aws_region = "us-east-1"
my_ip_cidr = "YOUR.IP.ADDRESS.HERE/32"  # Replace with your actual IP

# OpenAI Configuration (required for AI features)
openai_api_key = "sk-your-actual-openai-api-key"
openai_model = "gpt-4"

# Discord Bot Configuration (required for Discord integration)
discord_bot_token = "your-discord-bot-token"
discord_application_id = "your-application-id"
discord_public_key = "your-application-public-key"

# Additional settings...
```

### 3. Deploy Infrastructure
```bash
# Initialize Terraform
terraform init

# Review the deployment plan
terraform plan -var-file="secrets.tfvars"

# Deploy the infrastructure
terraform apply -var-file="secrets.tfvars"
```

### 4. Access Your Resources
```bash
# View all deployment outputs
terraform output

# Get database connection command
terraform output -raw connection_command
```

## 🔧 Component Details

### Database Module (`modules/database/`)
- **PostgreSQL 15.14** with automatic backups and encryption
- **VPC networking** with public/private subnets across 2 AZs
- **Security groups** with least privilege access
- **KMS encryption** for data at rest
- **Secrets Manager** for credential storage
- **VPC endpoints** for cost-effective AWS service access

### Lambda Module (`modules/lambda/`)
- **Discord Bot Handler** for processing slash commands
- **AI Query Handler** for ChatGPT integration
- **VPC configuration** for secure database access
- **IAM roles** with minimal required permissions

### Secrets Module (`modules/secrets/`)
- **OpenAI API keys** with organization settings
- **Discord bot tokens** and application configuration
- **Application settings** for environment-specific configuration
- **KMS encryption** for all secrets

## 🔒 Security Features

### Secrets Management
- ✅ All sensitive data in AWS Secrets Manager
- ✅ KMS encryption for secrets and database
- ✅ No hardcoded credentials in Terraform code
- ✅ Git-ignored configuration files

### Network Security
- ✅ Database in private subnets only
- ✅ Security groups with minimal required access
- ✅ VPC endpoints for AWS service communication
- ✅ No direct internet access for sensitive resources

### Access Control
- ✅ IAM roles with least privilege principles
- ✅ Resource-based policies for fine-grained access
- ✅ Environment isolation

## 💰 Cost Optimization

### Development Environment (~$20/month)
- **T3.micro RDS instance** for cost savings
- **Minimal backup retention** (3 days)
- **VPC endpoints** instead of NAT Gateway
- **Disabled monitoring** for development

### Production Scaling
- Upgrade to larger RDS instances with Multi-AZ
- Enable enhanced monitoring and Performance Insights
- Increase backup retention period
- Add CloudWatch alarms and monitoring

## 🛠️ Database Schema Deployment

Since the Lambda initialization has been removed, deploy database schema manually:

```bash
# 1. Get database connection details
terraform output -raw connection_command

# 2. Run the connection command to access database
# (Follow the output instructions)

# 3. Execute SQL scripts from the Database/ directory
# Upload and run the SQL files in the correct order
```

## 🔍 Troubleshooting

### Common Issues

#### Database Connection
```bash
# Check security groups
aws ec2 describe-security-groups --group-ids <sg-id>

# Verify credentials
aws secretsmanager get-secret-value --secret-id <secret-name>
```

#### Lambda Functions
```bash
# Check function logs
aws logs tail /aws/lambda/dnd-ai-dev-discord-bot --follow
```

#### API Keys
```bash
# List all secrets
aws secretsmanager list-secrets --filters Key=name,Values=dnd-ai
```

## 📋 Next Steps

1. **Deploy infrastructure** using the steps above
2. **Test database connectivity** with the provided connection command
3. **Deploy database schema** using SQL scripts from the `Database/` directory
4. **Deploy Lambda function code** from the `src/lambda-functions/` directory
5. **Configure Discord bot** with the deployed Lambda function URLs

## 🔄 Maintenance

### Regular Tasks
- Monitor costs through AWS Cost Explorer
- Review and rotate API keys quarterly
- Update Terraform modules for security patches
- Review access logs and usage patterns

### Best Practices
- Test infrastructure changes in development first
- Use Terraform planning to review changes before applying
- Maintain separate state files per environment
- Document any manual configuration changes

---

**Important:** Never commit `secrets.tfvars` or any files containing API keys to Git. The `.gitignore` file is configured to prevent this, but always double-check before committing.