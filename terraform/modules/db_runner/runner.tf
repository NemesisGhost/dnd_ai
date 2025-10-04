data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
}

resource "aws_instance" "db_runner" {
  ami                    = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = "t3.micro"
  subnet_id              = var.private_subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.db_runner.id]
  iam_instance_profile   = aws_iam_instance_profile.db_runner.name
  user_data_replace_on_change = true

  # The user_data script installs psql and jq and embeds the SQL hash
  # so that any change to the scripts forces an instance replacement:contentReference[oaicite:0]{index=0}.
  user_data = <<-EOF
    #!/bin/bash
    set -xeuo pipefail
    # Hash of SQL scripts: ${local.sql_hash}
    dnf -y update
    dnf -y install postgresql15 jq || dnf -y install postgresql jq
    # Additional bootstrapping commands can go here, e.g. enabling SSM agent
  EOF

  tags = {
    Name = "${local.runner_name}-instance"
    Role = local.runner_name
  }
}
