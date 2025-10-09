variable "name_prefix" {
	type    = string
	default = "dnd-ai-dev"
}
variable "aws_region" {
	type    = string
	default = "us-east-1"
}

variable "secret_name_api_key" {
	type    = string
	default = "dnd-ai/dev/api-key"
}
variable "secret_name_basic_auth" {
	type    = string
	default = "dnd-ai/dev/basic-auth"
}

variable "api_key_value" {
	type    = string
	default = ""
}
variable "secret_arn_basic_auth" {
	type    = string
	default = ""
}

variable "db_host" { type = string }
variable "db_port" {
	type    = string
	default = "5432"
}
variable "db_name" { type = string }
variable "db_user" { type = string }

variable "vpc_subnet_ids" {
	type    = list(string)
	default = null
}
variable "vpc_security_group_ids" {
	type    = list(string)
	default = null
}

variable "api_path" {
	type    = string
	default = "query"
}
variable "http_method" {
	type    = string
	default = "POST"
}
variable "stage_name" {
	type    = string
	default = "dev"
}
variable "throttle_burst_limit" {
	type    = number
	default = 10
}
variable "throttle_rate_limit" {
	type    = number
	default = 5
}

variable "layer_arns" {
	type    = list(string)
	default = []
}

variable "rds_resource_id" {
	description = "RDS DB resource ID used in rds-db:connect ARN"
	type        = string
	default     = ""
}