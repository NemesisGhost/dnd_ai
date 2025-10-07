output "api_invoke_url" {
  value = "https://${aws_api_gateway_rest_api.this.id}.execute-api.${var.region}.amazonaws.com/${aws_api_gateway_stage.this.stage_name}${aws_api_gateway_resource.proxy.path}"
}

output "lambda_arn" {
  value = aws_lambda_function.this.arn
}

output "authorizer_arn" {
  value = aws_lambda_function.authorizer.arn
}

output "lambda_execution_role_arn" {
  value = aws_iam_role.lambda_exec.arn
}
