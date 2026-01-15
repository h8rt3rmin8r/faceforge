<#
.SYNOPSIS
  Runs FaceForge Desktop in development mode.

.DESCRIPTION
  This starts the Tauri desktop app as a normal `cargo run` process (keeps the terminal attached).

  Note: `cargo tauri build` produces installers on Windows (MSI + NSIS `*-setup.exe`).
  This script is for *running* the dev app, not packaging.

.EXAMPLE
  ./scripts/dev-desktop.ps1

.EXAMPLE
  ./scripts/dev-desktop.ps1 -Release
#>

[CmdletBinding(PositionalBinding = $false)]
param(
  [switch]$Release
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
$desktopTauriDir = Join-Path $repoRoot 'desktop/src-tauri'

Write-Host 'Running FaceForge Desktop (dev)…' -ForegroundColor Cyan
Write-Host "Dir: $desktopTauriDir" -ForegroundColor DarkGray
Write-Host 'Notes:' -ForegroundColor DarkGray
Write-Host '  - This runs the Desktop app. It does NOT build installers.' -ForegroundColor DarkGray
Write-Host '  - Installers are produced by `./scripts/build-desktop.ps1` (MSI + NSIS `*-setup.exe`).' -ForegroundColor DarkGray
Write-Host '  - If no window appears, check the system tray (default is minimize-to-tray on close/exit).' -ForegroundColor DarkGray

Push-Location $desktopTauriDir
try {
  if ($Release) {
    Invoke-Checked { cargo run --release --no-default-features -- | Out-Host } 'Desktop run failed'
  } else {
    Invoke-Checked { cargo run --no-default-features -- | Out-Host } 'Desktop run failed'
  }
} finally {
  Pop-Location
}
