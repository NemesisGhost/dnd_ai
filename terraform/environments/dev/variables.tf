# =====================================================
# Development Environment Variables
# =====================================================

variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

variable "owner_name" {
  description = "Name of the person/team owning this deployment"
  type        = string
  default     = "developer"
}

variable "my_ip_cidr" {
  description = "Your IP address in CIDR format for database access (e.g., '203.0.113.0/32')"
  type        = string
  default     = "0.0.0.0/0" # WARNING: This allows access from anywhere. Replace with your actual IP.
}

variable "enable_public_access" {
  description = "Enable public access to the database (for development only)"
  type        = bool
  default     = false
}

# OpenAI Configuration
variable "openai_api_key" {
  description = "OpenAI API key for ChatGPT integration"
  type        = string
  sensitive   = true
  default     = ""
}

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

# Discord Bot Configuration
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

# Additional tags
variable "additional_tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}