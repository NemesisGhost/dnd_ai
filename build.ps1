<#
.SYNOPSIS
  End-to-end build/deploy script for any environment.

.DESCRIPTION
  Orchestrates Terraform (init/plan/apply/destroy) for the selected environment
  and runs post-deploy steps like Secrets Manager upserts. Keeps secret values
  out of git and Terraform state by using a local JSON file and AWS CLI.

.PARAMETER Environment
  Target environment: dev | staging | prod

.PARAMETER Action
  Terraform action: plan | apply | destroy (default: apply)

.PARAMETER Region
  AWS region (default: us-east-1)

.PARAMETER VarsFile
  Optional tfvars file to pass to Terraform.
  If not specified, defaults to terraform/environments/<env>/terraform.tfvars when present.

.PARAMETER AutoApprove
  Skip interactive approval on apply/destroy.

.PARAMETER Upgrade
  Run 'terraform init -upgrade'.

.PARAMETER SecretsFile
  Path to local secrets JSON to upsert after successful apply.
  If not provided, defaults to terraform/environments/<env>/secrets.local.json when present.

.PARAMETER SkipSecrets
  Skip secrets upsert step.

.PARAMETER AwsProfile
  Optional AWS CLI profile to use (sets AWS_PROFILE for child processes).

.EXAMPLE
  # Apply dev using environment tfvars and upsert secrets if file exists
  ./build.ps1 -Environment dev -Action apply -AutoApprove

.EXAMPLE
  # Plan staging with a specific tfvars
  ./build.ps1 -Environment staging -Action plan -VarsFile ./terraform/environments/staging/custom.tfvars

.EXAMPLE
  # Apply prod and explicitly supply secrets file
  ./build.ps1 -Environment prod -Action apply -AutoApprove -SecretsFile ./terraform/environments/prod/secrets.local.json

.NOTES
  Requires Terraform and AWS CLI installed and on PATH.
  The upsert-secrets step requires permissions to PutSecretValue.
#>

param(
  [Parameter(Mandatory=$true)][ValidateSet('dev','staging','prod','production')] [string]$Environment,
  [ValidateSet('plan','apply','destroy')] [string]$Action = 'apply',
  [string]$Region = 'us-east-1',
  [string]$VarsFile,
  [switch]$AutoApprove,
  [switch]$Upgrade,
  [string]$SecretsFile,
  [switch]$SkipSecrets,
  [string]$AwsProfile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Normalize environment name
if ($Environment -eq 'production') { $Environment = 'prod' }

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvDir   = Join-Path $RepoRoot "terraform\environments\$Environment"
$UpsertScript = Join-Path $RepoRoot "terraform\scripts\upsert-secrets.ps1"

if (-not (Test-Path $EnvDir)) {
  throw "Environment folder not found: $EnvDir"
}

# Determine tfvars file
if (-not $VarsFile) {
  $DefaultTfVars = Join-Path $EnvDir 'terraform.tfvars'
  if (Test-Path $DefaultTfVars) { $VarsFile = $DefaultTfVars }
}

# Optionally set AWS_PROFILE for child processes
$originalAwsProfile = $env:AWS_PROFILE
if ($AwsProfile) { $env:AWS_PROFILE = $AwsProfile }

try {
  Write-Host "==> Terraform init ($Environment)" -ForegroundColor Cyan
  $initArgs = @("-chdir=$EnvDir", 'init')
  if ($Upgrade) { $initArgs += '-upgrade' }
  & terraform @initArgs

  if ($LASTEXITCODE -ne 0) { throw "terraform init failed with exit code $LASTEXITCODE" }

  switch ($Action) {
    'plan' {
      Write-Host "==> Terraform plan ($Environment)" -ForegroundColor Cyan
      $planArgs = @("-chdir=$EnvDir", 'plan', "-var=aws_region=$Region")
      if ($VarsFile) { $planArgs += @('-var-file', $VarsFile) }
      & terraform @planArgs
      if ($LASTEXITCODE -ne 0) { throw "terraform plan failed with exit code $LASTEXITCODE" }
    }
    'apply' {
      Write-Host "==> Terraform apply ($Environment)" -ForegroundColor Cyan
      $applyArgs = @("-chdir=$EnvDir", 'apply', "-var=aws_region=$Region")
      if ($VarsFile) { $applyArgs += @('-var-file', $VarsFile) }
      if ($AutoApprove) { $applyArgs += '-auto-approve' }
      & terraform @applyArgs
      if ($LASTEXITCODE -ne 0) { throw "terraform apply failed with exit code $LASTEXITCODE" }

      if (-not $SkipSecrets) {
        # Determine secrets file
        if (-not $SecretsFile) {
          $DefaultSecrets = Join-Path $EnvDir 'secrets.local.json'
          if (Test-Path $DefaultSecrets) { $SecretsFile = $DefaultSecrets }
        }
        if ($SecretsFile) {
          if (-not (Test-Path $UpsertScript)) {
            Write-Warning "Upsert script not found at $UpsertScript. Skipping secrets upsert."
          } else {
            Write-Host "==> Upserting secrets from $SecretsFile" -ForegroundColor Cyan
            & $UpsertScript -Environment $Environment -Region $Region -File $SecretsFile
            if ($LASTEXITCODE -ne 0) { throw "Secrets upsert failed with exit code $LASTEXITCODE" }
          }
        } else {
          Write-Host "No secrets file provided or found; skipping secrets upsert." -ForegroundColor Yellow
        }
      } else {
        Write-Host "SkipSecrets flag set; skipping secrets upsert." -ForegroundColor Yellow
      }
    }
    'destroy' {
      Write-Host "==> Terraform destroy ($Environment)" -ForegroundColor Cyan
      $destroyArgs = @("-chdir=$EnvDir", 'destroy', "-var=aws_region=$Region")
      if ($VarsFile) { $destroyArgs += @('-var-file', $VarsFile) }
      if ($AutoApprove) { $destroyArgs += '-auto-approve' }
      & terraform @destroyArgs
      if ($LASTEXITCODE -ne 0) { throw "terraform destroy failed with exit code $LASTEXITCODE" }

      Write-Host "Destroy complete. Skipping post-deploy steps." -ForegroundColor Yellow
    }
  }

  # Optional: show a brief output summary
  try {
    Write-Host "==> Terraform outputs ($Environment)" -ForegroundColor Cyan
    & terraform -chdir=$EnvDir output
  } catch {
    Write-Host "Could not display outputs." -ForegroundColor Yellow
  }

  Write-Host "All done." -ForegroundColor Green
}
finally {
  # Restore AWS_PROFILE
  $env:AWS_PROFILE = $originalAwsProfile
}