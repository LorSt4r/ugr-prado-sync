# E2E Test Infra: PradoOS (`prado-os`)

## Test Philosophy
- **Opaque-box, requirement-driven**: Test suite is derived strictly from `ORIGINAL_REQUEST.md` and user specifications, not internal implementation details.
- **Independent decomposition**: Decomposed by user-visible functional areas, exercising the CLI and library as an external consumer would.
- **Methodology**: 4-Tier Progressive Testing (Category-Partition, Boundary Value Analysis, Pairwise Combinatorial Testing, Real-World Workload Scenarios).
- **Progressive testability**: Lower tiers test fundamental capabilities without requiring higher-tier features.

---

## Feature Inventory Coverage Matrix

| # | Feature | Requirement Source | Tier 1 (Isolated) | Tier 2 (Boundary) | Tier 3 (Pairwise) | Tier 4 (Scenario) |
|---|---------|-------------------|:-----------------:|:-----------------:|:-----------------:|:-----------------:|
| 1 | Git Hygiene & Privacy | ORIGINAL_REQUEST §17 | 5 | 5 | ✓ | ✓ |
| 2 | Package Setup & CLI Entry | ORIGINAL_REQUEST §39 | 5 | 5 | ✓ | ✓ |
| 3 | Config & State Isolation (0600) | ORIGINAL_REQUEST §22 | 5 | 5 | ✓ | ✓ |
| 4 | Native Keyring & Fallback | ORIGINAL_REQUEST §22 | 5 | 5 | ✓ | ✓ |
| 5 | Headless SimpleSAMLphp SSO | ORIGINAL_REQUEST §22 | 5 | 5 | ✓ | ✓ |
| 6 | 3-Tier MFA: Tier 1 Cookie Reuse | ORIGINAL_REQUEST §22 | 5 | 5 | ✓ | ✓ |
| 7 | 3-Tier MFA: Tier 2 IMAP SSL | ORIGINAL_REQUEST §22 | 5 | 5 | ✓ | ✓ |
| 8 | 3-Tier MFA: Tier 3 Prompt/JSON | ORIGINAL_REQUEST §22 | 5 | 5 | ✓ | ✓ |
| 9 | Course Auto-Discovery (AJAX/DOM) | ORIGINAL_REQUEST §25 | 5 | 5 | ✓ | ✓ |
| 10 | Course Metadata & Toggling | ORIGINAL_REQUEST §25 | 5 | 5 | ✓ | ✓ |
| 11 | HTML Activity Parsing | ORIGINAL_REQUEST §25 | 5 | 5 | ✓ | ✓ |
| 12 | Dual Folder Routing (Mirror/Smart) | ORIGINAL_REQUEST §25 | 5 | 5 | ✓ | ✓ |
| 13 | Subgroup Filtering & Archiving | ORIGINAL_REQUEST §25 | 5 | 5 | ✓ | ✓ |
| 14 | Safe Chunked Downloader | ORIGINAL_REQUEST §25 | 5 | 5 | ✓ | ✓ |
| 15 | Dry-Run Tree Preview | ORIGINAL_REQUEST §25 | 5 | 5 | ✓ | ✓ |
| 16 | Mid-Semester Adoption | ORIGINAL_REQUEST §25 | 5 | 5 | ✓ | ✓ |
| 17 | Overwrite Collision Protection | ORIGINAL_REQUEST §25 | 5 | 5 | ✓ | ✓ |
| 18 | Local State Database (SQLite) | ORIGINAL_REQUEST §25 | 5 | 5 | ✓ | ✓ |
| 19 | DASHBOARD.md Exporter | ORIGINAL_REQUEST §28 | 5 | 5 | ✓ | ✓ |
| 20 | CHANGELOG.md Exporter | ORIGINAL_REQUEST §28 | 5 | 5 | ✓ | ✓ |
| 21 | RFC-5545 deadlines.ics Exporter | ORIGINAL_REQUEST §28 | 5 | 5 | ✓ | ✓ |
| 22 | Multi-OS Desktop Alerts | ORIGINAL_REQUEST §28 | 5 | 5 | ✓ | ✓ |
| 23 | Webhook Alerts (Telegram/Discord) | ORIGINAL_REQUEST §28 | 5 | 5 | ✓ | ✓ |
| 24 | Pluggable BYO-AI Layer | ORIGINAL_REQUEST §28 | 5 | 5 | ✓ | ✓ |
| 25 | Background Daemon Manager | ORIGINAL_REQUEST §28 | 5 | 5 | ✓ | ✓ |
| 26 | `prado doctor` Health Diagnostics | ORIGINAL_REQUEST §28 | 5 | 5 | ✓ | ✓ |
| 27 | Unified CLI Suite & --json mode | ORIGINAL_REQUEST §31 | 5 | 5 | ✓ | ✓ |
| 28 | OpenClaw Phase 1 Onboarding | ORIGINAL_REQUEST §31 | 5 | 5 | ✓ | ✓ |
| 29 | GitHub Star Loop (prado star) | ORIGINAL_REQUEST §31 | 5 | 5 | ✓ | ✓ |
| 30 | OpenClaw Agent Workspace & Playbooks | ORIGINAL_REQUEST §31 | 5 | 5 | ✓ | ✓ |
| 31 | One-Liner Installers (sh/ps1) | ORIGINAL_REQUEST §31 | 5 | 5 | ✓ | ✓ |
| 32 | Bilingual Documentation (EN/ES) | ORIGINAL_REQUEST §45 | 5 | 5 | ✓ | ✓ |

---

## Test Architecture
- **Test Runner**: `pytest`
- **Location**: `tests/`
  - `tests/conftest.py`: Reusable mock HTTP fixtures (responses/urllib/requests mocks), mock SAML IdP endpoints, sample Moodle HTML fixtures for courses/sections/activities, and isolated temporary directory fixtures.
  - `tests/unit/`: Component-level tests.
  - `tests/e2e/`: Full CLI and system tests (`test_cli_onboard.py`, `test_cli_sync.py`, `test_cli_json.py`, `test_live_readonly.py`).
- **Pass/Fail Semantics**: All test assertions return exit code 0 on success.

---

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | **Fresh Semester Onboarding (<60s)**: Brand new student installs `prado`, runs `prado onboard`, authenticates with 2FA, selects destination folder, previews tree, runs first sync, verifies folder created and GitHub star prompt triggered. | F1, F2, F3, F4, F5, F6, F8, F9, F12, F14, F18, F27, F28, F29 | High |
| 2 | **Mid-Semester Adoption**: Existing student who already downloaded files manually adopts PradoOS. Verifies existing files are indexed via SHA-256 and NOT re-downloaded; new files and assignments are downloaded cleanly. | F9, F11, F14, F16, F17, F18, F19, F20, F21 | High |
| 3 | **Professor Update vs Local Student Edit**: Student modifies `lab1.ipynb` locally. Professor uploads a revised `lab1.ipynb`. PradoOS detects hash conflict, preserves student file unchanged, and saves professor revision as `lab1_server_YYYYMMDD_HHMMSS.ipynb`. | F14, F17, F18, F20 | High |
| 4 | **Subgroup Routing & Mirroring**: Student in subgroup C2 synchronizes courses. Verifies C2 materials are in `Practicas/`, while C1/C3 materials are either filtered out or routed to `_subgroups_archive/`. | F9, F10, F11, F12, F13, F14 | Medium |
| 5 | **Agent-Mediated Non-Interactive Execution**: AI agent invokes `prado discover --json` and `prado sync --json`. Verifies clean structured JSON stdout, exit codes (0 for success, 2 for MFA required), and zero terminal hang. | F3, F8, F9, F15, F27, F30 | High |
| 6 | **Live Read-Only Verification**: Read-only verification against live `pradogrado2627.ugr.es` using existing credentials/session, verifying `prado doctor`, `prado discover --json`, and `prado sync --dry-run` without side-effects. | F4, F5, F6, F9, F15, F26, F27 | High |

---

## Coverage Thresholds
- **Tier 1 (Feature Coverage)**: ≥5 test cases per feature (32 features × 5 = 160 test cases minimum).
- **Tier 2 (Boundary & Corner Cases)**: ≥5 test cases per feature covering error handling, network drops, malformed HTML, invalid cookies, corrupted files, and permission constraints (160 test cases minimum).
- **Tier 3 (Cross-Feature Combinations)**: ≥32 pairwise interaction test cases.
- **Tier 4 (Real-World Scenarios)**: ≥6 end-to-end integration scenario test cases.
- **Total Minimum**: ≥358 test cases.
