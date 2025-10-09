variable "name_prefix" { type = string }
variable "aws_region" { type = string }

variable "db_host" { type = string }
variable "db_port" { type = string }
variable "db_name" { type = string }
variable "db_user" { type = string }
variable "rds_resource_id" { type = string }
variable "db_schemas" {
	type    = string
	default = "public"
}

variable "api_path" {
	type    = string
	default = "db-schema"
}
variable "http_method" {
	type    = string
	default = "POST"
}
variable "stage_name" {
	type    = string
	default = "dev"
}

variable "secret_name_api_key" { type = string }
variable "secret_name_basic_auth" { type = string }

# Optional direct wiring to avoid plan-time data source lookups
variable "api_key_value" {
	type    = string
	default = ""
}
variable "secret_arn_basic_auth" {
	type    = string
	default = ""
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

variable "vpc_subnet_ids" {
	type    = list(string)
	default = null
}
variable "vpc_security_group_ids" {
	type    = list(string)
	default = null
}
