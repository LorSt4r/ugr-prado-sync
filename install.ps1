# =============================================================================
# PradoOS (`prado-os`) — Self-Bootstrapping Installer for Windows 10/11
# Works on fresh Windows machines without Python or Git pre-installed!
# Usage:
#   irm https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.ps1 | iex
# =============================================================================

function Download-BinaryFile($Url, $DestFile) {
    $Parent = Split-Path -Parent $DestFile
    if ($Parent) { New-Item -ItemType Directory -Force -Path $Parent -ErrorAction SilentlyContinue | Out-Null }
    if (Test-Path $DestFile) { Remove-Item -Force $DestFile -ErrorAction SilentlyContinue }

    # Method 1: Native Windows 10/11 curl.exe (bypasses PowerShell TLS/redirect quirks)
    $SysCurl = Join-Path $env:SystemRoot "System32\curl.exe"
    if (Test-Path $SysCurl) {
        & $SysCurl -fsSL --retry 2 -o $DestFile $Url 2>$null
        if ((Test-Path $DestFile) -and ((Get-Item $DestFile).Length -gt 1000)) {
            return $true
        }
    }

    # Method 2: .NET System.Net.WebClient
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $wc = New-Object System.Net.WebClient
        $wc.Headers.Add("User-Agent", "PradoOS-Installer/1.0")
        $wc.DownloadFile($Url, $DestFile)
        if ((Test-Path $DestFile) -and ((Get-Item $DestFile).Length -gt 1000)) {
            return $true
        }
    } catch {}

    # Method 3: Invoke-WebRequest
    try {
        Invoke-WebRequest -Uri $Url -OutFile $DestFile -UseBasicParsing -ErrorAction Stop
        if ((Test-Path $DestFile) -and ((Get-Item $DestFile).Length -gt 1000)) {
            return $true
        }
    } catch {}

    return $false
}

function Extract-ZipFile($ZipFile, $DestDir) {
    New-Item -ItemType Directory -Force -Path $DestDir -ErrorAction SilentlyContinue | Out-Null

    # Method 1: Native Windows 10/11 tar.exe (bypasses PowerShell ExecutionPolicy / .psm1 restrictions)
    $SysTar = Join-Path $env:SystemRoot "System32\tar.exe"
    if (Test-Path $SysTar) {
        & $SysTar -xf $ZipFile -C $DestDir 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $true
        }
    }

    # Method 2: .NET System.IO.Compression.ZipFile (Pure CLR, no PowerShell script modules)
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
        $Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipFile)
        foreach ($Entry in $Archive.Entries) {
            $TargetFile = Join-Path $DestDir $Entry.FullName
            $TargetParent = Split-Path -Parent $TargetFile
            if ($TargetParent) { New-Item -ItemType Directory -Force -Path $TargetParent -ErrorAction SilentlyContinue | Out-Null }
            if (-not $Entry.FullName.EndsWith("/") -and -not $Entry.FullName.EndsWith("\")) {
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $TargetFile, $true)
            }
        }
        $Archive.Dispose()
        return $true
    } catch {}

    # Method 3: PowerShell Expand-Archive fallback
    try {
        Expand-Archive -Path $ZipFile -DestinationPath $DestDir -Force -ErrorAction Stop
        return $true
    } catch {}

    return $false
}

function Find-WorkingPython {
    # 1. Check standard user/system installation directories directly (even if not in current PATH)
    $CandidatePaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"),
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe",
        "C:\Program Files\Python313\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python310\python.exe"
    )
    foreach ($p in $CandidatePaths) {
        if (Test-Path $p) {
            try {
                $out = & $p -c "import sys; print(int(sys.version_info >= (3, 10)))" 2>$null
                if ("$out".Trim() -eq "1") { return $p }
            } catch {}
        }
    }

    # 2. Check python in PATH (excluding WindowsApps Microsoft Store stub)
    $PyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($PyCmd -and ($PyCmd.Source -notlike "*WindowsApps\python.exe*")) {
        try {
            $out = & $PyCmd.Source -c "import sys; print(int(sys.version_info >= (3, 10)))" 2>$null
            if ("$out".Trim() -eq "1") { return $PyCmd.Source }
        } catch {}
    }

    # 3. Check py launcher
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        try {
            $out = & py -3 -c "import sys; print(int(sys.version_info >= (3, 10)) + '|' + sys.executable)" 2>$null
            $str = "$out".Trim()
            if ($str.StartsWith("1|")) {
                return $str.Substring(2)
            }
        } catch {}
    }

    return $null
}

function Install-PradoOS {
    $ErrorActionPreference = "Continue"
    $ProgressPreference = "SilentlyContinue"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $RepoUrl = if ($env:PRADO_REPO_URL) { $env:PRADO_REPO_URL } else { "https://github.com/LorSt4r/ugr-prado-sync.git" }
    $ZipUrl = "https://github.com/LorSt4r/ugr-prado-sync/archive/refs/heads/main.zip"
    $InstallDir = if ($env:PRADO_INSTALL_DIR) { $env:PRADO_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "ugr-prado-sync" }

    Write-Host ""
    Write-Host "==> PradoOS Installer (Windows 10/11)" -ForegroundColor Cyan

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

        if (-not (Test-Path (Join-Path $InstallDir "pyproject.toml"))) {
            Write-Host "==> Downloading PradoOS source archive from GitHub..." -ForegroundColor Cyan
            $ZipPath = Join-Path $env:TEMP "ugr-prado-sync-main.zip"
            $ExtractPath = Join-Path $env:TEMP "ugr-prado-sync-extract"

            if (Test-Path $ExtractPath) { Remove-Item -Recurse -Force $ExtractPath -ErrorAction SilentlyContinue }
            if (-not (Download-BinaryFile $ZipUrl $ZipPath)) {
                Write-Host "ERROR: Could not download PradoOS archive from GitHub. Check your internet connection." -ForegroundColor Red
                return
            }
            if (-not (Extract-ZipFile $ZipPath $ExtractPath)) {
                Write-Host "ERROR: Could not extract PradoOS archive." -ForegroundColor Red
                return
            }

            $ExtractedRoot = Join-Path $ExtractPath "ugr-prado-sync-main"
            if (-not (Test-Path $ExtractedRoot)) {
                $FirstSub = Get-ChildItem -Directory $ExtractPath | Select-Object -First 1
                if ($FirstSub) { $ExtractedRoot = $FirstSub.FullName }
            }

            Copy-Item -Path "$ExtractedRoot\*" -Destination $InstallDir -Recurse -Force
            Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
            Remove-Item -Recurse -Force $ExtractPath -ErrorAction SilentlyContinue
        }
        $SrcDir = $InstallDir
    }

    # -------------------------------------------------------------------------
    # 2. Python / uv Detection & Multi-Tier Automatic Bootstrapping
    # -------------------------------------------------------------------------
    $PythonExe = Find-WorkingPython
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

    # Tier 2A: Download standalone uv.exe binary directly (via curl.exe / WebClient + tar.exe / .NET ZipFile)
    if (-not $PythonExe -and -not $UvExe) {
        Write-Host "==> Python >= 3.10 not found. Bootstrapping standalone uv manager..." -ForegroundColor Yellow
        $Arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64-pc-windows-msvc" } else { "x86_64-pc-windows-msvc" }
        $UvUrls = @(
            "https://releases.astral.sh/github/uv/releases/download/0.13.6/uv-$Arch.zip",
            "https://github.com/astral-sh/uv/releases/latest/download/uv-$Arch.zip"
        )
        $UvBinDir = Join-Path $env:LOCALAPPDATA "uv\bin"
        $UvZipPath = Join-Path $env:TEMP "uv-$Arch.zip"

        foreach ($u in $UvUrls) {
            if (Download-BinaryFile $u $UvZipPath) {
                if (Extract-ZipFile $UvZipPath $UvBinDir) {
                    $DownloadedUv = Join-Path $UvBinDir "uv.exe"
                    if (Test-Path $DownloadedUv) {
                        $UvExe = $DownloadedUv
                        Write-Host "==> Standalone uv ready at $UvExe" -ForegroundColor Green
                        break
                    }
                }
            }
        }
        Remove-Item -Force $UvZipPath -ErrorAction SilentlyContinue
    }

    # Tier 2B: Fallback to Official Python 3.12 User-Space Silent Installer from python.org (No Admin Needed!)
    if (-not $PythonExe -and -not $UvExe) {
        Write-Host "==> Downloading official Python 3.12 installer from python.org (user-mode, no admin required)..." -ForegroundColor Yellow
        $PyInstallerUrl = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") {
            "https://www.python.org/ftp/python/3.12.8/python-3.12.8-arm64.exe"
        } else {
            "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
        }
        $PyInstallerPath = Join-Path $env:TEMP "python-3.12.8-installer.exe"
        if (Download-BinaryFile $PyInstallerUrl $PyInstallerPath) {
            Write-Host "==> Installing Python 3.12 in user profile (please wait ~30 seconds)..." -ForegroundColor Cyan
            Start-Process -FilePath $PyInstallerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_doc=0" -Wait
            Remove-Item -Force $PyInstallerPath -ErrorAction SilentlyContinue
            $PythonExe = Find-WorkingPython
        }
    }

    # -------------------------------------------------------------------------
    # 3. Virtual Environment Creation & Package Installation
    # -------------------------------------------------------------------------
    $VenvDir = Join-Path $SrcDir ".venv"
    Write-Host "==> Preparing isolated Python environment at $VenvDir..." -ForegroundColor Cyan

    if ($UvExe) {
        Write-Host "==> Installing portable Python 3.12 via uv..." -ForegroundColor Cyan
        & $UvExe python install 3.12
        & $UvExe venv --clear $VenvDir --python 3.12
        $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
        if (Test-Path $VenvPython) {
            Write-Host "==> Installing PradoOS and dependencies..." -ForegroundColor Cyan
            & $UvExe pip install --python $VenvPython -e $SrcDir
        } else {
            Write-Host "==> uv venv did not create python.exe, falling back to system Python..." -ForegroundColor Yellow
            $PythonExe = Find-WorkingPython
        }
    }

    $PradoExe = Join-Path $VenvDir "Scripts\prado.exe"
    if (-not (Test-Path $PradoExe) -and $PythonExe) {
        Write-Host "==> Creating virtual environment using $PythonExe..." -ForegroundColor Cyan
        & $PythonExe -m venv --clear $VenvDir
        $PipExe = Join-Path $VenvDir "Scripts\pip.exe"
        & $PipExe install --upgrade pip setuptools wheel
        & $PipExe install -e $SrcDir
    }

    if (-not (Test-Path $PradoExe)) {
        Write-Host "ERROR: Could not complete PradoOS installation. Please check the messages above." -ForegroundColor Red
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
