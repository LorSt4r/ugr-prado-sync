# 🎓 PradoOS — AI Agent Bootstrap Playbook (`BOOTSTRAP.md`)

Welcome, AI Coding Assistant (**Antigravity**, **Claude Code**, **Cursor**, **Codex**, or **Windsurf**)!
A student has shared this repository with you so you can autonomously install, configure, and tailor **PradoOS (`ugr-prado-sync`)** to their operating system (macOS, Windows, or Linux Desktop) and academic faculty.

---

## 🌐 Language Priority & Adaptive Onboarding

- **Spanish is the primary language of PradoOS and UGR**: By default, greet the student and conduct the onboarding in **Spanish** if they write in Spanish, mention UGR, or have a `@correo.ugr.es` account.
- **Adaptive Multi-Language Support**:
  1. At the very first turn, greet the student and either detect their language from their initial prompt or ask whether they prefer **Español** or **English** (or their native tongue).
  2. If the student writes in English or requests English, conduct all explanations, questions, and summaries in **English**.
  3. If the student prefers another native language (e.g., Italian, German, French), conduct the onboarding in their native tongue and configure the setup accordingly, defaulting to English if technical terms are clearer.
- **Golden UX Rule: Zero CLI Jargon to the Student**:
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

### Step 2 — Language Check & The 2 Essential Questions
Greet the student warmly in their preferred language (defaulting to Spanish for UGR, or English for international students) and ask only:
1. **Where would you like to keep your university courses folder?**
   - *ES:* ¿Dónde te gustaría guardar la carpeta de tus asignaturas? (Ej. `~/Documents/UGR_Courses`, o tu carpeta actual si ya tienes apuntes descargados).
   - *EN:* Where would you like to keep your university courses folder? (e.g. `~/Documents/UGR_Courses`, or your existing folder if you already have files).
2. **How often would you like me to check PRADO for new materials or deadlines?**
   - *ES:* ¿Cada cuánto tiempo deseas que revise automáticamente nuevos materiales o entregas en PRADO? *(Recomendado: 3 veces al día — ej. 08:30, 14:00 y 20:00 — o cada 4 horas)*.
   - *EN:* How often should I check PRADO for new slides, lab tasks, or deadlines? *(Recommended: 3 times a day — e.g. 08:30, 14:00, 20:00 — or every 4 hours)*.

*(Note for AI Agents: In this agent-mediated setup, apply the **Smart Theory vs Practice** (`smart`) preset by default (`--preset smart`), because as an AI agent you can intelligently curate files into `Teoria/` and `Practicas/P1..Pn/` while checking syllabus and archiving inactive subgroups. Only use `mirror` if the student specifically requests an exact 1:1 replica of PRADO's layout).*

Once they answer, apply their choices in the background:
```bash
.venv/bin/prado onboard --courses-root "<PATH>" --preset smart --no-interactive --no-star --json
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

### Step 5 — Configure Autonomous Agent Automation (Based on Your AI Assistant)
Based on the student's preferred frequency chosen in Step 2, set up recurring background sync according to your agent environment:

1. **In Google Antigravity:**
   - Suggest or trigger the `/automation` slash command or `schedule` tool (e.g., cron `0 8,14,20 * * 1-5` or every 4 hours) to run `.venv/bin/prado sync --adopt --json` in background and alert the student in chat only when new materials or deadlines are detected.
2. **In Claude Code (`claude` CLI):**
   - Claude Code executes headlessly via `-p` / `--print`.
   - Configure a recurring task or cron script running:
     ```bash
     claude -p "Run .venv/bin/prado sync --adopt --json, review DASHBOARD.md and CHANGELOG.md, and alert me only if there are new materials, urgent forum posts, or deliverables in the next 3 days." --allowedTools "Bash,Read"
     ```
3. **In OpenAI Codex / Cursor / Terminal Agents:**
   - Install the native OS background daemon:
     ```bash
     .venv/bin/prado daemon install --interval 14400 --json
     ```
     *(Installs macOS `launchd`, Linux `systemd --user`, or Windows `schtasks` running 24/7 even when IDE/terminal is closed)*.
   - Save a prompt template in `.agents/prompts/daily-check.md` for the agent.
4. **Direct Google Calendar API Push:**
   - If the student uses Google Calendar, run:
     ```bash
     .venv/bin/prado gcalendar --json
     ```
     *(Automatically detects their university calendar and syncs deadlines with tiered popup alarms: 3d/1d/2h for exams, 2d/1d/3h for assignments)*.

---

## ⭐ Post-Sync Milestone: The GitHub Star Loop

Right after the first successful sync:
- Politely ask the student in natural language (without mentioning CLI commands!):
  > *"Your courses are all synced and organized! If this tool saved you time, would you like me to leave a star on the GitHub repository for you?"*
- If they say yes, run `.venv/bin/prado star --json` silently in the background.

---

## ⚡ Phase 2: Personalización Sartorial de Élite (Concierge Académico Personal)

Una vez completada la primera sincronización de base, **no te detengas aquí**. Como asistente de IA (Antigravity, Claude Code, Cursor, Codex), tu verdadero valor añadido es transformar este entorno en un **Concierge Académico Personal de élite**, tal como el creador de PradoOS diseñó para optimizar al máximo su tiempo y rendimiento en la UGR.

Presenta al estudiante de forma cercana y entusiasta estas personalizaciones avanzadas, ofreciéndote a configurarlas paso a paso:

1. **📅 Horario Semanal y Bloques de Estudio Inteligentes (Google Calendar Deep Work):**
   - Pregunta al estudiante su horario semanal de clases y laboratorios (ej. *"¿Qué días y a qué horas tienes clases presenciales?"*).
   - Con esos datos, tu agente calcula sus huecos libres reales entre clases (ej. mañanas libres de los lunes o tardes sin docencia) y programa bloques automáticos de estudio diario (*"📚 [ESTUDIO ...]"*) con aviso previo en Google Calendar (`prado gcalendar`).
2. **🏛️ Fusión y Alias de Cursos Teórico-Prácticos (Course Aliasing):**
   - En facultades como la ETSIIT, muchas asignaturas tienen dos portales en PRADO: uno general (*COMÚN*) para transparencias de teoría y otro específico de prácticas (*Grupo E, C, B*).
   - Pregunta si desea fusionarlos en una única carpeta local unificada (ej. unificar *Sistemas Operativos COMÚN* y *Sistemas Operativos Grupo E* en `SO_E/`), manteniendo apuntes y guiones juntos sin carpetas redundantes.
3. **📊 Ponderación de Evaluaciones y Metas Académicas:**
   - Pregunta los porcentajes de evaluación de sus asignaturas (ej. 60% examen de teoría, 35% proyecto final en equipo, 15% problemas) y sus metas académicas.
   - Esto te permitirá priorizar las cuentas regresivas y enfocar las sesiones de estudio donde el impacto matemático sobre la nota final sea máximo.
4. **🧪 Filtro Quirúrgico de Subgrupos de Laboratorio:**
   - Pregunta a qué subgrupos pertenece (ej. `C2`, `E3`, `A1`) para archivar limpiamente los enunciados de otros subgrupos en `_subgroups_archive/` y mantener la carpeta principal impecable. *(Se aplica en segundo plano con `.venv/bin/prado onboard --subgroups "ED_C=C2,..." --no-interactive --no-star --json`)*.
5. **👤 Creación del Perfil Permanente `USER.md`:**
   - Guarda todas estas preferencias en un archivo local `USER.md` (tomando como referencia `USER.md.example`). Al estar registrado en `.gitignore`, sus datos y notas jamás se compartirán en Git, pero tú y cualquier sesión futura de IA recordaréis exactamente quién es el estudiante, su horario y sus metas académicas.
