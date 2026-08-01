# =====================================================
# GitHub Actions CI Module Outputs
# =====================================================

output "role_arn" {
  description = "ARN of the IAM role GitHub Actions assumes via OIDC — set as the AWS_CI_ROLE_ARN repository secret"
  value       = aws_iam_role.github_actions_ci.arn
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider (created here, or the existing one passed in)"
  value       = local.oidc_provider_arn
}
