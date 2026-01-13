<#
.SYNOPSIS
    Runs FaceForge Core locally in development mode.

.DESCRIPTION
    Bootstraps the repo-local virtual environment (`.venv`) if needed, installs FaceForge Core
    in editable mode with development dependencies, then launches the Core server.

    Environment variables (optional):
      - FACEFORGE_BIND: bind host for Uvicorn/FastAPI (default: 127.0.0.1)
      - FACEFORGE_PORT: bind port for Core (default: 8787)

    This script is intended for local development. For Desktop orchestration, run the Tauri app
    and let it start Core.

.EXAMPLE
    ./scripts/dev-core.ps1
    Starts Core at http://127.0.0.1:8787

.EXAMPLE
    $env:FACEFORGE_PORT = '43210'
    ./scripts/dev-core.ps1
    Starts Core at http://127.0.0.1:43210

.NOTES
    This script intentionally uses `.venv\Scripts\python.exe` for all Python execution.
    External command failures (pip install, server start) cause the script to fail fast.
#>

[CmdletBinding(PositionalBinding = $false)]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot '_ensure-venv.ps1')

function Invoke-Checked {
    param(
        [scriptblock]$Command,
        [string]$FailureMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit $LASTEXITCODE)"
    }
}

$repoRoot = Get-RepoRoot
Push-Location $repoRoot
try {
    $venvPython = Ensure-Venv -RepoRoot $repoRoot

    Write-Host 'Installing Core (editable) + dev deps into .venv' -ForegroundColor Cyan
    Invoke-Checked { & $venvPython -m pip install -e .\core[dev] | Out-Host } 'pip install (core[dev]) failed'

    if (-not $env:FACEFORGE_BIND) { $env:FACEFORGE_BIND = '127.0.0.1' }
    if (-not $env:FACEFORGE_PORT) { $env:FACEFORGE_PORT = '8787' }

    Write-Host "Starting FaceForge Core on http://$($env:FACEFORGE_BIND):$($env:FACEFORGE_PORT)" -ForegroundColor Green
    Invoke-Checked { & $venvPython -m faceforge_core } 'FaceForge Core exited with an error'
}
finally {
    Pop-Location
}
