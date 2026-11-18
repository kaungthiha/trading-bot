# Starts the FastAPI backend on 127.0.0.1:8000 (loopback only; enforced in settings).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root\backend"
try {
    & .\.venv\Scripts\python.exe -m app.cli migrate
    & .\.venv\Scripts\python.exe -m app.main
} finally { Pop-Location }
