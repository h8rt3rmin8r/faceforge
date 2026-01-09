Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot '_ensure-venv.ps1')

$repoRoot = Get-RepoRoot
Push-Location $repoRoot
try {
    $venvPython = Ensure-Venv -RepoRoot $repoRoot

    Write-Host 'Installing Core (editable) + dev deps into .venv' -ForegroundColor Cyan
    & $venvPython -m pip install -e .\core[dev]

    Write-Host 'ruff: format check' -ForegroundColor Cyan
    & $venvPython -m ruff format --check .\core\src .\core\tests

    Write-Host 'ruff: lint' -ForegroundColor Cyan
    & $venvPython -m ruff check .\core\src .\core\tests

    Write-Host 'pytest' -ForegroundColor Cyan
    & $venvPython -m pytest .\core\tests
}
finally {
    Pop-Location
}
