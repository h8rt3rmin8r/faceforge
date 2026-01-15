<#
.SYNOPSIS
    Builds HTML and PDF renderings for selected Markdown docs.

.DESCRIPTION
        Reads scripts/update-docs_config.json for a list of "actions" and executes them in phases:
            1) copy      (sync files into their canonical docs/ locations)
            2) transform (e.g. Markdown -> HTML)
            3) print     (e.g. HTML -> PDF via headless Chromium)

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
    [string]$ConfigPath,
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
    throw 'Get-PdfEngineCommand is deprecated in config version 2. Use defaults.headless primary/fallback instead.'
}

function Get-OsKey {
    if ($IsWindows) { return 'windows' }
    if ($IsMacOS) { return 'darwin' }
    return 'linux'
}

function Resolve-HeadlessBrowserCommand {
    param(
        [Parameter(Mandatory)]$HeadlessConfig
    )

    $osKey = Get-OsKey

    function Resolve-One {
        param([Parameter(Mandatory)]$Entry)

        $name = [string]$Entry.name
        $pathMap = $Entry.path
        $pathCandidate = $null
        if ($null -ne $pathMap -and $null -ne $pathMap.$osKey) {
            $pathCandidate = [string]$pathMap.$osKey
        }

        if (-not [string]::IsNullOrWhiteSpace($pathCandidate)) {
            $expanded = [System.Environment]::ExpandEnvironmentVariables($pathCandidate)
            if (Test-Path -LiteralPath $expanded) {
                return $expanded
            }
        }

        # Fall back to PATH-based resolution.
        if ($name -eq 'edge') {
            $cmd = Get-Command msedge -ErrorAction SilentlyContinue
            if ($null -ne $cmd) { return $cmd.Source }
        }
        if ($name -eq 'chrome') {
            $cmd = Get-Command chrome -ErrorAction SilentlyContinue
            if ($null -ne $cmd) { return $cmd.Source }
        }

        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $cmd) { return $cmd.Source }

        return $null
    }

    if ($null -eq $HeadlessConfig.primary -or $null -eq $HeadlessConfig.fallback) {
        throw 'defaults.headless.primary and defaults.headless.fallback must be configured.'
    }

    $primary = Resolve-One -Entry $HeadlessConfig.primary
    if ($null -ne $primary) { return $primary }

    $fallback = Resolve-One -Entry $HeadlessConfig.fallback
    if ($null -ne $fallback) { return $fallback }

    $primaryName = [string]$HeadlessConfig.primary.name
    $fallbackName = [string]$HeadlessConfig.fallback.name
    throw @(
        'No headless browser found for PDF printing.',
        "Tried primary='$primaryName' and fallback='$fallbackName'.",
        'Install Edge/Chrome or update defaults.headless.*.path for your OS.'
    ) -join "`n"
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
    $syntaxCss = & $VenvPython -c "from pygments.formatters import HtmlFormatter; print('@media screen {'); print(HtmlFormatter(style='monokai').get_style_defs('.codehilite')); print('}'); print('@media print {'); print(HtmlFormatter(style='default').get_style_defs('.codehilite')); print('pre, code, .codehilite pre, .codehilite code { font-size: 10px; line-height: 1.25; }'); print('pre, .codehilite pre { white-space: pre-wrap !important; overflow-x: visible !important; overflow-wrap: anywhere; word-break: break-word; }'); print('code { white-space: pre-wrap; }'); print('}')" | Out-String
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

$repoRoot = Get-RepoRoot
$venvPython = Ensure-Venv -RepoRoot $repoRoot

$defaultConfigPath = Join-Path $PSScriptRoot 'update-docs_config.json'
$configProvided = $PSBoundParameters.ContainsKey('ConfigPath')

if ($configProvided -and [string]::IsNullOrWhiteSpace($ConfigPath)) {
    throw @(
        'ConfigPath was provided but is empty.',
        "Provide -ConfigPath <path> or omit it to use the default:",
        "  $defaultConfigPath"
    ) -join "`n"
}

if (-not $configProvided) {
    $ConfigPath = $defaultConfigPath
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    if ($configProvided) {
        throw "Config not found: $ConfigPath"
    }

    throw @(
        'Default docs config not found next to this script.',
        "Looked for:",
        "  $defaultConfigPath",
        'Either create that file or pass a config explicitly:',
        '  ./scripts/update-docs.ps1 -ConfigPath <path-to-update-docs_config.json>'
    ) -join "`n"
}

$configJson = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json

if ($null -eq $configJson.version -or [int]$configJson.version -ne 2) {
    throw "Unsupported config version in $ConfigPath. Expected version=2."
}

$defaults = $configJson.defaults
if ($null -eq $defaults) { $defaults = @{} }

function Get-OptionalJsonValue {
    param(
        [Parameter(Mandatory)]$Object,
        [Parameter(Mandatory)][string]$Name,
        $DefaultValue
    )

    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $DefaultValue }
    return $prop.Value
}

$skipUnchanged = $true
$skipUnchanged = [bool](Get-OptionalJsonValue -Object $defaults -Name 'skipUnchanged' -DefaultValue $skipUnchanged)

$failOnMissingSource = $true
$failOnMissingSource = [bool](Get-OptionalJsonValue -Object $defaults -Name 'failOnMissingSource' -DefaultValue $failOnMissingSource)

$emitHtml = $true
$emitHtml = [bool](Get-OptionalJsonValue -Object $defaults -Name 'emitHtml' -DefaultValue $emitHtml)

$emitPdf = $true
$emitPdf = [bool](Get-OptionalJsonValue -Object $defaults -Name 'emitPdf' -DefaultValue $emitPdf)

$cssFiles = @()
$cssFilesValue = Get-OptionalJsonValue -Object $defaults -Name 'cssFiles' -DefaultValue $null
if ($null -ne $cssFilesValue) { $cssFiles = @($cssFilesValue) }

$headless = Get-OptionalJsonValue -Object $defaults -Name 'headless' -DefaultValue $null

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
function Get-ActionTargets {
    param([Parameter(Mandatory)]$Action)
    if ($null -eq $Action.targets) { return @() }
    return @($Action.targets)
}

$actions = @($configJson.actions)
if ($actions.Count -eq 0) {
    Write-Host "No actions listed in config: $ConfigPath" -ForegroundColor Yellow
    exit 0
}

$copyActions = @()
$transformActions = @()
$printActions = @()

foreach ($a in $actions) {
    $kind = [string]$a.action
    switch ($kind) {
        'copy' { $copyActions += $a }
        'transform' { $transformActions += $a }
        'print' { $printActions += $a }
        default { throw "Unknown action type '$kind' in config." }
    }
}

# Install websockets only if we will print PDFs.
$resolvedHeadlessCmd = $null
if ($printActions.Count -gt 0) {
    & $venvPython -c "import websockets" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing Python package: websockets (for PDF footer control)" -ForegroundColor Cyan
        & $venvPython -m pip install --upgrade "websockets>=12" | Out-Host
    }
    $resolvedHeadlessCmd = Resolve-HeadlessBrowserCommand -HeadlessConfig $headless
}

# Stage styles + brand assets for relative references in HTML output (only needed for markdownToHtml transforms).
$needsStyles = $false
foreach ($t in $transformActions) {
    if ([string]$t.transform -eq 'markdownToHtml') { $needsStyles = $true; break }
}
$staged = $null
if ($needsStyles) {
    $staged = Ensure-DocsStyles -RepoRoot $repoRoot -VenvPython $venvPython -CssFiles $cssFiles
}

$built = 0
$skipped = 0

foreach ($a in $copyActions) {
    $sourceRel = [string]$a.source
    $sourcePath = Join-Path $repoRoot $sourceRel
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        $msg = "Missing copy source: $sourceRel"
        if ($failOnMissingSource) { throw $msg }
        Write-Warning $msg
        continue
    }

    foreach ($t in (Get-ActionTargets -Action $a)) {
        $destRel = [string]$t.destination
        if ([string]::IsNullOrWhiteSpace($destRel)) {
            throw "Copy action missing target destination: source=$sourceRel"
        }
        $destPath = Join-Path $repoRoot $destRel

        $changed = $true
        if (-not $Force -and $skipUnchanged) {
            $changed = (Sync-FileIfChanged -Source $sourcePath -Destination $destPath)
        } else {
            if ($PSCmdlet.ShouldProcess($destRel, "Copy $sourceRel")) {
                Copy-Item -LiteralPath $sourcePath -Destination $destPath -Force
            }
        }

        if ($changed) {
            $built++
            Write-Host "COPY  $destRel" -ForegroundColor Green
        } else {
            $skipped++
            Write-Host "SKIP  $destRel" -ForegroundColor DarkGray
        }
    }
}

foreach ($a in $transformActions) {
    $transform = [string]$a.transform
    switch ($transform) {
        'scriptsReadme' {
            if ($SkipScriptsReadme) {
                $skipped++
                Write-Host "SKIP  scriptsReadme" -ForegroundColor DarkGray
                continue
            }

            $generator = Join-Path $PSScriptRoot 'generate-scripts-readme.ps1'
            if (-not (Test-Path -LiteralPath $generator)) {
                throw "Missing generator: $generator"
            }

            $targets = Get-ActionTargets -Action $a
            if ($targets.Count -ne 1 -or [string]$targets[0].type -ne 'md') {
                throw "scriptsReadme transform must have exactly one md target."
            }

            $outRel = [string]$targets[0].destination
            $outPath = Join-Path $repoRoot $outRel

            if ($PSCmdlet.ShouldProcess($outRel, 'Generate scripts docs markdown')) {
                & $generator -OutputPath $outPath -WhatIf:$WhatIfPreference
                $built++
                Write-Host "GEN   $outRel" -ForegroundColor Green
            }
        }
        'markdownToHtml' {
            if (-not $emitHtml) {
                $skipped++
                Write-Host "SKIP  markdownToHtml (emitHtml=false)" -ForegroundColor DarkGray
                continue
            }

            $sourceRel = [string]$a.source
            $sourcePath = Join-Path $repoRoot $sourceRel
            if (-not (Test-Path -LiteralPath $sourcePath)) {
                $msg = "Missing markdown source: $sourceRel"
                if ($failOnMissingSource) { throw $msg }
                Write-Warning $msg
                continue
            }

            foreach ($t in (Get-ActionTargets -Action $a)) {
                if ([string]$t.type -ne 'html') { continue }
                $htmlRel = [string]$t.destination
                $htmlPath = Join-Path $repoRoot $htmlRel

                $needsHtml = $true
                if (-not $Force -and $skipUnchanged -and (Test-Path -LiteralPath $htmlPath)) {
                    $srcItem = Get-Item -LiteralPath $sourcePath
                    $outItem = Get-Item -LiteralPath $htmlPath
                    if ($outItem.LastWriteTimeUtc -ge $srcItem.LastWriteTimeUtc) {
                        $needsHtml = $false
                    }
                }

                if (-not $needsHtml) {
                    $skipped++
                    Write-Host "SKIP  $htmlRel" -ForegroundColor DarkGray
                    continue
                }

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
        }
        default {
            throw "Unknown transform '$transform' in config."
        }
    }
}

foreach ($a in $printActions) {
    if (-not $emitPdf) {
        $skipped++
        Write-Host "SKIP  print (emitPdf=false)" -ForegroundColor DarkGray
        continue
    }

    $sourceRel = [string]$a.source
    $sourcePath = Join-Path $repoRoot $sourceRel
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        $msg = "Missing print source HTML: $sourceRel"
        if ($failOnMissingSource) { throw $msg }
        Write-Warning $msg
        continue
    }

    foreach ($t in (Get-ActionTargets -Action $a)) {
        if ([string]$t.type -ne 'pdf') { continue }
        $pdfRel = [string]$t.destination
        $pdfPath = Join-Path $repoRoot $pdfRel

        $needsPdf = $true
        if (-not $Force -and $skipUnchanged -and (Test-Path -LiteralPath $pdfPath)) {
            $srcItem = Get-Item -LiteralPath $sourcePath
            $outItem = Get-Item -LiteralPath $pdfPath

            # PDFs depend on the HTML plus any referenced local CSS assets.
            $latestDepUtc = $srcItem.LastWriteTimeUtc
            foreach ($css in @($staged.CssFiles)) {
                $cssPath = [string]$css
                if ([string]::IsNullOrWhiteSpace($cssPath)) { continue }
                if ($cssPath -match '^[a-zA-Z][a-zA-Z0-9+.-]*://') { continue }
                if (-not (Test-Path -LiteralPath $cssPath)) { continue }

                $cssItem = Get-Item -LiteralPath $cssPath
                if ($cssItem.LastWriteTimeUtc -gt $latestDepUtc) {
                    $latestDepUtc = $cssItem.LastWriteTimeUtc
                }
            }

            if ($outItem.LastWriteTimeUtc -ge $latestDepUtc) {
                $needsPdf = $false
            }
        }

        if (-not $needsPdf) {
            $skipped++
            Write-Host "SKIP  $pdfRel" -ForegroundColor DarkGray
            continue
        }

        if ($PSCmdlet.ShouldProcess($pdfRel, "Print PDF from $sourceRel")) {
            $pdfDir = Split-Path -Parent $pdfPath
            if ($pdfDir -and -not (Test-Path -LiteralPath $pdfDir)) {
                New-Item -ItemType Directory -Path $pdfDir -Force | Out-Null
            }

            & $venvPython $printPdfPy `
                --browser $resolvedHeadlessCmd `
                --html $sourcePath `
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
