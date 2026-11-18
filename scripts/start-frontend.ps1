# Starts the Vite dev server on http://127.0.0.1:5173 (proxies /api to the backend).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root\frontend"
try { npm run dev } finally { Pop-Location }
