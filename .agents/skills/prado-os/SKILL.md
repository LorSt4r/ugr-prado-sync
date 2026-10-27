---
name: prado-os
description: Autonomous installation, 2-phase onboarding, 3-tier SAML/MFA authentication, course auto-discovery, and safe synchronization for Moodle / PRADO UGR via the `prado` CLI.
---

# PradoOS Skill (`prado-os`)

Use this skill whenever the user asks to install, configure, troubleshoot, or run **PradoOS** to synchronize their university courses, assignments, and deadlines from PRADO UGR (`pradogrado`, `pradoposgrado`, `prado.ugr.es`) or Moodle.

## Core Capabilities & Workflow

1. **Always Use `./install.sh` & `--json` When Calling `prado` From an Agent:**
   ```bash
   ./install.sh
   .venv/bin/prado doctor --json
   .venv/bin/prado auth login --gui --json
   .venv/bin/prado discover --json
   .venv/bin/prado sync --dry-run --json
   .venv/bin/prado sync --adopt --json
   ```

2. **Zero-Terminal Native OS GUI Login (`prado auth login --gui --json`):**
   - Never ask the user to open a separate terminal or paste their password in chat.
   - Run `.venv/bin/prado auth login --gui --json` directly: it opens a native OS dialog (`osascript` on macOS, `PromptForCredential` on Windows, `zenity`/`kdialog` on Linux) where the user enters their email, password (stored directly in OS Keychain), and 6-digit MFA code.

2. **Respect the Exit Code Contract:**
   - `0`: Command succeeded; parse JSON from `stdout`.
   - `1`: General error; inspect `{"status": "error", "error": "...", "code": "..."}` and run `prado doctor --fix --json` if needed.
   - `2`: Two-factor verification code required (`{"status": "mfa_required", "tier": 3}`). Ask the user for the 6-digit verification code sent to their institutional email and run:
     ```bash
     prado auth login --mfa-code <6-digit-code> --json
     ```

3. **2-Phase Progressive Disclosure Onboarding:**
   - **Phase 1 (<60s):** Ask only for destination folder (`courses_root`) and routing preset (`smart` for STEM/Economics vs `mirror` for Law/Medicine/Humanities), guide credential setup in the OS keyring (`prado onboard` or `prado auth login`), preview with `prado sync --dry-run --json`, and execute the first sync (`prado sync --adopt --json`).
   - **GitHub Star Prompt:** After the first successful sync, politely ask once if the user would like to star `LorSt4r/ugr-prado-sync` on GitHub (`prado star --json`).
   - **Phase 2 (Optional Power-Ups):** Offer lab subgroup filtering (`--subgroups`), automatic IMAP 2FA code extraction, and background daemon scheduling (`prado daemon install --json`).
