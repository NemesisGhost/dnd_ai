# =====================================================
# Secrets Management Module
# =====================================================

# OpenAI API Key Secret
resource "aws_secretsmanager_secret" "openai_api_key" {
  count = var.openai_api_key != "" ? 1 : 0

  name                    = "${var.project_name}/${var.environment}/openai/api-key"
  description             = "OpenAI API key for ChatGPT integration"
  recovery_window_in_days = 7
  kms_key_id             = var.kms_key_arn

  tags = merge(var.additional_tags, {
    Name        = "${var.project_name}-${var.environment}-openai-api-key"
    Project     = var.project_name
    Environment = var.environment
    Purpose     = "OpenAI API Authentication"
  })
}

resource "aws_secretsmanager_secret_version" "openai_api_key" {
  count = var.openai_api_key != "" ? 1 : 0

  secret_id = aws_secretsmanager_secret.openai_api_key[0].id
  secret_string = jsonencode({
    api_key           = var.openai_api_key
    organization_id   = var.openai_organization_id
    default_model     = var.openai_model
    max_tokens        = var.max_tokens
    temperature       = var.temperature
  })
}

# Discord Bot Token Secret
resource "aws_secretsmanager_secret" "discord_bot_token" {
  count = var.discord_bot_token != "" ? 1 : 0

  name                    = "${var.project_name}/${var.environment}/discord/bot-token"
  description             = "Discord bot token and configuration"
  recovery_window_in_days = 7
  kms_key_id             = var.kms_key_arn

  tags = merge(var.additional_tags, {
    Name        = "${var.project_name}-${var.environment}-discord-bot-token"
    Project     = var.project_name
    Environment = var.environment
    Purpose     = "Discord Bot Authentication"
  })
}

resource "aws_secretsmanager_secret_version" "discord_bot_token" {
  count = var.discord_bot_token != "" ? 1 : 0

  secret_id = aws_secretsmanager_secret.discord_bot_token[0].id
  secret_string = jsonencode({
    bot_token      = var.discord_bot_token
    application_id = var.discord_application_id
    public_key     = var.discord_public_key
  })
}

# Application Configuration Secret
resource "aws_secretsmanager_secret" "app_config" {
  name                    = "${var.project_name}/${var.environment}/application/config"
  description             = "General application configuration values"
  recovery_window_in_days = 7
  kms_key_id             = var.kms_key_arn

  tags = merge(var.additional_tags, {
    Name        = "${var.project_name}-${var.environment}-app-config"
    Project     = var.project_name
    Environment = var.environment
    Purpose     = "Application Configuration"
  })
}

resource "aws_secretsmanager_secret_version" "app_config" {
  secret_id = aws_secretsmanager_secret.app_config.id
  secret_string = jsonencode({
    project_name    = var.project_name
    environment     = var.environment
    openai_model    = var.openai_model
    max_tokens      = var.max_tokens
    temperature     = var.temperature
    debug_mode      = var.environment == "dev" ? true : false
    log_level       = var.environment == "dev" ? "DEBUG" : "INFO"
  })
}