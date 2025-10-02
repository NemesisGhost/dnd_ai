#!/usr/bin/env powershell
<#
.SYNOPSIS
    Automated deployment verification script for D&D AI database infrastructure.

.DESCRIPTION
    This script runs through the complete verification process for the Terraform
    deployment and database schema creation.

.PARAMETER SkipDeploy
    Skip the actual Terraform deployment and only run post-deployment checks.

.PARAMETER Environment
    Environment to test (default: dev)

.EXAMPLE
    .\test-deployment.ps1
    .\test-deployment.ps1 -SkipDeploy
#>

param(
    [switch]$SkipDeploy,
    [string]$Environment = "dev"
)

# Configuration
$ErrorActionPreference = "Stop"
$TerraformDir = ".\terraform\environments\$Environment"
$ScriptsDir = ".\scripts"

function Write-TestResult {
    param(
        [string]$Test,
        [bool]$Success,
        [string]$Message = ""
    )
    
    $status = if ($Success) { "✅ PASS" } else { "❌ FAIL" }
    $output = "$status $Test"
    if ($Message) { $output += " - $Message" }
    Write-Host $output
    return $Success
}

function Test-Prerequisites {
    Write-Host "`n🔍 Testing Prerequisites..." -ForegroundColor Cyan
    
    $results = @()
    
    # Test Terraform
    try {
        $tfVersion = terraform --version 2>$null | Select-Object -First 1
        $results += Write-TestResult "Terraform installed" $true $tfVersion
    } catch {
        $results += Write-TestResult "Terraform installed" $false "Not found in PATH"
    }
    
    # Test AWS CLI
    try {
        $awsVersion = aws --version 2>$null
        $results += Write-TestResult "AWS CLI installed" $true $awsVersion
    } catch {
        $results += Write-TestResult "AWS CLI installed" $false "Not found in PATH"
    }
    
    # Test AWS credentials
    try {
        $identity = aws sts get-caller-identity 2>$null | ConvertFrom-Json
        $results += Write-TestResult "AWS credentials configured" $true "Account: $($identity.Account)"
    } catch {
        $results += Write-TestResult "AWS credentials configured" $false "Cannot authenticate"
    }
    
    # Test Python
    try {
        $pythonVersion = python --version 2>$null
        $results += Write-TestResult "Python installed" $true $pythonVersion
    } catch {
        $results += Write-TestResult "Python installed" $false "Not found in PATH"
    }
    
    return $results -notcontains $false
}

function Test-TerraformConfiguration {
    Write-Host "`n🔧 Testing Terraform Configuration..." -ForegroundColor Cyan
    
    $results = @()
    
    # Change to terraform directory
    Push-Location $TerraformDir
    
    try {
        # Test init
        terraform init -input=false 2>$null | Out-Null
        $results += Write-TestResult "Terraform init" $LASTEXITCODE -eq 0
        
        # Test validate
        terraform validate 2>$null | Out-Null
        $results += Write-TestResult "Terraform validate" $LASTEXITCODE -eq 0
        
        # Check if terraform.tfvars exists
        $tfvarsExists = Test-Path "terraform.tfvars"
        $results += Write-TestResult "terraform.tfvars exists" $tfvarsExists
        
        if ($tfvarsExists) {
            $content = Get-Content "terraform.tfvars" -Raw
            $hasCustomIP = $content -notmatch "0\.0\.0\.0/0"
            $results += Write-TestResult "Custom IP configured" $hasCustomIP "Check my_ip_cidr setting"
        }
        
    } finally {
        Pop-Location
    }
    
    return $results -notcontains $false
}

function Test-TerraformPlan {
    Write-Host "`n📋 Testing Terraform Plan..." -ForegroundColor Cyan
    
    Push-Location $TerraformDir
    
    try {
        Write-Host "Generating Terraform plan..."
        $planOutput = terraform plan -out=tfplan.test 2>&1
        $planSuccess = $LASTEXITCODE -eq 0
        
        if ($planSuccess) {
            # Count resources to be created
            $createCount = ($planOutput | Select-String "# .* will be created").Count
            Write-TestResult "Terraform plan generation" $true "$createCount resources to create"
            
            # Check for specific critical resources
            $hasRDS = $planOutput -match "aws_db_instance"
            $hasLambda = $planOutput -match "aws_lambda_function"
            $hasSecrets = $planOutput -match "aws_secretsmanager_secret"
            
            Write-TestResult "RDS instance in plan" $hasRDS
            Write-TestResult "Lambda function in plan" $hasLambda  
            Write-TestResult "Secrets Manager in plan" $hasSecrets
            
            return $hasRDS -and $hasLambda -and $hasSecrets
        } else {
            Write-TestResult "Terraform plan generation" $false "Check configuration"
            return $false
        }
    } finally {
        # Clean up test plan
        if (Test-Path "tfplan.test") { Remove-Item "tfplan.test" }
        Pop-Location
    }
}

function Test-LambdaPackage {
    Write-Host "`n📦 Testing Lambda Package..." -ForegroundColor Cyan
    
    $lambdaZip = ".\terraform\modules\database\db_init_lambda.zip"
    $results = @()
    
    # Check if package exists
    $packageExists = Test-Path $lambdaZip
    $results += Write-TestResult "Lambda package exists" $packageExists
    
    if ($packageExists) {
        # Check package size (should be reasonable)
        $size = (Get-Item $lambdaZip).Length
        $sizeOK = $size -gt 1KB -and $size -lt 10MB
        $results += Write-TestResult "Lambda package size OK" $sizeOK "$([math]::Round($size/1KB, 1)) KB"
        
        # Try to list contents
        try {
            $zipContents = & "C:\Program Files\7-Zip\7z.exe" l $lambdaZip 2>$null
            $hasIndex = $zipContents -match "index.py"
            $results += Write-TestResult "Lambda package contains index.py" $hasIndex
        } catch {
            Write-TestResult "Cannot inspect package contents" $false "7-Zip not available"
        }
    }
    
    return $results -notcontains $false
}

function Deploy-Infrastructure {
    Write-Host "`n🚀 Deploying Infrastructure..." -ForegroundColor Cyan
    
    Push-Location $TerraformDir
    
    try {
        Write-Host "Starting Terraform deployment (this may take 15-20 minutes)..."
        Write-Host "You can cancel with Ctrl+C if needed."
        
        $deployOutput = terraform apply -input=false -auto-approve tfplan 2>&1
        $deploySuccess = $LASTEXITCODE -eq 0
        
        if ($deploySuccess) {
            Write-TestResult "Infrastructure deployment" $true "All resources created"
            return $true
        } else {
            Write-TestResult "Infrastructure deployment" $false "Check Terraform output"
            Write-Host "Deployment output:" -ForegroundColor Red
            Write-Host $deployOutput
            return $false
        }
    } finally {
        Pop-Location
    }
}

function Test-PostDeployment {
    Write-Host "`n✅ Testing Post-Deployment..." -ForegroundColor Cyan
    
    Push-Location $TerraformDir
    
    try {
        # Get Terraform outputs
        $outputs = terraform output -json 2>$null | ConvertFrom-Json
        
        if (-not $outputs) {
            Write-TestResult "Terraform outputs available" $false
            return $false
        }
        
        $results = @()
        
        # Check each output
        $results += Write-TestResult "Database endpoint output" ($null -ne $outputs.database_endpoint)
        $results += Write-TestResult "Database port output" ($outputs.database_port.value -eq 5432)
        $results += Write-TestResult "Secrets manager output" ($null -ne $outputs.secrets_manager_secret_name)
        
        # Test RDS instance status
        if ($outputs.database_endpoint) {
            try {
                $dbStatus = aws rds describe-db-instances --db-instance-identifier "dnd-ai-$Environment-db" 2>$null | ConvertFrom-Json
                $isAvailable = $dbStatus.DBInstances[0].DBInstanceStatus -eq "available"
                $results += Write-TestResult "RDS instance available" $isAvailable $dbStatus.DBInstances[0].DBInstanceStatus
            } catch {
                $results += Write-TestResult "RDS instance status check" $false "Cannot query RDS"
            }
        }
        
        # Test Lambda function
        if ($outputs.init_status) {
            try {
                $lambdaInfo = aws lambda get-function --function-name $outputs.init_status.value 2>$null | ConvertFrom-Json
                $isActive = $lambdaInfo.Configuration.State -eq "Active"
                $results += Write-TestResult "Lambda function active" $isActive $lambdaInfo.Configuration.State
            } catch {
                $results += Write-TestResult "Lambda function check" $false "Cannot query Lambda"
            }
        }
        
        return $results -notcontains $false
        
    } finally {
        Pop-Location
    }
}

function Test-DatabaseSchema {
    Write-Host "`n🗃️ Testing Database Schema..." -ForegroundColor Cyan
    
    Push-Location $TerraformDir
    
    try {
        $outputs = terraform output -json 2>$null | ConvertFrom-Json
        
        if (-not $outputs.secrets_manager_secret_name) {
            Write-TestResult "Database validation" $false "No secrets manager output"
            return $false
        }
        
        $secretName = $outputs.secrets_manager_secret_name.value
        
        # Check if validation script exists
        $validationScript = "$ScriptsDir\validate_database.py"
        if (-not (Test-Path $validationScript)) {
            Write-TestResult "Database validation script" $false "Script not found"
            return $false
        }
        
        # Run database validation
        Write-Host "Running database schema validation..."
        try {
            $validationOutput = python $validationScript $secretName 2>&1
            $validationSuccess = $LASTEXITCODE -eq 0
            
            Write-TestResult "Database schema validation" $validationSuccess
            
            if (-not $validationSuccess) {
                Write-Host "Validation output:" -ForegroundColor Yellow
                Write-Host $validationOutput
            }
            
            return $validationSuccess
        } catch {
            Write-TestResult "Database validation execution" $false "Python script error"
            return $false
        }
        
    } finally {
        Pop-Location
    }
}

function Show-Summary {
    param([hashtable]$Results)
    
    Write-Host "`n" + ("="*60) -ForegroundColor White
    Write-Host "DEPLOYMENT VERIFICATION SUMMARY" -ForegroundColor White  
    Write-Host ("="*60) -ForegroundColor White
    
    $allPassed = $true
    foreach ($test in $Results.Keys) {
        $status = if ($Results[$test]) { "✅ PASS" } else { "❌ FAIL"; $allPassed = $false }
        Write-Host "$status $test"
    }
    
    Write-Host ""
    if ($allPassed) {
        Write-Host "🎉 ALL TESTS PASSED! Your D&D AI database is ready to use." -ForegroundColor Green
        
        # Show connection info
        Push-Location $TerraformDir
        try {
            $outputs = terraform output -json 2>$null | ConvertFrom-Json
            if ($outputs.database_endpoint) {
                Write-Host "`nDatabase Connection Info:" -ForegroundColor Cyan
                Write-Host "  Endpoint: $($outputs.database_endpoint.value)"
                Write-Host "  Port: $($outputs.database_port.value)"
                Write-Host "  Database: $($outputs.database_name.value)"
                Write-Host "  Credentials: $($outputs.secrets_manager_secret_name.value)"
            }
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "⚠️ SOME TESTS FAILED. Please review the errors above." -ForegroundColor Red
    }
}

# Main execution
Write-Host "D&D AI Database Deployment Verification" -ForegroundColor Magenta
Write-Host "Environment: $Environment" -ForegroundColor Magenta
Write-Host ("="*60) -ForegroundColor Magenta

$testResults = @{}

# Run tests
$testResults["Prerequisites"] = Test-Prerequisites
$testResults["Terraform Configuration"] = Test-TerraformConfiguration  
$testResults["Lambda Package"] = Test-LambdaPackage
$testResults["Terraform Plan"] = Test-TerraformPlan

if (-not $SkipDeploy -and $testResults["Terraform Plan"]) {
    Write-Host "`n⚠️ WARNING: This will create real AWS resources and incur costs!" -ForegroundColor Yellow
    Write-Host "Estimated cost: ~$15-20/month for development environment" -ForegroundColor Yellow
    $confirm = Read-Host "Continue with deployment? (y/N)"
    
    if ($confirm -eq "y" -or $confirm -eq "Y") {
        $testResults["Infrastructure Deployment"] = Deploy-Infrastructure
    } else {
        Write-Host "Deployment skipped by user." -ForegroundColor Yellow
        $testResults["Infrastructure Deployment"] = $false
    }
} elseif ($SkipDeploy) {
    Write-Host "`nSkipping deployment as requested." -ForegroundColor Yellow
    $testResults["Infrastructure Deployment"] = $true  # Assume existing deployment
}

if ($testResults["Infrastructure Deployment"]) {
    $testResults["Post-Deployment Checks"] = Test-PostDeployment
    $testResults["Database Schema Validation"] = Test-DatabaseSchema
}

# Show final summary
Show-Summary $testResults

# Exit with appropriate code
$overallSuccess = ($testResults.Values | Where-Object { $_ -eq $false }).Count -eq 0
exit $(if ($overallSuccess) { 0 } else { 1 })