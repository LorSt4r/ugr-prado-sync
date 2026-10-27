# Project: PradoOS (`prado-os`)

A production-ready, cross-platform (macOS, Linux Desktop, Windows) open-source academic workflow engine for Moodle / PRADO UGR (`pradogrado`, `pradoposgrado`, `prado.ugr.es`, and generic Moodle instances). Supports both Agent-Mediated Onboarding (`BOOTSTRAP.md`, `AGENTS.md`, `CLAUDE.md`, `.agents/skills/prado-os/SKILL.md`, `USER.md`) and a 100% Free & Deterministic Standalone CLI (`prado onboard`, `prado sync`, `prado discover`, `prado doctor`, `prado daemon`, `prado star`) with optional local/external LLM integration (Ollama, DeepSeek, Gemini, OpenAI).

---

## Architecture

### Component Diagram & Data Flow
```
User / AI Agent (Terminal / IDE)
        │
        ▼
   [ prado CLI ] (Click/Argparse, universal --json and --help)
   ├── onboard, auth, discover, courses, sync, doctor, daemon, star
        │
        ├──► [ Config & Credential Layer ]
        │     ├── OS User Config (~/.config/prado or %APPDATA%/prado, mode 0700/0600)
        │     ├── CredentialStore (Keyring: macOS Keychain / Windows CredMgr / Linux SecretService, fallback encrypted/0600)
        │     └── SessionManager (MoodleSession, persistent 30-day MFA_TOKEN device trust)
        │
        ├──► [ Auth & 3-Tier MFA Engine ]
        │     ├── UgrSamlDriver (Headless SimpleSAMLphp HTTP dance with IdP redirect & SAMLResponse extraction)
        │     ├── Tier 1: 30-day MFA_TOKEN cookie reuse (zero network prompts)
        │     ├── Tier 2: Cross-platform imaplib.IMAP4_SSL auto-fetch (with macOS AppleScript fallback)
        │     └── Tier 3: Interactive TTY prompt or Non-interactive --json agent protocol (exit code 2)
        │
        ├──► [ Discovery & Parser Engine ]
        │     ├── CourseDiscovery (Moodle AJAX core_course_get_enrolled_courses + DOM fallback)
        │     └── CourseHtmlParser (Sections li#section-N, mod/resource, mod/folder, mod/assign, mod/forum, mod/url)
        │
        ├──► [ Storage, Downloader & Adoption ]
        │     ├── Router (PRADO Mirror vs Smart Theory/Practice for STEM and non-STEM faculties)
        │     ├── SafeDownloader (Atomic 64KB chunked streaming to .prado_tmp_*, live SHA-256, atomic replace)
        │     ├── Mid-Semester Adoption (Pre-scan local files by (sha256, size) to avoid redownloads)
        │     ├── OverwriteProtection (4-quadrant collision matrix; student-modified files never overwritten, server updates saved as _server_YYYYMMDD_HHMMSS)
        │     └── StateDb (SQLite tracking files, original hashes, URLs, modtimes, student edits)
        │
        ├──► [ Exporters & Notification Engine ]
        │     ├── MarkdownExporters (DASHBOARD.md countdowns, CHANGELOG.md timeline)
        │     ├── CalendarExporter (RFC-5545 deadlines.ics with tiered VALARMs: 3d/1d/2h exams, 2d/1d/3h assignments)
        │     └── NotificationDispatcher (Multi-OS Desktop notifications, Telegram, Discord, SMTP)
        │
        ├──► [ Optional BYO-AI Layer ]
        │     └── AIProvider (Pluggable Ollama, DeepSeek, Gemini, OpenAI for forum summary & study plan)
        │
        └──► [ Diagnostics & Background Scheduler ]
              ├── Doctor (9 health probes for credentials, connectivity, permissions, config)
              └── DaemonManager (macOS launchd, Linux systemd --user / cron, Windows schtasks)
```

---

## Code Layout

```
projects/prado-sync/
├── pyproject.toml              # Package build configuration & CLI entry points
├── README.md                   # Bilingual English & Spanish documentation
├── config.example.yaml         # Comprehensive annotated configuration template
├── install.sh                  # One-liner Unix (macOS / Linux) installer
├── install.ps1                 # One-liner Windows PowerShell installer
├── BOOTSTRAP.md                # AI agent bootstrap and progressive disclosure guide
├── AGENTS.md                   # Agent workspace manifesto and operational instructions
├── CLAUDE.md                   # Claude Code workspace guidelines
├── USER.md.example             # Example student context and preferences template
├── .gitignore                  # Git ignore rules (including .agents/teamwork/)
├── .agents/
│   └── skills/
│       └── prado-os/
│           └── SKILL.md        # Tracked Antigravity / AI agent skill definition
├── src/
│   └── prado/
│       ├── __init__.py         # Package metadata
│       ├── cli.py              # CLI entry point (prado) & command dispatch
│       ├── config.py           # Configuration manager & paths (0700/0600)
│       ├── state.py            # SQLite state database & tracking
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── credentials.py  # Keyring & encrypted 0600 fallback
│       │   ├── saml.py         # Headless SimpleSAMLphp SSO driver
│       │   ├── mfa.py          # 3-Tier MFA resolution (cookie, IMAP, prompt)
│       │   └── session.py      # Session cookie manager (MFA_TOKEN reuse)
│       ├── core/
│       │   ├── __init__.py
│       │   ├── discovery.py    # Enrolled courses auto-discovery
│       │   ├── parser.py       # Moodle HTML section & activity parser
│       │   ├── router.py       # Folder routing (Mirror vs Smart) & subgroups
│       │   ├── downloader.py   # Streaming chunked downloader
│       │   ├── adoption.py     # Mid-semester deduplication scanner
│       │   └── overwrite.py    # Overwrite protection collision resolver
│       ├── exporters/
│       │   ├── __init__.py
│       │   ├── dashboard.py    # DASHBOARD.md generator
│       │   ├── changelog.py    # CHANGELOG.md generator
│       │   └── calendar.py     # RFC-5545 deadlines.ics generator
│       ├── notifications/
│       │   ├── __init__.py
│       │   ├── desktop.py      # Multi-OS desktop notification
│       │   ├── webhooks.py     # Telegram & Discord webhooks
│       │   └── email.py        # SMTP email alerts
│       ├── ai/
│       │   ├── __init__.py
│       │   ├── base.py         # Abstract AI provider
│       │   ├── ollama.py       # Local Ollama client
│       │   └── external.py     # DeepSeek / Gemini / OpenAI client
│       ├── scheduler/
│       │   ├── __init__.py
│       │   ├── daemon.py       # launchd / systemd / schtasks manager
│       │   └── doctor.py       # 9-probe health diagnostic command
│       └── onboarding/
│           ├── __init__.py
│           ├── wizard.py       # 2-Phase interactive onboarding
│           └── star.py         # GitHub star loop (gh api / browser)
└── tests/
    ├── conftest.py             # Fixtures, mock IdP, mock Moodle HTML
    ├── unit/
    │   ├── test_config.py
    │   ├── test_credentials.py
    │   ├── test_saml_auth.py
    │   ├── test_mfa.py
    │   ├── test_discovery.py
    │   ├── test_parser.py
    │   ├── test_router.py
    │   ├── test_downloader.py
    │   ├── test_adoption.py
    │   ├── test_overwrite.py
    │   ├── test_calendar.py
    │   ├── test_exporters.py
    │   └── test_doctor.py
    └── e2e/
        ├── test_cli_onboard.py
        ├── test_cli_sync.py
        ├── test_cli_json.py
        ├── test_live_readonly.py
        └── test_adversarial.py
```

---

## Feature Inventory

Every feature from the Survey phase appears here with its assigned milestone.

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Git Hygiene & Privacy | Amend initial commit author to `Lorenzo Vasile <lorenzovasile07@gmail.com>`, zero personal emails/credentials, zero forbidden tool mentions, gitignore .agents/teamwork | M1 | Survey 3 / Req |
| 2 | Package Foundation & Build | `pyproject.toml` with console script `prado`, clean dependencies, installable via `pip install -e .` | M1 | Survey 3 / Req |
| 3 | Config & State Isolation | Config in OS user dir (`~/.config/prado/` or `%APPDATA%/prado`, 0700/0600), isolated from course root | M1 | Survey 1 / Req R1 |
| 4 | Native Credential Store | `keyring` (macOS Keychain, Windows CredMgr, Linux SecretService) with encrypted/0600 file fallback | M1 | Survey 1 / Req R1 |
| 5 | Headless SimpleSAMLphp SSO | Headless SAML dance, IdP redirect, SAMLResponse extraction, ACS submission, session cookies | M1 | Survey 1 / Req R1 |
| 6 | Tier 1 MFA: Cookie Reuse | Persistent 30-day `MFA_TOKEN` device trust cookie storage and injection | M1 | Survey 1 / Req R1 |
| 7 | Tier 2 MFA: IMAP Auto-Fetch | Cross-platform `imaplib.IMAP4_SSL` 2FA code extraction + macOS AppleScript fallback | M1 | Survey 1 / Req R1 |
| 8 | Tier 3 MFA: Terminal / JSON | Interactive TTY 6-digit prompt and non-interactive `--json` protocol (exit code 2, error `mfa_required`) | M1 | Survey 1 / Req R1 |
| 9 | Course Auto-Discovery | Moodle AJAX `core_course_get_enrolled_courses` with DOM fallback on `/my/courses.php` | M2 | Survey 2 / Req R2 |
| 10 | Course Metadata & Toggles | Course filtering by semester, term, `active: true/false` toggling | M2 | Survey 2 / Req R2 |
| 11 | HTML Activity Parser | Canonical sections (`li#section-N`), resources, multi-file folders, assignments (with briefs), forums, URLs | M2 | Survey 2 / Req R2 |
| 12 | Dual Folder Routing | Presets for `PRADO Mirror` and `Smart Theory/Practice` (STEM & non-STEM taxonomies) | M2 | Survey 2 / Req R2 |
| 13 | Subgroup Filtering & Archiving | Subgroup detection (e.g. C1 vs C2) and archiving to `_subgroups_archive/` | M2 | Survey 2 / Req R2 |
| 14 | Safe Chunked Downloader | Streaming 64KB into `.prado_tmp_*`, live SHA-256 calculation, atomic replace | M2 | Survey 2 / Req R2 |
| 15 | Dry-Run Tree Preview | `--dry-run` flag with JSON output and pretty tree formatting without disk writes | M2 | Survey 2 / Req R2 |
| 16 | Mid-Semester Adoption | Local filesystem pre-scan matching existing files via (sha256, size), registering as `is_adopted = 1` | M2 | Survey 2 / Req R2 |
| 17 | Overwrite Protection | 4-quadrant matrix: modified local files never overwritten; server updates saved as `_server_YYYYMMDD_HHMMSS` | M2 | Survey 2 / Req R2 |
| 18 | Local SQLite State Database | SQLite schema tracking file paths, original hashes, remote URLs, modtimes, student edits (0600) | M2 | Survey 2 / Req R2 |
| 19 | `DASHBOARD.md` Exporter | Markdown dashboard with countdowns to deadlines, active courses, upcoming deliverables | M3 | Survey 3 / Req R3 |
| 20 | `CHANGELOG.md` Exporter | Chronological log of newly downloaded files, assignment updates, forum posts | M3 | Survey 3 / Req R3 |
| 21 | RFC-5545 `deadlines.ics` | Standard calendar with deterministic UIDs and tiered `VALARM`s (3d/1d/2h exams, 2d/1d/3h assignments) | M3 | Survey 3 / Req R3 |
| 22 | Multi-OS Desktop Alerts | Zero-dependency desktop alerts (macOS `osascript`, Linux `notify-send`, Windows PowerShell toast) | M3 | Survey 3 / Req R3 |
| 23 | Webhook Notifications | Telegram Bot, Discord webhook, and SMTP email alerts | M3 | Survey 3 / Req R3 |
| 24 | Optional BYO-AI Layer | Free & deterministic by default; optional Ollama, DeepSeek, Gemini, OpenAI for forum summary & study plan | M3 | Survey 3 / Req R3 |
| 25 | Background Daemon Manager | OS service integration (`launchd` on macOS, `systemd --user` / `cron` on Linux, `schtasks` on Windows) | M3 | Survey 3 / Req R3 |
| 26 | `prado doctor` Diagnostics | 9 diagnostic probes checking credentials, network, permissions, dependencies, config integrity | M3 | Survey 3 / Req R3 |
| 27 | Unified CLI Suite | `prado onboard`, `auth`, `discover`, `courses`, `sync`, `doctor`, `daemon`, `star` with `--help` and `--json` | M4 | Survey 3 / Req R4 |
| 28 | Phase 1 Onboarding | <60s flow: Credentials -> Destination -> Course selection & dry-run -> First sync -> Folder reveal | M4 | Survey 3 / Req R4 |
| 29 | GitHub Star Loop | Tasteful 1-time prompt after first successful sync (`prado star` via `gh api` or browser URL) | M4 | Survey 3 / Req R4 |
| 30 | Agent Workspace | `BOOTSTRAP.md`, `AGENTS.md`, `CLAUDE.md`, `USER.md.example`, `.agents/skills/prado-os/SKILL.md` | M4 | Survey 3 / Req R4 |
| 31 | One-Liner Installers | Cross-platform `install.sh` (macOS/Linux) and `install.ps1` (Windows) | M4 | Survey 3 / Req R4 |
| 32 | Bilingual Documentation | Comprehensive `README.md` (English & Spanish), `config.example.yaml` | M4 | Survey 3 / Req R4 |
| 33 | Opaque-Box E2E Test Suite | 4-tier requirement-driven test suite (Tiers 1-4) published as `TEST_READY.md` | Testing Track | Req R1-R4 |
| 34 | E2E Acceptance Pass | 100% test pass on macOS & Linux + Live read-only macOS integration test (`prado doctor`, `discover`, `sync --dry-run`) | M5 | Acceptance |
| 35 | Adversarial Hardening | Tier 5 white-box coverage hardening with adversarial edge-case stress tests | M5 | Project Pattern |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Core Foundation, Security & 3-Tier SAML/MFA Auth | Features 1-8: Git hygiene, pyproject.toml, config/state isolation, keyring & fallback, headless SAML SSO, 3-tier MFA | none | PLANNED |
| M2 | Course Discovery, HTML Parsing, Routing & Safe Downloader | Features 9-18: AJAX discovery, activity parsing, PRADO Mirror & Smart Theory/Practice routing, chunked downloader, mid-semester adoption, overwrite protection, SQLite state | M1 | PLANNED |
| M3 | Exporters, Notifications, Scheduler & Doctor | Features 19-26: DASHBOARD.md, CHANGELOG.md, RFC-5545 deadlines.ics, multi-OS notifications, BYO-AI layer, background daemon, prado doctor | M2 | PLANNED |
| M4 | Dual Onboarding, CLI Suite & GitHub Star Loop | Features 27-32: Standalone CLI commands with --json, agent playbooks (BOOTSTRAP, AGENTS, CLAUDE, USER, SKILL), install.sh/ps1, README (EN/ES), prado star | M3 | PLANNED |
| M5 | Final E2E Pass, Live Integration & Adversarial Hardening | Features 34-35: 100% E2E test pass (Tiers 1-4), live macOS integration test against pradogrado2627.ugr.es, Tier 5 adversarial coverage hardening | M4, E2E Testing Track | PLANNED |

---

## Interface Contracts

### M1 ↔ M2 Contract
- **Session Provider**: `prado.auth.session.MoodleSessionManager.get_authenticated_session() -> requests.Session`
  - Returns an active `requests.Session` populated with authenticated cookies (including `MoodleSession`, `MFA_TOKEN_*`, `MOODLEID1_`).
  - Raises `prado.exceptions.AuthenticationRequiredError` or `prado.exceptions.MfaChallengeRequiredError`.
- **Config & State Paths**: `prado.config.get_config_dir() -> Path`, `prado.config.get_state_db_path() -> Path`.
- **Course Root Path**: `prado.config.load_config().courses_root -> Path`.

### M2 ↔ M3 Contract
- **Activity & Deadlines DTO**: `prado.core.parser.CourseActivity`
  - Fields: `id: str`, `course_id: str`, `section: str`, `mod_type: str`, `title: str`, `url: str`, `due_date: Optional[datetime]`, `submission_status: Optional[str]`, `attachments: List[FileAttachment]`.
- **Sync Result Summary**: `prado.core.downloader.SyncSummary`
  - Fields: `downloaded_files: List[DownloadedFile]`, `updated_files: List[DownloadedFile]`, `conflict_files: List[ConflictFile]`, `adopted_files: List[AdoptedFile]`, `deadlines: List[DeadlineItem]`, `forum_announcements: List[ForumPost]`.

### M3 ↔ M4 Contract
- **CLI Command Protocol**: Each subcommand in `prado.cli` (`onboard`, `auth`, `discover`, `courses`, `sync`, `doctor`, `daemon`, `star`) accepts `--json` flag and returns structured JSON to stdout with exit codes:
  - `0`: Success
  - `1`: General Error (JSON includes `{"error": "message", "code": "error_code"}`)
  - `2`: MFA Required (JSON includes `{"status": "mfa_required", "tier": 3, "message": "Prompt"}`)

---

## Verification & Forensic Audit Policy

- Every milestone executes the strict gate cycle: Explorer → Worker → Reviewer → Challenger → Forensic Auditor.
- Mandatory Integrity Directive: ZERO TOLERANCE FOR CHEATING OR FACADES.
- Forensic Auditor has a BINARY VETO. Any violation of genuine implementation immediately fails the gate.
