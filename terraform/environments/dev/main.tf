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

# Caller identity for helper outputs and wiring
data "aws_caller_identity" "current" {}

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

  additional_tags = var.additional_tags
}

# -----------------------------------------------------
# Module: Lambda (Discord bot, AI query)
# -----------------------------------------------------
/* module "lambda" {
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
 */
# -----------------------------------------------------
# Module: DB Runner (SSM-driven SQL migrations from S3)
# -----------------------------------------------------
module "db_runner" {
  source = "../../modules/db_runner"

  vpc_id              = module.database.vpc_id
  private_subnet_ids  = module.database.private_subnet_ids
  rds_security_group_id = module.database.database_security_group_id
  db_secret_arn       = module.database.rds_master_user_secret_arn
  db_name             = module.database.database_name

  # Let the module generate a unique bucket name in dev; only pass the prefix
  # sql_bucket_name   = ""  # optional
  sql_prefix         = var.sql_prefix
}

# -----------------------------------------------------
# Wire db-schema-introspect variables from environment outputs
# -----------------------------------------------------
module "db_schema_introspect_vars" {
  source = "./db-schema-introspect"

  name_prefix = var.name_prefix
  aws_region  = var.aws_region

  db_host = module.database.database_endpoint
  db_port = tostring(module.database.database_port)
  db_name = module.database.database_name
  db_user = "app_iam_user"  # TODO: set your IAM DB username
  rds_resource_id = module.database.database_resource_id

  secret_name_api_key   = var.api_secret_name_api_key
  secret_name_basic_auth = var.api_secret_name_basic_auth

  layer_arns = []

  vpc_subnet_ids         = module.database.private_subnet_ids
  vpc_security_group_ids = [module.database.database_security_group_id]
}