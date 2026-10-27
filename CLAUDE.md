# 🧭 CLAUDE.md — Claude Code Guide for PradoOS

This repository implements **PradoOS (`prado-os`)**, an open-source, cross-platform academic workflow engine for Moodle and PRADO UGR.

## Quick Reference for Claude Code

1. **First-Time Student Setup:**
   Read [`BOOTSTRAP.md`](BOOTSTRAP.md) and `.agents/skills/prado-os/SKILL.md` to guide the student through the 2-Phase Progressive Disclosure onboarding flow.
2. **Architecture & Invariants:**
   Read [`AGENTS.md`](AGENTS.md) and [`PROJECT.md`](PROJECT.md) for the security invariants (strict `0700`/`0600` config/credential separation from `courses_root`, 3-tier MFA resolution, and 4-quadrant overwrite protection).
3. **Development & Testing Commands:**
   ```bash
   # Run full test suite
   .venv/bin/pytest

   # Run CLI diagnostics in JSON mode
   .venv/bin/prado doctor --json

   # Preview sync tree without writing to disk
   .venv/bin/prado sync --dry-run --json
   ```
