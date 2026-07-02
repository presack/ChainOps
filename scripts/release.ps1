# release.ps1 -- build the Windows binary, tag, and publish a GitHub release
# Usage:  .\scripts\release.ps1 v1.0.0 ["Release notes here"]
#
# Windows-only for now -- Linux/WSL2 build (build-linux.sh) is a follow-up
# chunk; once it exists, this script gains the same Linux build/upload/
# checksum steps StealthOps' release.ps1 has.
#
# Requires: gh CLI authenticated

param(
    [Parameter(Mandatory)][string]$Version,
    [string]$Notes = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

# Validate version format
if ($Version -notmatch '^v\d+\.\d+\.\d+$') {
    Write-Error "Version must be in the form v1.2.3"
    exit 1
}

# Ensure no uncommitted changes (untracked files are fine)
$status = git status --porcelain | Where-Object { $_ -notmatch '^\?\?' }
if ($status) {
    Write-Error "Working tree has uncommitted changes. Commit or stash first.`n$status"
    exit 1
}

# Ensure tag doesn't already exist
if (git tag -l $Version) {
    Write-Error "Tag $Version already exists."
    exit 1
}

$WinBin       = Join-Path $ProjectRoot "dist\windows\chainops.exe"
$WinUpload    = Join-Path $ProjectRoot "dist\chainops-windows-x64.exe"
$ChecksumFile = Join-Path $ProjectRoot "dist\checksums.txt"

# Locate gh CLI (check PATH, then common install locations)
$GhExe = (Get-Command gh -ErrorAction SilentlyContinue)?.Source
if (-not $GhExe) {
    foreach ($candidate in @(
        "C:\Program Files\GitHub CLI\gh.exe",
        "$env:LOCALAPPDATA\Programs\GitHub CLI\gh.exe",
        "$env:ProgramFiles\GitHub CLI\gh.exe"
    )) {
        if (Test-Path $candidate) { $GhExe = $candidate; break }
    }
}
if (-not $GhExe) {
    Write-Error ("gh CLI not found. Install from https://cli.github.com/ then run:`n" +
        "  gh release create $Version --title 'ChainOps $Version' ``
        --notes 'ChainOps $Version' ``
        '${WinBin}#chainops-windows-x64.exe'")
    exit 1
}

# -- Stamp version -----------------------------------------------------------
$VersionNum = $Version.TrimStart("v")
Set-Content (Join-Path $ProjectRoot "_version.py") "__version__ = `"$VersionNum`"`n"
git add "_version.py"
git commit -m "Bump version to $Version"
git push

# -- Build Windows ------------------------------------------------------------
Write-Host ""
Write-Host "=== Building Windows EXE ===" -ForegroundColor Cyan
& "$ScriptDir\build.ps1"
if (-not (Test-Path $WinBin)) { Write-Error "Windows build failed -- $WinBin not found"; exit 1 }

# -- Checksums ------------------------------------------------------------------
Write-Host ""
Write-Host "=== Generating checksums ===" -ForegroundColor Cyan
Copy-Item $WinBin $WinUpload -Force
$WinHash = (Get-FileHash $WinUpload -Algorithm SHA256).Hash.ToLower()
"$WinHash  chainops-windows-x64.exe" | Set-Content $ChecksumFile
Write-Host "  $WinHash  chainops-windows-x64.exe"

# -- Tag and release ------------------------------------------------------------
Write-Host ""
Write-Host "=== Creating release $Version ===" -ForegroundColor Cyan

git tag $Version
git push origin $Version

$InstallLine = "irm https://github.com/presack/ChainOps/releases/latest/download/install.ps1 | iex"
$ReleaseNotes = if ($Notes) { $Notes } else {
@"
ChainOps $Version

Blockchain address/tx recon utility.

**Install (Windows -- no admin required)**

Open PowerShell and run:

``````powershell
$InstallLine
``````

**Downloads**
- ``chainops-windows-x64.exe`` -- Windows x64
"@
}

$InstallPs1 = Join-Path $ProjectRoot "install.ps1"

& $GhExe release create $Version `
    --title "ChainOps $Version" `
    --notes $ReleaseNotes `
    $WinUpload `
    "$ChecksumFile#checksums.txt" `
    "$InstallPs1#install.ps1"

Write-Host ""
Write-Host "Release $Version published." -ForegroundColor Green
& $GhExe release view $Version --web
