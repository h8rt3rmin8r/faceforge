<#
.SYNOPSIS
    Bumps FaceForge version across Core + Desktop manifests.

.DESCRIPTION
    Updates version strings in the following files:
      - core/pyproject.toml
      - core/src/faceforge_core/app.py
      - desktop/src-tauri/Cargo.toml
    - desktop/src-tauri/Cargo.lock
      - desktop/src-tauri/tauri.conf.json

    The script supports -WhatIf / -Confirm for safe previews.

.PARAMETER Version
    The semantic version to set (e.g. 0.1.2).

.EXAMPLE
    ./scripts/set-version.ps1 -Version 0.1.2
    Updates all known manifests to 0.1.2.

.EXAMPLE
    ./scripts/set-version.ps1 -Version 0.1.2 -WhatIf
    Shows what would change without modifying files.

.NOTES
    If a target file or pattern is not found, the script emits a warning and continues.
#>
[CmdletBinding(SupportsShouldProcess = $true, PositionalBinding = $false, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Version
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot/..").Path

function Update-FileContent {
    [CmdletBinding(SupportsShouldProcess = $true, PositionalBinding = $false, ConfirmImpact = 'Medium')]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Regex,

        [Parameter(Mandatory = $true)]
        [ValidateNotNullOrEmpty()]
        [string]$Replacement
    )
    $FullPath = Join-Path $Root $Path
    if (-not (Test-Path $FullPath)) {
        Write-Warning "File not found: $Path"
        return
    }

    $Content = Get-Content $FullPath -Raw
    # Verify match first
    if ($Content -match $Regex) {
        $NewContent = $Content -replace $Regex, $Replacement
        if ($PSCmdlet.ShouldProcess($FullPath, "Update version to $Version")) {
            Set-Content $FullPath -NoNewline -Value $NewContent
            Write-Host "Updated $Path to $Version"
        }
    } else {
        Write-Warning "Pattern '$Regex' not found in $Path"
    }
}

Write-Host "Bumping version to $Version..."

# core/pyproject.toml
# version = "0.1.0"
Update-FileContent -Path "core/pyproject.toml" -Regex '(?m)^version = "\d+\.\d+\.\d+"' -Replacement "version = `"$Version`""

# desktop/src-tauri/Cargo.toml
# version = "0.1.0"
Update-FileContent -Path "desktop/src-tauri/Cargo.toml" -Regex '(?m)^version = "\d+\.\d+\.\d+"' -Replacement "version = `"$Version`""

# desktop/src-tauri/Cargo.lock
# Update only the local faceforge_desktop package entry.
Update-FileContent -Path "desktop/src-tauri/Cargo.lock" -Regex '(?ms)(\[\[package\]\]\s*\r?\nname = "faceforge_desktop"\s*\r?\nversion = ")\d+\.\d+\.\d+(")' -Replacement "`$1$Version`$2"

# desktop/src-tauri/tauri.conf.json
# "version": "0.1.0"
Update-FileContent -Path "desktop/src-tauri/tauri.conf.json" -Regex '(?m)"version": "\d+\.\d+\.\d+"' -Replacement "`"version`": `"$Version`""

# core/src/faceforge_core/app.py
# version="0.0.0"
Update-FileContent -Path "core/src/faceforge_core/app.py" -Regex 'version="\d+\.\d+\.\d+"' -Replacement "version=`"$Version`""

Write-Host "Version bump complete."
