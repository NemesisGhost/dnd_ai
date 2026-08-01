# =====================================================
# GitHub Actions CI OIDC role
# =====================================================
# Lets the aws-verification job in .github/workflows/ci.yml assume an AWS
# role via GitHub's OIDC provider — no long-lived AWS access keys stored in
# GitHub. Scoped narrowly per docs/PLAN.md §29.9: this role may only open and
# close its own ingress rule on the dev database security group, nothing else.

data "aws_caller_identity" "current" {}

# GitHub's OIDC provider is one-per-account, not one-per-repo. Create it only
# where it doesn't already exist (create_oidc_provider = false elsewhere).
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  tags = {
    Name        = "${var.project_name}-github-actions-oidc"
    Project     = var.project_name
    Environment = var.environment
  }
}

locals {
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.existing_oidc_provider_arn
}

data "aws_iam_policy_document" "github_actions_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Repo-scoped, not branch-scoped: covers both push (ref:refs/heads/main)
    # and pull_request event subjects. Narrowing further to a specific ref
    # would block CI on pull requests from other branches.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_org}/${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github_actions_ci" {
  name               = "${var.project_name}-${var.environment}-github-actions-ci"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json

  tags = {
    Name        = "${var.project_name}-${var.environment}-github-actions-ci"
    Project     = var.project_name
    Environment = var.environment
  }
}

data "aws_iam_policy_document" "github_actions_permissions" {
  statement {
    sid    = "ManageDevIngressRule"
    effect = "Allow"
    actions = [
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:RevokeSecurityGroupIngress",
    ]
    resources = [
      for sg_id in var.security_group_ids :
      "arn:aws:ec2:*:${data.aws_caller_identity.current.account_id}:security-group/${sg_id}"
    ]
  }
}

resource "aws_iam_role_policy" "github_actions_permissions" {
  name   = "${var.project_name}-${var.environment}-github-actions-ci"
  role   = aws_iam_role.github_actions_ci.id
  policy = data.aws_iam_policy_document.github_actions_permissions.json
}
