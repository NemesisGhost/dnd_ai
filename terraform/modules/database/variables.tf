# =====================================================
# Database Module Variables
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

# Network Configuration
variable "vpc_id" {
  description = "ID of existing VPC (leave null to create new VPC)"
  type        = string
  default     = null
}

variable "vpc_cidr" {
  description = "CIDR block for VPC (used only if creating new VPC)"
  type        = string
  default     = "10.0.0.0/16"
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (used only with existing VPC)"
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "private_subnet_ids" {
  description = "IDs of existing private subnets to use (skip subnet creation when provided)"
  type        = list(string)
  default     = []
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed to connect to the database"
  type        = list(string)
  default     = ["10.0.0.0/16"]
}

variable "allowed_security_group_ids" {
  description = "Security group IDs allowed to connect to the database"
  type        = list(string)
  default     = []
}

# Database Configuration
variable "database_name" {
  description = "Name of the initial database"
  type        = string
  default     = "dnd_ai"
}

variable "master_username" {
  description = "Master username for the database"
  type        = string
  default     = "dnd_admin"
}

variable "postgres_version" {
  description = "PostgreSQL version"
  type        = string
  default     = "15.4"
}

variable "instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "allocated_storage" {
  description = "Initial allocated storage in GB"
  type        = number
  default     = 20
}

variable "max_allocated_storage" {
  description = "Maximum allocated storage in GB (for autoscaling)"
  type        = number
  default     = 100
}

variable "storage_type" {
  description = "Storage type (gp2, gp3, io1, io2)"
  type        = string
  default     = "gp3"
}

variable "publicly_accessible" {
  description = "Whether the database should be publicly accessible"
  type        = bool
  default     = false
}

# Backup and Maintenance
variable "backup_retention_period" {
  description = "Backup retention period in days"
  type        = number
  default     = 7
}

variable "backup_window" {
  description = "Preferred backup window (UTC)"
  type        = string
  default     = "03:00-04:00"
}

variable "maintenance_window" {
  description = "Preferred maintenance window (UTC)"
  type        = string
  default     = "sun:04:00-sun:05:00"
}

variable "deletion_protection" {
  description = "Enable deletion protection"
  type        = bool
  default     = true
}

variable "skip_final_snapshot" {
  description = "Skip final snapshot when deleting"
  type        = bool
  default     = false
}

# Monitoring and Performance
variable "enhanced_monitoring" {
  description = "Enable enhanced monitoring"
  type        = bool
  default     = true
}

variable "performance_insights_enabled" {
  description = "Enable Performance Insights"
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention period in days"
  type        = number
  default     = 7
}

# IAM Database Authentication
variable "iam_database_authentication_enabled" {
  description = "Enable IAM database authentication on the RDS instance"
  type        = bool
  default     = true
}

# Note: Database initialization is now handled separately
# via SQL migration scripts rather than Lambda functions

variable "create_vpc_endpoints" {
  description = "Whether to create VPC endpoints for AWS services (recommended for Lambda in VPC)"
  type        = bool
  default     = true
}

variable "use_nat_gateway" {
  description = "Whether to use NAT Gateway instead of VPC endpoints for internet access (more expensive but allows general internet access)"
  type        = bool
  default     = false
}

# Tags
variable "additional_tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}