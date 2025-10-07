locals {
  deps_hash = filesha1(var.requirements_path)

  function_src_hash = length(var.function_trigger_files) > 0 ? sha1(join("", [for f in var.function_trigger_files : filesha1(f)])) : ""
  authorizer_src_hash = length(var.authorizer_trigger_files) > 0 ? sha1(join("", [for f in var.authorizer_trigger_files : filesha1(f)])) : ""
}

resource "null_resource" "build_layer" {
  triggers = { deps_hash = local.deps_hash }

  provisioner "local-exec" {
    interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
    command     = "$req='${var.requirements_path}'; $root='${var.repo_root}'; $build=Join-Path $root '.terraform-build/${var.function_name}_layer'; $site=Join-Path $build 'python'; $zip=Join-Path $root 'dist/layers/${var.function_name}-python-deps.zip'; if (Test-Path $build) { Remove-Item -Recurse -Force $build }; New-Item -ItemType Directory -Force -Path $site | Out-Null; $pip='${var.python_exe} -m pip'; Write-Host 'Installing deps from' $req; & $pip install -r $req -t $site; $distDir = Split-Path $zip; if (!(Test-Path $distDir)) { New-Item -ItemType Directory -Force -Path $distDir | Out-Null }; if (Test-Path $zip) { Remove-Item -Force $zip }; Compress-Archive -Path ($build + '\\*') -DestinationPath $zip -Force;"
  }
}

resource "aws_lambda_layer_version" "deps" {
  layer_name          = "${var.name_prefix}-${var.function_name}-deps"
  filename            = "${var.repo_root}/dist/layers/${var.function_name}-python-deps.zip"
  source_code_hash    = filebase64sha256("${var.repo_root}/dist/layers/${var.function_name}-python-deps.zip")
  compatible_runtimes = [var.runtime]
  description         = "${var.function_name} deps ${substr(local.deps_hash,0,8)}"

  depends_on = [null_resource.build_layer]
}

resource "null_resource" "build_lambda" {
  triggers = { src_hash = local.function_src_hash }
  provisioner "local-exec" {
    interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
    command     = "cd '${var.repo_root}'; ./scripts/build_lambda.ps1 -FunctionName ${var.build_function_name}"
  }
}

resource "null_resource" "build_authorizer" {
  triggers = { src_hash = local.authorizer_src_hash }
  provisioner "local-exec" {
    interpreter = ["PowerShell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
    command     = length(var.authorizer_trigger_files) > 0 ? "cd '${var.repo_root}'; ./scripts/build_lambda.ps1 -FunctionName ${var.build_authorizer_function_name}" : "Write-Host 'Skipping authorizer build (no trigger files)'"
  }
}

module "lambda_api" {
  source = "../lambda-api"

  name_prefix = var.name_prefix
  region      = var.region

  function_name = var.function_name
  lambda_zip    = var.lambda_zip
  handler       = var.handler
  runtime       = var.runtime
  timeout       = var.timeout
  memory_size   = var.memory_size

  layer_arns = concat(var.extra_layer_arns, [aws_lambda_layer_version.deps.arn])

  environment = var.environment

  vpc_subnet_ids         = var.vpc_subnet_ids
  vpc_security_group_ids = var.vpc_security_group_ids

  api_path     = var.api_path
  http_method  = var.http_method
  stage_name   = var.stage_name

  api_key_value          = var.api_key_value
  throttle_burst_limit   = var.throttle_burst_limit
  throttle_rate_limit    = var.throttle_rate_limit

  authorizer_zip         = var.authorizer_zip
  authorizer_handler     = var.authorizer_handler
  secret_id_basic_auth   = var.secret_id_basic_auth

  allow_rds_iam_auth     = var.allow_rds_iam_auth
  rds_dbuser_arns        = var.rds_dbuser_arns

  # CORS
  enable_cors        = var.enable_cors
  cors_allow_origin  = var.cors_allow_origin
  cors_allow_headers = var.cors_allow_headers
  cors_allow_methods = var.cors_allow_methods

  depends_on = [
    aws_lambda_layer_version.deps,
    null_resource.build_lambda,
    null_resource.build_authorizer
  ]
}

output "api_invoke_url" { value = module.lambda_api.api_invoke_url }
output "lambda_arn" { value = module.lambda_api.lambda_arn }
output "lambda_execution_role_arn" { value = module.lambda_api.lambda_execution_role_arn }