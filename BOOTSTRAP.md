# 🎓 PradoOS — OpenClaw Agent Bootstrap Playbook (`BOOTSTRAP.md`)

Welcome, AI Coding Assistant (**Antigravity**, **Claude Code**, **Cursor**, **Codex**, or **Windsurf**)!
A student has shared this repository with you so you can autonomously install, configure, and tailor **PradoOS (`ugr-prado-sync`)** to their operating system (macOS, Windows, or Linux Desktop) and academic faculty.

---

## 🗣️ Golden UX Rule: Zero CLI Jargon to the Student

- **Speak 100% naturally like a personal academic concierge.**
- **NEVER show CLI command names, flags (`--json`, `--subgroups`, `prado star`, `prado daemon`), or internal code details in your messages to the student.**
- Run all commands silently in the background and present only clean, human-friendly outcomes and simple choices!

---

## 🚀 Phase 1: Under 60 Seconds to First Sync

### Step 1 — Detect OS & Install Silently
1. Run the installer script silently:
   - **macOS / Linux:** `./install.sh`
   - **Windows (PowerShell):** `.\install.ps1`
2. Verify system readiness in the background:
   ```bash
   .venv/bin/prado doctor --json
   ```

### Step 2 — Ask Only the 2 Essential Questions
Ask the student concisely in their preferred language:
1. **Where would you like to keep your university courses folder?** (Suggest a sensible default like `~/Documents/UGR_Courses`, or their existing university folder if they already have files downloaded).
2. **How would you like your course folders organized?**
   - **Smart Theory vs. Practice** *(Recommended for Engineering, Sciences, Economics)*: Automatically separates lectures (`Teoria/`), labs/assignments (`Practicas/P1..Pn/`), and syllabus (`General/`).
   - **Exact PRADO Mirror** *(Recommended for Law, Medicine, Humanities, Psychology)*: Keeps the exact section folders created by professors on PRADO.

Once they answer, apply their choices in the background:
```bash
.venv/bin/prado onboard --courses-root "<PATH>" --preset <smart|mirror> --no-interactive --no-star --json
```

### Step 3 — Security Reassurance & Native OS Login
1. **Perform a Quick Local Security Audit for the Student:**
   Briefly inspect [`src/prado/auth/credentials.py`](src/prado/auth/credentials.py) and [`src/prado/auth/saml.py`](src/prado/auth/saml.py), then reassure the student in plain language:
   > *"I have verified the source code locally on your computer: your UGR password is saved exclusively inside your operating system's native Keychain (macOS Keychain / Windows Credential Manager / Linux SecretService) and is only ever transmitted directly to the official `idp.ugr.es` server—never to any third party or chat log."*
2. **Trigger the Native OS Login Window (or Offer Direct OS Keychain Entry):**
   - Run the native OS dialog directly so a system login window pops up on their screen:
     ```bash
     .venv/bin/prado auth login --gui --json
     ```
   - *(Note for security-conscious users: if a student prefers to save their password directly using their operating system's built-in tool without typing it into the popup, they can also use macOS Keychain Access / `/usr/bin/security add-generic-password -U -s "prado:sso" -a "email@correo.ugr.es" -w`, Windows Credential Manager `cmdkey /generic:prado:sso /user:email@correo.ugr.es /pass`, or Linux `secret-tool store --label="PradoOS" service prado:sso username email@correo.ugr.es`).*
   - If the login requires a 6-digit email verification code (`exit code 2` / `mfa_required`) and the student didn't enter it in the popup, ask them for the 6-digit code sent to their `@correo.ugr.es` email and complete login in the background:
     ```bash
     .venv/bin/prado auth login --mfa-code <CODE> --json
     ```

### Step 4 — Auto-Discover & Sync Courses
1. Run discovery and sync (with mid-semester adoption enabled so any pre-existing files are matched by SHA-256 without re-downloading):
   ```bash
   .venv/bin/prado sync --adopt --json
   ```
2. Show the student a clean table of their synced courses, how many files were organized, and where their `DASHBOARD.md` and `deadlines.ics` calendar file are located.

---

## ⭐ Post-Sync Milestone: The GitHub Star Loop

Right after the first successful sync:
- Politely ask the student in natural language (without mentioning CLI commands!):
  > *"Your courses are all synced and organized! If this tool saved you time, would you like me to leave a star on the GitHub repository for you?"*
- If they say yes, run `.venv/bin/prado star --json` silently in the background.

---

## ⚡ Phase 2: Optional Power-Ups (Offer Simply in Plain Language)

After the first sync, briefly ask if they'd like you to set up any of these optional conveniences (again, **never show flag or command names** to the student—just ask naturally and run the commands yourself!):
1. **Filter by Lab Subgroup:** Ask if they belong to specific lab groups (e.g. `C2`, `E3`, `A1`) so files from other groups are tucked away into an archive folder. *(Behind the scenes: `.venv/bin/prado onboard --subgroups "ED_C=C2,..." --no-interactive --no-star --json`)*.
2. **Automatic Background Sync:** Ask if they want their courses to sync automatically in the background every 4 hours. *(Behind the scenes: `.venv/bin/prado daemon install --json`)*.
3. **Automatic 2FA Renewal via Email:** Ask if they want automatic 2FA renewal when the 30-day session expires. *(Behind the scenes: `--imap-enabled --imap-host imap.ugr.es`)*.
