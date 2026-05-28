# Luna Writing Studio Startup Utility
Write-Host "=========================================" -ForegroundColor Violet
Write-Host "    LUNA WEB NOVEL WRITING STUDIO" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Violet
# Load environment variables from backend/.env if present
$envFile = "$PSScriptRoot\backend\.env"
if (Test-Path $envFile) {
    Write-Host "Loading Azure environment credentials from .env..." -ForegroundColor Yellow
    Get-Content $envFile | Where-Object { $_ -match '=' -and $_ -notmatch '^#' } | ForEach-Object {
        $name, $value = $_.Split('=', 2)
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
    Write-Host "Running in cloud-backed mode (Azure Flexible SQL & Azure Storage)!" -ForegroundColor Green
} else {
    Write-Host "Running in zero-cost local environment (SQLite fallback)..." -ForegroundColor Gray
}

# 1. Check and install minimal dependencies
Write-Host "[1/4] Checking and installing Python dependencies..." -ForegroundColor Gray
& pip install fastapi uvicorn requests pydantic reportlab psycopg2-binary azure-storage-blob --quiet --no-warn-script-location

# 2. Initialize Database
Write-Host "[2/4] Initializing local SQLite schema..." -ForegroundColor Gray
& python "$PSScriptRoot\backend\db.py"

# 3. Start Backend Server in Background
Write-Host "[3/4] Starting FastAPI backend on http://127.0.0.1:8000 ..." -ForegroundColor Gray
$serverJob = Start-Job -ScriptBlock {
    param($root)
    cd "$root\backend"
    & uvicorn main:app --reload --port 8000
} -ArgumentList $PSScriptRoot

# 4. Open Frontend Dashboard in Browser
Write-Host "[4/4] Opening Web Dashboard..." -ForegroundColor Gray
$frontendPath = "file:///$PSScriptRoot/frontend/index.html"
Start-Process $frontendPath

Write-Host "-----------------------------------------" -ForegroundColor Violet
Write-Host "Studio launched! Keep this shell active." -ForegroundColor Green
Write-Host "To shut down studio, press Ctrl+C or run 'Stop-Job -Id $serverJob.Id'" -ForegroundColor Yellow
Write-Host "=========================================" -ForegroundColor Violet

# Keep the shell active to capture background logs
try {
    Receive-Job -Job $serverJob -Keep -Wait
}
finally {
    Write-Host "`nStopping backend server..." -ForegroundColor Yellow
    Stop-Job $serverJob
    Remove-Job $serverJob
}
