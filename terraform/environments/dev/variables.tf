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

# Optional wiring variables (exposed for flexibility when not using the bundled database module)
variable "vpc_id" {
  description = "VPC ID to deploy supporting resources (if overriding module-provided VPC)"
  type        = string
  default     = ""
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for supporting resources (if overriding module outputs)"
  type        = list(string)
  default     = []
}
