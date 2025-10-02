# Set environment
$env:TF_VAR_owner_name = $env:USERNAME
$env:TF_VAR_aws_region = "us-east-1"

# Get your public IP for database access (optional)
try {
    $MyIP = (Invoke-RestMethod -Uri "https://ifconfig.me").Trim()
    $env:TF_VAR_my_ip_cidr = "$MyIP/32"
    Write-Host "Your IP: $MyIP" -ForegroundColor Green
} catch {
    Write-Host "Could not determine public IP. Using default (0.0.0.0/0)" -ForegroundColor Yellow
    $env:TF_VAR_my_ip_cidr = "0.0.0.0/0"
}

Write-Host "Environment variables set:" -ForegroundColor Cyan
Write-Host "  TF_VAR_owner_name: $env:TF_VAR_owner_name" -ForegroundColor Gray
Write-Host "  TF_VAR_aws_region: $env:TF_VAR_aws_region" -ForegroundColor Gray
Write-Host "  TF_VAR_my_ip_cidr: $env:TF_VAR_my_ip_cidr" -ForegroundColor Gray