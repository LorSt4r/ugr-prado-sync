# 🎓 UGR PRADO Sync — PradoOS (`ugr-prado-sync` / `prado-os`)

**Autonomous, Cross-Platform Academic Workflow Engine for Moodle & PRADO UGR (`pradogrado`, `pradoposgrado`, `prado.ugr.es`)**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform: macOS | Linux | Windows](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-informational)](#)

> 🌐 **Languages / Idiomas:** [🇬🇧 English](#-english-documentation) | [🇪🇸 Español](#-documentación-en-español)

---

## 🇬🇧 English Documentation

**PradoOS** (`prado`) turns your university Moodle / PRADO UGR portal into a clean, self-updating local workspace on **macOS**, **Linux Desktop**, and **Windows**.

Whether you study Computer Engineering at ETSIIT, Law, Medicine, Humanities, or Sciences — or you are an **Erasmus+** student juggling courses across different years and subgroups — PradoOS automatically discovers your enrolled courses, downloads slides and starter notebooks, protects your local work from accidental overwrites, and exports your deadlines to `DASHBOARD.md`, `CHANGELOG.md`, and RFC-5545 `deadlines.ics`.

### ✨ Why PradoOS?

1. **⚡ Two Ways to Install & Onboard:**
   - **Agent-Mediated (OpenClaw Style):** Paste this repository URL into **Google Antigravity**, **Claude Code**, **Cursor**, or **Codex**. The AI agent reads [`BOOTSTRAP.md`](BOOTSTRAP.md) and `.agents/skills/prado-os/SKILL.md` and sets everything up for your OS in under 60 seconds.
   - **100% Free & Deterministic CLI:** No AI subscription required. Run `prado onboard` and `prado sync` standalone forever, with optional Bring-Your-Own-AI (`Ollama`, `DeepSeek`, `Gemini`, `OpenAI`) if you want AI forum summaries later.
2. **🔐 3-Tier Headless SAML SSO & MFA Engine:**
   - **Tier 1 (30-Day Device Trust):** Persists Moodle's `MFA_TOKEN` cookie with strict `0600` permissions (`~/.config/prado/session.json`) so you only verify 2FA once every 30 days.
   - **Tier 2 (Zero-Touch IMAP / Apple Mail Auto-Fetch):** Automatically extracts the 6-digit verification code from your `@correo.ugr.es` inbox via cross-platform `imaplib.IMAP4_SSL` (or macOS Apple Mail).
   - **Tier 3 (Interactive TTY / Agent `--json` Protocol):** Clean terminal prompt or structured exit code `2` (`mfa_required`) for AI agents.
3. **🛡️ 4-Quadrant Overwrite Protection & Mid-Semester Adoption:**
   - **Never Lose Your Work:** PradoOS tracks the original SHA-256 hash of every downloaded file. If you edit a `.ipynb` notebook, `.cpp` file, or `.docx` report and the professor uploads a revised version, your file is **never overwritten** — the professor's update is saved alongside as `{name}_server_{YYYYMMDD_HHMMSS}.{ext}`.
   - **Mid-Semester Adoption (`prado sync --adopt`):** Already downloaded files manually since September? PradoOS hashes your existing folder and links matching server files with zero duplicate downloads.
4. **🏛️ Built for Every Faculty (`smart` vs `mirror` Presets):**
   - **`smart` Preset:** Routes materials into `Teoria/`, `Practicas/P1..Pn/`, and `General/` while archiving inactive lab subgroups (`_subgroups_archive/C1_C3/`).
   - **`mirror` Preset:** Preserves the exact Moodle section hierarchy (`Bloque I`, `Casos Clínicos`, `Jurisprudencia`, `Seminarios`) for Law, Medicine, Humanities, and Social Sciences.
5. **🔒 Strict Credential & Data Separation:**
   - Passwords live in your native OS Keychain (`macOS Keychain`, `Windows Credential Manager`, `Linux SecretService`) or an AES-encrypted `0600` vault.
   - Config and SQLite state live in `~/.config/prado/` (or `%APPDATA%\prado`) — **never** inside your synced courses folder, so you can safely back up your courses to Google Drive, iCloud, OneDrive, or Git.

---

### 🚀 Quick Start

#### Option A: Paste to Your AI Coding Agent (Antigravity / Claude Code / Codex)
Send this prompt to your agent:
```text
Install and configure https://github.com/LorSt4r/ugr-prado-sync for me following BOOTSTRAP.md
```

#### Option B: Standalone Terminal Installation

**macOS & Linux Desktop:**
```bash
curl -fsSL https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.sh | bash
prado onboard
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.ps1 | iex
prado onboard
```

**From a Local Clone:**
```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/prado onboard
```

---

### 🛠️ CLI Command Reference

Every command supports `--help` and `--json`:

```bash
prado onboard                         # 2-Phase interactive setup wizard
prado auth login                      # Authenticate via UGR SimpleSAMLphp SSO
prado auth status                     # Check session validity and 30-day MFA trust tokens
prado discover                        # Auto-discover enrolled courses on PRADO
prado courses list                    # List cached courses and active status
prado courses set-preset mirror       # Switch between 'smart' and 'mirror' routing
prado sync --dry-run                  # Preview planned folder tree without writing to disk
prado sync --adopt                    # Sync all active courses & adopt existing local files
prado sync --course ED_C              # Sync a single course by slug or ID
prado doctor --fix                    # Run 9 diagnostic probes & repair 0700/0600 permissions
prado daemon install --interval 14400 # Install background sync every 4h (launchd/systemd/schtasks)
prado star                            # Star PradoOS on GitHub via `gh` CLI or browser
```

---

## 🇪🇸 Documentación en Español

**PradoOS** (`prado`) transforma PRADO UGR (`pradogrado`, `pradoposgrado`, `prado.ugr.es`) en un espacio de trabajo local siempre actualizado en **macOS**, **Linux Desktop** y **Windows**.

### ✨ Características Principales

1. **Instalación Dual (Con Agente IA o 100% Gratuita por Terminal):**
   - **Mediante Agente IA (Estilo OpenClaw):** Pega el enlace del repositorio en **Antigravity**, **Claude Code**, **Cursor** o **Codex** y el agente te guiará paso a paso leyendo [`BOOTSTRAP.md`](BOOTSTRAP.md).
   - **CLI Independiente y Determinista:** Funciona al 100% sin suscripciones de IA ni claves API.
2. **Autenticación Headless SAML SSO y MFA en 3 Niveles:**
   - **Nivel 1 (Confianza de 30 días):** Guarda el token `MFA_TOKEN` con permisos `0600` para no pedir código 2FA en cada sincronización.
   - **Nivel 2 (Auto-extracción IMAP SSL):** Lee automáticamente el código de 6 dígitos desde `imap.ugr.es` (`@correo.ugr.es`).
   - **Nivel 3 (Terminal / JSON):** Pide el código de 6 dígitos por terminal cuando sea necesario.
3. **Protección Anti-Sobrescritura y Adopción a Mitad de Cuatrimestre:**
   - Si modificas un archivo local (`.ipynb`, `.cpp`, `.docx`, `.pdf`) y el profesor sube una nueva versión en PRADO, **PradoOS jamás sobrescribe tu trabajo**: guarda la versión del servidor como `{nombre}_server_{AAAAMMDD_HHMMSS}.{ext}`.
   - Usa `prado sync --adopt` si ya tienes carpetas descargadas manualmente: PradoOS calcula el hash SHA-256 y las vincula sin volver a descargarlas.
4. **Adaptado a Todas las Facultades (`smart` vs `mirror`):**
   - **`smart`:** Organiza automáticamente en `Teoria/`, `Practicas/P1..Pn/` y `General/`, archivando otros subgrupos de prácticas en `_subgroups_archive/`.
   - **`mirror`:** Respeta exactamente los nombres de las secciones de PRADO (`Bloque I`, `Casos Prácticos`, `Jurisprudencia`, `Casos Clínicos`).

---

## ⭐ Support & License

If **PradoOS** saves you time during the semester, please consider giving the repository a star on GitHub (`prado star`)!  
Released under the **MIT License** — Created by **Lorenzo Vasile**.
