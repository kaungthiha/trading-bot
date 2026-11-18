# Runs all tests: backend (pytest + ruff) and frontend (typecheck + vitest).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Push-Location "$root\backend"
try {
    & .\.venv\Scripts\python.exe -m pytest
    if ($LASTEXITCODE -ne 0) { throw "backend tests failed" }
    & .\.venv\Scripts\python.exe -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "backend lint failed" }
} finally { Pop-Location }

Push-Location "$root\frontend"
try {
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw "frontend typecheck failed" }
    npm test
    if ($LASTEXITCODE -ne 0) { throw "frontend tests failed" }
} finally { Pop-Location }
Write-Host "All checks passed."
