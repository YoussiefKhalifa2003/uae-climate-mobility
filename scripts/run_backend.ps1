# Sets up (first run) and launches the FastAPI backend on Windows PowerShell.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"

if (-not (Test-Path "$root\backend\.venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
    & "$root\backend\.venv\Scripts\python.exe" -m pip install --upgrade pip
    & "$root\backend\.venv\Scripts\python.exe" -m pip install -r requirements.txt
    Write-Host "For GPU acceleration on your RTX 4080 Super, also run:" -ForegroundColor Yellow
    Write-Host "  .venv\Scripts\python.exe -m pip install cupy-cuda12x==13.3.0" -ForegroundColor Yellow
}

if (-not (Test-Path "$root\.env")) {
    Copy-Item "$root\.env.example" "$root\.env"
    Write-Host "Created .env from template." -ForegroundColor Green
}

& "$root\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
