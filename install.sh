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

# 1. Locate Python >= 3.10 (or uv)
PYTHON_BIN=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ] && ! command -v uv >/dev/null 2>&1; then
    printf "\033[1;31mError: Python >= 3.10 is required (macOS system /usr/bin/python3 is 3.9). Install Python 3.10+ via Homebrew ('brew install python') or uv ('curl -LsSf https://astral.sh/uv/install.sh | sh').\033[0m\n" >&2
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
printf "==> Preparing Python virtual environment at %s\n" "$VENV_DIR"
if [ -x "$VENV_DIR/bin/python" ] && "$VENV_DIR/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    printf "==> Reusing existing Python >= 3.10 virtual environment\n"
elif [ -n "$PYTHON_BIN" ]; then
    "$PYTHON_BIN" -m venv --clear "$VENV_DIR"
else
    uv venv --clear "$VENV_DIR" --python ">=3.10" --seed
fi
"$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel >/dev/null
"$VENV_DIR/bin/pip" install -e "$SRC_DIR"

# 4. Symlink `prado` binary into ~/.local/bin
mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/prado" "$BIN_DIR/prado"

printf "\033[1;32m✓ PradoOS installed successfully!\033[0m\n"
printf "  Executable : %s/prado\n" "$BIN_DIR"
printf "  Next step  : Run 'prado onboard' or 'prado doctor'\n"
