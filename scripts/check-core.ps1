<#
.SYNOPSIS
    Runs FaceForge Core quality gates (format, lint, tests).

.DESCRIPTION
    Installs FaceForge Core in editable mode with development dependencies into the repo-local
    virtual environment (`.venv`), then runs:
      - ruff format --check
      - ruff check
      - pytest

    This is intended for local verification and CI usage. It will stop on the first failure and
    return a non-zero exit code.

.OUTPUTS
    Console output from tooling. Exits non-zero on failure.

.EXAMPLE
    ./scripts/check-core.ps1
    Runs format, lint, and tests.

.NOTES
    Prerequisites:
      - Python 3.12.x is recommended (used only to bootstrap `.venv` on first run).
    This script does not rely on global Python packaging once `.venv` exists.
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
    Invoke-Checked { & $venvPython -m pip install -e .\core[dev] } 'pip install (core[dev]) failed'

    Write-Host 'ruff: format check' -ForegroundColor Cyan
    Invoke-Checked { & $venvPython -m ruff format --check .\core\src .\core\tests } 'ruff format --check failed'

    Write-Host 'ruff: lint' -ForegroundColor Cyan
    Invoke-Checked { & $venvPython -m ruff check .\core\src .\core\tests } 'ruff check failed'

    Write-Host 'pytest' -ForegroundColor Cyan
    Invoke-Checked { & $venvPython -m pytest .\core\tests } 'pytest failed'
}
finally {
    Pop-Location
}
