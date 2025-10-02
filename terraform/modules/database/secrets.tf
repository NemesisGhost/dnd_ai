# =====================================================
# KMS Key and Secrets Manager Resources
# =====================================================

# Data source for caller identity
data "aws_caller_identity" "current" {}

# Data source for current region
data "aws_region" "current" {}

# Random password for database
resource "random_password" "db_password" {
  length  = 32
  special = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# KMS key for encrypting database
resource "aws_kms_key" "db_encryption" {
  description             = "KMS key for D&D AI database encryption"
  deletion_window_in_days = 7

  # Key policy to allow various services to use the key
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Enable IAM User Permissions"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "Allow Lambda Service"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "lambda.${data.aws_region.current.name}.amazonaws.com"
          }
        }
      },
      {
        Sid    = "Allow Secrets Manager Service"
        Effect = "Allow"
        Principal = {
          Service = "secretsmanager.amazonaws.com"
        }
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey",
          "kms:Encrypt",
          "kms:GenerateDataKey",
          "kms:ReEncryptFrom",
          "kms:ReEncryptTo"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "secretsmanager.${data.aws_region.current.name}.amazonaws.com"
          }
        }
      },
      {
        Sid    = "Allow RDS Service"
        Effect = "Allow"
        Principal = {
          Service = "rds.amazonaws.com"
        }
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey",
          "kms:Encrypt",
          "kms:GenerateDataKey",
          "kms:ReEncryptFrom",
          "kms:ReEncryptTo"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "rds.${data.aws_region.current.name}.amazonaws.com"
          }
        }
      }
    ]
  })

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

# Store database credentials in Secrets Manager
resource "aws_secretsmanager_secret" "db_credentials" {
  name                    = "${var.project_name}/${var.environment}/database/credentials"
  description             = "Database credentials for D&D AI application"
  recovery_window_in_days = 7
  kms_key_id             = aws_kms_key.db_encryption.arn

  tags = {
    Name        = "${var.project_name}-${var.environment}-db-credentials"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = aws_db_instance.main.username
    password = random_password.db_password.result
    engine   = aws_db_instance.main.engine
    host     = aws_db_instance.main.endpoint
    port     = aws_db_instance.main.port
    dbname   = aws_db_instance.main.db_name
    url      = "postgresql://${aws_db_instance.main.username}:${random_password.db_password.result}@${aws_db_instance.main.endpoint}:${aws_db_instance.main.port}/${aws_db_instance.main.db_name}"
  })
}