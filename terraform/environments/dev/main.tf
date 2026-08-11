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

# Import default VPC and its subnets
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default_subnets" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# If a specific VPC ID is provided via var.vpc_id, fetch its details for CIDR lookups
data "aws_vpc" "selected" {
  count = var.vpc_id != "" ? 1 : 0
  id    = var.vpc_id
}

data "aws_subnets" "selected_subnets" {
  count = var.vpc_id != "" ? 1 : 0
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
}

# -----------------------------------------------------
# Module: Database (VPC, RDS, KMS, DB Secret)
# -----------------------------------------------------
module "database" {
  source = "../../modules/database"

  project_name = local.project_name
  environment  = local.environment

  # Networking & access
  # Use provided VPC and subnets when set; otherwise fall back to default VPC discovery
  vpc_id             = var.vpc_id != "" ? var.vpc_id : data.aws_vpc.default.id
  private_subnet_ids = length(var.private_subnet_ids) > 0 ? var.private_subnet_ids : (var.vpc_id != "" ? data.aws_subnets.selected_subnets[0].ids : data.aws_subnets.default_subnets.ids)

  publicly_accessible        = var.enable_public_access
  allowed_cidr_blocks        = var.enable_public_access ? [var.my_ip_cidr] : [var.vpc_id != "" ? data.aws_vpc.selected[0].cidr_block : data.aws_vpc.default.cidr_block]
  allowed_security_group_ids = []

  # DB sizing (dev-friendly defaults are already set in the module)

  # dev is disposable per docs/PLAN.md §29.3 and §26.2: fast teardown, no
  # final snapshot. The module defaults (deletion_protection = true,
  # skip_final_snapshot = false) are meant for staging/prod, not dev — see
  # INFRASTRUCTURE.md §11 gap 1 and docs/POSTGRES18_UPGRADE_PLAN.md §B1.
  deletion_protection = false
  skip_final_snapshot = true

  # Avoid creating VPC endpoints in default VPC until SG rule uses actual CIDR (now fixed in module)
  create_vpc_endpoints = false

  additional_tags = var.additional_tags
}

# -----------------------------------------------------
# Module: Secrets (OpenAI, Discord, App config)
# -----------------------------------------------------
module "secrets" {
  source = "../../modules/secrets"

  project_name = local.project_name
  environment  = local.environment

  # Note: kms_key_arn is not set - secrets will use AWS-managed key
  # To use customer-managed KMS key, uncomment and ensure IAM permissions
  # kms_key_arn = module.database.kms_key_arn

  additional_tags = var.additional_tags
}

# -----------------------------------------------------
# Module: Lambda (Discord bot, AI query)
# -----------------------------------------------------
# Not yet implemented. The application API and any background workers
# will be added here per docs/architecture/SYSTEM_ARCHITECTURE.md once
# the corresponding Python services exist.