# Start ngrok tunnel for the Streamlit app.
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\start_ngrok.ps1 -AuthToken <3FIHMwhDpzJEHdSeN3l3whNNYtr_pREVAHF1495K3jRGNHzj>
# Or set environment variable NGROK_AUTHTOKEN and run without params.

param(
    [string]$AuthToken = $env:NGROK_AUTHTOKEN
)

if (-not $AuthToken) {
    Write-Host "Ngrok auth token not found."
    Write-Host "1) Sign up at https://dashboard.ngrok.com/signup"
    Write-Host "2) Get token from https://dashboard.ngrok.com/get-started/your-authtoken"
    Write-Host "3) Run this script again with -AuthToken <token>"
    exit 1
}

$ngrokPath = Join-Path (Get-Location) ".ngrok\ngrok.exe"
if (-not (Test-Path $ngrokPath)) {
    Write-Host "ngrok executable not found at $ngrokPath"
    exit 1
}

Write-Host "Configuring ngrok auth token..."
& $ngrokPath config add-authtoken $AuthToken
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to configure ngrok auth token."
    exit $LASTEXITCODE
}

Write-Host "Starting ngrok tunnel to localhost:8501..."
& $ngrokPath http 8501
