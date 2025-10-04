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
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge({
      Project     = "dnd-ai",
      Environment = "dev",
      Owner       = var.owner_name
    }, var.additional_tags)
  }
}

locals {
  project_name = "dnd-ai"
  environment  = "dev"
}

# -----------------------------------------------------
# Module: Database (VPC, RDS, KMS, DB Secret)
# -----------------------------------------------------
module "database" {
  source = "../../modules/database"

  project_name = local.project_name
  environment  = local.environment

  # Networking & access
  publicly_accessible      = var.enable_public_access
  allowed_cidr_blocks      = var.enable_public_access ? [var.my_ip_cidr] : ["10.0.0.0/16"]
  allowed_security_group_ids = []

  # DB sizing (dev-friendly defaults are already set in the module)

  # Networking defaults (module will create a VPC if none provided)
  # vpc_id = null

  additional_tags = var.additional_tags
}

# -----------------------------------------------------
# Module: Secrets (OpenAI, Discord, App config)
# -----------------------------------------------------
module "secrets" {
  source = "../../modules/secrets"

  project_name = local.project_name
  environment  = local.environment

  kms_key_arn = module.database.kms_key_arn

  # OpenAI
  openai_api_key         = var.openai_api_key
  openai_organization_id = var.openai_organization_id
  openai_model           = var.openai_model
  max_tokens             = var.max_tokens
  temperature            = var.temperature

  # Discord
  discord_bot_token    = var.discord_bot_token
  discord_application_id = var.discord_application_id
  discord_public_key     = var.discord_public_key

  additional_tags = var.additional_tags
}

# -----------------------------------------------------
# Module: Lambda (Discord bot, AI query)
# -----------------------------------------------------
module "lambda" {
  source = "../../modules/lambda"

  project_name = local.project_name
  environment  = local.environment

  # Networking
  vpc_id     = module.database.vpc_id
  subnet_ids = module.database.private_subnet_ids

  database_security_group_id = module.database.database_security_group_id

  # Secrets / KMS
  database_secret_arn       = module.database.secrets_manager_arn
  kms_key_arn               = module.database.kms_key_arn
  openai_api_key_secret_arn = module.secrets.openai_api_key_secret_arn
  discord_token_secret_arn  = module.secrets.discord_bot_token_secret_arn

  # Logging & runtime
  log_retention_days = 7

  additional_tags = var.additional_tags
}

# -----------------------------------------------------
# Module: DB Runner (SSM-driven SQL migrations from S3)
# -----------------------------------------------------
module "db_runner" {
  source = "../../modules/db_runner"

  vpc_id              = module.database.vpc_id
  private_subnet_ids  = module.database.private_subnet_ids
  rds_security_group_id = module.database.database_security_group_id
  db_secret_arn       = module.database.secrets_manager_arn

  # Let the module generate a unique bucket name in dev; only pass the prefix
  # sql_bucket_name   = ""  # optional
  sql_prefix         = var.sql_prefix
}