<#
.SYNOPSIS
        Helper utilities for FaceForge PowerShell scripts.

.DESCRIPTION
        This file is intended to be dot-sourced by other scripts in the `scripts/` directory.
        It provides shared helpers for:
            - Resolving the repository root.
            - Creating and locating the repo-local Python virtual environment (`.venv`).
            - Returning the correct `.venv` Python executable path for downstream scripts.

        Design goals:
            - Never depend on global Python packages at runtime.
            - Prefer the Windows `py` launcher to bootstrap Python 3.12 venv creation.
            - Make failures actionable with clear error messages.

.NOTES
        This file defines functions and does not execute any build/run tasks on its own.
        Usage pattern:
            . (Join-Path $PSScriptRoot '_ensure-venv.ps1')
            $repoRoot = Get-RepoRoot
            $venvPython = Ensure-Venv -RepoRoot $repoRoot
#>

[CmdletBinding(PositionalBinding = $false)]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-RepoRoot {
    # scripts/ lives at the repo root
    return (Split-Path -Parent $PSScriptRoot)
}

function Get-VenvPythonPath([string]$RepoRoot) {
    return Join-Path $RepoRoot '.venv\Scripts\python.exe'
}

function Ensure-Venv {
    param(
        [string]$RepoRoot
    )

    $venvDir = Join-Path $RepoRoot '.venv'
    $venvPython = Get-VenvPythonPath -RepoRoot $RepoRoot

    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating venv at $venvDir" -ForegroundColor Cyan

        # Bootstrap NOTE: creating a venv necessarily requires a system Python.
        # After creation, all commands MUST run via .venv\Scripts\python.exe.
        $created = $false

        $py = Get-Command py -ErrorAction SilentlyContinue
        if ($null -ne $py) {
            try {
                & py -3.12 -m venv $venvDir | Out-Host
                if ($LASTEXITCODE -eq 0) { $created = $true }
            } catch {
                $created = $false
            }

            if (-not $created) {
                try {
                    & py -3 -m venv $venvDir | Out-Host
                    if ($LASTEXITCODE -eq 0) { $created = $true }
                } catch {
                    $created = $false
                }
            }
        }

        if (-not $created) {
            $python = Get-Command python -ErrorAction SilentlyContinue
            if ($null -ne $python) {
                & python -m venv $venvDir | Out-Host
                if ($LASTEXITCODE -eq 0) { $created = $true }
            }
        }

        if (-not $created -or -not (Test-Path $venvPython)) {
            throw @(
                'Failed to create .venv because no usable system Python was found.',
                'Install Python 3.12.x (recommended: enable the Windows "py" launcher), then re-run:',
                '  ./scripts/dev-core.ps1',
                '',
                'If Python is installed but not detected, ensure it is on PATH or that the "py" launcher can find it (run: py --list).'
            ) -join "`n"
        }
    }

    & $venvPython -m pip install --upgrade pip | Out-Host

    return $venvPython
}
