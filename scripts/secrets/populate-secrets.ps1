param(
  [Parameter(Mandatory = $true)][string]$Environment,
  [Parameter(Mandatory = $true)][string]$ConfigPath,
  [string]$ProjectName = "dnd-ai"
)

# Config JSON format example:
# {
#   "openai": {
#     "api_key": "...",
#     "organization_id": "",
#     "default_model": "gpt-4",
#     "max_tokens": 4000,
#     "temperature": 0.7
#   },
#   "discord": {
#     "bot_token": "...",
#     "application_id": "...",
#     "public_key": "..."
#   }
# }

if (!(Test-Path -Path $ConfigPath)) {
  Write-Error "Config file not found: $ConfigPath"; exit 1
}

$cfg = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json

function Upsert-SecretJson($name, $json) {
  $payload = ($json | ConvertTo-Json -Depth 8 -Compress)
  $existing = aws secretsmanager describe-secret --secret-id $name 2>$null
  if ($LASTEXITCODE -eq 0) {
    aws secretsmanager put-secret-value --secret-id $name --secret-string $payload | Out-Null
    Write-Host "Updated secret: $name"
  } else {
    aws secretsmanager create-secret --name $name --secret-string $payload | Out-Null
    Write-Host "Created secret: $name"
  }
}

$root = "$ProjectName/$Environment"

if ($cfg.openai) {
  $openaiName = "$root/openai/api-key"
  Upsert-SecretJson -name $openaiName -json $cfg.openai
}

if ($cfg.discord) {
  $discordName = "$root/discord/bot-token"
  Upsert-SecretJson -name $discordName -json $cfg.discord
}

Write-Host "Done."
