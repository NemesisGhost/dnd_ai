# =====================================================
# KMS Key and RDS-managed Secrets
# =====================================================

# Data source for caller identity
data "aws_caller_identity" "current" {}

# Data source for current region
data "aws_region" "current" {}

# KMS key for encrypting database (RDS storage, PI, and RDS-managed secret)
resource "aws_kms_key" "db_encryption" {
  description             = "KMS key for D&D AI database encryption"
  deletion_window_in_days = 7

  # Note: enable_key_rotation requires kms:EnableKeyRotation permission
  # Can be enabled later via AWS Console or when IAM permissions are updated
  # enable_key_rotation     = true

  # Use AWS default key policy which allows root account full access
  # This ensures key can be managed in the future
  # To grant service access, update policy via AWS Console when IAM permissions allow

  tags = {
    Name        = "${var.project_name}-${var.environment}-db-key"
    Project     = var.project_name
    Environment = var.environment
    Purpose     = "Database Encryption"
  }
}

resource "aws_kms_alias" "db_encryption" {
  name          = "alias/${var.project_name}-${var.environment}-db"
  target_key_id = aws_kms_key.db_encryption.key_id
}
