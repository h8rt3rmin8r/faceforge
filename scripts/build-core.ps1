$ErrorActionPreference = "Stop"
Write-Host "Building FaceForge Core executable..."

$RepoRoot = Resolve-Path "$PSScriptRoot/.."
$PythonExe = Join-Path $RepoRoot ".venv/Scripts/python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Could not find python in .venv at $PythonExe. Please run scripts/dev-core.ps1 to bootstrap."
    exit 1
}

Set-Location "$RepoRoot/core"

# Clean previous builds
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }

# Run PyInstaller via Python module to ensure we use the venv
& $PythonExe -m PyInstaller pyinstaller.spec --noconfirm

# Verify
if (Test-Path "dist/faceforge-core.exe") {
    Write-Host "Build success: dist/faceforge-core.exe"
} else {
    Write-Error "Build failed."
    exit 1
}
