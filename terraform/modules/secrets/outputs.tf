# =====================================================
# Secrets Management Module Outputs
# =====================================================

output "openai_api_key_secret_arn" {
  description = "ARN of the OpenAI API key secret"
  value       = aws_secretsmanager_secret.openai_api_key.arn
}

output "openai_api_key_secret_name" {
  description = "Name of the OpenAI API key secret"
  value       = aws_secretsmanager_secret.openai_api_key.name
}

output "discord_bot_token_secret_arn" {
  description = "ARN of the Discord bot token secret"
  value       = aws_secretsmanager_secret.discord_bot_token.arn
}

output "discord_bot_token_secret_name" {
  description = "Name of the Discord bot token secret"
  value       = aws_secretsmanager_secret.discord_bot_token.name
}

output "api_gateway_api_key_secret_name" {
  description = "Name of the API Gateway API key secret"
  value       = aws_secretsmanager_secret.api_gateway_api_key.name
}

output "basic_auth_secret_name" {
  description = "Name of the Basic Auth credentials secret"
  value       = aws_secretsmanager_secret.basic_auth.name
}

output "api_gateway_api_key_secret_arn" {
  description = "ARN of the API Gateway API key secret"
  value       = aws_secretsmanager_secret.api_gateway_api_key.arn
}

output "basic_auth_secret_arn" {
  description = "ARN of the Basic Auth credentials secret"
  value       = aws_secretsmanager_secret.basic_auth.arn
}
