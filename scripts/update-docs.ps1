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

    # By default, docs/FaceForge - Dev Guide - Scripts.md is regenerated (from comment-based help) before any doc conversions.
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

    # Return a filesystem path; the renderer will receive relative hrefs to staged assets.
    return (Resolve-Path -LiteralPath $cssPath).Path
}

function Normalize-RepoRelPath {
    param([string]$PathLike)

    if ([string]::IsNullOrWhiteSpace($PathLike)) {
        return ''
    }

    # Normalize to forward slashes for stable comparisons.
    return ([string]$PathLike).Trim() -replace '\\', '/'
}

function Get-ForwardSlashPath {
    param([Parameter(Mandatory)][string]$PathLike)
    return ([string]$PathLike) -replace '\\', '/'
}

function Get-RelativeHref {
    param(
        [Parameter(Mandatory)][string]$FromDir,
        [Parameter(Mandatory)][string]$ToPath
    )

    $rel = [System.IO.Path]::GetRelativePath($FromDir, $ToPath)
    return (Get-ForwardSlashPath -PathLike $rel)
}

function Sync-FileIfChanged {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination
    )

    $destDir = Split-Path -Parent $Destination
    if ($destDir -and -not (Test-Path -LiteralPath $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }

    if (Test-Path -LiteralPath $Destination) {
        $srcHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Source).Hash
        $dstHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash
        if ($srcHash -eq $dstHash) {
            return $false
        }
    }

    Copy-Item -LiteralPath $Source -Destination $Destination -Force
    return $true
}

function Sync-DirectoryIfChanged {
    param(
        [Parameter(Mandatory)][string]$SourceDir,
        [Parameter(Mandatory)][string]$DestinationDir
    )

    $changed = $false
    if (-not (Test-Path -LiteralPath $DestinationDir)) {
        New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null
        $changed = $true
    }

    $srcRoot = (Resolve-Path -LiteralPath $SourceDir).Path
    $files = Get-ChildItem -LiteralPath $srcRoot -Recurse -File
    foreach ($f in $files) {
        $rel = [System.IO.Path]::GetRelativePath($srcRoot, $f.FullName)
        $dest = Join-Path $DestinationDir $rel
        if (Sync-FileIfChanged -Source $f.FullName -Destination $dest) {
            $changed = $true
        }
    }

    return $changed
}

function Ensure-DocsReadmeFromRoot {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$RepoRoot
    )

    $src = Join-Path $RepoRoot 'README.md'
    if (-not (Test-Path -LiteralPath $src)) {
        throw "Missing root README.md: $src"
    }

    $dst = Join-Path $RepoRoot 'docs/FaceForge - Readme.md'
    if ($PSCmdlet.ShouldProcess($dst, 'Sync docs/FaceForge - Readme.md from root README.md')) {
        [void](Sync-FileIfChanged -Source $src -Destination $dst)
    }
}

function Ensure-DocsReleaseNotesFromRoot {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$RepoRoot
    )

    $src = Join-Path $RepoRoot 'RELEASE_NOTES.md'
    if (-not (Test-Path -LiteralPath $src)) {
        throw "Missing RELEASE_NOTES.md: $src"
    }

    $dst = Join-Path $RepoRoot 'docs/FaceForge - Dev Guide - Release Notes.md'
    if ($PSCmdlet.ShouldProcess($dst, 'Sync docs/FaceForge - Dev Guide - Release Notes.md from RELEASE_NOTES.md')) {
        [void](Sync-FileIfChanged -Source $src -Destination $dst)
    }
}

function Ensure-DocsStyles {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$VenvPython,
        [Parameter(Mandatory)][string[]]$CssFiles
    )

    $stylesDir = Join-Path $RepoRoot 'docs/styles'
    if (-not (Test-Path -LiteralPath $stylesDir)) {
        New-Item -ItemType Directory -Path $stylesDir -Force | Out-Null
    }

    $stagedCss = @()

    foreach ($css in @($CssFiles)) {
        if ([string]::IsNullOrWhiteSpace($css)) { continue }
        if ($css -match '^[a-zA-Z][a-zA-Z0-9+.-]*://') {
            # Allow external stylesheets; they won't be staged.
            $stagedCss += $css
            continue
        }

        $srcPath = (Resolve-CssHref -RepoRoot $RepoRoot -Css ([string]$css))
        $baseName = [System.IO.Path]::GetFileName($srcPath)

        $destPath = $null
        $norm = Normalize-RepoRelPath -PathLike $css
        if ($norm -eq 'brand/fonts/fonts.css') {
            $destPath = Join-Path $stylesDir (Join-Path 'fonts' $baseName)
        } else {
            $destPath = Join-Path $stylesDir $baseName
        }

        if ($PSCmdlet.ShouldProcess($destPath, "Stage CSS: $css")) {
            [void](Sync-FileIfChanged -Source $srcPath -Destination $destPath)
        }

        $stagedCss += $destPath
    }

    # Stage favicons (used by HTML renders).
    $faviconSrc = Join-Path $RepoRoot 'brand/favicon'
    if (Test-Path -LiteralPath $faviconSrc) {
        $faviconDst = Join-Path $stylesDir 'favicon'
        if ($PSCmdlet.ShouldProcess($faviconDst, 'Stage favicon assets')) {
            [void](Sync-DirectoryIfChanged -SourceDir $faviconSrc -DestinationDir $faviconDst)
        }
    }

    # Generate syntax highlighting CSS.
    # - Screen: dark code blocks (matches the default dark UI)
    # - Print/PDF: keep light code blocks (standard white document theme)
    $syntaxCssPath = Join-Path $stylesDir 'syntax.css'
    $syntaxCss = & $VenvPython -c "from pygments.formatters import HtmlFormatter; print('@media screen {'); print(HtmlFormatter(style='monokai').get_style_defs('.codehilite')); print('}'); print('@media print {'); print(HtmlFormatter(style='default').get_style_defs('.codehilite')); print('}')" | Out-String
    if (-not $syntaxCss.EndsWith("`n")) { $syntaxCss += "`n" }

    $needsWrite = $true
    if (Test-Path -LiteralPath $syntaxCssPath) {
        $existing = Get-Content -LiteralPath $syntaxCssPath -Raw -Encoding UTF8
        if ($existing -eq $syntaxCss) { $needsWrite = $false }
    }

    if ($needsWrite -and $PSCmdlet.ShouldProcess($syntaxCssPath, 'Write syntax highlighting CSS')) {
        Set-Content -LiteralPath $syntaxCssPath -Value $syntaxCss -Encoding UTF8
    }

    $stagedCss += $syntaxCssPath

    return [pscustomobject]@{
        StylesDir = $stylesDir
        CssFiles  = $stagedCss
    }
}

function Ensure-ScriptsReadmeDocInConfig {
    param(
        [Parameter(Mandatory)]
        $ConfigJson,

        [Parameter(Mandatory)]
        [string]$ConfigPath
    )

    # NOTE: Scripts docs are now emitted under docs/ as:
    #   docs/FaceForge - Dev Guide - Scripts.*
    # Config should be maintained manually in scripts/update-docs_config.json.
    return $false
}

$repoRoot = Get-RepoRoot
$venvPython = Ensure-Venv -RepoRoot $repoRoot

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "Config not found: $ConfigPath"
}

$configJson = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json

# Config is the source of truth for which docs are rendered.
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

$printPdfPy = Join-Path $PSScriptRoot '_update_docs_print_pdf.py'
if (-not (Test-Path -LiteralPath $printPdfPy)) {
    throw "Missing PDF printer: $printPdfPy"
}

# Ensure markdown renderer dependency is present in the repo venv.
# (No global Python packages; no Node.)
& $venvPython -c "import markdown" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing Python package: Markdown (for docs rendering)" -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade "Markdown>=3.6" | Out-Host
}

# Ensure syntax highlighting dependency is present.
& $venvPython -c "import pygments" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing Python package: Pygments (for docs syntax highlighting)" -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade "Pygments>=2.17" | Out-Host
}

# Ensure DevTools PDF printing dependency is present.
& $venvPython -c "import websockets" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing Python package: websockets (for PDF footer control)" -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade "websockets>=12" | Out-Host
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

# By default, regenerate docs/FaceForge - Dev Guide - Scripts.md from PowerShell comment-based help before conversions.
# This keeps scripts documentation in-sync and ensures subsequent HTML/PDF outputs are based on the latest content.
$generateScriptsReadme = Join-Path $PSScriptRoot 'generate-scripts-readme.ps1'
if (-not (Test-Path -LiteralPath $generateScriptsReadme)) {
    throw "Missing generator: $generateScriptsReadme"
}

if (-not $SkipScriptsReadme) {
    if ($PSCmdlet.ShouldProcess('docs/FaceForge - Dev Guide - Scripts.md', 'Generate docs/FaceForge - Dev Guide - Scripts.md from scripts/*.ps1 help')) {
        $outPath = Join-Path $repoRoot 'docs/FaceForge - Dev Guide - Scripts.md'
        & $generateScriptsReadme -OutputPath $outPath -WhatIf:$WhatIfPreference
    }
}

# Always ensure docs/FaceForge - Readme.md mirrors the root README.md before any conversions.
Ensure-DocsReadmeFromRoot -RepoRoot $repoRoot

# Always ensure docs/FaceForge - Dev Guide - Release Notes.md mirrors RELEASE_NOTES.md before any conversions.
Ensure-DocsReleaseNotesFromRoot -RepoRoot $repoRoot

# Stage styles + brand assets for relative references in HTML output.
$staged = Ensure-DocsStyles -RepoRoot $repoRoot -VenvPython $venvPython -CssFiles $cssFiles

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
            $outputDir = Split-Path -Parent $htmlPath

            $cssArgs = @()
            foreach ($css in @($staged.CssFiles)) {
                if ([string]::IsNullOrWhiteSpace([string]$css)) { continue }
                if ($css -match '^[a-zA-Z][a-zA-Z0-9+.-]*://') {
                    $cssArgs += @('--css', [string]$css)
                    continue
                }
                $cssArgs += @('--css', (Get-RelativeHref -FromDir $outputDir -ToPath ([string]$css)))
            }

            $faviconBase = Get-RelativeHref -FromDir $outputDir -ToPath ([string]$staged.StylesDir)

            & $venvPython $renderPy `
                --input $sourcePath `
                --output $htmlPath `
                --favicon-base $faviconBase `
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

            # Use DevTools protocol printing so we can control headers/footers.
            # This avoids Chromium's default footer showing machine-local absolute paths.
            & $venvPython $printPdfPy `
                --browser $pdfCmd `
                --html $htmlPath `
                --pdf $pdfPath | Out-Host
            $exit = $LASTEXITCODE
            if ($exit -ne 0) {
                throw "PDF generation failed for $sourceRel (exit code $exit)"
            }

            $built++
            Write-Host "PDF   $pdfRel" -ForegroundColor Green
        }
    }
}

Write-Host "Done. Built=$built Skipped=$skipped" -ForegroundColor Cyan
