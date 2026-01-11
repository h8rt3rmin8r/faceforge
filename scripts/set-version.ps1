param(
    [Parameter(Mandatory=$true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot/.."

function Update-FileContent {
    param($Path, $Regex, $Replacement)
    $FullPath = Join-Path $Root $Path
    if (-not (Test-Path $FullPath)) {
        Write-Warning "File not found: $Path"
        return
    }
    
    $Content = Get-Content $FullPath -Raw
    # Verify match first
    if ($Content -match $Regex) {
        $NewContent = $Content -replace $Regex, $Replacement
        Set-Content $FullPath -NoNewline -Value $NewContent
        Write-Host "Updated $Path to $Version"
    } else {
        Write-Warning "Pattern '$Regex' not found in $Path"
    }
}

Write-Host "Bumping version to $Version..."

# core/pyproject.toml
# version = "0.1.0"
Update-FileContent "core/pyproject.toml" '(?m)^version = "\d+\.\d+\.\d+"' "version = `"$Version`""

# desktop/package.json
# "version": "0.1.0"
Update-FileContent "desktop/package.json" '(?m)"version": "\d+\.\d+\.\d+"' "`"version`": `"$Version`""

# desktop/src-tauri/Cargo.toml
# version = "0.1.0"
Update-FileContent "desktop/src-tauri/Cargo.toml" '(?m)^version = "\d+\.\d+\.\d+"' "version = `"$Version`""

# desktop/src-tauri/tauri.conf.json
# "version": "0.1.0"
Update-FileContent "desktop/src-tauri/tauri.conf.json" '(?m)"version": "\d+\.\d+\.\d+"' "`"version`": `"$Version`""

# core/src/faceforge_core/app.py
# version="0.0.0"
Update-FileContent "core/src/faceforge_core/app.py" 'version="\d+\.\d+\.\d+"' "version=`"$Version`""

Write-Host "Version bump complete."
