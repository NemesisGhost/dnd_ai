Param(
  [string]$FunctionName,
  [string]$LayerName,
  [string]$RequirementsPath,
  [string]$Python = "python",
  [string]$OutputDir
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $ScriptDir
$OutputDir = if ($OutputDir) { $OutputDir } else { Join-Path $root 'dist\layers' }
# Resolve requirements path and artifact name
if ($RequirementsPath) {
  $req = $RequirementsPath
  $artifactName = Split-Path -Leaf (Split-Path -Parent $req)
}
elseif ($FunctionName) {
  $req = Join-Path $root "src\lambda-functions\$FunctionName\layer\requirements.txt"
  $artifactName = "$FunctionName-python-deps"
}
elseif ($LayerName) {
  $req = Join-Path $root "package\layers\$LayerName\requirements.txt"
  $artifactName = $LayerName
}
else {
  throw "Provide either -RequirementsPath, -FunctionName, or -LayerName"
}

if (!(Test-Path $req)) { throw "requirements.txt not found: $req" }

$buildRoot = Join-Path $env:TEMP ("layer-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
try {
  $site = Join-Path $buildRoot 'python'
  New-Item -ItemType Directory -Force -Path $site | Out-Null

  # Install into site-packages directly under python/ for Lambda layer
  & $Python -m pip install -r $req -t $site | Write-Output

  New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
  $zipPath = Join-Path $OutputDir ("$artifactName.zip")
  if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

  Push-Location $buildRoot
  try {
    Compress-Archive -Path 'python/*' -DestinationPath $zipPath -Force
  }
  finally {
    Pop-Location
  }

  Write-Host "Built layer package: $zipPath"
}
finally {
  if (Test-Path $buildRoot) { Remove-Item $buildRoot -Recurse -Force }
}
