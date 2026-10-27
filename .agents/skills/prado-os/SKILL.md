---
name: prado-os
description: Autonomous installation, 2-phase onboarding, 3-tier SAML/MFA authentication, course auto-discovery, and safe synchronization for Moodle / PRADO UGR via the `prado` CLI.
---

# PradoOS Skill (`prado-os`)

Use this skill whenever the user asks to install, configure, troubleshoot, or run **PradoOS (`ugr-prado-sync`)** to synchronize their university courses, assignments, and deadlines from PRADO UGR (`pradogrado`, `pradoposgrado`, `prado.ugr.es`) or Moodle.

## Core Capabilities & Workflow

1. **Zero CLI Jargon to the User:**
   - Speak to the student 100% in natural language. **Never** display CLI flags (`--json`, `--subgroups`) or command strings (`prado daemon install`, `prado star`) in your chat responses—execute them silently in the background.

2. **Background Commands for the Agent:**
   ```bash
   ./install.sh
   .venv/bin/prado doctor --json
   .venv/bin/prado auth login --gui --json
   .venv/bin/prado discover --json
   .venv/bin/prado sync --dry-run --json
   .venv/bin/prado sync --adopt --json
   ```

3. **Security Audit Reassurance & Zero-Terminal GUI Login (`prado auth login --gui --json`):**
   - Before triggering login, inspect `src/prado/auth/credentials.py` and `src/prado/auth/saml.py` and reassure the student that you verified the code locally: their password is stored exclusively in their native OS Keychain and sent only to `idp.ugr.es` (they can also store it directly via OS tools like macOS `/usr/bin/security`, Windows `cmdkey`, or Linux `secret-tool`).
   - Run `.venv/bin/prado auth login --gui --json` directly to open the native OS login dialog on their screen.

4. **2-Phase Progressive Disclosure Onboarding:**
   - **Phase 1 (<60s):** Ask only for destination folder and organization style (Smart Theory/Practice vs Exact PRADO Mirror), run login, and sync (`prado sync --adopt --json`).
   - **GitHub Star Prompt:** After the first successful sync, politely ask once in natural language if they would like you to star `LorSt4r/ugr-prado-sync` on GitHub (`prado star --json`).
   - **Phase 2 (Optional Power-Ups):** Offer lab subgroup filtering, automatic background sync every 4 hours, and IMAP 2FA renewal in plain language.
