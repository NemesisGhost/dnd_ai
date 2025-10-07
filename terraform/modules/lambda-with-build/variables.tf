variable "repo_root" { type = string }
variable "name_prefix" { type = string }
variable "region" { type = string }

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

variable "allow_rds_iam_auth" {
	type    = bool
	default = false
}
variable "rds_dbuser_arns" {
	type    = list(string)
	default = []
}

# CORS passthrough to lambda-api
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

# Build inputs
variable "requirements_path" { type = string }
variable "extra_layer_arns" {
	type    = list(string)
	default = []
}
variable "function_trigger_files" {
	type    = list(string)
	default = []
}
variable "authorizer_trigger_files" {
	type    = list(string)
	default = []
}
variable "python_exe" {
	type    = string
	default = "python"
}

# Optional build function names for scripts/build_lambda.ps1
variable "build_function_name" { type = string }
variable "build_authorizer_function_name" {
	type    = string
	default = "basic_auth_authorizer"
}
