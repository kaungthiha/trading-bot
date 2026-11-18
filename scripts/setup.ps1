# One-time setup: Python venv + backend deps, frontend deps, DB migration, mock seed.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\backend"
try {
    if (-not (Test-Path ".venv")) { python -m venv .venv }
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    & .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
    & .\.venv\Scripts\python.exe -m app.cli migrate
    & .\.venv\Scripts\python.exe -m app.cli seed-mock
} finally { Pop-Location }

Push-Location "$root\frontend"
try { npm ci } finally { Pop-Location }

if (-not (Test-Path "$root\.env")) {
    Write-Host "Tip: copy .env.example to .env when you are ready to add API keys (not needed yet)."
}
Write-Host "Setup complete. Run scripts\start-backend.ps1 and scripts\start-frontend.ps1."
