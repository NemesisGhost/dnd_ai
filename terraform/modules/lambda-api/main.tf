terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

locals {
  function_name = var.function_name
  layer_arns    = var.layer_arns
}

resource "aws_iam_role" "lambda_exec" {
  name               = "${var.name_prefix}-${var.function_name}-exec"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "this" {
  function_name = "${var.name_prefix}-${var.function_name}"
  filename      = var.lambda_zip
  source_code_hash = filebase64sha256(var.lambda_zip)
  role          = aws_iam_role.lambda_exec.arn
  handler       = var.handler
  runtime       = var.runtime
  timeout       = var.timeout
  memory_size   = var.memory_size
  layers        = local.layer_arns

  environment {
    variables = var.environment
  }

  dynamic "vpc_config" {
    for_each = var.vpc_subnet_ids == null ? [] : [1]
    content {
      subnet_ids         = var.vpc_subnet_ids
      security_group_ids = var.vpc_security_group_ids
    }
  }
}

# Optional IAM DB auth permissions
data "aws_iam_policy_document" "rds_iam_auth" {
  count = var.allow_rds_iam_auth ? 1 : 0

  statement {
    sid     = "GenerateToken"
    effect  = "Allow"
    actions = ["rds:GenerateDbAuthToken"]
    resources = ["*"]
  }

  dynamic "statement" {
    for_each = length(var.rds_dbuser_arns) > 0 ? [1] : []
    content {
      sid       = "ConnectRdsDb"
      effect    = "Allow"
      actions   = ["rds-db:connect"]
      resources = var.rds_dbuser_arns
    }
  }
}

resource "aws_iam_role_policy" "rds_iam_auth" {
  count  = var.allow_rds_iam_auth ? 1 : 0
  name   = "${var.name_prefix}-${var.function_name}-rds-iam-auth"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.rds_iam_auth[0].json
}

# Authorizer Lambda for Basic Auth
resource "aws_iam_role" "auth_exec" {
  name               = "${var.name_prefix}-${var.function_name}-auth-exec"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "auth_basic" {
  role       = aws_iam_role.auth_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "authorizer" {
  function_name = "${var.name_prefix}-${var.function_name}-authorizer"
  filename      = var.authorizer_zip
  source_code_hash = filebase64sha256(var.authorizer_zip)
  role          = aws_iam_role.auth_exec.arn
  handler       = var.authorizer_handler
  runtime       = var.runtime
  timeout       = 10
  memory_size   = 128

  environment {
    variables = {
      SECRET_ID_BASIC_AUTH = var.secret_id_basic_auth
    }
  }
}

resource "aws_api_gateway_rest_api" "this" {
  name = "${var.name_prefix}-${var.function_name}-api"
}

resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  parent_id   = aws_api_gateway_rest_api.this.root_resource_id
  path_part   = var.api_path
}

resource "aws_api_gateway_method" "proxy_method" {
  rest_api_id   = aws_api_gateway_rest_api.this.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = var.http_method
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.basic.id
  api_key_required = true
}

resource "aws_api_gateway_integration" "lambda" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_method.http_method
  type        = "AWS_PROXY"
  integration_http_method = "POST"
  uri         = aws_lambda_function.this.invoke_arn
}

# Optional CORS preflight support (OPTIONS method)
resource "aws_api_gateway_method" "options" {
  count        = var.enable_cors ? 1 : 0
  rest_api_id  = aws_api_gateway_rest_api.this.id
  resource_id  = aws_api_gateway_resource.proxy.id
  http_method  = "OPTIONS"
  authorization = "NONE"
  api_key_required = false
}

resource "aws_api_gateway_integration" "options_mock" {
  count                   = var.enable_cors ? 1 : 0
  rest_api_id             = aws_api_gateway_rest_api.this.id
  resource_id             = aws_api_gateway_resource.proxy.id
  http_method             = aws_api_gateway_method.options[0].http_method
  type                    = "MOCK"
  request_templates = {
    "application/json" = jsonencode({ statusCode = 200 })
  }
}

resource "aws_api_gateway_method_response" "options_200" {
  count       = var.enable_cors ? 1 : 0
  rest_api_id = aws_api_gateway_rest_api.this.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.options[0].http_method
  status_code = 200
  response_models = { "application/json" = "Empty" }
  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = true,
    "method.response.header.Access-Control-Allow-Methods" = true,
    "method.response.header.Access-Control-Allow-Headers" = true
  }
}

resource "aws_api_gateway_integration_response" "options_200" {
  count                   = var.enable_cors ? 1 : 0
  rest_api_id             = aws_api_gateway_rest_api.this.id
  resource_id             = aws_api_gateway_resource.proxy.id
  http_method             = aws_api_gateway_method.options[0].http_method
  status_code             = aws_api_gateway_method_response.options_200[0].status_code
  response_parameters = {
    "method.response.header.Access-Control-Allow-Origin"  = "'${var.cors_allow_origin}'",
    "method.response.header.Access-Control-Allow-Methods" = "'${var.cors_allow_methods}'",
    "method.response.header.Access-Control-Allow-Headers" = "'${var.cors_allow_headers}'"
  }
  response_templates = {
    "application/json" = ""
  }
  depends_on = [aws_api_gateway_integration.options_mock]
}

resource "aws_lambda_permission" "apigw_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.this.execution_arn}/*/${var.http_method}${aws_api_gateway_resource.proxy.path}"
}

# Authorizer resource
resource "aws_api_gateway_authorizer" "basic" {
  name                   = "${var.name_prefix}-${var.function_name}-basic-auth"
  rest_api_id            = aws_api_gateway_rest_api.this.id
  authorizer_uri         = aws_lambda_function.authorizer.invoke_arn
  authorizer_result_ttl_in_seconds = 30
  identity_source        = "method.request.header.Authorization"
  type                   = "REQUEST"
}

resource "aws_api_gateway_deployment" "this" {
  depends_on = [
    aws_api_gateway_integration.lambda,
    aws_api_gateway_method.options,
    aws_api_gateway_integration.options_mock,
    aws_api_gateway_method_response.options_200,
    aws_api_gateway_integration_response.options_200
  ]
  rest_api_id = aws_api_gateway_rest_api.this.id
}

resource "aws_api_gateway_stage" "this" {
  rest_api_id   = aws_api_gateway_rest_api.this.id
  deployment_id = aws_api_gateway_deployment.this.id
  stage_name    = var.stage_name
}

# Ensure CORS headers are present on Gateway-level errors (auth, throttling) when enabled
resource "aws_api_gateway_gateway_response" "default_4xx" {
  count         = var.enable_cors ? 1 : 0
  rest_api_id   = aws_api_gateway_rest_api.this.id
  response_type = "DEFAULT_4XX"
  response_parameters = {
    "gatewayresponse.header.Access-Control-Allow-Origin"  = "'${var.cors_allow_origin}'",
    "gatewayresponse.header.Access-Control-Allow-Headers" = "'${var.cors_allow_headers}'",
    "gatewayresponse.header.Access-Control-Allow-Methods" = "'${var.cors_allow_methods}'"
  }
}

resource "aws_api_gateway_gateway_response" "default_5xx" {
  count         = var.enable_cors ? 1 : 0
  rest_api_id   = aws_api_gateway_rest_api.this.id
  response_type = "DEFAULT_5XX"
  response_parameters = {
    "gatewayresponse.header.Access-Control-Allow-Origin"  = "'${var.cors_allow_origin}'",
    "gatewayresponse.header.Access-Control-Allow-Headers" = "'${var.cors_allow_headers}'",
    "gatewayresponse.header.Access-Control-Allow-Methods" = "'${var.cors_allow_methods}'"
  }
}

# API Key and Usage Plan
resource "aws_api_gateway_api_key" "this" {
  name      = "${var.name_prefix}-${var.function_name}-key"
  value     = var.api_key_value
  enabled   = true
}

resource "aws_api_gateway_usage_plan" "this" {
  name = "${var.name_prefix}-${var.function_name}-plan"
  api_stages {
    api_id = aws_api_gateway_rest_api.this.id
    stage  = aws_api_gateway_stage.this.stage_name
  }
  throttle_settings {
    burst_limit = var.throttle_burst_limit
    rate_limit  = var.throttle_rate_limit
  }
}

resource "aws_api_gateway_usage_plan_key" "this" {
  key_id        = aws_api_gateway_api_key.this.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.this.id
}

output "invoke_url" {
  value = "https://${aws_api_gateway_rest_api.this.id}.execute-api.${var.region}.amazonaws.com/${aws_api_gateway_stage.this.stage_name}${aws_api_gateway_resource.proxy.path}"
}
