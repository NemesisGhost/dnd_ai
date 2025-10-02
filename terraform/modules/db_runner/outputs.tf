output "runner_instance_id" {
  description = "ID of the db runner EC2 instance"
  value       = aws_instance.db_runner.id
}

output "runner_sg_id" {
  description = "ID of the security group for the db runner"
  value       = aws_security_group.db_runner.id
}
