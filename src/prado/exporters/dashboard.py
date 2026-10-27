"""
DASHBOARD.md Exporter for PradoOS.

Generates an active academic overview in Markdown format with:
- Upcoming deadlines sorted chronologically with urgency badge tiers
- Enrolled courses overview with file and pending counts
- Recent synchronization summary
"""

from __future__ import annotations

import datetime
from enum import Enum
import os
from pathlib import Path
from typing import Any, List, Optional, Tuple

from prado.core.downloader import DeadlineItem, SyncSummary
from prado.state import CourseRecord, StateDatabase


class DeadlineUrgency(str, Enum):
    OVERDUE = "overdue"
    URGENT = "urgent"
    SOON = "soon"
    NORMAL = "normal"


def escape_markdown_table_cell(text: str) -> str:
    """Escapes pipe characters (|) and cleans whitespace for Markdown tables."""
    if not text:
        return ""
    cleaned = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    return cleaned.replace("|", r"\|")


def classify_deadline_type(title: str) -> str:
    """
    Returns 'Exam' if title contains exam keywords (exam, prueba, parcial, test, quiz),
    otherwise 'Assignment'.
    """
    lower = title.lower()
    exam_keywords = ["exam", "prueba", "parcial", "test", "quiz", "control"]
    if any(k in lower for k in exam_keywords):
        return "Exam"
    return "Assignment"


def format_time_left(
    due_date: datetime.datetime,
    now: Optional[datetime.datetime] = None,
) -> Tuple[DeadlineUrgency, str, str]:
    """
    Computes time remaining until deadline.
    Returns: (urgency_enum, badge_str, human_duration_str)
    e.g. (DeadlineUrgency.URGENT, "🚨 Urgent", "2d 15h")
    """
    if now is None:
        if due_date.tzinfo is not None:
            now = datetime.datetime.now(due_date.tzinfo)
        else:
            now = datetime.datetime.now()
    else:
        # Reconcile timezone awareness
        if due_date.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=due_date.tzinfo)
        elif due_date.tzinfo is None and now.tzinfo is not None:
            due_date = due_date.replace(tzinfo=now.tzinfo)

    if due_date < now:
        delta = now - due_date
        days = delta.days
        hours = delta.seconds // 3600
        dur = f"{days}d {hours}h ago" if days > 0 else f"{hours}h ago"
        return DeadlineUrgency.OVERDUE, "⚠️ Overdue", dur

    delta = due_date - now
    total_hours = delta.total_seconds() / 3600.0
    days = delta.days
    hours = delta.seconds // 3600
    dur = f"{days}d {hours:02d}h"

    if total_hours < 48.0:
        return DeadlineUrgency.URGENT, "🚨 Urgent", dur
    elif total_hours < 168.0:  # 7 days
        return DeadlineUrgency.SOON, "⏳ Soon", dur
    else:
        return DeadlineUrgency.NORMAL, "📅 Scheduled", dur


class DashboardExporter:
    """Generates and writes DASHBOARD.md atomically."""

    def __init__(
        self,
        courses_root: Path,
        state_db: Optional[StateDatabase] = None,
        academic_year: Optional[str] = None,
    ):
        self.courses_root = Path(courses_root)
        self.state_db = state_db
        self.academic_year = academic_year or "2026/2027"

    def render(
        self,
        summary: Optional[SyncSummary] = None,
        courses: Optional[List[CourseRecord]] = None,
        now: Optional[datetime.datetime] = None,
    ) -> str:
        current_time = now or datetime.datetime.now()
        ts_str = current_time.strftime("%Y-%m-%d %H:%M:%S")

        # 1. Header
        lines = [
            f"# 🎓 Academic Dashboard — PradoOS ({self.academic_year})",
            "",
            f"**Last Sync:** {ts_str} CET",
            "",
            "## 📅 Upcoming Deadlines",
            "",
        ]

        # 2. Deadlines table
        raw_deadlines = summary.deadlines if summary else []
        deadlines = [d for d in raw_deadlines if d.due_date is not None]
        if not deadlines:
            lines.append("No upcoming deadlines scheduled.")
        else:
            def _sort_key(d: DeadlineItem) -> datetime.datetime:
                dt = d.due_date
                if dt.tzinfo is not None:
                    return dt.astimezone(datetime.timezone.utc)
                return dt.replace(tzinfo=datetime.timezone.utc)

            sorted_deadlines = sorted(deadlines, key=_sort_key)
            lines.append("| Status | Due Date | Time Left | Course | Activity / Exam | Type | Link |")
            lines.append("|---|---|:---:|:---:|---|:---:|:---:|")

            for item in sorted_deadlines:
                urgency, badge, time_left = format_time_left(item.due_date, now=current_time)
                due_str = item.due_date.strftime("%Y-%m-%d %H:%M")
                item_type = classify_deadline_type(item.title)
                safe_title = escape_markdown_table_cell(item.title)
                course_label = escape_markdown_table_cell(item.course)
                safe_url = item.url.replace("|", "%7C").replace("\r", "").replace("\n", "") if item.url else ""
                link_str = f"[Open]({safe_url})" if safe_url else "N/A"
                lines.append(
                    f"| {badge} | {due_str} | {time_left} | {course_label} | {safe_title} | {item_type} | {link_str} |"
                )

        lines.append("")

        # 3. Enrolled courses table
        course_list: List[CourseRecord] = []
        if courses is not None:
            course_list = courses
        elif self.state_db is not None:
            course_list = self.state_db.list_active_courses()

        if course_list:
            lines.append("## 📚 Enrolled Courses")
            lines.append("")
            lines.append("| Code | Course Name | Files | Pending |")
            lines.append("|---|---|:---:|:---:|")

            # Count pending deadlines per course
            pending_counts: dict[str, int] = {}
            for d in deadlines:
                cid = str(d.course).lower()
                pending_counts[cid] = pending_counts.get(cid, 0) + 1

            for c in course_list:
                cid_str = c.idnumber or str(c.course_id)
                name = escape_markdown_table_cell(c.fullname)
                
                # Count files from state_db if available
                file_count = 0
                if self.state_db is not None:
                    try:
                        file_count = len(self.state_db.list_files(c.course_id))
                    except Exception:
                        file_count = 0

                # Match pending
                pending = pending_counts.get(str(c.course_id).lower(), 0)
                if not pending and c.shortname:
                    pending = pending_counts.get(c.shortname.lower(), 0)
                if not pending and c.idnumber:
                    pending = pending_counts.get(c.idnumber.lower(), 0)

                lines.append(f"| {cid_str} | {name} | {file_count} | {pending} |")
            lines.append("")

        # 4. Recent sync summary
        if summary is not None:
            lines.append("## 🔄 Recent Sync Summary")
            lines.append("")
            lines.append(f"- **Downloaded files:** {len(summary.downloaded_files)}")
            lines.append(f"- **Updated files:** {len(summary.updated_files)}")
            lines.append(f"- **Adopted files:** {len(summary.adopted_files)}")
            lines.append(f"- **Conflicts detected:** {len(summary.conflict_files)}")
            lines.append(f"- **Forum announcements:** {len(summary.forum_announcements)}")
            lines.append("")

        return "\n".join(lines).strip() + "\n"

    def export(
        self,
        summary: Optional[SyncSummary] = None,
        courses: Optional[List[CourseRecord]] = None,
        dest_path: Optional[Path] = None,
        now: Optional[datetime.datetime] = None,
    ) -> Path:
        """Renders and atomically writes DASHBOARD.md to disk."""
        target = Path(dest_path) if dest_path else self.courses_root / "DASHBOARD.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        content = self.render(summary=summary, courses=courses, now=now)

        tmp_target = target.parent / f".{target.name}.tmp"
        tmp_target.write_text(content, encoding="utf-8")
        os.replace(tmp_target, target)
        return target


def generate_dashboard_md(
    courses_root: Path,
    summary: Optional[SyncSummary] = None,
    courses: Optional[List[CourseRecord]] = None,
    state_db: Optional[StateDatabase] = None,
    academic_year: Optional[str] = None,
    now: Optional[datetime.datetime] = None,
) -> str:
    """Generates DASHBOARD.md content string."""
    exporter = DashboardExporter(courses_root, state_db=state_db, academic_year=academic_year)
    return exporter.render(summary=summary, courses=courses, now=now)


def export_dashboard(
    courses_root: Path,
    summary: Optional[SyncSummary] = None,
    courses: Optional[List[CourseRecord]] = None,
    state_db: Optional[StateDatabase] = None,
    dest_path: Optional[Path] = None,
    academic_year: Optional[str] = None,
    now: Optional[datetime.datetime] = None,
) -> Path:
    """Renders and atomically saves DASHBOARD.md to disk."""
    exporter = DashboardExporter(courses_root, state_db=state_db, academic_year=academic_year)
    return exporter.export(summary=summary, courses=courses, dest_path=dest_path, now=now)
