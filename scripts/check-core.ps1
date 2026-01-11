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
