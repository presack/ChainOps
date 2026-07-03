# ChainOps installer for Windows (+ WSL2)
# Usage: irm https://github.com/presack/ChainOps/releases/latest/download/install.ps1 | iex

[CmdletBinding()]
param(
    [string]$Version = "",   # pin to a specific tag e.g. "v1.0.4"; default = latest
    [switch]$NoWsl,          # skip WSL2 Linux binary setup
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
$LinuxAsset    = "chainops-linux-x64"
$ChecksumAsset = "checksums.txt"

if (-not $Assets.ContainsKey($WinAsset)) {
    Write-Host "  ERROR: Windows binary '$WinAsset' not found in release $Tag." -ForegroundColor Red
    exit 1
}

$WinUrl      = $Assets[$WinAsset].browser_download_url
$LinuxUrl    = if ($Assets.ContainsKey($LinuxAsset))    { $Assets[$LinuxAsset].browser_download_url }    else { $null }
$ChecksumUrl = if ($Assets.ContainsKey($ChecksumAsset)) { $Assets[$ChecksumAsset].browser_download_url } else { $null }

# Download and parse checksums
$Checksums = @{}
if ($ChecksumUrl) {
    Write-Step "Fetching checksums..."
    try {
        $RawResponse = Invoke-WebRequest -Uri $ChecksumUrl -Headers @{ "User-Agent" = "ChainOps-Installer" }
        # GitHub serves checksums.txt as application/octet-stream, so
        # Invoke-WebRequest returns .Content as a byte[] rather than a
        # string -- decode explicitly or every "line" ends up being a
        # single byte and no checksum ever matches.
        if ($RawResponse.Content -is [byte[]]) {
            $Raw = [System.Text.Encoding]::UTF8.GetString($RawResponse.Content)
        } else {
            $Raw = $RawResponse.Content
        }
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

# Install Linux binary (used by WSL2)
$LinuxDest = $null
if ($LinuxUrl) {
    $LinuxDest = Join-Path $InstallDir "chainops"
    Install-Asset -Url $LinuxUrl -AssetName $LinuxAsset -DestPath $LinuxDest
    Write-Ok "chainops (Linux) installed"
} else {
    Write-Warn "Linux binary not found in release $Tag -- skipping"
}

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

# WSL2: chmod, symlink into ~/.local/bin, ensure ~/.local/bin is in PATH
$WslConfigured = $false
if (-not $NoWsl -and $LinuxDest -and (Get-Command wsl -ErrorAction SilentlyContinue)) {
    Write-Step "Configuring WSL2..."
    try {
        # Convert Windows paths to their WSL2 mount equivalents
        $WslSrc     = (wsl wslpath -u ($LinuxDest -replace '\\', '/')).Trim()
        $WinKeysDir = Join-Path $env:LOCALAPPDATA "ChainOps"
        $WslKeysDir = (wsl wslpath -u ($WinKeysDir -replace '\\', '/')).Trim()

        # Write the setup script to a temp file and run it by path rather
        # than passing it inline as a `wsl ... bash -c <string>` argument:
        # wsl.exe rebuilds the command line when relaying to the Linux side,
        # and in practice that both drops `wsl env VAR=val` passthrough and
        # mangles quoting in multi-line -c scripts (verified live -- $VAR
        # comes back empty inside bash even though the same script runs
        # correctly from a file).
        $VarLines = "CHAINOPS_SRC='$WslSrc'`nCHAINOPS_KEYS_DIR='$WslKeysDir'`n"
        $BashBody = @'
set -e
chmod +x "$CHAINOPS_SRC"
mkdir -p ~/.local/bin
ln -sf "$CHAINOPS_SRC" ~/.local/bin/chainops

# Add ~/.local/bin to PATH
grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' ~/.bashrc 2>/dev/null \
  || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
if [ -f ~/.zshrc ]; then
  grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' ~/.zshrc \
    || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
fi

# Point the Linux binary at the Windows keys store so both binaries share
# the same keys.env file and API keys only need to be entered once.
mkdir -p "$CHAINOPS_KEYS_DIR"
KEYS_LINE="export CHAINOPS_KEYS_DIR=\"$CHAINOPS_KEYS_DIR\""
grep -qF "CHAINOPS_KEYS_DIR" ~/.bashrc 2>/dev/null \
  || echo "$KEYS_LINE" >> ~/.bashrc
if [ -f ~/.zshrc ]; then
  grep -qF "CHAINOPS_KEYS_DIR" ~/.zshrc \
    || echo "$KEYS_LINE" >> ~/.zshrc
fi
'@
        $TempScript = Join-Path $env:TEMP "chainops-wsl-setup.sh"
        Set-Content -Path $TempScript -Value ($VarLines + $BashBody) -NoNewline -Encoding utf8
        $WslScriptPath = (wsl wslpath -u ($TempScript -replace '\\', '/')).Trim()
        wsl bash $WslScriptPath
        Remove-Item $TempScript -Force -ErrorAction SilentlyContinue

        Write-Ok "Symlinked in WSL2 ~/.local/bin/chainops"
        Write-Ok "WSL2 will share API keys with Windows ($WslKeysDir)"
        $WslConfigured = $true
    } catch {
        Write-Warn "WSL2 setup skipped: $_"
    }
} elseif (-not $NoWsl -and -not (Get-Command wsl -ErrorAction SilentlyContinue)) {
    Write-Warn "WSL2 not detected -- Linux binary is installed but not linked."
    Write-Warn "If you add WSL2 later, re-run this installer to set it up."
}

# Done
Write-Host ""
Write-Host "  ChainOps $Tag installed." -ForegroundColor Green
Write-Host ""
Write-Host "  chainops is ready in this terminal. Try:" -ForegroundColor White
Write-Host "    chainops --console" -ForegroundColor Cyan
Write-Host "    chainops 1933phfhK3ZgFQNLGSDXvqCn32k2buXY8a" -ForegroundColor Cyan
Write-Host ""
if ($WslConfigured) {
    Write-Host "  WSL2: open a new WSL terminal (or run 'source ~/.bashrc')" -ForegroundColor Gray
    Write-Host "        to use chainops there." -ForegroundColor Gray
    Write-Host ""
}
