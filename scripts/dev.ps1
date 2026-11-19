# One command to (re)start the app for development.
#   .\scripts\dev.ps1            restart backend + frontend
#   .\scripts\dev.ps1 -Worker    also (re)start the scheduled worker / scanner
#   .\scripts\dev.ps1 -Stop      just stop everything
#
# Stops anything already listening on 127.0.0.1:8000 / :5173 (and a running worker),
# runs database migrations, then opens each service in its own PowerShell window.
# The backend runs with auto-reload: saving a backend .py file restarts it for you.
# The frontend (Vite) hot-reloads on save, so it rarely needs a restart.
param([switch]$Worker, [switch]$Stop)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root "backend\.venv\Scripts\python.exe"

function Stop-Port([int]$port) {
    $pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $pids) {
        # Also stop the process tree (uvicorn reloader / npm wrapper) that owns the port.
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $procId" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped process $procId on port $port"
    }
    # Wait for the port to be released: Vite uses strictPort and exits if it's still taken.
    for ($i = 0; $i -lt 40; $i++) {
        if (-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Milliseconds 250
    }
    Write-Warning "Port $port is still in use; the new server may fail to start."
}

function Stop-Worker {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*-m app.worker*" -and $_.CommandLine -like "*$root*" } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped worker $($_.ProcessId)"
        }
}

Stop-Port 8000
Stop-Port 5173
if ($Worker -or $Stop) { Stop-Worker }
if ($Stop) { Write-Host "All stopped."; return }

if (-not (Test-Path $py)) { throw "Backend venv not found. Run .\scripts\setup.ps1 first." }
Push-Location (Join-Path $root "backend")
try {
    & $py -m app.cli migrate
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed" }
} finally { Pop-Location }

$backendCmd = "Set-Location '$root\backend'; `$host.UI.RawUI.WindowTitle = 'KRT backend'; " +
    "& '$py' -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload --reload-dir app"
$frontendCmd = "Set-Location '$root\frontend'; `$host.UI.RawUI.WindowTitle = 'KRT frontend'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd
if ($Worker) {
    $workerCmd = "Set-Location '$root\backend'; `$host.UI.RawUI.WindowTitle = 'KRT worker'; & '$py' -m app.worker"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $workerCmd
}
Write-Host ""
Write-Host "Started. Open http://127.0.0.1:5173  (API docs: http://127.0.0.1:8000/api/docs)"
Write-Host "Restart everything any time with: .\scripts\dev.ps1$(if ($Worker) { ' -Worker' })"
