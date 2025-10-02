terraform {
  required_version = ">= 1.3.0"
}

locals {
  name = "db-runner"
}

data "aws_ssm_parameter" "al2023_ami" {
  # Amazon Linux 2023 x86_64 Kernel 6.1
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
}

resource "aws_security_group" "db_runner" {
  name        = "sg-${local.name}"
  description = "Security group for ${local.name} instance"
  vpc_id      = var.vpc_id

  egress {
    description = "Allow all egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = {
    Name = "${local.name}-sg"
    Role = local.name
  }
}

resource "aws_security_group_rule" "rds_ingress_from_runner" {
  type                     = "ingress"
  description              = "Allow Postgres 5432 from ${local.name}"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = var.rds_security_group_id
  source_security_group_id = aws_security_group.db_runner.id
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "db_runner" {
  name_prefix        = "${local.name}-role-"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags = {
    Role = local.name
  }
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.db_runner.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "inline" {
  statement {
    sid     = "SecretsRead"
    effect  = "Allow"
    actions = [
      "secretsmanager:GetSecretValue"
    ]
    resources = [var.db_secret_arn]
  }

  statement {
    sid     = "ListBucketPrefix"
    effect  = "Allow"
    actions = [
      "s3:ListBucket"
    ]
    resources = ["arn:aws:s3:::${var.sql_bucket}"]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.sql_prefix}/*"]
    }
  }

  statement {
    sid     = "GetSQLObjects"
    effect  = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion"
    ]
    resources = ["arn:aws:s3:::${var.sql_bucket}/${var.sql_prefix}/*"]
  }
}

resource "aws_iam_role_policy" "db_runner_inline" {
  name_prefix = "${local.name}-inline-"
  role        = aws_iam_role.db_runner.id
  policy      = data.aws_iam_policy_document.inline.json
}

resource "aws_iam_instance_profile" "db_runner" {
  name_prefix = "${local.name}-profile-"
  role        = aws_iam_role.db_runner.name
}

resource "aws_instance" "db_runner" {
  ami                         = data.aws_ssm_parameter.al2023_ami.value
  instance_type               = "t3.micro"
  subnet_id                   = var.private_subnet_ids[0]
  associate_public_ip_address = false

  vpc_security_group_ids = [aws_security_group.db_runner.id]

  iam_instance_profile = aws_iam_instance_profile.db_runner.name

  user_data_replace_on_change = true
  user_data = <<-EOF
              #!/bin/bash
              set -xeuo pipefail
              dnf -y update
              # Install PostgreSQL 15 client and jq (fallback to default postgresql if 15 is unavailable)
              dnf -y install postgresql15 jq || dnf -y install postgresql jq
              EOF

  tags = {
    Name = local.name
    Role = local.name
  }
}

# SSM Document to run PostgreSQL SQL files from S3 using credentials from Secrets Manager
resource "aws_ssm_document" "apply_postgres_sql" {
  name          = "ApplyPostgresSql"
  document_type = "Command"

  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Sync SQL files from S3 and apply them to a PostgreSQL database using psql."
    parameters = {
      S3Bucket = {
        type        = "String"
        description = "S3 bucket containing SQL files"
        default     = ""
      }
      S3Prefix = {
        type        = "String"
        description = "S3 key prefix of SQL files"
        default     = ""
      }
      SecretArn = {
        type        = "String"
        description = "Secrets Manager ARN with JSON {username,password}"
        default     = ""
      }
      Host = {
        type        = "String"
        description = "PostgreSQL host"
        default     = ""
      }
      DbName = {
        type        = "String"
        description = "Database name"
        default     = ""
      }
      Port = {
        type        = "String"
        description = "PostgreSQL port"
        default     = "5432"
      }
    }
    mainSteps = [
      {
        action = "aws:runShellScript"
        name   = "RunSql"
        inputs = {
          runCommand = [
            "set -euo pipefail",
            "TMPDIR=$(mktemp -d)",
            "aws s3 sync \"s3://{{S3Bucket}}/{{S3Prefix}}\" \"$TMPDIR\"",
            "creds=$(aws secretsmanager get-secret-value --secret-id \"{{SecretArn}}\" --query SecretString --output text)",
            "user=$(echo \"$creds\" | jq -r .username); export PGPASSWORD=$(echo \"$creds\" | jq -r .password)",
            "files=$(ls -1 \"$TMPDIR\"/*.sql 2>/dev/null | sort || true)",
            "if [ -z \"$files\" ]; then echo \"No SQL files to apply.\"; exit 0; fi",
            "for f in $files; do echo \"Applying $f\"; psql \"host={{Host}} port={{Port}} dbname={{DbName}} user=$user sslmode=require\" -v ON_ERROR_STOP=1 -f \"$f\"; done"
          ]
        }
      }
    ]
  })
}

# Association is created but effectively disabled by scheduling far in the future and only at cron interval.
resource "aws_ssm_association" "apply_postgres_sql_disabled" {
  name = aws_ssm_document.apply_postgres_sql.name

  targets {
    key    = "tag:Role"
    values = [local.name]
  }

  schedule_expression         = "cron(0 0 1 1 ? 2099)" # far future
  apply_only_at_cron_interval = true
}
