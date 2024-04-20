# Discord Bot Token
variable "discord_bot_token" {
  type = string
  description = "Discord Secret Key"
}

resource "aws_secretsmanager_secret" "discord_bot_token" {
    name = "discord_bot_token"
    description = "Discord Bot ID Token"
    tags = {
        Name = "discord_bot_token"
        Environment = var.app_environment
    }
}

resource "aws_secretsmanager_secret_version" "discord_bot_token" {
  secret_id     = aws_secretsmanager_secret.discord_bot_token.id
  secret_string = var.discord_bot_token
}

# OpenAI API Key
variable "openai_apikey" {
  type = string
  description = "OpenAI Secret Key"
}

resource "aws_secretsmanager_secret" "openai_apikey" {
    name = "openai_apikey"
    description = "OpenAI API Key"
    tags = {
        Name = "openai_apikey"
        Environment = var.app_environment
    }
} 

resource "aws_secretsmanager_secret_version" "openai_apikey" {
  secret_id     = aws_secretsmanager_secret.openai_apikey.id
  secret_string = var.openai_apikey
}