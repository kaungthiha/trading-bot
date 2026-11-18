# One-time setup: Python venv + locked backend deps, locked frontend deps, DB migration.
# Safe to re-run. Requires Python 3.12+ and Node.js 20+ on PATH.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\backend"
try {
    if (-not (Test-Path ".venv")) { python -m venv .venv }
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    # Exact, tested versions first; then the app itself without re-resolving dependencies.
    & .\.venv\Scripts\python.exe -m pip install -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw "pip install from requirements.lock failed" }
    & .\.venv\Scripts\python.exe -m pip install --no-deps -e .
    & .\.venv\Scripts\python.exe -m app.cli migrate
    & .\.venv\Scripts\python.exe -m app.cli seed-mock
} finally { Pop-Location }

Push-Location "$root\frontend"
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
} finally { Pop-Location }

if (-not (Test-Path "$root\.env")) {
    Write-Host "Tip: copy .env.example to .env and add KRT_FRED_API_KEY when ready (not needed for the demo)."
}
Write-Host ""
Write-Host "Setup complete."
Write-Host "  Real data:    .\scripts\start-backend.ps1  and  .\scripts\start-frontend.ps1"
Write-Host "  Offline demo: .\scripts\start-demo.ps1     and  .\scripts\start-frontend.ps1"
