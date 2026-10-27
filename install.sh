#!/usr/bin/env bash
# =============================================================================
# PradoOS (`prado-os`) — One-Liner Installer for macOS & Linux Desktop
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.sh | bash
#   or locally: ./install.sh
# =============================================================================
set -euo pipefail

REPO_URL="${PRADO_REPO_URL:-https://github.com/LorSt4r/ugr-prado-sync.git}"
INSTALL_DIR="${PRADO_INSTALL_DIR:-$HOME/.local/share/ugr-prado-sync}"
BIN_DIR="${PRADO_BIN_DIR:-$HOME/.local/bin}"

printf "\033[1;34m==> PradoOS Installer (macOS / Linux Desktop)\033[0m\n"

# 1. Verify Python >= 3.10
if ! command -v python3 >/dev/null 2>&1; then
    printf "\033[1;31mError: python3 is not installed. Please install Python 3.10 or newer.\033[0m\n" >&2
    exit 1
fi

PY_OK=$(python3 -c 'import sys; print(int(sys.version_info >= (3, 10)))')
if [ "$PY_OK" != "1" ]; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    printf "\033[1;31mError: Python >= 3.10 is required (found Python %s).\033[0m\n" "$PY_VER" >&2
    exit 1
fi

# 2. Determine source directory (local checkout vs remote git clone)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"
if [ -f "$SCRIPT_DIR/pyproject.toml" ] && [ -d "$SCRIPT_DIR/src/prado" ]; then
    SRC_DIR="$SCRIPT_DIR"
    printf "==> Installing from local repository: %s\n" "$SRC_DIR"
else
    if ! command -v git >/dev/null 2>&1; then
        printf "\033[1;31mError: git is required to clone PradoOS.\033[0m\n" >&2
        exit 1
    fi
    mkdir -p "$(dirname "$INSTALL_DIR")"
    if [ -d "$INSTALL_DIR/.git" ]; then
        printf "==> Updating existing installation in %s\n" "$INSTALL_DIR"
        git -C "$INSTALL_DIR" pull --ff-only
    else
        printf "==> Cloning PradoOS into %s\n" "$INSTALL_DIR"
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
    SRC_DIR="$INSTALL_DIR"
fi

# 3. Create isolated virtual environment & install package
VENV_DIR="$SRC_DIR/.venv"
printf "==> Creating Python virtual environment at %s\n" "$VENV_DIR"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
"$VENV_DIR/bin/pip" install -e "$SRC_DIR"

# 4. Symlink `prado` binary into ~/.local/bin
mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/prado" "$BIN_DIR/prado"

printf "\033[1;32m✓ PradoOS installed successfully!\033[0m\n"
printf "  Executable : %s/prado\n" "$BIN_DIR"
printf "  Next step  : Run 'prado onboard' or 'prado doctor'\n"
