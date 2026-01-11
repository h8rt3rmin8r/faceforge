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

Write-Host 'Building FaceForge Core executable...' -ForegroundColor Cyan

$repoRoot = Get-RepoRoot
Push-Location $repoRoot
try {
    $venvPython = Ensure-Venv -RepoRoot $repoRoot

    Write-Host 'Installing build dependencies into .venv' -ForegroundColor Cyan
    Invoke-Checked { & $venvPython -m pip install -e .\core | Out-Host } 'pip install (core) failed'
    Invoke-Checked { & $venvPython -m pip install pyinstaller | Out-Host } 'pip install (pyinstaller) failed'

    Set-Location (Join-Path $repoRoot 'core')

    $distPath = 'dist'
    $workPath = 'build'

    # Clean previous builds (but don't fail if dist is locked by another process)
    if (Test-Path $workPath) {
        try {
            Remove-Item -Recurse -Force $workPath
        }
        catch {
            $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            $workPath = "build-$stamp"
            Write-Warning "Could not remove existing build/ (likely in use). Building into $workPath instead."
        }
    }
    if (Test-Path $distPath) {
        try {
            Remove-Item -Recurse -Force $distPath
        }
        catch {
            $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            $distPath = "dist-$stamp"
            $workPath = "build-$stamp"
            Write-Warning "Could not remove existing dist/ (likely in use). Building into $distPath instead."
        }
    }

    # Run PyInstaller via Python module to ensure we use the venv
    Invoke-Checked {
        & $venvPython -m PyInstaller pyinstaller.spec --noconfirm --distpath $distPath --workpath $workPath
    } 'PyInstaller build failed'

    # Verify + normalize output location for callers (e.g., GitHub Actions expects core/dist/faceforge-core.exe)
    $exePath = Join-Path $distPath 'faceforge-core.exe'
    if (-not (Test-Path $exePath)) {
        throw "Build failed: core/$exePath not found"
    }

    $stableDist = 'dist'
    $stableExePath = Join-Path $stableDist 'faceforge-core.exe'
    if ($distPath -ne $stableDist) {
        if (-not (Test-Path $stableDist)) {
            New-Item -ItemType Directory -Path $stableDist | Out-Null
        }

        try {
            Copy-Item -Force $exePath $stableExePath
        }
        catch {
            Write-Warning "Build produced core/$exePath but could not copy to core/$stableExePath. $($_.Exception.Message)"
        }
    }

    if (Test-Path $stableExePath) {
        Write-Host "Build success: core/$stableExePath" -ForegroundColor Green
    } else {
        Write-Host "Build success: core/$exePath" -ForegroundColor Green
    }
}
finally {
    Pop-Location
}
