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

# Lambda Outputs
/* output "lambda_execution_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = module.lambda.lambda_execution_role_arn
}

output "discord_bot_function_name" {
  description = "Name of the Discord bot Lambda function"
  value       = module.lambda.discord_bot_function_name
}

output "ai_query_function_name" {
  description = "Name of the AI query Lambda function"
  value       = module.lambda.ai_query_function_name
} */

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
      endpoint = module.database.database_endpoint
      name     = module.database.database_name
      resource_id = module.database.database_resource_id
    }
    secrets = {
  rds_master_user_secret = module.database.rds_master_user_secret_arn
      openai_secret   = module.secrets.openai_api_key_secret_name
      discord_secret  = module.secrets.discord_bot_token_secret_name
      app_config      = null
    }
/*     lambda_functions = {
      discord_bot = module.lambda.discord_bot_function_name
      ai_query    = module.lambda.ai_query_function_name
    } */
  }
}

# DB Runner Outputs
output "runner_instance_id" {
  description = "EC2 instance ID of the SQL runner"
  value       = module.db_runner.runner_instance_id
}

output "runner_sg_id" {
  description = "Security group ID of the SQL runner"
  value       = module.db_runner.runner_security_group_id
}

output "rds_address" {
  description = "Address of the PostgreSQL RDS instance"
  value       = module.database.database_endpoint
}

output "sql_s3_uri" {
  description = "S3 URI where SQL files are synced"
  value       = "s3://${module.db_runner.sql_bucket_name}/${var.sql_prefix}"
}

output "sql_bucket_name" {
  description = "The S3 bucket name created for SQL files"
  value       = module.db_runner.sql_bucket_name
}

# db-schema-introspect API
output "db_schema_introspect_invoke_url" {
  description = "Invoke URL for the db-schema-introspect REST API"
  value       = module.db_schema_introspect_vars.invoke_url
}

# IAM auth helper output (for reference when granting rds-db:connect)
output "rds_iam_connect_resource_arn" {
  description = "The db-user ARN pattern to use in IAM policies for rds-db:connect"
  value       = "arn:aws:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:${module.database.database_resource_id}/*"
}