param(
    # By default we prune old timestamped build/dist folders under core/ to keep the repo tidy.
    # Use -KeepBuildHistory to preserve build-* and dist-* folders.
    [switch]$KeepBuildHistory,

    # If dist/ or build/ cannot be deleted (e.g., another process is holding a handle),
    # the default behavior is to FAIL with a helpful message instead of creating timestamped folders.
    # Use -AllowTimestampFallback to opt into the old behavior.
    [switch]$AllowTimestampFallback
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# This build script is expected to run non-interactively (CI and local dev).
# Disable confirmation prompts triggered by ShouldProcess/ConfirmImpact.
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

function Invoke-OldPyInstallerOutputCleanup {
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory = $true)]
        [string]$CoreDir,
        [string[]]$ExcludeNames = @()
    )

    if (-not (Test-Path $CoreDir)) {
        return
    }

    $exclude = @{}
    foreach ($name in $ExcludeNames) {
        if ($null -ne $name -and $name.Trim().Length -gt 0) {
            $exclude[$name] = $true
        }
    }

    $candidates = Get-ChildItem -Path $CoreDir -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -like 'build-*' -or $_.Name -like 'dist-*'
        }

    foreach ($dir in $candidates) {
        if ($exclude.ContainsKey($dir.Name)) {
            continue
        }

        try {
            if ($PSCmdlet.ShouldProcess($dir.FullName, 'Remove old PyInstaller output directory')) {
                Remove-Item -Recurse -Force $dir.FullName
            }
        }
        catch {
            Write-Warning "Could not remove $($dir.FullName). $($_.Exception.Message)"
        }
    }
}

function Invoke-DirectoryRemovalWithRetries {
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [int]$MaxAttempts = 5,
        [int]$DelayMs = 250
    )

    if (-not (Test-Path $Path)) {
        return
    }

    if (-not $PSCmdlet.ShouldProcess($Path, 'Remove directory')) {
        return
    }

    $lastError = $null
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Remove-Item -Recurse -Force $Path
            return
        }
        catch {
            $lastError = $_
            Start-Sleep -Milliseconds ($DelayMs * $attempt)
        }
    }

    if ($null -ne $lastError) {
        throw $lastError
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

    # Keep the repo tidy: prune old timestamped outputs from previous locked builds.
    if (-not $KeepBuildHistory) {
        Invoke-OldPyInstallerOutputCleanup -CoreDir (Join-Path $repoRoot 'core')
    }

    $distPath = 'dist'
    $workPath = 'build'

    # Clean previous builds (but don't fail if dist is locked by another process)
    if (Test-Path $workPath) {
        try {
            Invoke-DirectoryRemovalWithRetries -Path $workPath
        }
        catch {
            if ($AllowTimestampFallback) {
                $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
                $workPath = "build-$stamp"
                Write-Warning "Could not remove existing build/ (likely in use). Building into $workPath instead."
            } else {
                throw "Could not remove core/build (likely a handle is open, e.g. a terminal with CWD in build/). Close any shells/Explorer windows using core/build and re-run. Details: $($_.Exception.Message)"
            }
        }
    }
    if (Test-Path $distPath) {
        try {
            Invoke-DirectoryRemovalWithRetries -Path $distPath
        }
        catch {
            if ($AllowTimestampFallback) {
                $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
                $distPath = "dist-$stamp"
                $workPath = "build-$stamp"
                Write-Warning "Could not remove existing dist/ (likely in use). Building into $distPath instead."
            } else {
                throw "Could not remove core/dist (likely a handle is open, e.g. a terminal with CWD in dist/). Close any shells/Explorer windows using core/dist and re-run. Details: $($_.Exception.Message)"
            }
        }
    }

    # Run PyInstaller via Python module to ensure we use the venv
    Invoke-Checked {
        & $venvPython -m PyInstaller pyinstaller.spec --noconfirm --distpath $distPath --workpath $workPath
    } 'PyInstaller build failed'

    # Debug: List generated files to diagnosing path issues in CI
    Write-Host "Listing contents of $distPath..." -ForegroundColor Gray
    if (Test-Path $distPath) {
        Get-ChildItem -Path $distPath -Recurse | Select-Object -First 20 | ForEach-Object { Write-Host " - $($_.Name)" }
    } else {
        Write-Warning "dist/ directory was not found after PyInstaller ran."
    }

    # Verify + normalize output location for callers (e.g., GitHub Actions expects core/dist/faceforge-core.exe)
    # PyInstaller output shape can vary across versions/configs:
    #  - onefile: dist/<name>.exe
    #  - onedir:  dist/<name>/<name>.exe
    #  - name normalization: some builds may emit faceforge_core.exe instead of faceforge-core.exe
    $coreDir = (Join-Path $repoRoot 'core')
    $expectedExeName = 'faceforge-core.exe'
    $normalizedExePath = Join-Path $distPath $expectedExeName
    $normalizedExeFullPath = Join-Path $coreDir $normalizedExePath

    $knownCandidateRelPaths = @(
        (Join-Path $distPath 'faceforge-core.exe'),
        (Join-Path $distPath 'faceforge_core.exe'),
        (Join-Path (Join-Path $distPath 'faceforge-core') 'faceforge-core.exe'),
        (Join-Path (Join-Path $distPath 'faceforge_core') 'faceforge_core.exe')
    )

    $foundExePath = $null
    foreach ($candidate in $knownCandidateRelPaths) {
        if (Test-Path $candidate) {
            $foundExePath = $candidate
            break
        }
    }

    if ($null -eq $foundExePath) {
        $nameCandidates = @(
            Get-ChildItem -Path $distPath -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -in @('faceforge-core.exe', 'faceforge_core.exe') } |
                Select-Object -ExpandProperty FullName
        )
        if ($nameCandidates.Count -ge 1) {
            $foundExePath = $nameCandidates[0]
        }
    }

    if ($null -eq $foundExePath) {
        # Last-resort: if exactly one .exe exists in dist/, use it.
        $exeCandidates = @(
            Get-ChildItem -Path $distPath -Recurse -File -Filter '*.exe' -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty FullName
        )
        if ($exeCandidates.Count -eq 1) {
            $foundExePath = $exeCandidates[0]
        }
    }

    if ($null -eq $foundExePath) {
        $distListing = Get-ChildItem -Path $distPath -Force -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty Name
        if ($distListing) {
            throw "Build failed: $normalizedExeFullPath not found. dist/ contains: $($distListing -join ', ')"
        }
        throw "Build failed: $normalizedExeFullPath not found"
    }

    # Always provide a stable path/name for downstream scripts and CI artifacts.
    if ($foundExePath -ne $normalizedExePath) {
        $foundExeFullPath = if ([System.IO.Path]::IsPathRooted($foundExePath)) { $foundExePath } else { (Join-Path $coreDir $foundExePath) }
        try {
            Copy-Item -Force $foundExePath $normalizedExePath
        }
        catch {
            throw "Build produced $foundExeFullPath but could not copy to $normalizedExeFullPath. Details: $($_.Exception.Message)"
        }
    }

    $exePath = $normalizedExePath

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

    # Post-build tidy-up: if we had to fall back to timestamped folders, delete older ones.
    if (-not $KeepBuildHistory) {
        $exclude = @($distPath, $workPath)
        Invoke-OldPyInstallerOutputCleanup -CoreDir (Join-Path $repoRoot 'core') -ExcludeNames $exclude
    }
}
finally {
    Pop-Location
}
