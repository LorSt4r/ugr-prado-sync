"""
RFC-5545 deadlines.ics Exporter for PradoOS.

Generates standard iCalendar files with:
- Deterministic SHA-256 UIDs
- Tiered VALARM reminders (-P3D, -P1D, -PT2H for exams; -P2D, -P1D, -PT3H for assignments)
- Zero-duration milestone markers (DTSTART == DTEND)
- 75-octet line folding
- CRLF line endings throughout
"""

from __future__ import annotations

import datetime
import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional

from prado.core.downloader import DeadlineItem
from prado.exporters.dashboard import classify_deadline_type


def generate_event_uid(
    course_id: str,
    item_id: str,
    item_type: str = "assign",
    domain: str = "prado-os.local",
) -> str:
    """
    Generates deterministic SHA-256 UID:
    sha256(prado-{course_id}-{item_type}-{item_id})[:16]@{domain}
    """
    seed = f"prado-{course_id}-{item_type}-{item_id}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{digest}@{domain}"


def escape_ical_text(text: str) -> str:
    r"""
    Escapes special characters according to RFC 5545 §3.3.11:
    '\' -> '\\', ';' -> '\;', ',' -> '\,', newlines -> '\n'
    Also normalizes standalone '\r' to '\n' to prevent bare CR injection.
    """
    if not text:
        return ""
    res = text.replace("\\", "\\\\")
    res = res.replace(";", r"\;").replace(",", r"\,")
    res = res.replace("\r\n", r"\n").replace("\r", r"\n").replace("\n", r"\n")
    return res


def fold_ical_line(line: str, max_octets: int = 75) -> str:
    """
    Folds lines exceeding max_octets (RFC-5545 specifies 75 octets)
    using CRLF followed by a single space ('\r\n ').
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= max_octets:
        return line

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_bytes = 0
    limit = max_octets

    for char in line:
        char_bytes = len(char.encode("utf-8"))
        if current_bytes + char_bytes > limit and current_chunk:
            chunks.append("".join(current_chunk))
            current_chunk = [char]
            current_bytes = char_bytes
            limit = max_octets - 1  # Subsequent lines account for space prefix
        else:
            current_chunk.append(char)
            current_bytes += char_bytes

    if current_chunk:
        chunks.append("".join(current_chunk))

    return "\r\n ".join(chunks)


def build_valarms(is_exam: bool, summary: str) -> List[Dict[str, str]]:
    """
    Returns tiered VALARM configurations:
    - Exams: -P3D (3 days), -P1D (1 day), -PT2H (2 hours)
    - Assignments: -P2D (2 days), -P1D (1 day), -PT3H (3 hours)
    """
    if is_exam:
        return [
            {"trigger": "-P3D", "desc": f"{summary} in 3 days"},
            {"trigger": "-P1D", "desc": f"{summary} tomorrow"},
            {"trigger": "-PT2H", "desc": f"{summary} in 2 hours!"},
        ]
    else:
        return [
            {"trigger": "-P2D", "desc": f"{summary} in 2 days"},
            {"trigger": "-P1D", "desc": f"{summary} tomorrow"},
            {"trigger": "-PT3H", "desc": f"{summary} in 3 hours!"},
        ]


def _normalize_dt_for_sort(dt: datetime.datetime) -> datetime.datetime:
    """Normalizes naive or timezone-aware datetimes to UTC for safe comparison."""
    if dt.tzinfo is not None:
        return dt.astimezone(datetime.timezone.utc)
    return dt.replace(tzinfo=datetime.timezone.utc)


def format_ical_datetime(dt: datetime.datetime) -> str:
    """Formats datetime as ISO 8601 UTC representation (YYYYMMDDTHHMMSSZ)."""
    utc_dt = _normalize_dt_for_sort(dt)
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")


class CalendarExporter:
    """Generates standard RFC-5545 deadlines.ics."""

    PRODID: str = "-//PradoOS//Academic Calendar Engine v1.0//EN"
    VERSION: str = "2.0"
    DEFAULT_TIMEZONE: str = "Europe/Madrid"

    def __init__(self, courses_root: Path, timezone_name: str = DEFAULT_TIMEZONE):
        self.courses_root = Path(courses_root)
        self.timezone_name = timezone_name

    def render_event(
        self,
        item: DeadlineItem,
        now: Optional[datetime.datetime] = None,
    ) -> str:
        current_time = now or datetime.datetime.now(datetime.timezone.utc)
        dtstamp = format_ical_datetime(current_time)
        dtstart = format_ical_datetime(item.due_date)
        dtend = dtstart  # Zero duration milestone

        is_exam = classify_deadline_type(item.title) == "Exam"
        item_type = "exam" if is_exam else "assign"
        uid = generate_event_uid(course_id=item.course, item_id=item.id, item_type=item_type)

        summary_text = f"[{item.course}] {item.title}"
        summary_escaped = escape_ical_text(summary_text)

        desc_raw = f"Course: {item.course}\nURL: {item.url}"
        desc_escaped = escape_ical_text(desc_raw)

        raw_lines = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:{summary_escaped}",
            f"DESCRIPTION:{desc_escaped}",
            "STATUS:CONFIRMED",
        ]

        # Add VALARMs
        alarms = build_valarms(is_exam, summary_text)
        for alarm in alarms:
            desc_alarm = escape_ical_text(alarm["desc"])
            raw_lines.extend(
                [
                    "BEGIN:VALARM",
                    "ACTION:DISPLAY",
                    f"DESCRIPTION:{desc_alarm}",
                    f"TRIGGER:{alarm['trigger']}",
                    "END:VALARM",
                ]
            )

        raw_lines.append("END:VEVENT")

        # Fold each line according to RFC 5545
        folded_lines = [fold_ical_line(line) for line in raw_lines]
        return "\r\n".join(folded_lines)

    def render(
        self,
        deadlines: List[DeadlineItem],
        now: Optional[datetime.datetime] = None,
        calendar_name: str = "PradoOS Academic Deadlines",
    ) -> str:
        header_raw = [
            "BEGIN:VCALENDAR",
            f"VERSION:{self.VERSION}",
            f"PRODID:{self.PRODID}",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:{escape_ical_text(calendar_name)}",
            f"X-WR-TIMEZONE:{self.timezone_name}",
        ]
        lines = [fold_ical_line(line) for line in header_raw]

        valid_deadlines = [d for d in deadlines if d.due_date is not None]
        sorted_deadlines = sorted(valid_deadlines, key=lambda d: _normalize_dt_for_sort(d.due_date))
        for item in sorted_deadlines:
            lines.append(self.render_event(item, now=now))

        lines.append("END:VCALENDAR")
        # Ensure CRLF endings throughout
        return "\r\n".join(lines) + "\r\n"

    def export(
        self,
        deadlines: List[DeadlineItem],
        dest_path: Optional[Path] = None,
        now: Optional[datetime.datetime] = None,
    ) -> Path:
        target = Path(dest_path) if dest_path else self.courses_root / "deadlines.ics"
        target.parent.mkdir(parents=True, exist_ok=True)

        content = self.render(deadlines, now=now)
        tmp_target = target.parent / f".{target.name}.tmp"
        tmp_target.write_bytes(content.encode("utf-8"))
        os.replace(tmp_target, target)
        return target


def generate_deadlines_ics(
    courses_root: Path,
    deadlines: List[DeadlineItem],
    dest_path: Optional[Path] = None,
    now: Optional[datetime.datetime] = None,
) -> Path:
    """Functional convenience entry point to generate deadlines.ics."""
    exporter = CalendarExporter(courses_root)
    return exporter.export(deadlines=deadlines, dest_path=dest_path, now=now)


def export_calendar(
    courses_root: Path,
    deadlines: List[DeadlineItem],
    dest_path: Optional[Path] = None,
    now: Optional[datetime.datetime] = None,
) -> Path:
    """Alias for generate_deadlines_ics."""
    return generate_deadlines_ics(courses_root=courses_root, deadlines=deadlines, dest_path=dest_path, now=now)
