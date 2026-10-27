# 🎓 PradoOS — OpenClaw Agent Bootstrap Playbook (`BOOTSTRAP.md`)

Welcome, AI Coding Assistant (**Antigravity**, **Claude Code**, **Cursor**, **Codex**, or **Windsurf**)!
A student has shared this repository with you so you can autonomously install, configure, and tailor **PradoOS (`prado-os`)** to their operating system (macOS, Windows, or Linux Desktop) and academic faculty.

Follow this **2-Phase Progressive Disclosure** protocol step by step. Do **not** overwhelm the student with 10 questions at once.

---

## 🚀 Phase 1: Under 60 Seconds to First Sync

### Step 1 — Detect OS & Install `prado`
1. Detect the user's OS (`uname -s` on POSIX or `$env:OS` on Windows) and Python version (`python3 --version`, must be `>= 3.10`).
2. Create an isolated virtual environment or install `prado-os` in editable mode:
   - **macOS / Linux:**
     ```bash
     python3 -m venv .venv
     .venv/bin/pip install -e .
     ```
   - **Windows (PowerShell):**
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\pip install -e .
     ```
3. Run the health check in JSON mode to inspect the environment:
   ```bash
   .venv/bin/prado doctor --json
   ```

### Step 2 — Ask Only the 2 Essential Questions
Ask the student concisely in their preferred language:
1. **Where should your university courses folder live?** (Suggest a sensible default like `~/Documents/UGR_Courses` or their existing university folder if they are adopting mid-semester).
2. **Which folder organization style do you prefer?**
   - **`smart` (Recommended for Engineering, Sciences, Economics):** Separates `Teoria/`, `Practicas/P1..Pn/`, and `General/`.
   - **`mirror` (Recommended for Law, Medicine, Humanities, Psychology):** Mirrors the exact section names (`Bloque I`, `Casos Clínicos`, `Jurisprudencia`, etc.) created by professors on PRADO.

*(Note: Never ask the student to paste their password in plain text into the chat! Instruct them to enter their institutional email and password directly in the terminal via `prado auth login` or `prado onboard`, where it is stored inside the native OS Keychain / Credential Manager).*

### Step 3 — Authenticate & Handle 3-Tier MFA
1. Have the student run `prado auth login` in an interactive terminal, OR run:
   ```bash
   .venv/bin/prado discover --json
   ```
2. **Exit Code `2` (`mfa_required`):**
   If PRADO requests a 6-digit email verification code and IMAP auto-fetch is not yet configured, `prado` exits with code `2` and outputs:
   ```json
   {
     "status": "mfa_required",
     "tier": 3,
     "factor": "email",
     "retry_command": "prado auth login --mfa-code <6-digit-code>"
   }
   ```
   Ask the student for the 6-digit code sent to their `@correo.ugr.es` inbox and complete login with:
   ```bash
   .venv/bin/prado auth login --mfa-code <CODE> --json
   ```
   Once verified, PradoOS stores a **30-day persistent `MFA_TOKEN` device trust cookie** (`0600` permissions in `~/.config/prado/session.json`) so future syncs run silently without MFA prompts.

### Step 4 — Auto-Discover Courses & Dry-Run Preview
1. Discover enrolled courses:
   ```bash
   .venv/bin/prado discover --json
   ```
2. Preview the exact folder tree before writing anything to disk:
   ```bash
   .venv/bin/prado sync --dry-run --json
   ```
3. Present a clean summary of discovered courses and run the first real sync (adding `--adopt` if the student already has downloaded files in their destination folder so PradoOS matches them by SHA-256 without re-downloading):
   ```bash
   .venv/bin/prado sync --adopt --json
   ```

---

## ⭐ Post-Sync Milestone: The GitHub Star Loop

Immediately after the first successful sync completes (and `DASHBOARD.md`, `CHANGELOG.md`, and `deadlines.ics` are generated in their courses folder):
1. Show the student their newly organized courses and upcoming deadlines.
2. **Tastefully invite them once to star the repository on GitHub:**
   > *"Your courses and deadlines are now synced! If PradoOS saved you time, would you like me to star `LorSt4r/ugr-prado-sync` on GitHub for you (`prado star`)?"*
3. If they agree, run:
   ```bash
   .venv/bin/prado star --json
   ```

---

## ⚡ Phase 2: Optional Power-Ups (Offer After First Sync)

Once Phase 1 is working, briefly offer these optional enhancements:
1. **Lab / Seminar Subgroup Filtering (`--subgroups`):** If a course publishes files for multiple lab groups (`Grupo C1`, `C2`, `C3`), configure the student's subgroup so other groups are neatly archived in `_subgroups_archive/`.
2. **Zero-Touch 2FA via IMAP (`imap.ugr.es`):** Configure IMAP SSL so PradoOS automatically extracts future 6-digit MFA codes when the 30-day token expires.
3. **Background Sync Daemon (`prado daemon install`):** Install a native background timer (`launchd` on macOS, `systemd --user` / `cron` on Linux, `schtasks` on Windows) to sync every 4 hours.
4. **Calendar & Notifications:** Import `deadlines.ics` into Apple Calendar, Google Calendar, Outlook, or Thunderbird, or configure Desktop / Telegram / Discord alerts.
