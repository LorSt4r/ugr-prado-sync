# 🎓 UGR PRADO Sync — PradoOS (`ugr-prado-sync`)

**El motor de sincronización y flujo académico inteligente para PRADO UGR (`pradogrado`, `pradoposgrado`, `prado.ugr.es`) y Moodle.**  
*Disponible para macOS, Linux Desktop y Windows.*

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform: macOS | Linux | Windows](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-informational)](#)
[![Tests: 707 Passing](https://img.shields.io/badge/tests-707%20passed-brightgreen)](#)
[![CI Matrix: 100% Passing](https://img.shields.io/badge/CI-Linux%20%7C%20macOS%20%7C%20Windows-brightgreen)](#)

> 🌐 **Idiomas / Languages:** [🇪🇸 Español (Principal)](#-documentación-en-español) | [🇬🇧 English](#-english-documentation)

---

## 👥 Autoría y AI Disclosure

### 🇮🇹 De una Necesidad Real en Granada a un Proyecto Open-Source
**PradoOS** fue desarrollado por **Lorenzo Vasile**, estudiante de Ingeniería Informática de la *Università degli Studi di Palermo (UniPa)* durante su estancia **Erasmus+** en la *Universidad de Granada (UGR, ETSIIT)* (Curso 2026/2027).  
Al compaginar múltiples asignaturas de distintos departamentos (Estructura de Datos, Modelos de Computación, Visión por Computador, Teoría de la Información y Sistemas Operativos), surgió la necesidad de optimizar el tiempo de estudio y **eliminar por completo las pérdidas de tiempo manuales**: descargar PDFs uno a uno, revisar foros repetitivamente, reorganizar carpetas y vigilar fechas de entrega dispersas.

### 🤖 AI Disclosure & Proceso de Desarrollo
Este proyecto fue diseñado e implementado mediante pair programming asistido por inteligencia artificial con **Google Antigravity**:
- **Lorenzo Vasile**: concepción del proyecto, definición de requisitos funcionales y de seguridad (aislamiento de credenciales en el Llavero nativo, flujo SAML/MFA sin contraseñas en texto plano, protección anti-sobrescritura) y validación en entornos reales (**macOS** y **Arch Linux**).
- **Stack de IA (Google Antigravity)**: se utilizó **Gemini 4 Argon** para el diseño de la arquitectura modular, análisis de seguridad y verificación, y **Gemini 3.8 Flash** para la generación ágil de código, la suite de tests automatizados (707 tests) y los pipelines de CI multiplataforma.

---

## 🇪🇸 Documentación en Español

### 💡 ¿Qué hace PradoOS por ti? (Sencillo, Claro e Impactante)

Si estudias en la Universidad de Granada, PradoOS resuelve en segundo plano todo lo que antes hacías a mano:

1. 📥 **Tus asignaturas siempre al día en tu ordenador, sin mover un dedo:**  
   PradoOS detecta automáticamente todas las asignaturas en las que estás matriculado en PRADO (`pradogrado`, `pradoposgrado` o `ceprud`) y descarga transparencias, apuntes y guiones de prácticas a tu carpeta local.
2. 🛡️ **Jamás pierdes ni se sobrescribe tu trabajo:**  
   Si resuelves una práctica, modificas un notebook `.ipynb` o compilas código `.cpp` y más tarde el profesor sube una corrección a PRADO, **tu archivo nunca se borra ni se sobreescribe**. PradoOS detecta tu modificación mediante hash SHA-256 y guarda la versión del profesor al lado como `{archivo}_server_{fecha}.ext`.
3. 📅 **Tus entregas y exámenes directos a Google Calendar:**  
   Olvídate de revisar PRADO para ver cuándo vence una tarea. PradoOS envía tus fechas límite directamente a tu Google Calendar universitario (`ETSIIT Granada` o calendario principal) con alarmas popup inteligentes: **3 días, 1 día y 2 horas antes para exámenes**; **2 días, 1 día y 3 horas antes para prácticas**.
4. 🔑 **Sin pedirte la contraseña todos los días:**  
   Gracias a su soporte del token de dispositivo de confianza (`MFA_TOKEN`), solo introduces tu segundo factor una vez cada 30 días. Tu contraseña se guarda en el Llavero nativo de tu sistema operativo (macOS Keychain, Windows Credential Manager o Linux SecretService), jamás en texto plano.
5. 📂 **Organización impecable según tu facultad:**  
   Elige entre una réplica exacta de las secciones de PRADO (`mirror`) o un árbol inteligente que separa `Teoria/`, `Practicas/P1..Pn/` y `General/` archivando subgrupos de prácticas que no te corresponden (`smart`).

---

### 🚀 Inicio Rápido

#### Opción A: Mediante Asistente de IA (Antigravity, Claude Code, Cursor, Codex)
Pega este mensaje en tu asistente de programación con IA:
```text
Instala y configura https://github.com/LorSt4r/ugr-prado-sync siguiendo BOOTSTRAP.md
```
*El agente leerá [`BOOTSTRAP.md`](BOOTSTRAP.md), te hablará en tu idioma preferido (español o inglés) y completará la configuración inicial en menos de 60 segundos.*

#### Opción B: Instalación Tradicional por Terminal (100% Determinista, sin IA)

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

*(Si ejecutas `prado` sin argumentos en tu terminal, se abrirá un menú interactivo con opciones numeradas del 1 al 7).*

---

### 🛠️ Comandos Principales de la CLI

Todos los comandos admiten `--help` y formato estructurado `--json`:

| Comando | Qué hace |
|---|---|
| `prado onboard` | Asistente de configuración inicial interactivo en 2 fases. |
| `prado sync --adopt` | Sincroniza materiales, detecta archivos existentes locales y actualiza `DASHBOARD.md`. |
| `prado gcalendar` | Sincroniza directamente las entregas y exámenes con Google Calendar API. |
| `prado sync --gcalendar` | Descarga materiales nuevos y empuja las fechas al calendario en un único paso. |
| `prado auth login --gui` | Abre la ventana emergente nativa del sistema operativo para iniciar sesión. |
| `prado auth status` | Comprueba la validez de la sesión y el estado del token de confianza a 30 días. |
| `prado discover` | Lista todas las asignaturas matriculadas detectadas en PRADO. |
| `prado doctor --json` | Diagnóstico de salud: comprueba red UGR, credenciales, permisos y dependencias. |
| `prado daemon install` | Instala un servicio en segundo plano para sincronizar cada 4 horas (`launchd`/`systemd`/`schtasks`). |
| `prado star` | Deja una estrella al repositorio en GitHub si la herramienta te ha sido útil. |

---

### 🔬 Especificaciones Técnicas y Arquitectura Interna (Deep Dive)

Para desarrolladores, administradores de sistemas o estudiantes que deseen conocer las tripas técnicas del motor:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           ARQUITECTURA PRADOOS                          │
└─────────────────────────────────────────────────────────────────────────┘
   [ Usuario / Agente IA ]
              │
              ▼
   [ CLI Engine: prado ]  (Click/Argparse, protocol --json universal, menús TUI)
              ├───► [ Auth & 3-Tier SAML Engine ]
              │       ├── UgrSamlDriver: Redirección HTTP headless con IdP SimpleSAMLphp
              │       ├── Tier 1: Persistencia de cookie MFA_TOKEN (Trust 30 días)
              │       ├── Tier 2: Extracción automática de código 2FA vía IMAP SSL (imap.ugr.es)
              │       └── Tier 3: Diálogo nativo GUI (prompt_gui_input) o TTY interactivo
              │
              ├───► [ Security & Isolation Layer ]
              │       ├── CredentialStore: Keyring nativo (Security / CredMgr / SecretService)
              │       ├── Bóveda AES-256 fallback con permisos estrictos 0600
              │       └── Separación total: config en ~/.config/prado, NUNCA en la carpeta de apuntes
              │
              ├───► [ Safe Downloader & 4-Quadrant Overwrite Protection ]
              │       ├── Streaming en chunks de 64 KB con hash SHA-256 sobre archivos temporales
              │       ├── Reemplazo atómico con backoff ante bloqueos NTFS de Windows
              │       └── Matriz de Colisiones:
              │             • Q1 (Local = Server): Sin acción.
              │             • Q2 (Local nuevo, Server nuevo): Descarga y registra hash.
              │             • Q3 (Estudiante modificó, Server igual): Protege trabajo local.
              │             • Q4 (Estudiante modificó, Server modificó): Conserva trabajo local y
              │               guarda actualización como {nombre}_server_{AAAAMMDD_HHMMSS}.{ext}
              │
              ├───► [ Exporters & Calendar Sync Engine ]
              │       ├── GoogleCalendarSync: REST API v3 con OAuth2 auto-refresh (stdlib urllib puro)
              │       ├── CalendarExporter: deadlines.ics estándar RFC-5545 con VALARMs a scaglioni
              │       ├── DashboardExporter: DASHBOARD.md con cuenta regresiva en vivo
              │       └── ChangelogExporter: Historial cronológico con hash SHA-256 en CHANGELOG.md
              │
              └───► [ Diagnostics & Background Daemons ]
                      ├── Doctor: 9 sondas de verificación (idp.ugr.es, pradogrado, permisos 0700/0600)
                      └── DaemonManager: macOS launchd, Linux systemd --user / cron, Windows schtasks
```

- **Manejo Seguro del Sistema Operativo:** Las carpetas y archivos sensibles (`config.yaml`, `session.json`, `state.db`) se crean forzando permisos POSIX `0700` y `0600` incluso bajo umasks permisivas (`0000`). En Windows NTFS, las operaciones de reemplazo atómico cuentan con un bucle de reintento con backoff exponencial para absorber cerrojos transitorios de lectura.
- **Sin Dependencias de Red Pesadas para Calendario:** La sincronización con Google Calendar no requiere librerías externas de Google de cientos de megabytes; se comunica directamente con la API REST v3 mediante `urllib.request` y gestiona el flujo de `refresh_token` de forma nativa.
- **Suite de Pruebas Opaque-Box y Adversarial:** Cuenta con 707 tests automatizados en `pytest` que verifican desde ataques de path traversal en nombres de secciones hasta árboles de carpetas anidados a 15 niveles de profundidad y condiciones de carrera multiproceso.

---

## 🇬🇧 English Documentation

### 💡 What Does PradoOS Do for You?

PradoOS turns your university Moodle / PRADO UGR portal into an automated, self-updating local workspace on **macOS**, **Linux Desktop**, and **Windows**:

1. 📥 **Zero Manual Downloads:** Auto-discovers all your enrolled courses and synchronizes slides, lecture notes, code templates, and assignment briefs directly to your machine.
2. 🛡️ **Zero Overwrites Guarantee:** Your work is sacred. If you edit a Jupyter Notebook (`.ipynb`), write code (`.cpp`, `.py`), or modify a report (`.docx`), PradoOS tracks original SHA-256 hashes and **never overwrites your local edits**. Professor updates are stored side-by-side as `{name}_server_{timestamp}.{ext}`.
3. 📅 **Direct Google Calendar Integration:** Pushes deadlines and exam milestones directly to your Google Calendar with tiered popup reminders (3d/1d/2h for exams, 2d/1d/3h for assignments).
4. 🔑 **30-Day Device Trust:** Enter your 2FA verification code once a month. Passwords live strictly in your operating system's Keychain—never in plaintext.
5. 📂 **Faculty-Tailored Routing:** Choose between exact Moodle section replicas (`mirror`) or an intelligent STEM layout separating `Teoria/`, `Practicas/P1..Pn/`, and `General/` while archiving other lab subgroups (`smart`).

---

### 🚀 Quick Start (English)

#### Option A: Via AI Assistant (Antigravity, Claude Code, Cursor, Codex)
Send this prompt to your AI assistant:
```text
Install and configure https://github.com/LorSt4r/ugr-prado-sync for me following BOOTSTRAP.md
```

#### Option B: Standalone Terminal Installation

```bash
# macOS & Linux Desktop:
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
