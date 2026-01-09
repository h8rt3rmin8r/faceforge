Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot '_ensure-venv.ps1')

$repoRoot = Get-RepoRoot
Push-Location $repoRoot
try {
    $venvPython = Ensure-Venv -RepoRoot $repoRoot

    Write-Host 'Installing Core (editable) + dev deps into .venv' -ForegroundColor Cyan
    & $venvPython -m pip install -e .\core[dev]

    if (-not $env:FACEFORGE_BIND) { $env:FACEFORGE_BIND = '127.0.0.1' }
    if (-not $env:FACEFORGE_PORT) { $env:FACEFORGE_PORT = '8787' }

    Write-Host "Starting FaceForge Core on http://$($env:FACEFORGE_BIND):$($env:FACEFORGE_PORT)" -ForegroundColor Green
    & $venvPython -m faceforge_core
}
finally {
    Pop-Location
}
