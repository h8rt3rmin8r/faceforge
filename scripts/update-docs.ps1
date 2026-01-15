<#[
.SYNOPSIS
    Builds HTML and PDF renderings for selected Markdown docs.

.DESCRIPTION
    Reads scripts/update-docs_config.json for a list of Markdown files and emits:
      - HTML (standalone wrapper)
      - PDF (via headless Chromium print-to-PDF using Microsoft Edge or Google Chrome)

    This intentionally does NOT add Node.js tooling to the repo.

.EXAMPLE
    ./scripts/update-docs.ps1

.EXAMPLE
    ./scripts/update-docs.ps1 -WhatIf

.EXAMPLE
    ./scripts/update-docs.ps1 -ConfigPath ./scripts/update-docs_config.json -Force
#>

[CmdletBinding(SupportsShouldProcess = $true, PositionalBinding = $false)]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'update-docs_config.json'),
    [switch]$Force,

    # By default, scripts/README.md is regenerated (from comment-based help) before any doc conversions.
    # Use this switch to bypass that behavior.
    [switch]$SkipScriptsReadme
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot '_ensure-venv.ps1')

function Resolve-RepoPath {
    param(
        [string]$RepoRoot,
        [string]$PathLike
    )

    if ([string]::IsNullOrWhiteSpace($PathLike)) {
        throw 'Empty path in update-docs config.'
    }

    if ([System.IO.Path]::IsPathRooted($PathLike)) {
        return (Resolve-Path -LiteralPath $PathLike).Path
    }

    return (Resolve-Path -LiteralPath (Join-Path $RepoRoot $PathLike)).Path
}

function Get-PdfEngineCommand {
    param(
        [ValidateSet('edge', 'chrome')]
        [string]$Engine
    )

    if ($Engine -eq 'edge') {
        $cmd = Get-Command msedge -ErrorAction SilentlyContinue
        if ($null -ne $cmd) { return $cmd.Source }

        $pf = $env:ProgramFiles
        $pf86 = ${env:ProgramFiles(x86)}
        $candidates = @()
        if ($pf) { $candidates += (Join-Path $pf 'Microsoft\Edge\Application\msedge.exe') }
        if ($pf86) { $candidates += (Join-Path $pf86 'Microsoft\Edge\Application\msedge.exe') }
        foreach ($p in $candidates) { if (Test-Path $p) { return $p } }

        return $null
    }

    if ($Engine -eq 'chrome') {
        $cmd = Get-Command chrome -ErrorAction SilentlyContinue
        if ($null -ne $cmd) { return $cmd.Source }

        $pf = $env:ProgramFiles
        $pf86 = ${env:ProgramFiles(x86)}
        $candidates = @()
        if ($pf) { $candidates += (Join-Path $pf 'Google\Chrome\Application\chrome.exe') }
        if ($pf86) { $candidates += (Join-Path $pf86 'Google\Chrome\Application\chrome.exe') }
        foreach ($p in $candidates) { if (Test-Path $p) { return $p } }

        return $null
    }
}

function Get-FileUri {
    param([string]$Path)
    return ([System.Uri](Resolve-Path -LiteralPath $Path).Path).AbsoluteUri
}

function Resolve-CssHref {
    param(
        [string]$RepoRoot,
        [string]$Css
    )

    if ([string]::IsNullOrWhiteSpace($Css)) {
        return $null
    }

    # Allow web URLs and explicit file URIs.
    if ($Css -match '^[a-zA-Z][a-zA-Z0-9+.-]*://') {
        return $Css
    }

    $cssPath = Join-Path $RepoRoot $Css
    if (-not (Test-Path -LiteralPath $cssPath)) {
        throw "Configured css file not found: $Css"
    }

    return (New-Object System.Uri((Resolve-Path -LiteralPath $cssPath).Path)).AbsoluteUri
}

function Normalize-RepoRelPath {
    param([string]$PathLike)

    if ([string]::IsNullOrWhiteSpace($PathLike)) {
        return ''
    }

    # Normalize to forward slashes for stable comparisons.
    return ([string]$PathLike).Trim() -replace '\\', '/'
}

function Ensure-ScriptsReadmeDocInConfig {
    param(
        [Parameter(Mandatory)]
        $ConfigJson,

        [Parameter(Mandatory)]
        [string]$ConfigPath
    )

    $targetSource = 'scripts/README.md'
    $targetHtml = 'scripts/README.html'
    $targetPdf = 'scripts/README.pdf'

    if ($null -eq $ConfigJson.docs) {
        $ConfigJson | Add-Member -MemberType NoteProperty -Name 'docs' -Value @() -Force
    }

    $docs = @($ConfigJson.docs)
    $targetNorm = Normalize-RepoRelPath -PathLike $targetSource

    foreach ($d in $docs) {
        if ($null -eq $d) { continue }
        $src = $d.PSObject.Properties['source'].Value
        if ((Normalize-RepoRelPath -PathLike ([string]$src)) -eq $targetNorm) {
            return $false
        }
    }

    $newEntry = [pscustomobject]@{
        source = $targetSource
        html   = $targetHtml
        pdf    = $targetPdf
    }

    $ConfigJson.docs = @($docs + $newEntry)

    if ($PSCmdlet.ShouldProcess($ConfigPath, "Add docs entry for $targetSource")) {
        $jsonOut = $ConfigJson | ConvertTo-Json -Depth 50
        # Ensure trailing newline for nicer diffs.
        if (-not $jsonOut.EndsWith("`n")) { $jsonOut += "`n" }
        Set-Content -LiteralPath $ConfigPath -Value $jsonOut -Encoding UTF8
    }

    return $true
}

$repoRoot = Get-RepoRoot
$venvPython = Ensure-Venv -RepoRoot $repoRoot

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "Config not found: $ConfigPath"
}

$configJson = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json

# Ensure scripts/README.md is included in the docs list (so it can be rendered).
# We do this early so the remainder of the script operates on the complete doc set.
$configUpdated = Ensure-ScriptsReadmeDocInConfig -ConfigJson $configJson -ConfigPath $ConfigPath

$defaults = $configJson.defaults
if ($null -eq $defaults) { $defaults = @{} }

$skipUnchanged = $true
if ($null -ne $defaults.skipUnchanged) { $skipUnchanged = [bool]$defaults.skipUnchanged }

$failOnMissingSource = $true
if ($null -ne $defaults.failOnMissingSource) { $failOnMissingSource = [bool]$defaults.failOnMissingSource }

$emitHtml = $true
if ($null -ne $defaults.emitHtml) { $emitHtml = [bool]$defaults.emitHtml }

$emitPdf = $true
if ($null -ne $defaults.emitPdf) { $emitPdf = [bool]$defaults.emitPdf }

$cssFiles = @()
if ($null -ne $defaults.cssFiles) { $cssFiles = @($defaults.cssFiles) }

$pdfEngine = 'edge'
if ($null -ne $defaults.pdf -and $null -ne $defaults.pdf.engine) { $pdfEngine = [string]$defaults.pdf.engine }

$renderPy = Join-Path $PSScriptRoot '_update_docs_render.py'
if (-not (Test-Path -LiteralPath $renderPy)) {
    throw "Missing renderer: $renderPy"
}

# Ensure markdown renderer dependency is present in the repo venv.
# (No global Python packages; no Node.)
& $venvPython -c "import markdown" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing Python package: Markdown (for docs rendering)" -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade "Markdown>=3.6" | Out-Host
}

$pdfCmd = $null
if ($emitPdf) {
    $pdfCmd = Get-PdfEngineCommand -Engine $pdfEngine
    if ($null -eq $pdfCmd) {
        throw @(
            "PDF engine '$pdfEngine' not found.",
            "Install Microsoft Edge (recommended) or set defaults.pdf.engine to 'chrome'."
        ) -join "`n"
    }
}

# By default, regenerate scripts/README.md from PowerShell comment-based help before conversions.
# This keeps scripts documentation in-sync and ensures subsequent HTML/PDF outputs are based on the latest README.
$generateScriptsReadme = Join-Path $PSScriptRoot 'generate-scripts-readme.ps1'
if (-not (Test-Path -LiteralPath $generateScriptsReadme)) {
    throw "Missing generator: $generateScriptsReadme"
}

if (-not $SkipScriptsReadme) {
    if ($PSCmdlet.ShouldProcess('scripts/README.md', 'Generate scripts/README.md from scripts/*.ps1 help')) {
        $outPath = Join-Path $repoRoot 'scripts/README.md'
        & $generateScriptsReadme -OutputPath $outPath -WhatIf:$WhatIfPreference
    }
}

$docs = @($configJson.docs)
if ($docs.Count -eq 0) {
    Write-Host "No docs listed in config: $ConfigPath" -ForegroundColor Yellow
    exit 0
}

$built = 0
$skipped = 0

foreach ($doc in $docs) {
    $sourceRel = [string]$doc.source
    $sourcePath = Join-Path $repoRoot $sourceRel

    if (-not (Test-Path -LiteralPath $sourcePath)) {
        $msg = "Missing source markdown: $sourceRel"
        if ($failOnMissingSource) { throw $msg }
        Write-Warning $msg
        continue
    }

    $htmlRel = [string]$doc.html
    $pdfRel = [string]$doc.pdf

    if ($emitHtml -and [string]::IsNullOrWhiteSpace($htmlRel)) {
        throw "Doc entry missing 'html' output path: source=$sourceRel"
    }
    if ($emitPdf -and [string]::IsNullOrWhiteSpace($pdfRel)) {
        throw "Doc entry missing 'pdf' output path: source=$sourceRel"
    }

    $htmlPath = if ($emitHtml) { Join-Path $repoRoot $htmlRel } else { $null }
    $pdfPath = if ($emitPdf) { Join-Path $repoRoot $pdfRel } else { $null }

    $sourceItem = Get-Item -LiteralPath $sourcePath
    $needsHtml = $emitHtml
    $needsPdf = $emitPdf

    if (-not $Force -and $skipUnchanged) {
        if ($emitHtml -and (Test-Path -LiteralPath $htmlPath)) {
            $htmlItem = Get-Item -LiteralPath $htmlPath
            if ($htmlItem.LastWriteTimeUtc -ge $sourceItem.LastWriteTimeUtc) {
                $needsHtml = $false
            }
        }

        if ($emitPdf -and (Test-Path -LiteralPath $pdfPath)) {
            $pdfItem = Get-Item -LiteralPath $pdfPath
            # PDF depends on HTML content; if HTML would be regenerated, force PDF too.
            if (-not $needsHtml -and $pdfItem.LastWriteTimeUtc -ge $sourceItem.LastWriteTimeUtc) {
                $needsPdf = $false
            }
        }
    }

    if (-not $needsHtml -and -not $needsPdf) {
        $skipped++
        Write-Host "SKIP  $sourceRel" -ForegroundColor DarkGray
        continue
    }

    if ($needsHtml) {
        if ($PSCmdlet.ShouldProcess($htmlRel, "Render HTML from $sourceRel")) {
            $cssArgs = @()
            foreach ($css in $cssFiles) {
                $href = Resolve-CssHref -RepoRoot $repoRoot -Css ([string]$css)
                if ($null -ne $href) {
                    $cssArgs += @('--css', $href)
                }
            }

            & $venvPython $renderPy `
                --input $sourcePath `
                --output $htmlPath `
                --base-href '__AUTO__' `
                @cssArgs

            $built++
            Write-Host "HTML  $htmlRel" -ForegroundColor Green
        }
    }

    if ($needsPdf) {
        # Ensure the HTML exists on disk (either we just built it, or it already existed)
        if (-not (Test-Path -LiteralPath $htmlPath)) {
            if ($WhatIfPreference) {
                Write-Host "WhatIf: PDF depends on HTML that would be generated ($htmlRel)" -ForegroundColor DarkGray
            } else {
                throw "Cannot build PDF because HTML is missing: $htmlRel"
            }
        }

        if ($PSCmdlet.ShouldProcess($pdfRel, "Render PDF from $htmlRel via $pdfEngine")) {
            $pdfDir = Split-Path -Parent $pdfPath
            if ($pdfDir -and -not (Test-Path -LiteralPath $pdfDir)) {
                New-Item -ItemType Directory -Path $pdfDir -Force | Out-Null
            }

            $htmlUri = (Get-Item -LiteralPath $htmlPath).FullName | ForEach-Object { (New-Object System.Uri($_)).AbsoluteUri }

            $argsNew = @(
                '--headless=new',
                '--disable-gpu',
                "--print-to-pdf=$pdfPath",
                '--no-first-run',
                '--no-default-browser-check',
                $htmlUri
            )

            & $pdfCmd @argsNew | Out-Host
            $exit = $LASTEXITCODE

            if ($exit -ne 0) {
                $argsOld = @(
                    '--headless',
                    '--disable-gpu',
                    "--print-to-pdf=$pdfPath",
                    '--no-first-run',
                    '--no-default-browser-check',
                    $htmlUri
                )

                & $pdfCmd @argsOld | Out-Host
                $exit = $LASTEXITCODE
            }

            if ($exit -ne 0) {
                throw "PDF generation failed for $sourceRel (exit code $exit)"
            }

            $built++
            Write-Host "PDF   $pdfRel" -ForegroundColor Green
        }
    }
}

Write-Host "Done. Built=$built Skipped=$skipped" -ForegroundColor Cyan
