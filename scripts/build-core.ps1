Write-Host "Building FaceForge Core executable..."
Set-Location "$PSScriptRoot/../core"

# Clean previous builds
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }

# Run PyInstaller
pyinstaller pyinstaller.spec --noconfirm

# Verify
if (Test-Path "dist/faceforge-core.exe") {
    Write-Host "Build success: dist/faceforge-core.exe"
} else {
    Write-Error "Build failed."
    exit 1
}
