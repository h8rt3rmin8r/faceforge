<#
.SYNOPSIS
  Ensures a valid SeaweedFS `weed.exe` (Windows x64) is present for Desktop packaging.

.DESCRIPTION
  The repo intentionally does NOT check in the real SeaweedFS binary. The file under
  `desktop/src-tauri/resources/tools/weed.exe` may be a placeholder.

  This script downloads the official SeaweedFS Windows amd64 release archive and stages
  `weed.exe` into `desktop/src-tauri/resources/tools/weed.exe` so `cargo tauri build`
  bundles the correct executable into the MSI.

.PARAMETER Version
  SeaweedFS release tag (e.g. 4.06). Default: latest.

.PARAMETER Force
  Re-download and overwrite even if a valid `weed.exe` already exists.

.PARAMETER LargeDisk
  Use the `windows_amd64_large_disk.zip` asset instead of `windows_amd64.zip`.
#>

[CmdletBinding(PositionalBinding = $false)]
param(
  [string]$Version = 'latest',
  [switch]$Force,
  [switch]$LargeDisk
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ConfirmPreference = 'None'

. (Join-Path $PSScriptRoot '_ensure-venv.ps1')

function Get-PeMachine {
  param([Parameter(Mandatory=$true)][string]$Path)

  $fs = [System.IO.File]::OpenRead($Path)
  $br = New-Object System.IO.BinaryReader($fs)
  try {
    # DOS header offset to PE header pointer
    $fs.Seek(0x3C, [System.IO.SeekOrigin]::Begin) | Out-Null
    $peOffset = $br.ReadInt32()
    $fs.Seek($peOffset, [System.IO.SeekOrigin]::Begin) | Out-Null
    $sig = $br.ReadUInt32()
    if ($sig -ne 0x00004550) { return $null } # "PE\0\0"
    return $br.ReadUInt16()
  } catch {
    return $null
  } finally {
    $br.Close(); $fs.Close()
  }
}

function Test-IsWindowsExe {
  param([Parameter(Mandatory=$true)][string]$Path)
  if (-not (Test-Path $Path)) { return $false }
  $fs = $null
  try {
    $fs = [System.IO.File]::OpenRead($Path)
    $buf = New-Object byte[] 2
    $n = $fs.Read($buf, 0, 2)
    return ($n -eq 2 -and $buf[0] -eq 0x4D -and $buf[1] -eq 0x5A) # MZ
  } catch {
    return $false
  } finally {
    if ($fs) { $fs.Close() }
  }
}

function Test-IsValidWeedExe {
  param([Parameter(Mandatory=$true)][string]$Path)

  if (-not (Test-Path $Path)) { return $false }
  $len = (Get-Item $Path).Length
  if ($len -lt 1024*1024) { return $false } # placeholders are tiny
  if (-not (Test-IsWindowsExe $Path)) { return $false }

  $machine = Get-PeMachine -Path $Path
  if ($null -eq $machine) { return $false }

  # x64 (AMD64) = 0x8664
  return ($machine -eq 0x8664)
}

function Resolve-SeaweedTag {
  param([Parameter(Mandatory=$true)][string]$Requested)

  if ($Requested -and $Requested -ne 'latest') {
    return $Requested.TrimStart('v')
  }

  $headers = @{ 'User-Agent' = 'faceforge-build-script' }
  $r = Invoke-RestMethod -Uri 'https://api.github.com/repos/seaweedfs/seaweedfs/releases/latest' -Headers $headers
  return [string]$r.tag_name
}

$repoRoot = Get-RepoRoot
$toolsDir = Join-Path $repoRoot 'desktop/src-tauri/resources/tools'
$dstWeed  = Join-Path $toolsDir 'weed.exe'
$dstVer   = Join-Path $toolsDir 'seaweedfs.version.txt'

New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null

if (-not $Force -and (Test-IsValidWeedExe -Path $dstWeed)) {
  Write-Host "SeaweedFS weed.exe already present and x64: $dstWeed" -ForegroundColor Green
  exit 0
}

$tag = Resolve-SeaweedTag -Requested $Version
$assetName = if ($LargeDisk) { 'windows_amd64_large_disk.zip' } else { 'windows_amd64.zip' }
$url = "https://github.com/seaweedfs/seaweedfs/releases/download/$tag/$assetName"

Write-Host "Ensuring SeaweedFS weed.exe (tag=$tag, asset=$assetName)..." -ForegroundColor Cyan

$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("faceforge-seaweedfs-$tag-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $tmpRoot | Out-Null

try {
  $zipPath = Join-Path $tmpRoot $assetName
  $headers = @{ 'User-Agent' = 'faceforge-build-script' }
  Invoke-WebRequest -Uri $url -Headers $headers -OutFile $zipPath

  Expand-Archive -Path $zipPath -DestinationPath $tmpRoot -Force

  $found = Get-ChildItem -Path $tmpRoot -Recurse -Filter 'weed.exe' | Select-Object -First 1
  if (-not $found) {
    throw "Downloaded archive did not contain weed.exe (url=$url)"
  }

  Copy-Item -Force -Path $found.FullName -Destination $dstWeed

  if (-not (Test-IsValidWeedExe -Path $dstWeed)) {
    $len = (Get-Item $dstWeed).Length
    $isMZ = Test-IsWindowsExe -Path $dstWeed
    $machine = Get-PeMachine -Path $dstWeed
    throw "Staged weed.exe failed validation (len=$len, MZ=$isMZ, machine=$machine)."
  }

  Set-Content -Path $dstVer -Value $tag -Encoding ascii

  Write-Host "SeaweedFS weed.exe installed: $dstWeed" -ForegroundColor Green
  Write-Host "SeaweedFS version recorded: $dstVer" -ForegroundColor DarkGray
} finally {
  Remove-Item -Recurse -Force -Path $tmpRoot -ErrorAction SilentlyContinue
}
