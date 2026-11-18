# Starts the scheduled collector (FRED evidence; Kalshi quotes if configured). Ctrl+C to stop.
# Only one worker can run at a time (file lock).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root\backend"
try {
    & .\.venv\Scripts\python.exe -m app.cli migrate
    & .\.venv\Scripts\python.exe -m app.worker
} finally { Pop-Location }
