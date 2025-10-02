# =====================================================
# Lambda Functions Module Variables
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

# Networking Configuration
variable "vpc_id" {
  description = "VPC ID where Lambda functions will be deployed"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for Lambda functions (typically private subnets)"
  type        = list(string)
}

variable "database_security_group_id" {
  description = "Security group ID that allows database access"
  type        = string
  default     = ""
}

# Database Configuration
variable "database_secret_arn" {
  description = "ARN of the Secrets Manager secret containing database credentials"
  type        = string
}

variable "kms_key_arn" {
  description = "ARN of the KMS key for encryption"
  type        = string
}

# Lambda Configuration
variable "lambda_runtime" {
  description = "Lambda runtime version"
  type        = string
  default     = "python3.11"
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 300
}

variable "lambda_memory_size" {
  description = "Lambda function memory size in MB"
  type        = number
  default     = 512
}

variable "log_retention_days" {
  description = "CloudWatch log retention period in days"
  type        = number
  default     = 7
}

# AI Integration
variable "openai_api_key_secret_arn" {
  description = "ARN of the Secrets Manager secret containing OpenAI API key"
  type        = string
  default     = ""
}

variable "discord_token_secret_arn" {
  description = "ARN of the Secrets Manager secret containing Discord bot token"
  type        = string
  default     = ""
}

# Tags
variable "additional_tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}