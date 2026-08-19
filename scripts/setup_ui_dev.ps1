$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $repositoryRoot ".env"
$portalDirectory = Join-Path $repositoryRoot "ui"

if (-not (Test-Path -LiteralPath $environmentFile)) {
    throw "Missing .env. Copy .env.example to .env and set the required database values first."
}

Push-Location $repositoryRoot
try {
    docker compose up -d db
    docker compose --profile tools run --rm migrate
    uv run python -m scripts.setup_demo_data

    Push-Location $portalDirectory
    try {
        npm ci
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}

Write-Host "UI development prerequisites are ready."
Write-Host "API:    uv run uvicorn dnd_ai.api.app:app --reload"
Write-Host "Portal: cd ui; npm run dev"
