---
name: prado-os
description: Autonomous installation, 2-phase onboarding, 3-tier SAML/MFA authentication, course auto-discovery, and safe synchronization for Moodle / PRADO UGR via the `prado` CLI.
---

# PradoOS Skill (`prado-os`)

Use this skill whenever the user asks to install, configure, troubleshoot, or run **PradoOS (`ugr-prado-sync`)** to synchronize their university courses, assignments, and deadlines from PRADO UGR (`pradogrado`, `pradoposgrado`, `prado.ugr.es`) or Moodle.

## Core Capabilities & Workflow

1. **Language Priority (Spanish Primary, English & Adaptive Multi-Language):**
   - PradoOS serves the Universidad de Granada community: prioritize **Spanish** by default if the user writes in Spanish or references UGR.
   - Detect or ask the student's preferred language (Spanish or English, or conduct onboarding in their native tongue if requested), defaulting to English if unavailable.

2. **Zero CLI Jargon to the User:**
   - Speak to the student 100% in natural language. **Never** display CLI flags (`--json`, `--subgroups`) or command strings (`prado daemon install`, `prado star`) in your chat responses—execute them silently in the background.

3. **Background Commands for the Agent:**
   ```bash
   ./install.sh
   .venv/bin/prado doctor --json
   .venv/bin/prado auth login --gui --json
   .venv/bin/prado discover --json
   .venv/bin/prado sync --adopt --json
   .venv/bin/prado gcalendar --json
   .venv/bin/prado daemon install --interval 14400 --json
   ```

4. **Security Audit Reassurance & Zero-Terminal GUI Login (`prado auth login --gui --json`):**
   - Before triggering login, inspect `src/prado/auth/credentials.py` and `src/prado/auth/saml.py` and reassure the student that you verified the code locally: their password is stored exclusively in their native OS Keychain and sent only to `idp.ugr.es` (they can also store it directly via OS tools like macOS `/usr/bin/security`, Windows `cmdkey`, or Linux `secret-tool`).
   - Run `.venv/bin/prado auth login --gui --json` directly to open the native OS login dialog on their screen.

5. **2-Phase Progressive Disclosure Onboarding:**
   - **Phase 1 (<60s):** Ask only for destination folder (`courses_root`) and sync frequency (e.g. 3x/day or every 4 hours). Apply the **Smart Theory vs Practice** (`smart`) preset automatically for agentic setups.
   - **Phase 2 (Sartorial Academic Concierge & Automation):**
     - **Autonomous Automation:**
       - **Google Antigravity:** Suggest `/automation` or schedule tool (cron `0 8,14,20 * * 1-5`).
       - **Claude Code:** Setup headless cron runner (`claude -p "..." --allowedTools "Bash,Read"`).
       - **OpenAI Codex / Terminal:** Install OS daemon via `prado daemon install --interval 14400 --json`.
       - **Google Calendar:** Run `prado gcalendar --json` to push deadlines with tiered popup alarms.
     - **Sartorial Personalization (`USER.md`):**
       - Ask the student for their weekly class timetable to schedule intelligent deep work study blocks between lectures.
       - Ask if they want to merge theoretical and lab portals (e.g. `SO_COMUN` + `SO_E` -> `SO_E/`).
       - Ask for evaluation weights (theory exam, lab project) and target grades (Sobresaliente / Matrícula de Honor) to prioritize dashboard countdowns.
       - Save all custom preferences into `.gitignore`-protected `USER.md` using `USER.md.example` as a model.
   - **GitHub Star Prompt:** After the first successful sync, politely ask once in natural language if they would like you to star `LorSt4r/ugr-prado-sync` on GitHub (`prado star --json`).
