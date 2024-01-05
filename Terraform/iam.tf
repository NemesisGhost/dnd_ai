resource "aws_iam_role" "discord_openai_interactions_role" {
    name = "discord_openai_interactions_role"
    assume_role_policy    = jsonencode(
        {
            Statement = [
                {
                    Action    = "sts:AssumeRole"
                    Effect    = "Allow"
                    Principal = {
                        Service = "lambda.amazonaws.com"
                    }
                }
            ]
            Version   = "2012-10-17"
        }
    )
    inline_policy {
        name = "discord_bot_secret_policy"
        policy = jsonencode(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": "secretsmanager:GetSecretValue",
                        "Resource": [
                            aws_secretsmanager_secret_version.discord_bot_token.arn,
                            aws_secretsmanager_secret_version.openai_apikey.arn
                        ]
                    }
                ]
            }
        )
    }
}