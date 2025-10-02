# =====================================================
# D&D AI Development Environment
# =====================================================

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Uncomment and configure for remote state
  # backend "s3" {
  #   bucket         = "your-terraform-state-bucket"
  #   key            = "dnd-ai/dev/terraform.tfstate"
  #   region         = "us-east-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}

# Configure AWS Provider
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "dnd-ai"
      Environment = "dev"
      ManagedBy   = "terraform"
      CreatedBy   = "terraform"
    }
  }
}

# Local variables
locals {
  project_name = "dnd-ai"
  environment  = "dev"

  # Development-specific settings
  db_instance_class   = "db.t3.micro" # Smallest instance for dev
  deletion_protection = false         # Allow easy teardown in dev
  skip_final_snapshot = true          # No snapshot needed for dev
}

# Database Module
module "database" {
  source = "../../modules/database"

  # Basic configuration
  project_name = local.project_name
  environment  = local.environment

  # Database configuration
  database_name    = "dnd_ai_dev"
  master_username  = "dnd_admin"
  postgres_version = "15.14"
  instance_class   = local.db_instance_class

  # Storage configuration
  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"

  # Network configuration (creates new VPC)
  vpc_id   = null # Create new VPC
  vpc_cidr = "10.0.0.0/16"
  allowed_cidr_blocks = [
    "10.0.0.0/16", # VPC CIDR
    var.my_ip_cidr # Your IP for development access
  ]

  # Security settings (development)
  publicly_accessible = var.enable_public_access
  deletion_protection = local.deletion_protection
  skip_final_snapshot = local.skip_final_snapshot

  # Backup settings (minimal for dev)
  backup_retention_period = 3
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"

  # Monitoring (basic for dev)
  enhanced_monitoring          = false
  performance_insights_enabled = false
  log_retention_days           = 3

  # Additional tags
  additional_tags = var.additional_tags
}

# Secrets Module
module "secrets" {
  source = "../../modules/secrets"

  # Basic configuration
  project_name = local.project_name
  environment  = local.environment

  # KMS key from database module
  kms_key_arn = module.database.kms_key_arn

  # API Keys and Configuration
  openai_api_key         = var.openai_api_key
  openai_organization_id = var.openai_organization_id
  openai_model          = var.openai_model
  max_tokens            = var.max_tokens
  temperature           = var.temperature

  discord_bot_token      = var.discord_bot_token
  discord_application_id = var.discord_application_id
  discord_public_key     = var.discord_public_key

  # Additional tags
  additional_tags = var.additional_tags
}

# Lambda Module
module "lambda" {
  source = "../../modules/lambda"

  # Basic configuration
  project_name = local.project_name
  environment  = local.environment

  # Network configuration from database module
  vpc_id     = module.database.vpc_id
  subnet_ids = module.database.private_subnet_ids

  # Database and secrets configuration
  database_secret_arn        = module.database.secrets_manager_arn
  kms_key_arn               = module.database.kms_key_arn
  openai_api_key_secret_arn = module.secrets.openai_api_key_secret_arn
  discord_token_secret_arn  = module.secrets.discord_bot_token_secret_arn

  # Lambda configuration
  lambda_runtime     = "python3.11"
  lambda_timeout     = 300
  lambda_memory_size = 512
  log_retention_days = 3

  # Additional tags
  additional_tags = var.additional_tags
}