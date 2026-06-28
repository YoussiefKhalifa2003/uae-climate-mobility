# Run backend + frontend in ONE terminal. Ctrl+C stops both.
# From project root:  npm run dev
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path "$root\backend\.venv")) {
    Write-Host "First-time setup: creating Python venv …" -ForegroundColor Yellow
    Set-Location "$root\backend"
    python -m venv .venv
    & "$root\backend\.venv\Scripts\pip.exe" install -r requirements.txt
    Set-Location $root
}

if (-not (Test-Path "$root\frontend\node_modules")) {
    Write-Host "First-time setup: npm install in frontend …" -ForegroundColor Yellow
    npm install --prefix frontend
}

if (-not (Test-Path "$root\node_modules")) {
    Write-Host "First-time setup: npm install at project root …" -ForegroundColor Yellow
    npm install
}

Write-Host "Starting backend (:8001) + frontend (:5173) …" -ForegroundColor Cyan
Write-Host "Keep this window open. Open http://127.0.0.1:5173 after ~30s warm-up." -ForegroundColor Green
node scripts/run-dev.mjs
