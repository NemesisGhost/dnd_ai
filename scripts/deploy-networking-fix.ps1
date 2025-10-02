# Database Module Networking Fix Deployment Script (PowerShell)

$ErrorActionPreference = "Stop"

Write-Host "🔧 Applying Database Module Networking Fixes..." -ForegroundColor Cyan

# Change to terraform directory
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

# Check if we're in the right directory
if (-not (Test-Path "main.tf")) {
    Write-Host "❌ Error: main.tf not found. Make sure you're in the database module directory." -ForegroundColor Red
    exit 1
}

Write-Host "📋 Planning Terraform changes..." -ForegroundColor Yellow
terraform plan -out=networking-fix.tfplan

Write-Host ""
Write-Host "📊 Review the plan above. The following resources should be created/modified:" -ForegroundColor Green
Write-Host "  ✅ VPC Endpoints for Secrets Manager and KMS" -ForegroundColor Green
Write-Host "  ✅ Security groups for Lambda and VPC endpoints" -ForegroundColor Green
Write-Host "  ✅ Updated Lambda function with new security group" -ForegroundColor Green
Write-Host "  ✅ Optional NAT Gateway resources (if enabled)" -ForegroundColor Green

Write-Host ""
$response = Read-Host "🤔 Do you want to apply these changes? (y/N)"

if ($response -match "^[Yy]$") {
    Write-Host "🚀 Applying changes..." -ForegroundColor Cyan
    terraform apply networking-fix.tfplan
    
    Write-Host ""
    Write-Host "✅ Networking fixes applied successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "📝 Next steps:" -ForegroundColor Yellow
    Write-Host "  1. Wait a few minutes for VPC endpoints to be fully available"
    Write-Host "  2. Test the Lambda function from AWS Console"
    Write-Host "  3. Check CloudWatch logs if issues persist"
    Write-Host ""
    Write-Host "🔍 Troubleshooting resources:" -ForegroundColor Blue
    Write-Host "  - VPC Endpoints: Check AWS Console > VPC > Endpoints"
    Write-Host "  - Lambda logs: CloudWatch > Log Groups > /aws/lambda/[function-name]"
    Write-Host "  - Security groups: EC2 > Security Groups"
    
    # Clean up plan file
    Remove-Item -Path "networking-fix.tfplan" -Force -ErrorAction SilentlyContinue
}
else {
    Write-Host "❌ Deployment cancelled. Cleaning up plan file..." -ForegroundColor Red
    Remove-Item -Path "networking-fix.tfplan" -Force -ErrorAction SilentlyContinue
}