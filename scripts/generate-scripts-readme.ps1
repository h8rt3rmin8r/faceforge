<#
.SYNOPSIS
    Generates docs/FaceForge - Dev Guide - Scripts.md from PowerShell comment-based help.

.DESCRIPTION
    Scans the repository's `scripts/` directory for `.ps1` files and generates a Markdown
    README at `docs/FaceForge - Dev Guide - Scripts.md`.

    The generated README is composed as follows:
      - A single top-level Markdown header (`# Scripts`).
      - The remainder of the file is the raw output of `Get-Help -Full` for each script in
        the `scripts/` directory.

    This ensures the canonical documentation for scripts stays in the scripts themselves,
    while the dev guide remains an always-up-to-date aggregated view.

.PARAMETER OutputPath
    The path to the generated README file.
    Default: `<repoRoot>/docs/FaceForge - Dev Guide - Scripts.md`.

.PARAMETER IncludeThisScript
    Include this generator script's own `Get-Help -Full` output in the generated README.
    Default: false.

.PARAMETER Width
    The width passed to `Out-String` to reduce wrapping in the captured help output.
    Default: 160.

.EXAMPLE
    ./scripts/generate-scripts-readme.ps1
    Generates `docs/FaceForge - Dev Guide - Scripts.md` from `Get-Help -Full` outputs.

.EXAMPLE
    ./scripts/generate-scripts-readme.ps1 -WhatIf
    Shows what would be written without modifying the output doc.

.EXAMPLE
    ./scripts/generate-scripts-readme.ps1 -OutputPath .\scripts\README.md -IncludeThisScript
    Writes the README and includes this generator script.

.NOTES
    - This script relies on comment-based help being present in each script.
    - If `Get-Help -Full` fails for any script, the error output from `Get-Help` is captured
      instead, so the README still reflects the current state.
    - The generated README is overwritten on each run.
#>

[CmdletBinding(SupportsShouldProcess = $true, PositionalBinding = $false, ConfirmImpact = 'Low')]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$OutputPath,

    [Parameter()]
    [switch]$IncludeThisScript,

    # When generating the canonical docs/FaceForge - Dev Guide - Scripts.md, this script can
    # optionally trigger HTML/PDF regeneration via ./scripts/update-docs.ps1.
    # This switch disables that follow-on step (used by update-docs.ps1 to avoid recursion).
    [Parameter()]
    [switch]$SkipDocRenders,

    [Parameter()]
    [ValidateRange(80, 400)]
    [int]$Width = 160
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ConfirmPreference = 'None'

function Get-RepoRoot {
    return (Split-Path -Parent $PSScriptRoot)
}

function Convert-CapitalHelpHeadingsToMarkdownBullets {
    param(
        [Parameter(Mandatory)]
        [string]$Text
    )

    # Convert help headings like:
    #   NAME
    #   SYNOPSIS
    #   SYNTAX
    # into list items with a single nested *indented* code block containing the section body:
    #   - NAME
    #
    #         <body lines>
    #
    # Why indented code blocks?
    # - Python-Markdown's fenced-code handling inside lists is finicky and can render literal
    #   backticks into HTML/PDF if indentation/blank-lines aren't perfect.
    # - Indented code blocks are more robust and preserve the Get-Help text layout.
    $pattern = '^(?<h>[A-Z][A-Z ]*[A-Z])\s*$'
    $headingRx = [regex]::new($pattern)

    $lines = $Text -split "`n"
    $outLines = New-Object System.Collections.Generic.List[string]

    # For a code block nested under a list item, we indent by 8 spaces from the left margin.
    # (This is reliably treated as code across Markdown renderers when nested in lists.)
    $codeIndent = '        '

    $inSection = $false

    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = $lines[$i]

        # Do not nest content under Markdown headings like "# Scripts" / "## foo.ps1".
        if ($line -match '^#{1,6}\s+\S') {
            $inSection = $false
            $outLines.Add($line)
            continue
        }

        if ($headingRx.IsMatch($line)) {
            $h = ($headingRx.Match($line)).Groups['h'].Value
            $outLines.Add("- $h")
            $outLines.Add('')
            $inSection = $true
            continue
        }

        if ($inSection) {
            # Keep blank lines inside the indented code block; a truly empty line would terminate the block.
            if ($line -match '^\s*$') {
                $outLines.Add($codeIndent)
            }
            else {
                # Get-Help typically indents section bodies by 4 spaces; strip that baseline so
                # the nested code block doesn't drift too far right.
                $normalized = $line -replace '^(?: {1,4})', ''
                $outLines.Add($codeIndent + $normalized)
            }
            continue
        }

        $outLines.Add($line)
    }

    return ($outLines -join "`n")
}

function Wrap-SyntaxSectionsInCodeBlocks {
    param(
        [Parameter(Mandatory)]
        [string]$Text
    )

    $lines = $Text -split "`n"
    $outLines = New-Object System.Collections.Generic.List[string]

    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = $lines[$i]

        # Support both legacy "### SYNTAX" and the current "- SYNTAX" list-item style.
        if ($line -match '^###\s+SYNTAX\s*$' -or $line -match '^\s*-\s+SYNTAX\s*$') {
            $outLines.Add($line)

            $isBullet = ($line -match '^\s*-\s+')
            $indent = if ($isBullet) { '  ' } else { '' }

            # If already wrapped, leave as-is.
            $lookAhead = $i + 1
            while ($lookAhead -lt $lines.Length -and $lines[$lookAhead] -match '^\s*$') { $lookAhead++ }
            if ($lookAhead -lt $lines.Length -and $lines[$lookAhead] -match '^\s*```') {
                continue
            }

            $outLines.Add($indent + '```text')

            # Skip initial blank lines right after the heading.
            $i++
            while ($i -lt $lines.Length -and $lines[$i] -match '^\s*$') { $i++ }

            while ($i -lt $lines.Length) {
                $nextLine = $lines[$i]
                if (
                    $nextLine -match '^\s*-\s+\S' -or
                    $nextLine -match '^###\s+\S' -or
                    $nextLine -match '^##\s+\S' -or
                    $nextLine -match '^#\s+\S'
                ) {
                    break
                }

                $outLines.Add($nextLine)
                $i++
            }

            $outLines.Add($indent + '```')
            $outLines.Add('')

            # The loop will increment $i again; step back so we re-process the delimiter line.
            $i--
            continue
        }

        $outLines.Add($line)
    }

    return ($outLines -join "`n")
}

function Format-PowerShellExamplePromptLines {
    param(
        [Parameter(Mandatory)]
        [string]$Text
    )

    $lines = $Text -split "`n"
    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = $lines[$i]
        if ($line -match '^\s*PS C:\\>' -and $line -notmatch '^\s*`PS C:\\>') {
            $lines[$i] = $line -replace '^(?<indent>\s*)(?<cmd>PS C:\\>.*)$', '${indent}`${cmd}`'
        }
    }

    return ($lines -join "`n")
}

function Squash-ExcessBlankLines {
    param(
        [Parameter(Mandatory)]
        [string]$Text
    )

    # Replace 3+ consecutive newlines with exactly 2.
    # Note: PowerShell string escaping uses backticks, so "\n" is passed through to .NET regex as a newline token.
    return [regex]::Replace($Text, "\n{3,}", "`n`n")
}

function Insert-HrBeforeLevelTwoHeadings {
    param(
        [Parameter(Mandatory)]
        [string]$Text
    )

    $lines = $Text -split "`n"
    $outLines = New-Object System.Collections.Generic.List[string]

    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = $lines[$i]

        if ($line -match '^##\s+\S') {
            # Trim trailing blank lines so we can enforce exactly one blank line before the HR.
            while ($outLines.Count -gt 0 -and [string]::IsNullOrWhiteSpace($outLines[$outLines.Count - 1])) {
                $outLines.RemoveAt($outLines.Count - 1)
            }

            # Insert separator block:
            # <blank>
            # ---
            # <blank>
            $outLines.Add('')
            $outLines.Add('---')
            $outLines.Add('')
            $outLines.Add($line)
            continue
        }

        $outLines.Add($line)
    }

    return ($outLines -join "`n")
}

function Format-GeneratedReadme {
    param(
        [Parameter(Mandatory)]
        [string]$Text
    )

    # Normalize to LF while transforming; we'll write back with whatever newlines are in the string.
    $t = $Text -replace "`r`n", "`n"
    $t = $t -replace "`r", "`n"
    $t = Convert-CapitalHelpHeadingsToMarkdownBullets -Text $t
    $t = ($t -replace '(?m)[ \t]+$', '')
    $t = Insert-HrBeforeLevelTwoHeadings -Text $t

    return $t
}

function Rewrite-AbsoluteRepoPathsToRelative {
    param(
        [Parameter(Mandatory)]
        [string]$Text,

        [Parameter(Mandatory)]
        [string]$RepoRoot
    )

    $root = (Resolve-Path -LiteralPath $RepoRoot).Path
    $escaped = [regex]::Escape($root)

    # Replace any absolute references to the repo root (e.g. A:\Code\faceforge\...) with a relative prefix.
    # This keeps generated docs stable across machines and prevents hard-coded personal paths in HTML/PDF renders.
    return [regex]::Replace($Text, "${escaped}\\", './')
}

function Test-CalledFromUpdateDocs {
    try {
        foreach ($f in (Get-PSCallStack)) {
            if ($null -ne $f.ScriptName -and (Split-Path -Leaf $f.ScriptName) -ieq 'update-docs.ps1') {
                return $true
            }
        }
    } catch {
        # If call stack is unavailable for any reason, assume not called from update-docs.
    }
    return $false
}

function Test-DerivedAssetsFresh {
    param(
        [Parameter(Mandatory)][string]$MarkdownPath,
        [Parameter(Mandatory)][string]$HtmlPath,
        [Parameter(Mandatory)][string]$PdfPath,
        [int]$WindowSeconds = 10
    )

    if (-not (Test-Path -LiteralPath $MarkdownPath)) { return $false }
    if (-not (Test-Path -LiteralPath $HtmlPath)) { return $false }
    if (-not (Test-Path -LiteralPath $PdfPath)) { return $false }

    $md = Get-Item -LiteralPath $MarkdownPath
    $html = Get-Item -LiteralPath $HtmlPath
    $pdf = Get-Item -LiteralPath $PdfPath

    # Use LastWriteTimeUtc as the stable signal for regeneration.
    $mdTime = $md.LastWriteTimeUtc
    $htmlDelta = ($html.LastWriteTimeUtc - $mdTime).TotalSeconds
    $pdfDelta = ($pdf.LastWriteTimeUtc - $mdTime).TotalSeconds

    return (
        $htmlDelta -ge 0 -and $htmlDelta -le $WindowSeconds -and
        $pdfDelta -ge 0 -and $pdfDelta -le $WindowSeconds
    )
}

$repoRoot = Get-RepoRoot
$scriptDir = Join-Path $repoRoot 'scripts'

if (-not $OutputPath) {
    $OutputPath = Join-Path $repoRoot 'docs/FaceForge - Dev Guide - Scripts.md'
}

if (-not (Test-Path $scriptDir)) {
    throw "Scripts directory not found: $scriptDir"
}

$generatorName = (Split-Path -Leaf $PSCommandPath)

$scriptFiles = Get-ChildItem -Path $scriptDir -Filter '*.ps1' -File |
    Where-Object {
        if ($IncludeThisScript) { return $true }
        return $_.Name -ne $generatorName
    } |
    Sort-Object -Property Name

$helpBlocks = foreach ($file in $scriptFiles) {
    $header = "## $($file.Name)`n`n"

    # Capture help output as plain text.
    # If help parsing fails, capture the error output from Get-Help so the README still shows why.
    $helpText = $null
    try {
        $helpText = Get-Help -Full $file.FullName -ErrorAction Stop | Out-String -Width $Width
    }
    catch {
        $helpText = (& {
            Get-Help -Full $file.FullName 2>&1 | Out-String -Width $Width
        })
    }

    $header + $helpText + "`n"
}

# Requirement: only the top-level header is authored; the remainder is raw `Get-Help -Full` outputs.
# Keep separators minimal (a blank line after the header).
$readmeContent = "# Scripts`n`n" + ($helpBlocks -join "")

if ($PSCmdlet.ShouldProcess($OutputPath, 'Write generated scripts README')) {
    $parent = Split-Path -Parent $OutputPath
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }

    # Use UTF-8 (no BOM in PowerShell 7+, BOM in Windows PowerShell). This is fine for Markdown.
    # 1) Write the raw aggregated help.
    Set-Content -Path $OutputPath -Value $readmeContent -Encoding utf8

    # 2) Post-process the generated doc to improve Markdown formatting.
    $generated = Get-Content -Path $OutputPath -Raw
    $formatted = Format-GeneratedReadme -Text $generated
    $formatted = Rewrite-AbsoluteRepoPathsToRelative -Text $formatted -RepoRoot $repoRoot
    Set-Content -Path $OutputPath -Value $formatted -Encoding utf8

    Write-Host "Generated: $OutputPath" -ForegroundColor Green

    # If we generated the canonical scripts dev guide doc, keep HTML/PDF in sync by running
    # the repo's docs pipeline (which already knows how to render and print).
    if (-not $SkipDocRenders -and -not $WhatIfPreference) {
        $canonicalMd = Join-Path $repoRoot 'docs/FaceForge - Dev Guide - Scripts.md'
        $resolvedOut = (Resolve-Path -LiteralPath $OutputPath).Path
        $resolvedCanonical = (Resolve-Path -LiteralPath $canonicalMd).Path

        if ($resolvedOut -eq $resolvedCanonical) {
            # If we were invoked from update-docs.ps1, do not re-enter the docs pipeline.
            if (Test-CalledFromUpdateDocs) {
                return
            }

            $canonicalHtml = Join-Path $repoRoot 'docs/FaceForge - Dev Guide - Scripts.html'
            $canonicalPdf = Join-Path $repoRoot 'docs/FaceForge - Dev Guide - Scripts.pdf'
            if (Test-DerivedAssetsFresh -MarkdownPath $canonicalMd -HtmlPath $canonicalHtml -PdfPath $canonicalPdf -WindowSeconds 10) {
                return
            }

            $updateDocs = Join-Path $repoRoot 'scripts/update-docs.ps1'
            if (Test-Path -LiteralPath $updateDocs) {
                Write-Host 'Updating HTML/PDF via scripts/update-docs.ps1...' -ForegroundColor DarkGray
                & $updateDocs -SkipScriptsReadme
            }
        }
    }
}
