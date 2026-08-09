# =====================================================
# RDS PostgreSQL Database Resources
# =====================================================

# Derived, not independently configurable: the parameter group family must
# match postgres_version's major component or RDS rejects the parameter
# group outright (a mismatch such as postgres_version = "19.x" with a
# "postgres18" family fails at apply time, not silently). Deriving it here
# makes that combination impossible to express in the first place, rather
# than validating it after the fact — there is no parameter_group_family
# variable to independently get out of sync. var.postgres_version's own
# validation (variables.tf) guarantees this split produces a sane result.
locals {
  postgres_major         = split(".", var.postgres_version)[0]
  parameter_group_family = "postgres${local.postgres_major}"
}

# Parameter group for PostgreSQL
#
# name_prefix + create_before_destroy: `family` forces replacement of this
# resource on a major-version change, but a fixed `name` would deadlock that
# replacement while attached to a live instance (the old group can't be
# destroyed while in use, and the new one can't reuse the name). This gives
# the correct order — create the new group, point the instance at it, then
# destroy the old one. See docs/POSTGRES18_UPGRADE_PLAN.md §B1.
resource "aws_db_parameter_group" "main" {
  family      = local.parameter_group_family
  name_prefix = "${var.project_name}-${var.environment}-db-params-"

  lifecycle {
    create_before_destroy = true
  }

  parameter {
    name  = "log_statement"
    value = "all"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
    # shared_preload_libraries is a static parameter - PostgreSQL/RDS reject
    # "immediate" apply for it outright ("cannot use immediate apply method
    # for static parameter"), which is the schema's default apply_method
    # when this is left unset. Must be explicit.
    apply_method = "pending-reboot"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-db-params"
    Project     = var.project_name
    Environment = var.environment
  }
}

# RDS instance
resource "aws_db_instance" "main" {
  identifier = "${var.project_name}-${var.environment}-db"

  # Engine configuration
  engine                     = "postgres"
  engine_version             = var.postgres_version
  auto_minor_version_upgrade = var.auto_minor_version_upgrade
  instance_class             = var.instance_class
  allocated_storage          = var.allocated_storage
  max_allocated_storage      = var.max_allocated_storage
  storage_type               = var.storage_type
  storage_encrypted          = true
  # Note: kms_key_id omitted - uses AWS-managed encryption key
  # To use customer-managed KMS key, set kms_key_id = aws_kms_key.db_encryption.arn

  # Database configuration
  db_name                     = var.database_name
  username                    = var.master_username
  manage_master_user_password = true
  # Note: master_user_secret_kms_key_id omitted - uses AWS-managed key
  # To use customer-managed KMS key, set master_user_secret_kms_key_id = aws_kms_key.db_encryption.arn
  port = 5432

  # Network configuration
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = var.publicly_accessible

  # Parameter and option groups
  parameter_group_name                = aws_db_parameter_group.main.name
  iam_database_authentication_enabled = var.iam_database_authentication_enabled

  # Backup configuration
  backup_retention_period  = var.backup_retention_period
  backup_window            = var.backup_window
  maintenance_window       = var.maintenance_window
  delete_automated_backups = false

  # Monitoring and logging
  monitoring_interval = var.enhanced_monitoring ? 60 : 0
  monitoring_role_arn = var.enhanced_monitoring ? aws_iam_role.rds_enhanced_monitoring[0].arn : null

  enabled_cloudwatch_logs_exports = ["postgresql"]

  # Deletion protection
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.project_name}-${var.environment}-final-snapshot-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"

  # Performance insights
  performance_insights_enabled = var.performance_insights_enabled
  # Note: performance_insights_kms_key_id omitted - uses AWS-managed key
  # To use customer-managed KMS key, set performance_insights_kms_key_id = aws_kms_key.db_encryption.arn

  tags = {
    Name        = "${var.project_name}-${var.environment}-db"
    Project     = var.project_name
    Environment = var.environment
    Purpose     = "Primary Database"
  }

  depends_on = [aws_db_subnet_group.main]
}

# IAM role for enhanced monitoring (optional)
resource "aws_iam_role" "rds_enhanced_monitoring" {
  count = var.enhanced_monitoring ? 1 : 0

  name = "${var.project_name}-${var.environment}-rds-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "monitoring.rds.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-${var.environment}-rds-monitoring-role"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "rds_enhanced_monitoring" {
  count = var.enhanced_monitoring ? 1 : 0

  role       = aws_iam_role.rds_enhanced_monitoring[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}