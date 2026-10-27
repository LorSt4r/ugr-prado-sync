"""
Unit tests for RFC-5545 deadlines.ics calendar exporter.
"""

from __future__ import annotations

import datetime
import hashlib
from pathlib import Path
import pytest

from prado.core.downloader import DeadlineItem
from prado.exporters.calendar import (
    CalendarExporter,
    build_valarms,
    escape_ical_text,
    export_calendar,
    fold_ical_line,
    format_ical_datetime,
    generate_deadlines_ics,
    generate_event_uid,
)


def test_rfc_5545_vcalendar_headers_and_footers(tmp_path):
    exporter = CalendarExporter(courses_root=tmp_path)
    content = exporter.render(deadlines=[])
    assert "BEGIN:VCALENDAR\r\n" in content
    assert "VERSION:2.0\r\n" in content
    assert "PRODID:-//PradoOS//Academic Calendar Engine v1.0//EN\r\n" in content
    assert "CALSCALE:GREGORIAN\r\n" in content
    assert "METHOD:PUBLISH\r\n" in content
    assert content.endswith("END:VCALENDAR\r\n")


def test_deterministic_uid_generation():
    course_id = "15819"
    item_type = "assign"
    item_id = "107917"
    seed = f"prado-{course_id}-{item_type}-{item_id}"
    expected_hash = hashlib.sha256(seed.encode()).hexdigest()[:16]
    expected_uid = f"{expected_hash}@prado-os.local"

    uid1 = generate_event_uid(course_id, item_id, item_type)
    uid2 = generate_event_uid(course_id, item_id, item_type)

    assert uid1 == expected_uid
    assert uid1 == uid2


def test_exam_tiered_valarms():
    alarms = build_valarms(is_exam=True, summary="[MC] 1ª Prueba Escrita")
    triggers = [a["trigger"] for a in alarms]
    assert "-P3D" in triggers
    assert "-P1D" in triggers
    assert "-PT2H" in triggers


def test_assignment_tiered_valarms():
    alarms = build_valarms(is_exam=False, summary="[TIC] Práctica 3")
    triggers = [a["trigger"] for a in alarms]
    assert "-P2D" in triggers
    assert "-P1D" in triggers
    assert "-PT3H" in triggers


def test_valarm_negative_trigger_syntax():
    exam_alarms = build_valarms(is_exam=True, summary="Exam")
    assign_alarms = build_valarms(is_exam=False, summary="Assign")

    for a in exam_alarms + assign_alarms:
        trig = a["trigger"]
        assert trig.startswith("-P")
        assert trig[-1] in ("D", "H")


def test_utc_dtstamp_and_dtstart_formatting():
    dt = datetime.datetime(2026, 10, 30, 9, 30, 0, tzinfo=datetime.timezone.utc)
    formatted = format_ical_datetime(dt)
    assert formatted == "20261030T093000Z"


def test_zero_duration_milestone(tmp_path):
    exporter = CalendarExporter(courses_root=tmp_path)
    due = datetime.datetime(2026, 10, 30, 9, 30, 0, tzinfo=datetime.timezone.utc)
    item = DeadlineItem(id="1", title="Quiz", course="MC", due_date=due, url="http://x")

    event_text = exporter.render_event(item)
    assert "DTSTART:20261030T093000Z" in event_text
    assert "DTEND:20261030T093000Z" in event_text


def test_escape_special_characters():
    raw = "Exam, Part 1; Special\\Note\nNext line"
    escaped = escape_ical_text(raw)
    assert r"\," in escaped
    assert r"\;" in escaped
    assert r"\\" in escaped
    assert r"\n" in escaped
    assert "\n" not in escaped


def test_rfc_5545_line_folding_at_75_octets():
    long_line = (
        "DESCRIPTION:This is a very long calendar description that exceeds "
        "seventy-five octets and must be folded according to RFC 5545 specifications."
    )
    folded = fold_ical_line(long_line, max_octets=75)
    assert "\r\n " in folded
    for part in folded.split("\r\n "):
        assert len(part.encode("utf-8")) <= 75


def test_crlf_line_terminators(tmp_path):
    exporter = CalendarExporter(courses_root=tmp_path)
    due = datetime.datetime(2026, 10, 30, 9, 30, 0, tzinfo=datetime.timezone.utc)
    item = DeadlineItem(id="1", title="Quiz", course="MC", due_date=due, url="http://x")

    ics_content = exporter.render(deadlines=[item])
    # Verify CRLF is used exclusively
    assert "\r\n" in ics_content
    # No standalone \n without preceding \r
    assert "\n" in ics_content
    raw_bytes = ics_content.encode("utf-8")
    assert b"\r\n" in raw_bytes
    # Confirm every newline in raw string is preceded by \r
    lines = ics_content.split("\r\n")
    for l in lines[:-1]:
        assert "\n" not in l


def test_calendar_atomic_export(tmp_path):
    due = datetime.datetime(2026, 10, 30, 9, 30, 0, tzinfo=datetime.timezone.utc)
    item = DeadlineItem(id="1", title="Quiz", course="MC", due_date=due, url="http://x")

    dest = export_calendar(courses_root=tmp_path, deadlines=[item])
    assert dest.exists()
    assert dest.name == "deadlines.ics"
    assert not (tmp_path / ".deadlines.ics.tmp").exists()
    content = dest.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in content
    assert "Quiz" in content
