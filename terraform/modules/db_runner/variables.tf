variable "vpc_id" {
  description = "VPC ID where the runner will be deployed"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for the runner instance"
  type        = list(string)
}

variable "rds_security_group_id" {
  description = "Security Group ID of the target RDS to allow ingress from the runner"
  type        = string
}

variable "db_secret_arn" {
  description = "ARN of the Secrets Manager secret containing DB credentials"
  type        = string
}

variable "db_name" {
  description = "Target PostgreSQL database name (if not included in secret)"
  type        = string
  default     = ""
}

variable "sql_bucket_name" {
  description = "Name of the S3 bucket to store SQL files. Leave empty to let Terraform generate a unique name."
  type        = string
  default     = ""
}

variable "sql_prefix" {
  description = "S3 key prefix under which SQL files are stored (e.g., 'dnd/sql')"
  type        = string
  default     = "dnd/sql"
}
