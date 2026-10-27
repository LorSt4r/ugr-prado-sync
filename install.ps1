# =============================================================================
# PradoOS (`prado-os`) — One-Liner PowerShell Installer for Windows 10/11
# Usage:
#   irm https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.ps1 | iex
#   or locally: .\install.ps1
# =============================================================================
$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:PRADO_REPO_URL) { $env:PRADO_REPO_URL } else { "https://github.com/LorSt4r/ugr-prado-sync.git" }
$InstallDir = if ($env:PRADO_INSTALL_DIR) { $env:PRADO_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "ugr-prado-sync" }

Write-Host "==> PradoOS Installer (Windows PowerShell)" -ForegroundColor Cyan

# 1. Verify Python >= 3.10
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python is not installed or not in PATH. Please install Python 3.10+ from python.org."
    exit 1
}

$PyCheck = python -c "import sys; print(int(sys.version_info >= (3, 10)))"
if ($PyCheck -ne "1") {
    Write-Error "Python 3.10 or newer is required."
    exit 1
}

# 2. Determine source directory
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
if ((Test-Path (Join-Path $ScriptDir "pyproject.toml")) -and (Test-Path (Join-Path $ScriptDir "src\prado"))) {
    $SrcDir = $ScriptDir
    Write-Host "==> Installing from local checkout: $SrcDir"
} else {
    if (-not (Test-Path $InstallDir)) {
        Write-Host "==> Cloning PradoOS into $InstallDir"
        git clone $RepoUrl $InstallDir
    } else {
        Write-Host "==> Updating existing installation in $InstallDir"
        git -C $InstallDir pull --ff-only
    }
    $SrcDir = $InstallDir
}

# 3. Create virtual environment and install package
$VenvDir = Join-Path $SrcDir ".venv"
Write-Host "==> Creating virtual environment at $VenvDir"
python -m venv $VenvDir
& (Join-Path $VenvDir "Scripts\pip.exe") install --upgrade pip | Out-Null
& (Join-Path $VenvDir "Scripts\pip.exe") install -e $SrcDir

$PradoExe = Join-Path $VenvDir "Scripts\prado.exe"
Write-Host "✓ PradoOS installed successfully!" -ForegroundColor Green
Write-Host "  Executable : $PradoExe"
Write-Host "  Next step  : Run '$PradoExe onboard' or '$PradoExe doctor'"
