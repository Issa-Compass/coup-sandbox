# Create .venv if missing, install requirements, run the local dashboard.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = $null
foreach ($Name in @("python", "py")) {
    $Cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($Cmd) {
        $Python = $Cmd.Source
        break
    }
}
if (-not $Python) {
    Write-Error "Python 3.11+ is required (python not found)."
}

& $Python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python 3.11+ is required."
}

$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating .venv…"
    & $Python -m venv $Venv
}

Write-Host "Installing requirements…"
& $VenvPython -m pip install --upgrade pip | Out-Null
& $VenvPython -m pip install -r requirements.txt

$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Host "Note: no .env yet — dashboard runs fine without it (play, local tournaments, watch)."
    Write-Host "      Submit stays disabled until you add a coup-master .env (see .env.example)."
} elseif (-not (Select-String -Path $EnvFile -Pattern '^COUP_MASTER_URL=.+' -Quiet)) {
    Write-Host "Note: .env has no COUP_MASTER_URL — dashboard still runs; submit stays disabled."
    Write-Host "      Fill COUP_MASTER_URL (+ API key) from .env.example when you are ready to upload."
}

$Port = if ($env:PORT) { $env:PORT } else { "8765" }
$HostName = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }
Write-Host "Starting dashboard at http://${HostName}:${Port}"
$env:PYTHONUNBUFFERED = "1"
& $VenvPython scripts/serve_dashboard.py --host $HostName --port $Port
