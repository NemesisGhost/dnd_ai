# =====================================================
# Secrets Management Module Outputs
# =====================================================

output "openai_api_key_secret_arn" {
  description = "ARN of the OpenAI API key secret"
  value       = var.openai_api_key != "" ? aws_secretsmanager_secret.openai_api_key[0].arn : ""
}

output "openai_api_key_secret_name" {
  description = "Name of the OpenAI API key secret"
  value       = var.openai_api_key != "" ? aws_secretsmanager_secret.openai_api_key[0].name : ""
}

output "discord_bot_token_secret_arn" {
  description = "ARN of the Discord bot token secret"
  value       = var.discord_bot_token != "" ? aws_secretsmanager_secret.discord_bot_token[0].arn : ""
}

output "discord_bot_token_secret_name" {
  description = "Name of the Discord bot token secret"
  value       = var.discord_bot_token != "" ? aws_secretsmanager_secret.discord_bot_token[0].name : ""
}

output "app_config_secret_arn" {
  description = "ARN of the application configuration secret"
  value       = aws_secretsmanager_secret.app_config.arn
}

output "app_config_secret_name" {
  description = "Name of the application configuration secret"
  value       = aws_secretsmanager_secret.app_config.name
}

# For convenience, output all secret ARNs that Lambda functions might need
output "all_secret_arns" {
  description = "List of all secret ARNs for Lambda function permissions"
  value = compact([
    var.openai_api_key != "" ? aws_secretsmanager_secret.openai_api_key[0].arn : "",
    var.discord_bot_token != "" ? aws_secretsmanager_secret.discord_bot_token[0].arn : "",
    aws_secretsmanager_secret.app_config.arn
  ])
}