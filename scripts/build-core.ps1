Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot '_ensure-venv.ps1')

Write-Host 'Building FaceForge Core executable...' -ForegroundColor Cyan

$repoRoot = Get-RepoRoot
Push-Location $repoRoot
try {
    $venvPython = Ensure-Venv -RepoRoot $repoRoot

    Write-Host 'Installing build dependencies into .venv' -ForegroundColor Cyan
    & $venvPython -m pip install -e .\core | Out-Host
    & $venvPython -m pip install pyinstaller | Out-Host

    Set-Location (Join-Path $repoRoot 'core')

    $distPath = 'dist'
    $workPath = 'build'

    # Clean previous builds (but don't fail if dist is locked by another process)
    if (Test-Path $workPath) {
        Remove-Item -Recurse -Force $workPath
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
    & $venvPython -m PyInstaller pyinstaller.spec --noconfirm --distpath $distPath --workpath $workPath

    # Verify
    $exePath = Join-Path $distPath 'faceforge-core.exe'
    if (Test-Path $exePath) {
        Write-Host "Build success: core/$exePath" -ForegroundColor Green
    } else {
        throw "Build failed: core/$exePath not found"
    }
}
finally {
    Pop-Location
}
