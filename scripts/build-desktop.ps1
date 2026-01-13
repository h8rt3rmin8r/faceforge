<#
.SYNOPSIS
  Builds a full FaceForge Desktop bundle (Desktop + Core sidecar).

.DESCRIPTION
  This script follows the project’s packaging intent:
    - Build FaceForge Core as a standalone executable (PyInstaller)
    - Stage it into Desktop’s Tauri sidecar binaries folder
    - Produce Desktop installers via `tauri build`

  Outputs (Windows):
    - desktop/src-tauri/target/release/bundle/msi/*.msi
    - desktop/src-tauri/target/release/bundle/nsis/*-setup.exe

.PARAMETER Bundles
  Which bundle target(s) to build. Allowed values: all, msi, nsis.
  Default: all.

.PARAMETER SkipCoreBuild
  Skip running scripts/build-core.ps1 (expects core/dist/faceforge-core.exe to already exist).

.PARAMETER SkipNpmInstall
  Skip `npm install` (assumes dependencies are already installed).

.PARAMETER KeepBuildHistory
  Forwarded to scripts/build-core.ps1; preserves old build/dist folders under core/.

.PARAMETER AllowTimestampFallback
  Forwarded to scripts/build-core.ps1; if core/build or core/dist are locked, build into timestamped folders.

.EXAMPLE
  ./scripts/build-desktop.ps1

.EXAMPLE
  ./scripts/build-desktop.ps1 -Bundles nsis

.EXAMPLE
  ./scripts/build-desktop.ps1 -SkipCoreBuild -SkipNpmInstall -Bundles msi
#>

[CmdletBinding()]
param(
  [ValidateSet('all','msi','nsis')]
  [string]$Bundles = 'all',

  [switch]$SkipCoreBuild,
  [switch]$SkipNpmInstall,

  [switch]$KeepBuildHistory,
  [switch]$AllowTimestampFallback
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ConfirmPreference = 'None'

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

Write-Host "Building FaceForge Desktop bundle ($Bundles)..." -ForegroundColor Cyan

Push-Location $repoRoot
try {
  if (-not $SkipCoreBuild) {
    Write-Host 'Step 1/3: Building Core executable (PyInstaller)' -ForegroundColor Cyan
    $coreArgs = @{}
    if ($KeepBuildHistory) { $coreArgs['KeepBuildHistory'] = $true }
    if ($AllowTimestampFallback) { $coreArgs['AllowTimestampFallback'] = $true }

    Invoke-Checked { & (Join-Path $repoRoot 'scripts/build-core.ps1') @coreArgs | Out-Host } 'Core build failed'
  } else {
    Write-Host 'Step 1/3: Skipping Core build (using existing executable)' -ForegroundColor Yellow
  }

  $coreExe = Join-Path $repoRoot 'core/dist/faceforge-core.exe'
  if (-not (Test-Path $coreExe)) {
    throw "Core executable not found at $coreExe. Re-run without -SkipCoreBuild."
  }

  Write-Host 'Step 2/3: Staging Core sidecar into Desktop binaries/' -ForegroundColor Cyan
  $dstDir = Join-Path $repoRoot 'desktop/src-tauri/binaries'
  New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
  Copy-Item -Force $coreExe (Join-Path $dstDir 'faceforge-core.exe')

  Write-Host 'Step 3/3: Building Desktop installer(s) via Tauri' -ForegroundColor Cyan
  $desktopDir = Join-Path $repoRoot 'desktop'

  if (-not $SkipNpmInstall) {
    Push-Location $desktopDir
    try {
      Invoke-Checked { npm install | Out-Host } 'npm install failed'
    } finally {
      Pop-Location
    }
  } else {
    Write-Host 'Skipping npm install' -ForegroundColor Yellow
  }

  Push-Location $desktopDir
  try {
    if ($Bundles -eq 'all') {
      Invoke-Checked { npx tauri build | Out-Host } 'tauri build failed'
    } else {
      Invoke-Checked { npx tauri build --bundles=$Bundles --verbose | Out-Host } "tauri build ($Bundles) failed"
    }
  } finally {
    Pop-Location
  }

  $bundleDir = Join-Path $repoRoot 'desktop/src-tauri/target/release/bundle'
  Write-Host "Build complete. Bundle outputs under: $bundleDir" -ForegroundColor Green
} finally {
  Pop-Location
}
