variable "name_prefix" { type = string }
variable "function_name" { type = string }
variable "lambda_zip" { type = string }
variable "handler" { type = string }
variable "runtime" {
	type    = string
	default = "python3.11"
}
variable "timeout" {
	type    = number
	default = 30
}
variable "memory_size" {
	type    = number
	default = 512
}
variable "layer_arns" {
	type    = list(string)
	default = []
}
variable "environment" {
	type    = map(string)
	default = {}
}

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
variable "region" { type = string }

variable "api_key_value" { type = string }
variable "throttle_burst_limit" {
	type    = number
	default = 10
}
variable "throttle_rate_limit" {
	type    = number
	default = 5
}

variable "authorizer_zip" { type = string }
variable "authorizer_handler" {
	type    = string
	default = "app.handler"
}
variable "secret_id_basic_auth" { type = string }

# Optional CORS support for browser clients
variable "enable_cors" {
	type    = bool
	default = false
}
variable "cors_allow_origin" {
	type    = string
	default = "*"
}
variable "cors_allow_headers" {
	type    = string
	default = "Authorization,x-api-key,Content-Type"
}
variable "cors_allow_methods" {
	type    = string
	default = "OPTIONS,POST"
}

# Optional: IAM DB auth wiring
variable "allow_rds_iam_auth" {
	type        = bool
	default     = false
	description = "If true, attach policy to allow rds:GenerateDBAuthToken and rds-db:connect to specified resources"
}
variable "rds_dbuser_arns" {
	type        = list(string)
	default     = []
	description = "List of arn:aws:rds-db:...:dbuser:<resource-id>/<db-username> ARNs to allow rds-db:connect"
}
