data "archive_file" "discord_openai_layer_file" {
  type        = "zip"
  source_dir  = "${path.module}/layers/discord_openai_layer"
  output_path = "${path.module}/layers/discord_openai_layer_file.zip"
  depends_on  = [null_resource.pip_install_discord_openai]
}

data "archive_file" "discord_openai_interactions_function" {
  type        = "zip"
  output_path = "${path.module}/code/discord_openai_interactions_function.zip"
  source_file  = "../Lambda_functions/interactions.py"
}

resource "aws_lambda_layer_version" "discord_openai_layer" {
    layer_name          = "discord_openai_layer"
    filename            = data.archive_file.discord_openai_layer_file.output_path
    source_code_hash    = data.archive_file.discord_openai_layer_file.output_base64sha256
    compatible_runtimes = ["python3.12"]
    compatible_architectures = ["x86_64"]
}

resource "aws_lambda_function" "discord_openai_lambda_function" {
  function_name = "discord_openai_lambda_function"
  handler       = "interactions.lambda_handler"
  runtime       = "python3.12"
  filename      = data.archive_file.discord_openai_interactions_function.output_path
  source_code_hash = data.archive_file.discord_openai_interactions_function.output_base64sha256
  role          = aws_iam_role.discord_openai_interactions_role.arn
  layers = [
    aws_lambda_layer_version.discord_openai_layer.arn,
    "arn:aws:lambda:us-east-2:590474943231:layer:AWS-Parameters-and-Secrets-Lambda-Extension:11"
  ]
  environment {
    variables = {
      PARAMETERS_SECRETS_EXTENSION_CACHE_SIZE = "2"
    }
  }
}