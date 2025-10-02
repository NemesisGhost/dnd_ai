# Build script for Lambda deployment package with dependencies
param(
    [string]$ScriptDir = $PSScriptRoot
)

$ProjectRoot = Split-Path $ScriptDir -Parent
$TerraformModuleDir = Join-Path $ProjectRoot "terraform\modules\database"
$BuildDir = Join-Path $ScriptDir "lambda_build"
$ZipFile = Join-Path $TerraformModuleDir "db_init_lambda.zip"

Write-Host "Building Lambda deployment package..."

# Clean up previous build
if (Test-Path $BuildDir) {
    Remove-Item $BuildDir -Recurse -Force
}
if (Test-Path $ZipFile) {
    Remove-Item $ZipFile -Force
}

# Create build directory
New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null

# Copy Python files
Copy-Item (Join-Path $TerraformModuleDir "db_init_lambda.py") (Join-Path $BuildDir "index.py")

# Install dependencies
Write-Host "Installing dependencies..."
pip install -r (Join-Path $TerraformModuleDir "requirements.txt") -t $BuildDir

# Create zip file
Write-Host "Creating deployment package..."
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($BuildDir, $ZipFile)

# Clean up build directory
Remove-Item $BuildDir -Recurse -Force

Write-Host "Lambda deployment package created: $ZipFile"