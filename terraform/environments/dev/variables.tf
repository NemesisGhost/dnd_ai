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


# Additional tags
variable "additional_tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}

# -----------------------------------------------------
# db_schema_introspect API inputs
# -----------------------------------------------------
variable "name_prefix" {
  description = "Name prefix for resources"
  type        = string
  default     = "dnd-ai-dev"
}

variable "api_secret_name_api_key" {
  description = "Secrets Manager name of the API Key secret containing JSON {api_key}"
  type        = string
  default     = "dnd-ai/dev/api-key"
}

variable "api_secret_name_basic_auth" {
  description = "Secrets Manager name of the Basic Auth secret containing JSON {username,password}"
  type        = string
  default     = "dnd-ai/dev/basic-auth"
}

variable "db_host" {
  description = "DB host"
  type        = string
  default     = ""
}
variable "db_port" {
  description = "DB port"
  type        = string
  default     = "5432"
}
variable "db_name" {
  description = "DB name"
  type        = string
  default     = ""
}
variable "db_user" {
  description = "DB user"
  type        = string
  default     = ""
}
variable "db_password" {
  description = "DB password"
  type        = string
  default     = ""
}
variable "db_schemas" {
  description = "Comma-separated schemas"
  type        = string
  default     = "public"
}

variable "api_path" {
  description = "API resource path"
  type        = string
  default     = "db-schema"
}
variable "http_method" {
  description = "HTTP method"
  type        = string
  default     = "POST"
}
variable "stage_name" {
  description = "API Gateway stage name"
  type        = string
  default     = "dev"
}
variable "throttle_burst_limit" {
  description = "Usage plan burst limit"
  type        = number
  default     = 10
}
variable "throttle_rate_limit" {
  description = "Usage plan rate limit"
  type        = number
  default     = 5
}

# SQL Runner inputs
variable "sql_bucket" {
  description = "S3 bucket name containing SQL files for the db runner"
  type        = string
  default     = ""
}

variable "sql_prefix" {
  description = "S3 key prefix under which SQL files are stored (e.g., 'dnd/sql')"
  type        = string
  default     = "dnd/sql"
}

# Optional wiring variables (exposed for flexibility when not using the bundled database module)
variable "vpc_id" {
  description = "VPC ID to deploy supporting resources (if overriding module-provided VPC)"
  type        = string
  default     = ""
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for placing the SQL runner EC2 (if overriding module outputs)"
  type        = list(string)
  default     = []
}

variable "rds_security_group_id" {
  description = "Security Group ID attached to the PostgreSQL RDS instance to open 5432 from the runner"
  type        = string
  default     = ""
}

variable "db_secret_arn" {
  description = "Secrets Manager ARN containing JSON {username,password} for DB access"
  type        = string
  default     = ""
}

variable "runner_db_name_override" {
  description = "Override: Target PostgreSQL database name for migrations (leave empty to use module output)"
  type        = string
  default     = ""
}