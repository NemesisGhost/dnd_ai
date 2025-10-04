output "sql_bucket_name" {
  description = "Name of the S3 bucket created for SQL files"
  value       = aws_s3_bucket.sql_bucket.bucket
}

output "runner_instance_id" {
  description = "ID of the EC2 instance running the DB runner"
  value       = aws_instance.db_runner.id
}

output "runner_security_group_id" {
  description = "Security group ID attached to the runner"
  value       = aws_security_group.db_runner.id
}

output "apply_postgres_sql_document" {
  description = "Name of the SSM document used to apply SQL"
  value       = aws_ssm_document.apply_postgres_sql.name
}