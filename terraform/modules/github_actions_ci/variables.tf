# =====================================================
# GitHub Actions CI Module Variables
# =====================================================

variable "project_name" {
  description = "Name of the project"
  type        = string
  default     = "dnd-ai"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "github_org" {
  description = "GitHub organization or user that owns the repository"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name (without the org/user prefix)"
  type        = string
}

variable "create_oidc_provider" {
  description = <<-EOT
    Whether to create the GitHub Actions OIDC identity provider. AWS allows
    only one provider per issuer URL per account — set this to false and
    supply `existing_oidc_provider_arn` if a provider for
    token.actions.githubusercontent.com already exists (e.g. created by
    another environment's apply).
  EOT
  type        = bool
  default     = true
}

variable "existing_oidc_provider_arn" {
  description = "ARN of an existing GitHub OIDC provider, used when create_oidc_provider is false"
  type        = string
  default     = ""
}

variable "security_group_ids" {
  description = <<-EOT
    Security group IDs the CI role may manage ingress rules on — scoped to
    ec2:AuthorizeSecurityGroupIngress / RevokeSecurityGroupIngress only, per
    the dev reachability mechanism in docs/PLAN.md §29.9. Never grant this
    role broader EC2 permissions.
  EOT
  type        = list(string)
}

# Tags
variable "additional_tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
