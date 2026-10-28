# =============================================================================
# PradoOS (`prado-os`) — Self-Bootstrapping Installer for Windows 10/11
# Works on fresh Windows machines without Python or Git pre-installed!
# Usage:
#   irm https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.ps1 | iex
# =============================================================================

function Install-PradoOS {
    $ErrorActionPreference = "Continue"
    $ProgressPreference = "SilentlyContinue"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $RepoUrl = if ($env:PRADO_REPO_URL) { $env:PRADO_REPO_URL } else { "https://github.com/LorSt4r/ugr-prado-sync.git" }
    $ZipUrl = "https://github.com/LorSt4r/ugr-prado-sync/archive/refs/heads/main.zip"
    $InstallDir = if ($env:PRADO_INSTALL_DIR) { $env:PRADO_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "ugr-prado-sync" }

    Write-Host ""
    Write-Host "==> PradoOS Installer (Windows 10/11)" -ForegroundColor Cyan

    # Allow scripts in current process so venv activation or shims are never blocked
    try {
        Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force -ErrorAction SilentlyContinue
    } catch {}

    # -------------------------------------------------------------------------
    # 1. Source Code Resolution (Local checkout vs Git vs Direct GitHub ZIP)
    # -------------------------------------------------------------------------
    $ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
    if ((Test-Path (Join-Path $ScriptDir "pyproject.toml")) -and (Test-Path (Join-Path $ScriptDir "src\prado"))) {
        $SrcDir = $ScriptDir
        Write-Host "==> Using local repository checkout: $SrcDir"
    } else {
        New-Item -ItemType Directory -Force -Path $InstallDir -ErrorAction SilentlyContinue | Out-Null
        $GitCmd = Get-Command git -ErrorAction SilentlyContinue
        if ($GitCmd) {
            if (-not (Test-Path (Join-Path $InstallDir ".git"))) {
                Write-Host "==> Cloning PradoOS repository into $InstallDir..."
                & git clone $RepoUrl $InstallDir
            } else {
                Write-Host "==> Updating existing installation in $InstallDir..."
                & git -C $InstallDir pull --ff-only
            }
        }

        # Fallback to direct GitHub ZIP download if git wasn't installed or clone didn't populate pyproject.toml
        if (-not (Test-Path (Join-Path $InstallDir "pyproject.toml"))) {
            Write-Host "==> Downloading PradoOS archive directly from GitHub..." -ForegroundColor Cyan
            $ZipPath = Join-Path $env:TEMP "ugr-prado-sync-main.zip"
            $ExtractPath = Join-Path $env:TEMP "ugr-prado-sync-extract"

            try {
                if (Test-Path $ExtractPath) { Remove-Item -Recurse -Force $ExtractPath -ErrorAction SilentlyContinue }
                Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipPath -UseBasicParsing -ErrorAction Stop
                Expand-Archive -Path $ZipPath -DestinationPath $ExtractPath -Force -ErrorAction Stop

                $ExtractedRoot = Join-Path $ExtractPath "ugr-prado-sync-main"
                if (-not (Test-Path $ExtractedRoot)) {
                    $ExtractedRoot = (Get-ChildItem -Directory $ExtractPath | Select-Object -First 1).FullName
                }

                Copy-Item -Path "$ExtractedRoot\*" -Destination $InstallDir -Recurse -Force -ErrorAction Stop
                Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
                Remove-Item -Recurse -Force $ExtractPath -ErrorAction SilentlyContinue
            } catch {
                Write-Host "ERROR: Failed to download PradoOS from GitHub: $($_.Exception.Message)" -ForegroundColor Red
                return
            }
        }
        $SrcDir = $InstallDir
    }

    # -------------------------------------------------------------------------
    # 2. Python Detection & Direct Standalone uv Binary Bootstrap
    # -------------------------------------------------------------------------
    $PythonBin = $null
    $PyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($PyCmd -and ($PyCmd.Source -notlike "*WindowsApps\python.exe*")) {
        try {
            $PyOut = & python -c "import sys; print(int(sys.version_info >= (3, 10)))" 2>$null
            if ("$PyOut".Trim() -eq "1") {
                $PythonBin = "python"
            }
        } catch {}
    }

    if (-not $PythonBin) {
        $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($PyLauncher) {
            try {
                $PyOut = & py -3 -c "import sys; print(int(sys.version_info >= (3, 10)))" 2>$null
                if ("$PyOut".Trim() -eq "1") {
                    $PythonBin = "py"
                }
            } catch {}
        }
    }

    $UvExe = $null
    $CandidateUv = @(
        (Join-Path $env:LOCALAPPDATA "uv\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe")
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

    if (-not $PythonBin -and -not $UvExe) {
        Write-Host "==> Python >= 3.10 not found. Downloading standalone uv manager..." -ForegroundColor Yellow
        $Arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64-pc-windows-msvc" } else { "x86_64-pc-windows-msvc" }
        $UvZipUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-$Arch.zip"
        $UvBinDir = Join-Path $env:LOCALAPPDATA "uv\bin"
        $UvZipPath = Join-Path $env:TEMP "uv-$Arch.zip"

        try {
            New-Item -ItemType Directory -Force -Path $UvBinDir -ErrorAction SilentlyContinue | Out-Null
            Invoke-WebRequest -Uri $UvZipUrl -OutFile $UvZipPath -UseBasicParsing -ErrorAction Stop
            Expand-Archive -Path $UvZipPath -DestinationPath $UvBinDir -Force -ErrorAction Stop
            Remove-Item -Force $UvZipPath -ErrorAction SilentlyContinue

            $DownloadedUv = Join-Path $UvBinDir "uv.exe"
            if (Test-Path $DownloadedUv) {
                $UvExe = $DownloadedUv
                Write-Host "==> Standalone uv installed at $UvExe" -ForegroundColor Green
            }
        } catch {
            Write-Host "Notice: Could not download uv binary ($($_.Exception.Message))." -ForegroundColor DarkYellow
        }
    }

    # -------------------------------------------------------------------------
    # 3. Virtual Environment Creation & Package Installation
    # -------------------------------------------------------------------------
    $VenvDir = Join-Path $SrcDir ".venv"
    Write-Host "==> Preparing isolated Python environment at $VenvDir (this takes ~15 seconds)..." -ForegroundColor Cyan

    if ($UvExe) {
        Write-Host "==> Downloading portable Python 3.12 via uv..." -ForegroundColor Cyan
        & $UvExe python install 3.12
        & $UvExe venv --clear $VenvDir --python 3.12
        $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
        Write-Host "==> Installing PradoOS and dependencies..." -ForegroundColor Cyan
        & $UvExe pip install --python $VenvPython -e $SrcDir
    } elseif ($PythonBin) {
        if ($PythonBin -eq "py") {
            & py -3 -m venv --clear $VenvDir
        } else {
            & python -m venv --clear $VenvDir
        }
        $PipExe = Join-Path $VenvDir "Scripts\pip.exe"
        & $PipExe install --upgrade pip setuptools wheel
        & $PipExe install -e $SrcDir
    } else {
        Write-Host "ERROR: Could not locate or bootstrap Python. Please install Python 3.12 from https://www.python.org/downloads/" -ForegroundColor Red
        return
    }

    $PradoExe = Join-Path $VenvDir "Scripts\prado.exe"
    if (-not (Test-Path $PradoExe)) {
        Write-Host "ERROR: Installation did not produce $PradoExe. Check output above for errors." -ForegroundColor Red
        return
    }

    # -------------------------------------------------------------------------
    # 4. Global PATH Registration & Windows Wrapper Shims
    # -------------------------------------------------------------------------
    $ScriptsDir = Join-Path $VenvDir "Scripts"
    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($UserPath -notlike "*$ScriptsDir*") {
        [Environment]::SetEnvironmentVariable("Path", "$ScriptsDir;$UserPath", "User")
    }
    $env:Path = "$ScriptsDir;$env:Path"

    $WindowsAppsDir = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"
    if (Test-Path $WindowsAppsDir) {
        $CmdWrapper = Join-Path $WindowsAppsDir "prado.cmd"
        $CmdContent = "@echo off`r`n`"$PradoExe`" %*"
        try {
            Set-Content -Path $CmdWrapper -Value $CmdContent -Force -ErrorAction SilentlyContinue
        } catch {}
    }

    Write-Host ""
    Write-Host "✓ PradoOS installed successfully!" -ForegroundColor Green
    Write-Host "  Command    : prado"
    Write-Host "  Executable : $PradoExe"
    Write-Host ""

    # -------------------------------------------------------------------------
    # 5. Launch Onboarding Wizard
    # -------------------------------------------------------------------------
    if (-not $env:CI -and -not (Test-Path env:PRADO_NO_INTERACTIVE)) {
        Write-Host "==> Starting PradoOS Onboarding Wizard..." -ForegroundColor Cyan
        & $PradoExe onboard
    } else {
        Write-Host "Next step: run 'prado onboard' to configure your courses."
    }
}

Install-PradoOS
