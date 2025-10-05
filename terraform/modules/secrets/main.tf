# =====================================================
# Secrets Management Module (metadata only)
# =====================================================
# This module creates named Secrets Manager secrets encrypted with KMS
# but never writes secret values. Use an external script to upsert values
# and data sources (in consumers) to read latest values at apply/runtime.

# OpenAI API Key Secret (name/metadata only)
resource "aws_secretsmanager_secret" "openai_api_key" {
  name                    = "${var.project_name}/${var.environment}/openai/api-key"
  description             = "OpenAI API key and related config"
  recovery_window_in_days = 7
  kms_key_id              = var.kms_key_arn

  tags = merge(var.additional_tags, {
    Name        = "${var.project_name}-${var.environment}-openai-api-key"
    Project     = var.project_name
    Environment = var.environment
    Purpose     = "OpenAI API Authentication"
  })
}

# Discord Bot Token Secret (name/metadata only)
resource "aws_secretsmanager_secret" "discord_bot_token" {
  name                    = "${var.project_name}/${var.environment}/discord/bot-token"
  description             = "Discord bot token and application metadata"
  recovery_window_in_days = 7
  kms_key_id              = var.kms_key_arn

  tags = merge(var.additional_tags, {
    Name        = "${var.project_name}-${var.environment}-discord-bot-token"
    Project     = var.project_name
    Environment = var.environment
    Purpose     = "Discord Bot Authentication"
  })
}
