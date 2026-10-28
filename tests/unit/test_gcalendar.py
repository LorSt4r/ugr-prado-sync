"""
Unit and Integration Tests for PradoOS Google Calendar REST API Exporter.
"""

import datetime
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from prado.core.downloader import DeadlineItem
from prado.exporters.gcalendar import GoogleCalendarSync, load_deadlines_from_ics


def test_resolve_token_file(tmp_path):
    custom = tmp_path / "custom_token.json"
    custom.write_text("{}", encoding="utf-8")
    assert GoogleCalendarSync.resolve_token_file(custom) == custom
    assert GoogleCalendarSync.resolve_token_file(tmp_path / "nonexistent.json") is None


def test_load_deadlines_from_ics(tmp_path):
    ics_file = tmp_path / "deadlines.ics"
    content = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:abc123@prado-os.local\r\n"
        "SUMMARY:[VC_A] Entrega Propuesta Proyecto Final\r\n"
        "DTSTART:20261106T235959Z\r\n"
        "DESCRIPTION:Entrega oficial en https://pradogrado.ugr.es/mod/assign/view.php?id=83748\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    ics_file.write_text(content, encoding="utf-8")

    items = load_deadlines_from_ics(ics_file)
    assert len(items) == 1
    assert items[0].course == "VC_A"
    assert items[0].title == "Entrega Propuesta Proyecto Final"
    assert items[0].due_date.year == 2026
    assert items[0].due_date.month == 11
    assert items[0].due_date.day == 6


def test_sync_deadlines_dry_run(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({
        "token": {
            "access_token": "mock_access_token",
            "expiry": "2099-01-01T00:00:00+00:00"
        }
    }), encoding="utf-8")

    sync = GoogleCalendarSync(token_file=token_file, calendar_id="primary")

    with patch.object(sync, "api_request", return_value=({"items": []}, None)):
        deadlines = [
            DeadlineItem(
                id="123",
                title="Examen Parcial Módulo 1",
                course="SO_E",
                due_date=datetime.datetime(2026, 11, 20, 10, 0),
                url="https://prado.ugr.es"
            ),
            DeadlineItem(
                id="456",
                title="Práctica 3 Entrega",
                course="TIC_A",
                due_date=datetime.datetime(2026, 11, 27, 23, 59),
                url="https://prado.ugr.es"
            )
        ]
        res = sync.sync_deadlines(deadlines, dry_run=True)
        assert res["status"] == "success"
        assert res["created"] == 2
        assert res["total_deadlines"] == 2


def test_sync_deadlines_deduplication(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({
        "token": {
            "access_token": "mock_access_token",
            "expiry": "2099-01-01T00:00:00+00:00"
        }
    }), encoding="utf-8")

    sync = GoogleCalendarSync(token_file=token_file, calendar_id="primary")

    # Simulate existing event already in Google Calendar
    existing = {
        "items": [
            {
                "id": "existing_ev_1",
                "summary": "💻 [ENTREGA PRADO] TIC_A: Práctica 3 Entrega",
                "start": {"dateTime": "2026-11-27T23:59:00"}
            }
        ]
    }

    with patch.object(sync, "api_request", side_effect=[
        (existing, None),  # list events response
        ({"id": "new_ev_2"}, None)  # create event response
    ]):
        deadlines = [
            DeadlineItem(
                id="456",
                title="Práctica 3 Entrega",
                course="TIC_A",
                due_date=datetime.datetime(2026, 11, 27, 23, 59),
                url="https://prado.ugr.es"
            ),
            DeadlineItem(
                id="789",
                title="Práctica 4 Entrega",
                course="TIC_A",
                due_date=datetime.datetime(2026, 12, 14, 23, 59),
                url="https://prado.ugr.es"
            )
        ]
        res = sync.sync_deadlines(deadlines, dry_run=False)
        assert res["status"] == "success"
        assert res["skipped"] == 1
        assert res["created"] == 1
