# =====================================================
# Lambda Functions Module
# =====================================================

# Data sources
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# Security group for Lambda functions
resource "aws_security_group" "lambda" {
  name_prefix = "${var.project_name}-${var.environment}-lambda-"
  vpc_id      = var.vpc_id

  # Allow access to PostgreSQL database
  egress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
    description = "PostgreSQL access"
  }

  # Allow HTTPS access for AWS services and external APIs
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS access for AWS services and external APIs"
  }

  # Allow HTTP access for external APIs (if needed)
  egress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP access for external APIs"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-lambda-sg"
    Project     = var.project_name
    Environment = var.environment
  }

  lifecycle {
    create_before_destroy = true
  }
}

# IAM role for Lambda functions
resource "aws_iam_role" "lambda_execution" {
  name = "${var.project_name}-${var.environment}-lambda-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-${var.environment}-lambda-execution-role"
    Project     = var.project_name
    Environment = var.environment
  }
}

# IAM policy for Lambda functions
resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.project_name}-${var.environment}-lambda-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          var.database_secret_arn,
          var.openai_api_key_secret_arn,
          var.discord_token_secret_arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = var.kms_key_arn
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DeleteNetworkInterface"
        ]
        Resource = "*"
      }
    ]
  })
}

# Attach the basic execution role policy
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
  role       = aws_iam_role.lambda_execution.name
}

# Attach the VPC access execution role policy
resource "aws_iam_role_policy_attachment" "lambda_vpc_access" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
  role       = aws_iam_role.lambda_execution.name
}

# Example Lambda function - Discord Bot Handler
resource "aws_lambda_function" "discord_bot" {
  count = var.discord_token_secret_arn != "" ? 1 : 0

  filename         = "${path.module}/lambda_code/discord_bot.zip"
  function_name    = "${var.project_name}-${var.environment}-discord-bot"
  role            = aws_iam_role.lambda_execution.arn
  handler         = "discord_handler.handler"
  runtime         = var.lambda_runtime
  timeout         = var.lambda_timeout
  memory_size     = var.lambda_memory_size

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      DATABASE_SECRET_ARN = var.database_secret_arn
      DISCORD_TOKEN_SECRET_ARN = var.discord_token_secret_arn
      OPENAI_API_KEY_SECRET_ARN = var.openai_api_key_secret_arn
      ENVIRONMENT = var.environment
    }
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-discord-bot"
    Project     = var.project_name
    Environment = var.environment
    Purpose     = "Discord Bot Handler"
  }
}

# Example Lambda function - AI Query Handler
resource "aws_lambda_function" "ai_query" {
  count = var.openai_api_key_secret_arn != "" ? 1 : 0

  filename         = "${path.module}/lambda_code/ai_query.zip"
  function_name    = "${var.project_name}-${var.environment}-ai-query"
  role            = aws_iam_role.lambda_execution.arn
  handler         = "ai_query_handler.handler"
  runtime         = var.lambda_runtime
  timeout         = var.lambda_timeout
  memory_size     = var.lambda_memory_size

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      DATABASE_SECRET_ARN = var.database_secret_arn
      OPENAI_API_KEY_SECRET_ARN = var.openai_api_key_secret_arn
      ENVIRONMENT = var.environment
    }
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-ai-query"
    Project     = var.project_name
    Environment = var.environment
    Purpose     = "AI Query Handler"
  }
}

# CloudWatch log groups
resource "aws_cloudwatch_log_group" "discord_bot" {
  count = var.discord_token_secret_arn != "" ? 1 : 0

  name              = "/aws/lambda/${aws_lambda_function.discord_bot[0].function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-${var.environment}-discord-bot-logs"
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "ai_query" {
  count = var.openai_api_key_secret_arn != "" ? 1 : 0

  name              = "/aws/lambda/${aws_lambda_function.ai_query[0].function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-${var.environment}-ai-query-logs"
    Project     = var.project_name
    Environment = var.environment
  }
}