# =====================================================
# Development Environment Outputs
# =====================================================

# Database Outputs
output "database_endpoint" {
  description = "Database endpoint for connections"
  value       = module.database.database_endpoint
}

output "database_port" {
  description = "Database port"
  value       = module.database.database_port
}

output "database_name" {
  description = "Database name"
  value       = module.database.database_name
}

output "database_secret_name" {
  description = "Name of the secrets manager secret containing database credentials"
  value       = module.database.rds_master_user_secret_arn
}

output "vpc_id" {
  description = "VPC ID where resources are deployed"
  value       = module.database.vpc_id
}

output "database_security_group_id" {
  description = "Security group ID for database access"
  value       = module.database.database_security_group_id
}

# GitHub Actions CI outputs
output "github_actions_ci_role_arn" {
  description = "IAM role ARN GitHub Actions assumes via OIDC — set as the AWS_CI_ROLE_ARN repository secret"
  value       = module.github_actions_ci.role_arn
}

# Secrets Outputs
output "openai_secret_name" {
  description = "Name of the OpenAI API key secret"
  value       = module.secrets.openai_api_key_secret_name
}

output "discord_secret_name" {
  description = "Name of the Discord bot token secret"
  value       = module.secrets.discord_bot_token_secret_name
}

output "app_config_secret_name" {
  description = "Name of the application configuration secret"
  value       = ""
}

# Connection Information
output "connection_command" {
  description = "Command to connect to the database (requires AWS CLI and jq)"
  sensitive   = true
  value       = <<-EOT
    # Get database credentials from Secrets Manager
    aws secretsmanager get-secret-value \
  --secret-id "${module.database.rds_master_user_secret_arn}" \
      --query SecretString --output text | jq -r .password > /tmp/db_password
    
    # Connect using psql
    PGPASSWORD=$(cat /tmp/db_password) psql \
      -h ${module.database.database_endpoint} \
      -p ${module.database.database_port} \
      -U ${module.database.database_username} \
      -d ${module.database.database_name}
    
    # Clean up password file
    rm /tmp/db_password
  EOT
}

# Deployment Information
output "deployment_summary" {
  description = "Summary of deployed resources"
  value = {
    database = {
      endpoint    = module.database.database_endpoint
      name        = module.database.database_name
      resource_id = module.database.database_resource_id
    }
    secrets = {
      rds_master_user_secret = module.database.rds_master_user_secret_arn
      openai_secret          = module.secrets.openai_api_key_secret_name
      discord_secret         = module.secrets.discord_bot_token_secret_name
      app_config             = null
    }
  }
}

output "rds_address" {
  description = "Address of the PostgreSQL RDS instance"
  value       = module.database.database_endpoint
}

# IAM auth helper outputs (for reference when granting rds-db:connect)

# Wildcard pattern — convenient for exploration, too broad for a real policy.
# Prefer rds_iam_connect_arns below, which names one role per entry.
output "rds_iam_connect_resource_arn" {
  description = "The db-user ARN pattern to use in IAM policies for rds-db:connect"
  value       = "arn:aws:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:${module.database.database_resource_id}/*"
}

output "rds_iam_connect_arns" {
  description = "Per-role dbuser ARNs for rds-db:connect, keyed by database role name"
  value       = module.database.rds_iam_connect_arns
}