# Start backend (8001) then frontend (5173). Run from project root.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "Starting backend on http://127.0.0.1:8001 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; .\scripts\run_backend.ps1"

Start-Sleep -Seconds 3

Write-Host "Starting frontend on http://127.0.0.1:5173 ..." -ForegroundColor Cyan
Write-Host "Close any OLD frontend/backend terminals first if you see connection errors." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; .\scripts\run_frontend.ps1"

Write-Host "Done. Open http://127.0.0.1:5173/ after ~15s (first geo load may take longer)." -ForegroundColor Green
