# daily_scrape.ps1 — Windows PowerShell daily scrape script for Moltbook
# Usage: pwsh scripts/daily_scrape.ps1
# Resolves all paths relative to $PSScriptRoot (no hardcoded paths).

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DbPath = Join-Path $ProjectRoot "data\raw\moltbook.db"
$LogDir = Join-Path $ProjectRoot "logs"
$Date = Get-Date -Format "yyyy-MM-dd"
$LogFile = Join-Path $LogDir "scrape-$Date.log"

# Ensure logs directory exists
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Activate virtual environment
$VenvActivate = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    . $VenvActivate
} else {
    Write-Error "Virtual environment not found at $VenvActivate"
    exit 1
}

# Load .env file (dotenv style: KEY=VALUE lines)
$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), "Process")
        }
    }
} else {
    Write-Error ".env file not found at $EnvFile"
    exit 1
}

function Run-Stage {
    param(
        [string]$Label,
        [string[]]$Args
    )
    $timestamp = Get-Date -Format "HH:mm:ss"
    Write-Host "[$timestamp] $Label"
    $allArgs = @("-m", "src.cli") + $Args + @("--db", $DbPath)
    python @allArgs 2>&1 | Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Stage failed: $Label (exit code $LASTEXITCODE)"
        exit $LASTEXITCODE
    }
}

# --- Staged pipeline ---
$startTimestamp = Get-Date -Format "HH:mm:ss"
"[$startTimestamp] Starting daily scrape (DB: $DbPath)" | Tee-Object -FilePath $LogFile -Append

Push-Location $ProjectRoot
try {
    Run-Stage "Scraping submolts..."      @("submolts")
    Run-Stage "Scraping posts..."         @("posts")
    Run-Stage "Scraping comments (missing only)..." @("comments", "--only-missing")
    Run-Stage "Scraping moderators..."    @("moderators")
    Run-Stage "Enriching agent profiles..." @("enrich")
    Run-Stage "Creating snapshots..."     @("snapshots")
} finally {
    Pop-Location
}

$endTimestamp = Get-Date -Format "HH:mm:ss"
"[$endTimestamp] Daily scrape complete." | Tee-Object -FilePath $LogFile -Append
