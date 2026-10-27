"""
CHANGELOG.md Exporter for PradoOS.

Maintains a reverse chronological log of sync runs in the student courses root,
tracking downloaded files, updated files, overwrite warnings, and forum notices.
Automatically caps historical runs to MAX_RUNS (50) to prevent unbounded file growth.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
import re
from typing import Optional

from prado.core.downloader import SyncSummary


def format_file_size(size_bytes: int) -> str:
    """Formats bytes as '850 KB' (if < 1MB) or '15.0 MB' (if >= 1MB)."""
    if size_bytes < 1024 * 1024:
        kb = size_bytes / 1024.0
        return f"{kb:.0f} KB"
    else:
        mb = size_bytes / (1024.0 * 1024.0)
        return f"{mb:.1f} MB"


def escape_markdown_filename(filename: str) -> str:
    """Escapes markdown square brackets: '[' -> r'\\[' and ']' -> r'\\]'."""
    return filename.replace("[", r"\[").replace("]", r"\]")


def truncate_text(text: str, max_chars: int = 200) -> str:
    """Truncates string to max_chars, appending '...' if truncated."""
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


class ChangelogExporter:
    """Maintains reverse chronological CHANGELOG.md entries."""

    MAX_RUNS: int = 50

    def __init__(self, courses_root: Path):
        self.courses_root = Path(courses_root)

    def render_run_entry(
        self,
        summary: SyncSummary,
        run_time: Optional[datetime.datetime] = None,
    ) -> str:
        current_time = run_time or datetime.datetime.now()
        ts_str = current_time.strftime("%Y-%m-%d %H:%M CET")

        lines = [f"## 🔄 [{ts_str}] Sync Run", ""]

        has_changes = any(
            [
                summary.downloaded_files,
                summary.updated_files,
                summary.conflict_files,
                summary.forum_announcements,
            ]
        )

        if not has_changes:
            lines.append("- All course directories verified up to date.")
            lines.append("")
            return "\n".join(lines)

        # 1. Downloaded files
        if summary.downloaded_files:
            lines.append("### 📥 Downloaded Files")
            for f in summary.downloaded_files:
                short_hash = f.sha256[:8] if f.sha256 else "unknown"
                course_tag = f"**[{f.course_id}]** " if f.course_id else ""
                size_str = format_file_size(f.size_bytes)
                safe_name = escape_markdown_filename(f.path.name)
                lines.append(f"- {course_tag}`{safe_name}` ({size_str}) `[{short_hash}]`")
            lines.append("")

        # 2. Updated files
        if summary.updated_files:
            lines.append("### 🔄 Updated Files")
            for f in summary.updated_files:
                short_hash = f.sha256[:8] if f.sha256 else "unknown"
                course_tag = f"**[{f.course_id}]** " if f.course_id else ""
                size_str = format_file_size(f.size_bytes)
                safe_name = escape_markdown_filename(f.path.name)
                lines.append(f"- {course_tag}`{safe_name}` ({size_str}) `[{short_hash}]` (Updated)")
            lines.append("")

        # 3. Overwrite protection warnings
        if summary.conflict_files:
            lines.append("### ⚠️ Overwrite Warnings")
            for c in summary.conflict_files:
                orig_name = escape_markdown_filename(c.original_path.name)
                fork_name = escape_markdown_filename(c.forked_path.name)
                lines.append(
                    f"- ⚠️ OVERWRITE PROTECTION: Preserved local `{orig_name}`, saved server update as `{fork_name}`"
                )
            lines.append("")

        # 4. Forum announcements
        if summary.forum_announcements:
            lines.append("### 📢 Forum Announcements")
            for post in summary.forum_announcements:
                course_tag = f"**[{post.forum_id}]** " if post.forum_id else ""
                safe_author = " ".join((post.author or "").splitlines()).strip()
                author_tag = f" (*{safe_author}*)" if safe_author else ""
                safe_subj = " ".join((post.subject or "").splitlines()).strip()
                lines.append(f"- {course_tag}{safe_subj}{author_tag}")
                if post.content:
                    cleaned_body = " ".join(post.content.split())
                    snippet = truncate_text(cleaned_body, 200)
                    lines.append(f"  > {snippet}")
            lines.append("")

        return "\n".join(lines)

    def export(
        self,
        summary: SyncSummary,
        dest_path: Optional[Path] = None,
        run_time: Optional[datetime.datetime] = None,
    ) -> Path:
        target = Path(dest_path) if dest_path else self.courses_root / "CHANGELOG.md"
        target.parent.mkdir(parents=True, exist_ok=True)

        new_entry = self.render_run_entry(summary, run_time=run_time).strip()

        existing_runs: list[str] = []
        if target.exists():
            try:
                raw_existing = target.read_text(encoding="utf-8")
                # Split runs by heading pattern "## 🔄 " or "## "
                blocks = re.split(r"(?=^## )", raw_existing, flags=re.MULTILINE)
                for b in blocks:
                    clean_b = re.sub(r"(?:\r?\n|\s|---)+$", "", b).strip()
                    if clean_b and clean_b.startswith("## "):
                        existing_runs.append(clean_b)
            except Exception:
                existing_runs = []

        all_runs = [new_entry] + existing_runs
        retained_runs = all_runs[: self.MAX_RUNS]

        combined = "\n\n---\n\n".join(retained_runs).strip() + "\n"

        tmp_target = target.parent / f".{target.name}.tmp"
        tmp_target.write_text(combined, encoding="utf-8")
        os.replace(tmp_target, target)
        return target


def prepend_changelog_md(
    courses_root: Path,
    summary: SyncSummary,
    dest_path: Optional[Path] = None,
    run_time: Optional[datetime.datetime] = None,
) -> Path:
    """Functional convenience entry point to prepend sync run to CHANGELOG.md."""
    exporter = ChangelogExporter(courses_root)
    return exporter.export(summary=summary, dest_path=dest_path, run_time=run_time)


def export_changelog(
    courses_root: Path,
    summary: SyncSummary,
    dest_path: Optional[Path] = None,
    run_time: Optional[datetime.datetime] = None,
) -> Path:
    """Alias for prepend_changelog_md."""
    return prepend_changelog_md(courses_root, summary, dest_path=dest_path, run_time=run_time)
