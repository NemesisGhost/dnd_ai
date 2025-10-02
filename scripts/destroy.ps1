#!/usr/bin/env powershell

param(
    [string]$Environment = "dev",
    [switch]$AutoApprove
)

$ErrorActionPreference = "Stop"

Write-Host "D&D AI Infrastructure Destruction Script" -ForegroundColor Red
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

    # Plan destruction
    Write-Host "`nGenerating destruction plan..." -ForegroundColor Red
    terraform plan -destroy -out=destroy-plan

    # Confirm destruction
    if (-not $AutoApprove) {
        $confirmation = Read-Host "`nAre you sure you want to destroy all resources? Type 'yes' to confirm"
        if ($confirmation -ne "yes") {
            Write-Host "Destruction cancelled." -ForegroundColor Yellow
            return
        }
    }

    # Apply destruction
    Write-Host "`nDestroying infrastructure..." -ForegroundColor Red
    if ($AutoApprove) {
        terraform apply destroy-plan
    } else {
        terraform apply destroy-plan
    }

    Write-Host "`nInfrastructure destroyed successfully!" -ForegroundColor Green

} catch {
    Write-Error "Destruction failed: $_"
    exit 1
} finally {
    Pop-Location
}