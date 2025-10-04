# 1. Trust policy allowing EC2 to assume the role
data "aws_iam_policy_document" "assume_ec2_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# 2. IAM role for the runner instance
resource "aws_iam_role" "db_runner" {
  name_prefix        = "${local.runner_name}-role-"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2_role.json

  tags = {
    Role = local.runner_name
  }
}

# 3. Attach the AWS‑managed SSM policy so the instance can register with Systems Manager
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.db_runner.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# 4. Inline policy granting access to Secrets Manager and the SQL S3 bucket
data "aws_iam_policy_document" "db_runner_inline" {
  # Allow reading the database credentials
  statement {
    sid       = "SecretsRead"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.db_secret_arn]
  }

  # Allow listing the bucket under the specified prefix
  statement {
    sid     = "ListBucketPrefix"
    effect  = "Allow"
    actions = ["s3:ListBucket"]
    resources = [
      "arn:aws:s3:::${aws_s3_bucket.sql_bucket.bucket}"
    ]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.sql_prefix}/*"]
    }
  }

  # Allow downloading the SQL files
  statement {
    sid     = "GetSQLObjects"
    effect  = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion"
    ]
    resources = [
      "arn:aws:s3:::${aws_s3_bucket.sql_bucket.bucket}/${var.sql_prefix}/*"
    ]
  }
}

resource "aws_iam_role_policy" "db_runner_inline" {
  name_prefix = "${local.runner_name}-inline-"
  role        = aws_iam_role.db_runner.id
  policy      = data.aws_iam_policy_document.db_runner_inline.json
}

# 5. Instance profile that associates the role with an EC2 instance
resource "aws_iam_instance_profile" "db_runner" {
  name_prefix = "${local.runner_name}-profile-"
  role        = aws_iam_role.db_runner.name
}

# Security group for the DB runner EC2 instance
resource "aws_security_group" "db_runner" {
  name        = "${local.runner_name}-sg"
  description = "Security group for ${local.runner_name} instance"
  vpc_id      = var.vpc_id

  # Allow all outbound traffic so the runner can reach SSM, S3, Secrets Manager and RDS
  egress {
    description      = "Allow all outbound"
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = {
    Name = "${local.runner_name}-sg"
    Role = local.runner_name
  }
}

resource "aws_security_group_rule" "rds_ingress_from_runner" {
  type                     = "ingress"
  description              = "Allow Postgres 5432 from ${local.runner_name}"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = var.rds_security_group_id
  source_security_group_id = aws_security_group.db_runner.id
}