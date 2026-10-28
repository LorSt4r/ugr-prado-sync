# =============================================================================
# PradoOS (`prado-os`) — Self-Bootstrapping Installer for Windows 10/11
# Works on fresh Windows machines even without Python or Git pre-installed!
# Usage:
#   irm https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.ps1 | iex
#   or: powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.ps1 | iex"
# =============================================================================
$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:PRADO_REPO_URL) { $env:PRADO_REPO_URL } else { "https://github.com/LorSt4r/ugr-prado-sync.git" }
$ZipUrl = "https://github.com/LorSt4r/ugr-prado-sync/archive/refs/heads/main.zip"
$InstallDir = if ($env:PRADO_INSTALL_DIR) { $env:PRADO_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "ugr-prado-sync" }

Write-Host "==> PradoOS Installer (Windows)" -ForegroundColor Cyan

# -----------------------------------------------------------------------------
# 1. Source Code Resolution (Local checkout vs Git Clone vs Direct GitHub ZIP)
# -----------------------------------------------------------------------------
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
if ((Test-Path (Join-Path $ScriptDir "pyproject.toml")) -and (Test-Path (Join-Path $ScriptDir "src\prado"))) {
    $SrcDir = $ScriptDir
    Write-Host "==> Using local repository checkout: $SrcDir"
} else {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $GitCmd = Get-Command git -ErrorAction SilentlyContinue
    if ($GitCmd) {
        if (-not (Test-Path (Join-Path $InstallDir ".git"))) {
            Write-Host "==> Cloning PradoOS repository into $InstallDir..."
            git clone $RepoUrl $InstallDir
        } else {
            Write-Host "==> Updating existing installation in $InstallDir..."
            git -C $InstallDir pull --ff-only
        }
    } else {
        Write-Host "==> Git not detected. Downloading PradoOS archive directly from GitHub..." -ForegroundColor Cyan
        $ZipPath = Join-Path $env:TEMP "ugr-prado-sync-main.zip"
        $ExtractPath = Join-Path $env:TEMP "ugr-prado-sync-extract"

        if (Test-Path $ExtractPath) { Remove-Item -Recurse -Force $ExtractPath }
        Invoke-RestMethod -Uri $ZipUrl -OutFile $ZipPath
        Expand-Archive -Path $ZipPath -DestinationPath $ExtractPath -Force

        $ExtractedRoot = Join-Path $ExtractPath "ugr-prado-sync-main"
        if (-not (Test-Path $ExtractedRoot)) {
            $ExtractedRoot = (Get-ChildItem -Directory $ExtractPath | Select-Object -First 1).FullName
        }

        Copy-Item -Path "$ExtractedRoot\*" -Destination $InstallDir -Recurse -Force
        Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $ExtractPath -ErrorAction SilentlyContinue
    }
    $SrcDir = $InstallDir
}

# -----------------------------------------------------------------------------
# 2. Python Environment Detection & Automatic Bootstrapping
# -----------------------------------------------------------------------------
$PythonBin = $null
$PyCmd = Get-Command python -ErrorAction SilentlyContinue
if ($PyCmd) {
    try {
        $PyCheck = python -c "import sys; print(int(sys.version_info >= (3, 10)))" 2>$null
        if ($PyCheck -eq "1") {
            $PythonBin = "python"
        }
    } catch {}
}

if (-not $PythonBin) {
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        try {
            $PyCheck = py -c "import sys; print(int(sys.version_info >= (3, 10)))" 2>$null
            if ($PyCheck -eq "1") {
                $PythonBin = "py"
            }
        } catch {}
    }
}

$UvExe = $null
if (-not $PythonBin) {
    # Check if uv is already installed
    $CandidateUv = @(
        (Join-Path $env:LOCALAPPDATA "uv\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe")
    )
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $UvExe = (Get-Command uv).Source
    } else {
        foreach ($cand in $CandidateUv) {
            if (Test-Path $cand) {
                $UvExe = $cand
                break
            }
        }
    }

    # If neither Python >= 3.10 nor uv is found, automatically bootstrap uv
    if (-not $UvExe) {
        Write-Host "==> Python >= 3.10 was not found on this system." -ForegroundColor Yellow
        Write-Host "==> Bootstrapping isolated Python runtime via Astral uv (zero admin rights needed)..." -ForegroundColor Cyan
        try {
            $env:UV_INSTALL_DIR = Join-Path $env:LOCALAPPDATA "uv\bin"
            New-Item -ItemType Directory -Force -Path $env:UV_INSTALL_DIR | Out-Null
            Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
            
            $NewUv = Join-Path $env:LOCALAPPDATA "uv\bin\uv.exe"
            if (Test-Path $NewUv) {
                $UvExe = $NewUv
            } else {
                foreach ($cand in $CandidateUv) {
                    if (Test-Path $cand) {
                        $UvExe = $cand
                        break
                    }
                }
            }
        } catch {
            Write-Host "Notice: uv auto-download failed ($($_.Exception.Message))." -ForegroundColor DarkYellow
        }
    }

    # If uv is available, install portable standalone Python 3.12
    if ($UvExe) {
        Write-Host "==> Downloading and configuring standalone Python 3.12..." -ForegroundColor Cyan
        & $UvExe python install 3.12
    } elseif (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "==> Attempting automated Python 3.12 installation via winget..." -ForegroundColor Cyan
        try {
            winget install --id Python.Python.3.12 --exact --source winget --accept-source-agreements --accept-package-agreements --silent
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
            if (Get-Command python -ErrorAction SilentlyContinue) {
                $PythonBin = "python"
            }
        } catch {}
    }

    if (-not $UvExe -and -not $PythonBin) {
        Write-Error "Could not automatically bootstrap Python. Please install Python 3.10+ from https://www.python.org/downloads/ or run 'winget install Python.Python.3.12'."
        exit 1
    }
}

# -----------------------------------------------------------------------------
# 3. Virtual Environment Creation & Package Installation
# -----------------------------------------------------------------------------
$VenvDir = Join-Path $SrcDir ".venv"
Write-Host "==> Preparing isolated virtual environment at $VenvDir..."

if ($UvExe) {
    & $UvExe venv $VenvDir --python 3.12 --seed
    & $UvExe pip install --python (Join-Path $VenvDir "Scripts\python.exe") -e $SrcDir
} else {
    & $PythonBin -m venv $VenvDir
    & (Join-Path $VenvDir "Scripts\pip.exe") install --upgrade pip setuptools wheel | Out-Null
    & (Join-Path $VenvDir "Scripts\pip.exe") install -e $SrcDir
}

$PradoExe = Join-Path $VenvDir "Scripts\prado.exe"
if (-not (Test-Path $PradoExe)) {
    Write-Error "Installation failed: $PradoExe was not created."
    exit 1
}

# -----------------------------------------------------------------------------
# 4. Global PATH Registration & Windows Wrapper Shims
# -----------------------------------------------------------------------------
$ScriptsDir = Join-Path $VenvDir "Scripts"
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$ScriptsDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$ScriptsDir;$UserPath", "User")
}
$env:Path = "$ScriptsDir;$env:Path"

# Create a prado.cmd wrapper in %LOCALAPPDATA%\Microsoft\WindowsApps (pre-included in standard Windows PATH)
$WindowsAppsDir = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"
if (Test-Path $WindowsAppsDir) {
    $CmdWrapper = Join-Path $WindowsAppsDir "prado.cmd"
    $CmdContent = "@echo off`r`n`"$PradoExe`" %*"
    try {
        Set-Content -Path $CmdWrapper -Value $CmdContent -Force
    } catch {}
}

Write-Host ""
Write-Host "✓ PradoOS installed successfully!" -ForegroundColor Green
Write-Host "  Command    : prado"
Write-Host "  Executable : $PradoExe"
Write-Host ""

# -----------------------------------------------------------------------------
# 5. Launch Onboarding Wizard
# -----------------------------------------------------------------------------
if (-not $env:CI -and -not (Test-Path env:PRADO_NO_INTERACTIVE)) {
    Write-Host "==> Starting PradoOS Onboarding Wizard..." -ForegroundColor Cyan
    & $PradoExe onboard
} else {
    Write-Host "Next step: run 'prado onboard' to configure your courses and deadlines."
}
