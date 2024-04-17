resource "aws_apigatewayv2_api" "discord_openai_interactions_gateway" {
  name          = "discord_openai_interactions_gateway"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "discord_openai_lambda_handler" {
  api_id = aws_apigatewayv2_api.discord_openai_interactions_gateway.id

  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.discord_openai_lambda_function.invoke_arn
}

resource "aws_apigatewayv2_route" "post_handler" {
  api_id    = aws_apigatewayv2_api.discord_openai_interactions_gateway.id
  route_key = "ANY /interactions"

  target = "integrations/${aws_apigatewayv2_integration.discord_openai_lambda_handler.id}"
  authorization_type   = "AWS_IAM"
}

resource "aws_apigatewayv2_stage" "discord_stage" {
  api_id = aws_apigatewayv2_api.discord_openai_interactions_gateway.id

  name = "dev"
  auto_deploy = true
}