# 🎓 UGR PRADO Sync — PradoOS (`ugr-prado-sync`)

**Motor de sincronización y flujo académico para PRADO UGR (`pradogrado`, `pradoposgrado`, `prado.ugr.es`) y Moodle en macOS, Linux y Windows.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform: macOS | Linux | Windows](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-informational)](#)
[![CI Matrix: 100% Passing](https://img.shields.io/badge/CI-Linux%20%7C%20macOS%20%7C%20Windows-brightgreen)](#)

> 🌐 **Idiomas / Languages:** [🇪🇸 Español (Principal)](#-documentación-en-español) | [🇬🇧 English](#-english-documentation)

---

### 🇮🇹 Nota del Autor / Author's Note
> **PradoOS** fue creado por **Lorenzo Vasile**, estudiante siciliano de Ingeniería Informática de la *Università degli Studi di Palermo (UniPa)* actualmente cursando su estancia **Erasmus+** en la *Universidad de Granada (UGR, ETSIIT)*.  
> Nació para resolver un problema cotidiano de todo estudiante: sincronizar de forma autónoma materiales, transparencias, guiones de prácticas y fechas límite de PRADO entre múltiples asignaturas, subgrupos de laboratorio y sistemas operativos, protegiendo siempre los trabajos y modificaciones locales frente a sobrescrituras accidentales.  
> Al estar dirigido principalmente a la comunidad universitaria de la UGR, **el español es el idioma prioritario del proyecto**, contando además con soporte íntegro en inglés para estudiantes internacionales Erasmus+.

---

## 🇪🇸 Documentación en Español

**PradoOS** (`prado`) transforma el portal PRADO UGR (`pradogrado`, `pradoposgrado`, `prado.ugr.es`) en un espacio de trabajo local limpio y auto-actualizado en **macOS**, **Linux Desktop** y **Windows**.

Tanto si estudias en la **ETSIIT** (Ingeniería Informática, Telecomunicaciones), **Derecho**, **Medicina**, **Ciencias**, **Filosofía y Letras** o **Económicas** — o si eres un estudiante **Erasmus+** con asignaturas de diferentes cursos y subgrupos —, PradoOS descubre automáticamente tus asignaturas matriculadas, descarga apuntes y ejercicios, protege tus archivos frente a cambios del profesor y exporta tus entregas a `DASHBOARD.md`, `CHANGELOG.md` y `deadlines.ics`.

### ✨ ¿Por qué PradoOS?

1. **⚡ Dos Modos de Instalación y Configuración:**
   - **Mediante Agente de IA:** Pega el enlace de este repositorio en **Google Antigravity**, **Claude Code**, **Cursor** o **Codex**. El agente leerá [`BOOTSTRAP.md`](BOOTSTRAP.md) y te guiará en tu idioma preferido (español o inglés) en menos de 60 segundos.
   - **CLI 100% Gratuito y Determinista:** No requiere ninguna suscripción de IA ni claves API. Puedes ejecutar `prado onboard` y `prado sync` por terminal de forma totalmente independiente.
2. **🔐 Motor Headless SAML SSO y MFA en 3 Niveles:**
   - **Nivel 1 (Dispositivo de Confianza de 30 días):** Almacena de forma segura la cookie `MFA_TOKEN` con permisos estrictos `0600` (`~/.config/prado/session.json`), solicitando verificación 2FA únicamente una vez al mes.
   - **Nivel 2 (Extracción Automática IMAP SSL):** Detecta automáticamente el código de verificación de 6 dígitos desde tu buzón `@correo.ugr.es` a través de IMAP SSL (o Apple Mail en macOS).
   - **Nivel 3 (Diálogo Nativo del Sistema / Terminal):** Muestra una ventana nativa de inicio de sesión (`prado auth login --gui`) o un prompt seguro por terminal.
3. **🛡️ Protección Anti-Sobrescritura a 4 Cuadrantes y Adopción:**
   - **Jamás pierdas tu trabajo:** PradoOS registra el hash SHA-256 original de cada archivo. Si modificas un notebook `.ipynb`, código `.cpp` o informe `.docx` y el docente sube una nueva versión a PRADO, tu archivo **nunca se sobrescribe**: la actualización del servidor se guarda como `{nombre}_server_{AAAAMMDD_HHMMSS}.{ext}`.
   - **Adopción a mitad de cuatrimestre (`prado sync --adopt`):** ¿Ya descargaste apuntes manualmente desde septiembre? PradoOS calcula los hashes locales y los vincula sin re-descargar duplicados.
4. **🏛️ Adaptado a Cada Facultad (`smart` vs `mirror`):**
   - **Preset `smart` (Ingenierías, Ciencias):** Organiza automáticamente en `Teoria/`, `Practicas/P1..Pn/` y `General/`, archivando subgrupos de laboratorio inactivos en `_subgroups_archive/`.
   - **Preset `mirror` (Derecho, Medicina, Humanidades, Salud):** Mantiene la estructura exacta de secciones de PRADO (`Bloque I`, `Casos Prácticos`, `Jurisprudencia`, `Seminarios`).
5. **🔒 Aislamiento Estricto de Datos y Credenciales:**
   - Las contraseñas residen en el llavero nativo del sistema operativo (`macOS Keychain`, `Windows Credential Manager`, `Linux SecretService`) o en una bóveda cifrada AES con permisos `0600`.
   - La configuración y la base de datos SQLite residen en `~/.config/prado/` (o `%APPDATA%\prado`) — **nunca** dentro de la carpeta sincronizada de asignaturas, permitiéndote subir tus apuntes a Google Drive, iCloud, OneDrive o Git con total seguridad.

---

### 🚀 Inicio Rápido

#### Opción A: Mediante tu Asistente de IA (Antigravity / Claude Code / Codex / Cursor)
Simplemente envía este mensaje a tu asistente de IA:
```text
Instala y configura https://github.com/LorSt4r/ugr-prado-sync siguiendo BOOTSTRAP.md
```
*(El asistente te preguntará en español qué carpeta deseas utilizar y qué estilo de organización prefieres).*

#### Opción B: Instalación por Terminal (Standalone)

**macOS y Linux Desktop:**
```bash
curl -fsSL https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.sh | bash
prado onboard
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.ps1 | iex
prado onboard
```

**Desde clon local:**
```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/prado onboard
```

---

### 🛠️ Referencia de Comandos CLI

Todos los comandos admiten `--help` y `--json`:

```bash
prado onboard                         # Asistente interactivo de bienvenida (en 2 fases)
prado auth login                      # Inicio de sesión mediante SimpleSAMLphp SSO de la UGR
prado auth login --gui                # Abre la ventana nativa de login del sistema operativo
prado auth status                     # Comprueba estado de sesión y token de confianza a 30 días
prado discover                        # Descubrimiento automático de asignaturas en PRADO
prado courses list                    # Lista asignaturas matriculadas y estado activo
prado courses set-preset smart        # Cambia entre organización 'smart' y 'mirror'
prado sync --dry-run                  # Previsualiza la estructura sin descargar en disco
prado sync --adopt                    # Sincroniza asignaturas activas y vincula archivos locales
prado sync --course ED_C              # Sincroniza una única asignatura por código o ID
prado doctor --json                   # Diagnóstico de 9 sondas (red UGR, credenciales, permisos)
prado daemon install --interval 14400 # Demonio de sincronización en segundo plano (cada 4 horas)
prado star                            # Apoya el proyecto con una estrella en GitHub
```

---

## 🇬🇧 English Documentation

**PradoOS** (`prado`) turns your university Moodle / PRADO UGR portal into a clean, self-updating local workspace on **macOS**, **Linux Desktop**, and **Windows**.

Whether you study Computer Engineering at ETSIIT, Law, Medicine, Humanities, or Sciences — or you are an **Erasmus+** student juggling courses across different years and subgroups — PradoOS automatically discovers your enrolled courses, downloads slides and starter notebooks, protects your local work from accidental overwrites, and exports your deadlines to `DASHBOARD.md`, `CHANGELOG.md`, and RFC-5545 `deadlines.ics`.

### ✨ Key Capabilities

1. **⚡ Dual Installation & Onboarding:**
   - **Agent-Mediated Onboarding:** Share this repo with **Google Antigravity**, **Claude Code**, **Cursor**, or **Codex**. The AI agent reads [`BOOTSTRAP.md`](BOOTSTRAP.md) and completes setup in under 60 seconds in your preferred language.
   - **100% Free & Deterministic CLI:** No AI subscription required. Run `prado onboard` and `prado sync` standalone forever.
2. **🔐 3-Tier Headless SAML SSO & MFA Engine:**
   - **Tier 1 (30-Day Device Trust):** Stores Moodle's `MFA_TOKEN` cookie with strict `0600` permissions (`~/.config/prado/session.json`) so 2FA is only requested once every 30 days.
   - **Tier 2 (Zero-Touch IMAP SSL Auto-Fetch):** Automatically extracts 6-digit verification codes from `@correo.ugr.es` via IMAP SSL (or macOS Apple Mail).
   - **Tier 3 (Native GUI / Interactive TTY):** Pops up a native OS login dialog (`prado auth login --gui`) or a secure terminal prompt.
3. **🛡️ 4-Quadrant Overwrite Protection & Mid-Semester Adoption:**
   - **Never Lose Your Work:** PradoOS tracks original SHA-256 hashes. Modified `.ipynb` notebooks, `.cpp` source files, or `.docx` reports are never overwritten: professor updates are saved as `{name}_server_{YYYYMMDD_HHMMSS}.{ext}`.
   - **Mid-Semester Adoption (`prado sync --adopt`):** Already downloaded course materials? PradoOS indexes existing files and avoids duplicate downloads.
4. **🏛️ Built for Every Faculty (`smart` vs `mirror`):**
   - **`smart` Preset (Engineering, STEM):** Routes into `Teoria/`, `Practicas/P1..Pn/`, and `General/`, archiving unused lab subgroups in `_subgroups_archive/`.
   - **`mirror` Preset (Law, Medicine, Humanities):** Preserves the exact section titles from PRADO.
5. **🔒 Strict Credential & Data Isolation:**
   - Passwords stay in the native OS Keychain (`macOS Keychain`, `Windows Credential Manager`, `Linux SecretService`) or an encrypted `0600` vault.
   - Configuration lives in `~/.config/prado/` (or `%APPDATA%\prado`) — never inside your synced courses folder.

---

### 🚀 Quick Start (English)

**Prompt for AI Coding Agents:**
```text
Install and configure https://github.com/LorSt4r/ugr-prado-sync for me following BOOTSTRAP.md
```

**Terminal Installation:**
```bash
# macOS & Linux:
curl -fsSL https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.sh | bash
prado onboard

# Windows (PowerShell):
irm https://raw.githubusercontent.com/LorSt4r/ugr-prado-sync/main/install.ps1 | iex
prado onboard
```

---

## ⭐ Support & License

Si **PradoOS** te ayuda a ahorrar tiempo durante el cuatrimestre, apoya el repositorio con una estrella en GitHub (`prado star`)!  
If **PradoOS** saves you time during your university semester, please consider starring the repository on GitHub (`prado star`)!

Distribuido bajo la **Licencia MIT** — Desarrollado por **Lorenzo Vasile**.
Distributed under the **MIT License** — Created by **Lorenzo Vasile**.
