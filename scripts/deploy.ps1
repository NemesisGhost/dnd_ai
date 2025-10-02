#!/usr/bin/env powershell

param(
    [string]$Environment = "dev",
    [switch]$PlanOnly,
    [switch]$AutoApprove
)

$ErrorActionPreference = "Stop"

Write-Host "D&D AI Infrastructure Deployment Script" -ForegroundColor Cyan
Write-Host "Environment: $Environment" -ForegroundColor Yellow

# Change to environment directory
$EnvPath = Join-Path $PSScriptRoot ".." "terraform" "environments" $Environment
if (-not (Test-Path $EnvPath)) {
    Write-Error "Environment directory not found: $EnvPath"
    exit 1
}

Push-Location $EnvPath

try {
    # Set environment variables
    Write-Host "`nSetting environment variables..." -ForegroundColor Green
    & (Join-Path $PSScriptRoot "set-env.ps1")

    # Prepare Lambda function
    Write-Host "`nPreparing Lambda function..." -ForegroundColor Green
    python (Join-Path $PSScriptRoot "prepare_lambda.py")

    # Initialize Terraform
    Write-Host "`nInitializing Terraform..." -ForegroundColor Green
    terraform init

    # Validate configuration
    Write-Host "`nValidating Terraform configuration..." -ForegroundColor Green
    terraform validate

    # Plan deployment
    Write-Host "`nGenerating Terraform plan..." -ForegroundColor Green
    terraform plan -out=tfplan

    if ($PlanOnly) {
        Write-Host "`nPlan completed. Use -AutoApprove to apply changes." -ForegroundColor Yellow
        return
    }

    # Apply changes
    if ($AutoApprove) {
        Write-Host "`nApplying Terraform plan..." -ForegroundColor Green
        terraform apply tfplan
    } else {
        Write-Host "`nApplying Terraform plan (interactive)..." -ForegroundColor Green
        terraform apply tfplan
    }

    # Show outputs
    Write-Host "`nDeployment completed! Here are the outputs:" -ForegroundColor Green
    terraform output

    Write-Host "`nNext steps:" -ForegroundColor Cyan
    Write-Host "1. Note the database endpoint and credentials location" -ForegroundColor White
    Write-Host "2. The database should be automatically initialized with the schema" -ForegroundColor White
    Write-Host "3. Check the Lambda function logs if initialization fails" -ForegroundColor White

} catch {
    Write-Error "Deployment failed: $_"
    exit 1
} finally {
    Pop-Location
}