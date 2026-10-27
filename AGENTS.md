# 🧠 AGENTS.md — PradoOS Operational Manifesto & Agent Protocol

**Project:** PradoOS (`prado-os`, CLI binary: `prado`)  
**Supported Platforms:** macOS, Linux Desktop (Ubuntu, Fedora, Arch, Debian), Windows 10/11  
**Supported LMS:** PRADO Universidad de Granada (`pradogrado`, `pradoposgrado`, `prado.ugr.es`) & Moodle 4.x  

---

## 1. Purpose & Design Philosophy

PradoOS is an open-source academic workflow engine built for two complementary modes of operation:
1. **Agent-Mediated Mode:** When a student gives this repository URL to an AI coding agent (Antigravity, Claude Code, Codex, Cursor), the agent reads [`BOOTSTRAP.md`](BOOTSTRAP.md) and `.agents/skills/prado-os/SKILL.md` to guide the student through setup and daily academic management.
2. **100% Free & Deterministic Standalone CLI:** Every feature works deterministically without any paid AI subscription or external API keys via the `prado` command-line interface. Optional BYO-AI providers (`Ollama` local models, `DeepSeek`, `Gemini`, `OpenAI`) can be enabled in `config.yaml` if desired.

---

## 2. Strict Security & Data Isolation Invariants

When operating or extending PradoOS, all agents MUST uphold these non-negotiable invariants:
1. **Strict Separation of Course Data and Credentials:**
   - Configuration (`config.yaml`), session cookies (`session.json`), encrypted fallback vaults (`credentials.vault`), and the SQLite state database (`state.db`) MUST live exclusively inside the OS user configuration directory (`~/.config/prado/` on macOS/Linux with `0700` dir / `0600` file permissions, or `%APPDATA%\prado` on Windows).
   - **Never** write credentials, cookies, or `.db` files inside the student's synced courses folder (`courses_root`), which is frequently backed up to Google Drive, iCloud, OneDrive, or Git.
2. **Zero Plaintext Passwords in Agent Context:**
   - Never ask a student to paste their institutional password into an AI chat window.
   - Always use interactive TTY input (`prado auth login` or `prado onboard`) or the native OS keyring (`macOS Keychain`, `Windows Credential Manager`, `Linux SecretService / libsecret`).
3. **4-Quadrant Student Overwrite Protection:**
   - PradoOS tracks the original SHA-256 hash (`original_hash`) of every downloaded file in `state.db`.
   - If a student modifies a local file (`.ipynb`, `.cpp`, `.docx`, `.pdf` annotations) and the professor uploads a new version on PRADO, **never overwrite the student's work**. Save the professor's updated version alongside as `{stem}_server_{YYYYMMDD_HHMMSS}{ext}`.

---

## 3. Machine-Readable `--json` CLI Contract

Every `prado` subcommand supports `--json` for deterministic agent orchestration:

| Command | Purpose | Exit Codes |
|---|---|---|
| `prado onboard --json` | Non-interactive Phase 1 & Phase 2 configuration | `0` OK, `1` Error |
| `prado auth status --json` | Inspect session validity, 30d MFA trust tokens, and stored credentials | `0` OK, `1` Error |
| `prado auth login --mfa-code <6-digit> --json` | Complete SAML SSO + Tier 3 MFA verification | `0` OK, `1` Error, `2` MFA Required |
| `prado discover --json` | Auto-discover enrolled courses via Moodle AJAX + DOM fallback | `0` OK, `1` Error, `2` MFA Required |
| `prado courses [list\|enable\|disable\|set-preset] --json` | Manage active courses and folder routing preset (`smart` vs `mirror`) | `0` OK, `1` Error |
| `prado sync [--course ID] [--dry-run] [--adopt] --json` | Synchronize courses, adopt existing files, and export `DASHBOARD.md`, `CHANGELOG.md`, `deadlines.ics` | `0` OK, `1` Error, `2` MFA Required |
| `prado doctor [--fix] --json` | Execute 9 health probes and optionally repair file permissions | `0` Healthy, `1` Issues Detected |
| `prado daemon [install\|uninstall\|status] --json` | Manage OS background scheduler (`launchd`, `systemd`, `schtasks`) | `0` OK, `1` Error |
| `prado star --json` | Star `LorSt4r/ugr-prado-sync` via `gh api` or browser | `0` OK |

---

## 4. Onboarding & User Context

- If `USER.md` does not exist in the workspace, follow [`BOOTSTRAP.md`](BOOTSTRAP.md) to onboard the student.
- Optionally copy [`USER.md.example`](USER.md.example) to `USER.md` (which is git-ignored) to remember the student's degree, faculty preset, and preferred language locally.
