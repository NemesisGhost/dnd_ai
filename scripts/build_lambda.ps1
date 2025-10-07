Param(
  [Parameter(Mandatory=$true)][string]$FunctionName,
  [string]$OutputDir
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $ScriptDir
$OutputDir = if ($OutputDir) { $OutputDir } else { Join-Path $root 'dist\lambdas' }
$src = Join-Path $root "src\lambda-functions\$FunctionName"
if (!(Test-Path $src)) { throw "Function source not found: $src" }

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$zipPath = Join-Path $OutputDir "$FunctionName.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

Push-Location $src
try {
  Compress-Archive -Path * -DestinationPath $zipPath -Force
}
finally {
  Pop-Location
}

Write-Host "Built function package: $zipPath"
