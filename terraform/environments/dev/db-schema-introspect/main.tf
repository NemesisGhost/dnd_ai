terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

locals {
  name_prefix = var.name_prefix
  region      = var.aws_region
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Secrets Manager references (values not stored in TF state)
data "aws_secretsmanager_secret" "api_key" {
  name = var.secret_name_api_key
}
data "aws_secretsmanager_secret_version" "api_key" {
  secret_id = data.aws_secretsmanager_secret.api_key.id
}

data "aws_secretsmanager_secret" "basic_auth" {
  name = var.secret_name_basic_auth
}

module "db_schema_introspect" {
  source = "../../../modules/lambda-with-build"

  name_prefix = local.name_prefix
  region      = local.region

  function_name = "db-schema-introspect"
  repo_root     = abspath("${path.root}/../../../")
  lambda_zip    = "${abspath(path.root)}/../../../dist/lambdas/db_schema_introspect.zip"
  handler       = "app.handler"
  runtime       = "python3.11"
  timeout       = 30
  memory_size   = 512

  environment = {
    DB_HOST    = var.db_host
    DB_PORT    = var.db_port
    DB_NAME    = var.db_name
    DB_USER    = var.db_user
    DB_SCHEMAS = var.db_schemas
  }

  authorizer_zip     = "${abspath(path.root)}/../../../dist/lambdas/basic_auth_authorizer.zip"
  authorizer_handler = "app.handler"
  secret_id_basic_auth = data.aws_secretsmanager_secret.basic_auth.arn

  api_path     = var.api_path
  http_method  = var.http_method
  stage_name   = var.stage_name

  api_key_value = jsondecode(data.aws_secretsmanager_secret_version.api_key.secret_string)["api_key"]

  throttle_burst_limit = var.throttle_burst_limit
  throttle_rate_limit  = var.throttle_rate_limit

  # Allow IAM DB auth (generate token + connect as the specified DB user)
  allow_rds_iam_auth = true
  rds_dbuser_arns    = [
    "arn:aws:rds-db:${local.region}:${data.aws_caller_identity.current.account_id}:dbuser:${var.rds_resource_id}/${var.db_user}"
  ]

  # VPC networking to reach private RDS
  vpc_subnet_ids        = var.vpc_subnet_ids
  vpc_security_group_ids = var.vpc_security_group_ids

  # Layer and build triggers
  requirements_path = "${abspath(path.root)}/../../../src/lambda-functions/db_schema_introspect/layer/requirements.txt"
  extra_layer_arns  = var.layer_arns
  function_trigger_files = [
    "${abspath(path.root)}/../../../src/lambda-functions/db_schema_introspect/app.py"
  ]
  authorizer_trigger_files = [
    "${abspath(path.root)}/../../../src/lambda-functions/basic_auth_authorizer/app.py"
  ]
  build_function_name            = "db_schema_introspect"
  build_authorizer_function_name = "basic_auth_authorizer"

  # Enable CORS for browser clients (adjust origin as needed)
  enable_cors        = true
  cors_allow_origin  = "*"
  cors_allow_headers = "Authorization,x-api-key,Content-Type"
  cors_allow_methods = "OPTIONS,POST"
}

output "invoke_url" {
  value = module.db_schema_introspect.api_invoke_url
}
