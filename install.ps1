# ChainOps installer for Windows
# Usage: irm https://github.com/presack/ChainOps/releases/latest/download/install.ps1 | iex
#
# Linux/WSL2 support is not wired up yet (ChainOps doesn't have a Linux
# build/asset yet -- see ROADMAP Phase 3.5), so this only installs the
# Windows binary. StealthOps' installer additionally symlinks a Linux
# binary into WSL2; that logic will get ported here once build-linux.sh
# and a Linux release asset exist.

[CmdletBinding()]
param(
    [string]$Version = "",   # pin to a specific tag e.g. "v1.0.4"; default = latest
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\ChainOps")
)

$ErrorActionPreference = "Stop"
$Repo = "presack/ChainOps"

function Write-Step { param([string]$Msg) Write-Host "  $Msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Msg) Write-Host "  + $Msg" -ForegroundColor Green }
function Write-Warn { param([string]$Msg) Write-Host "  ! $Msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  ChainOps Installer" -ForegroundColor White
Write-Host ("  " + "-" * 38)
Write-Host ""

# Fetch release metadata
$ApiBase = "https://api.github.com/repos/$Repo/releases"
$ApiUrl  = if ($Version) { "$ApiBase/tags/$Version" } else { "$ApiBase/latest" }

Write-Step "Fetching release info..."
try {
    $Release = Invoke-RestMethod -Uri $ApiUrl -Headers @{ "User-Agent" = "ChainOps-Installer" }
} catch {
    Write-Host "  ERROR: Could not reach GitHub API. Check network and try again." -ForegroundColor Red
    exit 1
}

$Tag    = $Release.tag_name
$Assets = @{}
foreach ($a in $Release.assets) { $Assets[$a.name] = $a }
Write-Ok "Release: $Tag"

# Resolve asset URLs
$WinAsset      = "chainops-windows-x64.exe"
$ChecksumAsset = "checksums.txt"

if (-not $Assets.ContainsKey($WinAsset)) {
    Write-Host "  ERROR: Windows binary '$WinAsset' not found in release $Tag." -ForegroundColor Red
    exit 1
}

$WinUrl      = $Assets[$WinAsset].browser_download_url
$ChecksumUrl = if ($Assets.ContainsKey($ChecksumAsset)) { $Assets[$ChecksumAsset].browser_download_url } else { $null }

# Download and parse checksums
$Checksums = @{}
if ($ChecksumUrl) {
    Write-Step "Fetching checksums..."
    try {
        $Raw = (Invoke-WebRequest -Uri $ChecksumUrl -Headers @{ "User-Agent" = "ChainOps-Installer" }).Content
        foreach ($Line in ($Raw -split "`n")) {
            $Line = $Line.Trim()
            if ($Line) {
                $Parts = $Line -split '\s+', 2
                if ($Parts.Count -eq 2) { $Checksums[$Parts[1]] = $Parts[0] }
            }
        }
    } catch {
        Write-Warn "Could not fetch checksums -- SHA256 verification will be skipped."
    }
}

# Helper: download, verify, place
function Install-Asset {
    param([string]$Url, [string]$AssetName, [string]$DestPath)
    $Tmp = "$DestPath.tmp"
    Write-Step "Downloading $AssetName..."
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Tmp -Headers @{ "User-Agent" = "ChainOps-Installer" }
    } catch {
        Write-Host "  ERROR: Download failed for ${AssetName}: $_" -ForegroundColor Red
        if (Test-Path $Tmp) { Remove-Item $Tmp -Force }
        exit 1
    }
    $Expected = $Checksums[$AssetName]
    if ($Expected) {
        $Actual = (Get-FileHash $Tmp -Algorithm SHA256).Hash.ToLower()
        if ($Actual -ne $Expected) {
            Remove-Item $Tmp -Force
            Write-Host "  ERROR: SHA256 mismatch for $AssetName" -ForegroundColor Red
            Write-Host "    expected: $Expected"
            Write-Host "    got:      $Actual"
            exit 1
        }
        Write-Ok "SHA256 verified"
    } else {
        Write-Warn "No checksum for $AssetName -- skipping verification"
    }
    Move-Item -Path $Tmp -Destination $DestPath -Force
}

# Create install directory
Write-Step "Installing to $InstallDir ..."
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# Install Windows binary
$WinDest = Join-Path $InstallDir "chainops.exe"
Install-Asset -Url $WinUrl -AssetName $WinAsset -DestPath $WinDest
Write-Ok "chainops.exe installed"

# Add InstallDir to the user PATH registry key (no admin required)
Write-Step "Updating PATH..."
$RegPath     = "HKCU:\Environment"
$CurrentPath = (Get-ItemProperty -Path $RegPath -Name Path -ErrorAction SilentlyContinue).Path
if (-not $CurrentPath) { $CurrentPath = "" }

$AlreadyInRegistry = ($CurrentPath -split ";" | Where-Object { $_ -ieq $InstallDir }).Count -gt 0
if (-not $AlreadyInRegistry) {
    $NewPath = ($CurrentPath.TrimEnd(";") + ";" + $InstallDir).TrimStart(";")
    Set-ItemProperty -Path $RegPath -Name Path -Value $NewPath
    Write-Ok "Added to user PATH (registry)"
} else {
    Write-Ok "Already in user PATH"
}

# Also update the current session so chainops works immediately without reopening the terminal
$AlreadyInSession = ($env:PATH -split ";" | Where-Object { $_ -ieq $InstallDir }).Count -gt 0
if (-not $AlreadyInSession) {
    $env:PATH = $env:PATH.TrimEnd(";") + ";" + $InstallDir
    Write-Ok "Added to current session PATH"
}

# Broadcast WM_SETTINGCHANGE so other open terminals pick up the registry change
try {
    $sig  = '[DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);'
    $Type = Add-Type -MemberDefinition $sig -Name WinApi -Namespace Win32 -PassThru -ErrorAction SilentlyContinue
    $result = [UIntPtr]::Zero
    $Type::SendMessageTimeout([IntPtr]0xffff, 0x1a, [UIntPtr]::Zero, "Environment", 2, 5000, [ref]$result) | Out-Null
} catch { }

# Done
Write-Host ""
Write-Host "  ChainOps $Tag installed." -ForegroundColor Green
Write-Host ""
Write-Host "  chainops is ready in this terminal. Try:" -ForegroundColor White
Write-Host "    chainops --console" -ForegroundColor Cyan
Write-Host "    chainops 1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a" -ForegroundColor Cyan
Write-Host ""
