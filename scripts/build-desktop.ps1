<#
.SYNOPSIS
  Builds a full FaceForge Desktop bundle (Desktop + Core sidecar).

.DESCRIPTION
  This script follows the project’s packaging intent:
    - Build FaceForge Core as a standalone executable (PyInstaller)
    - Stage it into Desktop’s Tauri sidecar binaries folder
    - Produce Desktop installers via `tauri build`

  This script is designed for repeatable local and CI builds:
    - Uses the repo-local `.venv` for Core builds (never global site-packages).
    - Stages the Core sidecar into `desktop/src-tauri/binaries/faceforge-core.exe`.
    - Runs `cargo tauri build` to produce installable artifacts.

  Prerequisites (Windows):
    - Rust toolchain installed (cargo).
    - Tauri prerequisites (WebView2, bundler toolchains). Tauri will prompt/download some tooling.

  Outputs (Windows):
    - desktop/src-tauri/target/release/bundle/msi/*.msi
    - desktop/src-tauri/target/release/bundle/nsis/*-setup.exe

.PARAMETER Bundles
  Which bundle target(s) to build. Allowed values: all, msi, nsis.
  Default: all.

.PARAMETER SkipCoreBuild
  Skip running scripts/build-core.ps1 (expects core/dist/faceforge-core.exe to already exist).

.PARAMETER KeepBuildHistory
  Forwarded to scripts/build-core.ps1; preserves old build/dist folders under core/.

.PARAMETER AllowTimestampFallback
  Forwarded to scripts/build-core.ps1; if core/build or core/dist are locked, build into timestamped folders.

.EXAMPLE
  ./scripts/build-desktop.ps1
  Builds Core + Desktop, producing both MSI and NSIS artifacts.

.EXAMPLE
  ./scripts/build-desktop.ps1 -Bundles nsis
  Builds only the NSIS installer.

.EXAMPLE
  ./scripts/build-desktop.ps1 -SkipCoreBuild -Bundles msi
  Fast path when nothing changed in Core.

.NOTES
  Outputs (Windows):
    - desktop/src-tauri/target/release/bundle/msi/*.msi
    - desktop/src-tauri/target/release/bundle/nsis/*-setup.exe

  This script sets `PositionalBinding = $false` to discourage ambiguous invocation.
#>

[CmdletBinding(PositionalBinding = $false)]
param(
  [ValidateSet('all','msi','nsis')]
  [string]$Bundles = 'all',

  [switch]$SkipCoreBuild,

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
    Write-Host 'Step 1/4: Building Core executable (PyInstaller)' -ForegroundColor Cyan
    $coreArgs = @{}
    if ($KeepBuildHistory) { $coreArgs['KeepBuildHistory'] = $true }
    if ($AllowTimestampFallback) { $coreArgs['AllowTimestampFallback'] = $true }

    Invoke-Checked { & (Join-Path $repoRoot 'scripts/build-core.ps1') @coreArgs | Out-Host } 'Core build failed'
  } else {
    Write-Host 'Step 1/4: Skipping Core build (using existing executable)' -ForegroundColor Yellow
  }

  $coreExe = Join-Path $repoRoot 'core/dist/faceforge-core.exe'
  if (-not (Test-Path $coreExe)) {
    throw "Core executable not found at $coreExe. Re-run without -SkipCoreBuild."
  }

  Write-Host 'Step 2/4: Staging Core sidecar into Desktop binaries/' -ForegroundColor Cyan
  $dstDir = Join-Path $repoRoot 'desktop/src-tauri/binaries'
  New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
  Copy-Item -Force $coreExe (Join-Path $dstDir 'faceforge-core.exe')

  Write-Host 'Step 3/4: Ensuring SeaweedFS weed.exe (Windows x64)' -ForegroundColor Cyan
  Invoke-Checked { & (Join-Path $repoRoot 'scripts/ensure-seaweedfs.ps1') | Out-Host } 'SeaweedFS tool setup failed'

  Write-Host 'Step 4/4: Building Desktop installer(s) via Tauri' -ForegroundColor Cyan
  $desktopTauriDir = Join-Path $repoRoot 'desktop/src-tauri'

  Push-Location $desktopTauriDir
  try {
    if ($Bundles -eq 'all') {
      Invoke-Checked { cargo tauri build | Out-Host } 'tauri build failed'
    } else {
      Invoke-Checked { cargo tauri build --bundles=$Bundles --verbose | Out-Host } "tauri build ($Bundles) failed"
    }
  } finally {
    Pop-Location
  }

  $bundleDir = Join-Path $repoRoot 'desktop/src-tauri/target/release/bundle'
  Write-Host "Build complete. Bundle outputs under: $bundleDir" -ForegroundColor Green
  Write-Host 'What you just built:' -ForegroundColor DarkGray
  Write-Host '  - MSI: Windows Installer package (enterprise-friendly installer)' -ForegroundColor DarkGray
  Write-Host '  - NSIS `*-setup.exe`: Windows installer executable (this is an installer, not the app itself)' -ForegroundColor DarkGray
  Write-Host 'For running the dev app (no installers), use: `./scripts/dev-desktop.ps1`' -ForegroundColor DarkGray
} finally {
  Pop-Location
}
