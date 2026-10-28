#!/usr/bin/env bash
# =============================================================================
# PradoOS (`prado-os`) — Self-Bootstrapping Installer for macOS & Linux Desktop
# Works even on fresh systems without Python or Git pre-installed!
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.sh | bash
#   or locally: ./install.sh
# =============================================================================
set -euo pipefail

REPO_URL="${PRADO_REPO_URL:-https://github.com/LorSt4r/ugr-prado-sync.git}"
TAR_URL="https://github.com/LorSt4r/ugr-prado-sync/archive/refs/heads/main.tar.gz"
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
    printf "\033[1;33m==> Python >= 3.10 not found. Bootstrapping isolated Python runtime via Astral uv...\033[0m\n"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

# 2. Determine source directory (local checkout vs remote git clone vs archive)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"
if [ -f "$SCRIPT_DIR/pyproject.toml" ] && [ -d "$SCRIPT_DIR/src/prado" ]; then
    SRC_DIR="$SCRIPT_DIR"
    printf "==> Installing from local repository: %s\n" "$SRC_DIR"
else
    mkdir -p "$(dirname "$INSTALL_DIR")"
    if command -v git >/dev/null 2>&1; then
        if [ -d "$INSTALL_DIR/.git" ]; then
            printf "==> Updating existing installation in %s\n" "$INSTALL_DIR"
            git -C "$INSTALL_DIR" pull --ff-only
        else
            printf "==> Cloning PradoOS into %s\n" "$INSTALL_DIR"
            git clone "$REPO_URL" "$INSTALL_DIR"
        fi
    else
        printf "\033[1;36m==> Git not detected. Downloading PradoOS archive directly from GitHub...\033[0m\n"
        mkdir -p "$INSTALL_DIR"
        curl -fsSL "$TAR_URL" | tar -xz -C "$INSTALL_DIR" --strip-components=1
    fi
    SRC_DIR="$INSTALL_DIR"
fi

# 3. Create isolated virtual environment & install package
VENV_DIR="$SRC_DIR/.venv"
printf "==> Preparing Python virtual environment at %s\n" "$VENV_DIR"

if [ -x "$VENV_DIR/bin/python" ] && "$VENV_DIR/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    printf "==> Reusing existing Python >= 3.10 virtual environment\n"
    "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel >/dev/null 2>&1 || true
    "$VENV_DIR/bin/pip" install -e "$SRC_DIR"
elif [ -n "$PYTHON_BIN" ]; then
    "$PYTHON_BIN" -m venv --clear "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel >/dev/null
    "$VENV_DIR/bin/pip" install -e "$SRC_DIR"
else
    uv python install 3.12
    uv venv --clear "$VENV_DIR" --python 3.12 --seed
    uv pip install --python "$VENV_DIR/bin/python" -e "$SRC_DIR"
fi

# 4. Symlink `prado` binary into ~/.local/bin
mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/prado" "$BIN_DIR/prado"

# Ensure ~/.local/bin is in PATH for future sessions if missing
SHELL_RC=""
case "${SHELL:-}" in
    */zsh) SHELL_RC="$HOME/.zshrc" ;;
    */bash) SHELL_RC="$HOME/.bashrc" ;;
esac

if [ -n "$SHELL_RC" ] && [ -f "$SHELL_RC" ]; then
    if ! grep -q '\.local/bin' "$SHELL_RC" 2>/dev/null; then
        printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$SHELL_RC"
    fi
fi

printf "\033[1;32m✓ PradoOS installed successfully!\033[0m\n"
printf "  Command    : %s/prado\n" "$BIN_DIR"
printf "  Executable : %s/prado\n\n" "$BIN_DIR"

# 5. Launch Onboarding Wizard if interactive
if [ -z "${CI:-}" ] && [ -z "${PRADO_NO_INTERACTIVE:-}" ] && [ -t 0 ]; then
    printf "\033[1;36m==> Starting PradoOS Onboarding Wizard...\033[0m\n"
    exec "$BIN_DIR/prado" onboard
else
    printf "Next step: run 'prado onboard' to configure your courses.\n"
fi
