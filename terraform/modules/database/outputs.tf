# =====================================================
# Database Module Outputs
# =====================================================

output "database_instance_id" {
  description = "RDS instance identifier"
  value       = aws_db_instance.main.identifier
}

output "database_endpoint" {
  description = "RDS instance endpoint"
  value       = aws_db_instance.main.endpoint
}

output "database_port" {
  description = "RDS instance port"
  value       = aws_db_instance.main.port
}

output "database_name" {
  description = "Database name"
  value       = aws_db_instance.main.db_name
}

output "database_username" {
  description = "Database master username"
  value       = aws_db_instance.main.username
  sensitive   = true
}

output "database_arn" {
  description = "RDS instance ARN"
  value       = aws_db_instance.main.arn
}

output "database_resource_id" {
  description = "RDS instance resource ID used for IAM auth (for rds-db:connect)"
  value       = aws_db_instance.main.resource_id
}

output "database_security_group_id" {
  description = "Security group ID for database access"
  value       = aws_security_group.db.id
}

output "database_subnet_group_name" {
  description = "Database subnet group name"
  value       = aws_db_subnet_group.main.name
}

output "rds_master_user_secret_arn" {
  description = "ARN of the AWS-managed secret for the RDS master user"
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
}


output "kms_key_id" {
  description = "KMS key ID used for database encryption"
  value       = aws_kms_key.db_encryption.key_id
}

output "kms_key_arn" {
  description = "KMS key ARN used for database encryption"
  value       = aws_kms_key.db_encryption.arn
}

output "vpc_id" {
  description = "VPC ID where database is deployed"
  value       = var.vpc_id != null ? var.vpc_id : aws_vpc.main[0].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs where database is deployed (created by module)"
  value       = aws_subnet.private[*].id
}

output "effective_private_subnet_ids" {
  description = "Private subnet IDs actually used by the DB subnet group (either provided or created)"
  value       = length(aws_subnet.private[*].id) > 0 ? aws_subnet.private[*].id : var.private_subnet_ids
}

output "public_subnet_ids" {
  description = "Public subnet IDs (if VPC was created)"
  value       = var.vpc_id == null ? aws_subnet.public[*].id : []
}

# Intentionally do not output a connection string to avoid exposing passwords

# Note: Database initialization Lambda function has been removed
# Database schema deployment now handled via separate migration process

# Networking outputs
output "vpc_endpoints" {
  description = "VPC endpoint details"
  value = var.create_vpc_endpoints ? {
    secretsmanager = {
      id           = aws_vpc_endpoint.secretsmanager[0].id
      dns_names    = aws_vpc_endpoint.secretsmanager[0].dns_entry[*].dns_name
    }
    kms = {
      id           = aws_vpc_endpoint.kms[0].id
      dns_names    = aws_vpc_endpoint.kms[0].dns_entry[*].dns_name
    }
  } : null
}

output "nat_gateway_id" {
  description = "NAT Gateway ID (if created)"
  value       = var.use_nat_gateway && var.vpc_id == null ? aws_nat_gateway.main[0].id : null
}

