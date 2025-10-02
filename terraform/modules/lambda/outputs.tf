# =====================================================
# Lambda Functions Module Outputs
# =====================================================

output "lambda_execution_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_execution.arn
}

output "lambda_security_group_id" {
  description = "Security group ID for Lambda functions"
  value       = aws_security_group.lambda.id
}

output "discord_bot_function_name" {
  description = "Name of the Discord bot Lambda function"
  value       = var.discord_token_secret_arn != "" ? aws_lambda_function.discord_bot[0].function_name : null
}

output "discord_bot_function_arn" {
  description = "ARN of the Discord bot Lambda function"
  value       = var.discord_token_secret_arn != "" ? aws_lambda_function.discord_bot[0].arn : null
}

output "ai_query_function_name" {
  description = "Name of the AI query Lambda function"
  value       = var.openai_api_key_secret_arn != "" ? aws_lambda_function.ai_query[0].function_name : null
}

output "ai_query_function_arn" {
  description = "ARN of the AI query Lambda function"
  value       = var.openai_api_key_secret_arn != "" ? aws_lambda_function.ai_query[0].arn : null
}