resource "aws_ssm_document" "apply_postgres_sql" {
  name          = "${local.runner_name}-apply-sql"
  document_type = "Command"

  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Apply PostgreSQL schema and seed data using a manifest"
    parameters    = {
      SQLBucket = {
        type        = "String"
        description = "S3 bucket where SQL files reside"
        default     = aws_s3_bucket.sql_bucket.bucket
      }
      SQLPrefix = {
        type        = "String"
        description = "S3 prefix for SQL files"
        default     = var.sql_prefix
      }
      SecretArn = {
        type        = "String"
        description = "Secrets Manager ARN containing DB credentials"
        default     = var.db_secret_arn
      }
      DBName = {
        type        = "String"
        description = "Target PostgreSQL database name (fallback if not in secret)"
        default     = var.db_name
      }
    }
    mainSteps     = [{
      action = "aws:runShellScript"
      name   = "ApplySql"
      inputs = {
        runCommand = [
          "set -eo pipefail",
          "mkdir -p /tmp/sql",
          # Sync entire folder (including order.txt) from S3
          "aws s3 sync s3://${aws_s3_bucket.sql_bucket.bucket}/${var.sql_prefix} /tmp/sql",
          "# Retrieve DB credentials from Secrets Manager",
          "SECRET_JSON=$(aws secretsmanager get-secret-value --secret-id {{ SecretArn }} --query SecretString --output text)",
          "export PGHOST=$(echo \"$SECRET_JSON\" | jq -r .host)",
          "export PGPORT=$(echo \"$SECRET_JSON\" | jq -r .port)",
          "export PGUSER=$(echo \"$SECRET_JSON\" | jq -r .username)",
          "export PGPASSWORD=$(echo \"$SECRET_JSON\" | jq -r .password)",
          "DB_IN_SECRET=$(echo \"$SECRET_JSON\" | jq -r '.dbname // empty')",
          "if [ -n \"$DB_IN_SECRET\" ]; then",
          "  export PGDATABASE=\"$DB_IN_SECRET\"",
          "else",
          "  export PGDATABASE='{{ DBName }}'",
          "fi",
          "echo \"Connecting to $PGUSER@$PGHOST:$PGPORT/$PGDATABASE\"",
          # Execute files in the order specified in order.txt
          "while read sql_file; do",
          "  if [ -f \"/tmp/sql/$sql_file\" ]; then",
          "    echo \"Applying $sql_file\"",
          "    psql --set=ON_ERROR_STOP=1 -f \"/tmp/sql/$sql_file\"",
          "  else",
          "    echo \"Warning: file $sql_file not found in /tmp/sql\"",
          "  fi",
          "done < /tmp/sql/order.txt"
        ]
      }
    }]
  })
}

resource "null_resource" "apply_sql_now" {
  triggers = {
    sql_hash = local.sql_hash
  }
  provisioner "local-exec" {
    command = <<-EOT
      aws s3 sync ${local.database_dir} s3://${aws_s3_bucket.sql_bucket.bucket}/${var.sql_prefix} --delete
      aws ssm send-command \
        --document-name ${aws_ssm_document.apply_postgres_sql.name} \
        --targets "Key=tag:Role,Values=${local.runner_name}" \
        --comment "Apply SQL" \
        --timeout-seconds 600 \
        --max-concurrency "1" \
        --max-errors "0"
    EOT
  }
}