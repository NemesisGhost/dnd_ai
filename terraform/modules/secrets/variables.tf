# =====================================================
# Secrets Management Module Variables
# =====================================================

variable "project_name" {
  description = "Name of the project"
  type        = string
  default     = "dnd-ai"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "kms_key_arn" {
  description = "ARN of the KMS key for encryption"
  type        = string
}

# API Keys and Tokens
variable "openai_api_key" {
  description = "OpenAI API key for ChatGPT integration"
  type        = string
  sensitive   = true
  default     = ""
}

variable "discord_bot_token" {
  description = "Discord bot token for bot authentication"
  type        = string
  sensitive   = true
  default     = ""
}

variable "discord_application_id" {
  description = "Discord application ID"
  type        = string
  default     = ""
}

variable "discord_public_key" {
  description = "Discord application public key"
  type        = string
  default     = ""
}

# Other Configuration Values
variable "openai_organization_id" {
  description = "OpenAI organization ID (optional)"
  type        = string
  default     = ""
}

variable "openai_model" {
  description = "Default OpenAI model to use"
  type        = string
  default     = "gpt-4"
}

variable "max_tokens" {
  description = "Maximum tokens for OpenAI API calls"
  type        = number
  default     = 4000
}

variable "temperature" {
  description = "Temperature for OpenAI API calls"
  type        = number
  default     = 0.7
}

# Tags
variable "additional_tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}