$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$VenvDir     = Join-Path $ProjectRoot ".venv-build-windows"
$PythonExe   = Join-Path $VenvDir "Scripts\python.exe"
$PipExe      = Join-Path $VenvDir "Scripts\pip.exe"
$DistDir     = Join-Path $ProjectRoot "dist\windows"
$BuildDir    = Join-Path $ProjectRoot "build\windows"
$ReqFile     = Join-Path $ProjectRoot "requirements.txt"
$HashFile    = Join-Path $VenvDir ".req_hash"
$PyiExe      = Join-Path $VenvDir "Scripts\pyinstaller.exe"

Set-Location $ProjectRoot

# Create venv only if it doesn't exist
if (-not (Test-Path $PythonExe)) {
    Write-Host "==> Creating build venv"
    py -3.12 -m venv $VenvDir
    & $PipExe install --upgrade pip --quiet
}

# Reinstall dependencies only when requirements.txt changes or PyInstaller is missing
$CurrentHash = (Get-FileHash $ReqFile -Algorithm SHA256).Hash
$StoredHash  = if (Test-Path $HashFile) { (Get-Content $HashFile).Trim() } else { "" }

if ($CurrentHash -ne $StoredHash -or -not (Test-Path $PyiExe)) {
    Write-Host "==> Installing/updating dependencies"
    & $PipExe install --upgrade pip --quiet
    & $PipExe install -r $ReqFile pyinstaller --quiet
    Set-Content $HashFile $CurrentHash
} else {
    Write-Host "==> Dependencies up to date, skipping install"
}

$pyiArgs = @(
    "--noconfirm",
    "--onefile",
    "--name", "chainops",
    "--distpath", $DistDir,
    "--workpath", $BuildDir,
    "--hidden-import", "_version",
    "--collect-submodules", "uvicorn",
    "--collect-submodules", "fastapi",
    "--collect-submodules", "starlette",
    (Join-Path $ProjectRoot "main.py")
)

& $PythonExe -m PyInstaller @pyiArgs

Write-Host "Build complete: $(Join-Path $DistDir 'chainops.exe')"
