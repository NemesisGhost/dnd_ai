<#
.SYNOPSIS
  Upserts secret values into AWS Secrets Manager for this project without exposing them to Terraform state or git.

.DESCRIPTION
  Reads a local JSON file (excluded from git) and writes values to Secrets Manager using PutSecretValue.
  Secrets must already exist (created by the Terraform secrets module). Each secret value is stored as a JSON object.

.PARAMETER Environment
  Environment name (dev|staging|prod)

.PARAMETER Region
  AWS region, defaults to us-east-1

.PARAMETER File
  Path to the local JSON file containing secret values.

.EXAMPLE
  ./upsert-secrets.ps1 -Environment dev -Region us-east-1 -File ../environments/dev/secrets.local.json

  The JSON file structure:
  {
    "openai": { "api_key": "sk-...", "organization_id": "org_..." },
    "discord": { "bot_token": "...", "application_id": "...", "public_key": "..." }
  }
#>

param(
  [Parameter(Mandatory=$true)][ValidateSet('dev','staging','prod')] [string]$Environment,
  [string]$Region = 'us-east-1',
  [Parameter(Mandatory=$true)] [string]$File
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $File)) {
  throw "Secrets file not found: $File"
}

$json = Get-Content -Raw -Path $File | ConvertFrom-Json

function Set-SecretJson {
  param(
    [Parameter(Mandatory=$true)][string]$Name,
    [Parameter(Mandatory=$true)]$Object
  )
  $secretString = ($Object | ConvertTo-Json -Depth 10)

  # Ensure secret exists
  try {
    $null = aws --region $Region secretsmanager describe-secret --secret-id $Name | Out-Null
  } catch {
    throw "Secret does not exist: $Name. Run terraform apply to create secrets first."
  }

  # Put a new version (does not expose value to TF state)
  aws --region $Region secretsmanager put-secret-value --secret-id $Name --secret-string $secretString | Out-Null
  Write-Host "Updated secret: $Name"
}

$project = 'dnd-ai'

if ($json.openai) {
  $name = "$project/$Environment/openai/api-key"
  Set-SecretJson -Name $name -Object $json.openai
}

if ($json.discord) {
  $name = "$project/$Environment/discord/bot-token"
  Set-SecretJson -Name $name -Object $json.discord
}

Write-Host "Secrets upsert complete."
