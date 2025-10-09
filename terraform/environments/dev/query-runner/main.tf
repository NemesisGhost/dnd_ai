terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
  }
}

locals {
  name_prefix = var.name_prefix
  region      = var.aws_region
}

data "aws_caller_identity" "current" {}

# Secrets Manager references (values not stored in TF state)
// Secrets are passed from the parent via variables to avoid plan-time lookups

module "query_runner" {
  source = "../../../modules/lambda-with-build"

  name_prefix = local.name_prefix
  region      = local.region

  function_name = "query_runner"
  repo_root     = abspath("${path.root}/../../../")
  lambda_zip    = "${abspath(path.root)}/../../../dist/lambdas/query_runner.zip"
  handler       = "app.handler"
  runtime       = "python3.11"
  timeout       = 30
  memory_size   = 768

  environment = {
    DB_HOST           = var.db_host
    DB_PORT           = var.db_port
    DB_NAME           = var.db_name
    DB_USER           = var.db_user
    QUERY_SCHEMA_PATH = "/var/task/Database/query_json_schema.json"
  }

  authorizer_zip       = "${abspath(path.root)}/../../../dist/lambdas/basic_auth_authorizer.zip"
  authorizer_handler   = "app.handler"
  secret_id_basic_auth = var.secret_arn_basic_auth

  api_path    = var.api_path
  http_method = var.http_method
  stage_name  = var.stage_name

  api_key_value        = var.api_key_value
  throttle_burst_limit = var.throttle_burst_limit
  throttle_rate_limit  = var.throttle_rate_limit

  # Allow IAM DB auth
  allow_rds_iam_auth = true
  rds_dbuser_arns    = [
    "arn:aws:rds-db:${local.region}:${data.aws_caller_identity.current.account_id}:dbuser/${var.rds_resource_id}/${var.db_user}"
  ]

  # VPC networking to reach private RDS (pass through from env)
  vpc_subnet_ids          = var.vpc_subnet_ids
  vpc_security_group_ids  = var.vpc_security_group_ids

  # Build inputs
  requirements_path = "${abspath(path.root)}/../../../src/lambda-functions/query_runner/layer/requirements.txt"
  extra_layer_arns  = var.layer_arns
  function_trigger_files = [
    "${abspath(path.root)}/../../../src/lambda-functions/query_runner/app.py"
  ]
  authorizer_trigger_files = [
    "${abspath(path.root)}/../../../src/lambda-functions/basic_auth_authorizer/app.py"
  ]

  build_function_name            = "query_runner"
  build_authorizer_function_name = "basic_auth_authorizer"

  enable_cors        = true
  cors_allow_origin  = "*"
  cors_allow_headers = "Authorization,x-api-key,Content-Type"
  cors_allow_methods = "OPTIONS,POST"
}
 
