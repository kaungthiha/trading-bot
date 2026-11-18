# Offline demo: (re)builds backend\data\demo.sqlite3 from SYNTHETIC data and serves it on
# 127.0.0.1:8000. No network, no API keys, and your real database is not touched.
# Then run .\scripts\start-frontend.ps1 in a second terminal and open http://127.0.0.1:5173
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root\backend"
try {
    & .\.venv\Scripts\python.exe -m app.cli demo
    if ($LASTEXITCODE -ne 0) { throw "demo build failed" }
    $demo = (Resolve-Path ".\data\demo.sqlite3").Path -replace '\\', '/'
    # Process-scoped overrides only; your .env and real database stay as they are.
    $env:KRT_DATABASE_URL = "sqlite:///$demo"
    $env:KRT_ENV = "demo"
    $env:KRT_MARKET_DATA_SOURCE = "fixture"
    $env:KRT_QUOTE_MAX_AGE_SECONDS = "31536000"  # demo quotes are static snapshots
    Write-Host "Serving the DEMO database. Press Ctrl+C to stop."
    & .\.venv\Scripts\python.exe -m app.main
} finally {
    Remove-Item Env:KRT_DATABASE_URL, Env:KRT_ENV, Env:KRT_MARKET_DATA_SOURCE, Env:KRT_QUOTE_MAX_AGE_SECONDS -ErrorAction SilentlyContinue
    Pop-Location
}
