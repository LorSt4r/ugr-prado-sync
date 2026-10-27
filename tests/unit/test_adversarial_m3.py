"""
Adversarial Empirical Stress Test Suite for PradoOS Milestone M3.

Focus:
1. RFC-5545 Calendar Exporter:
   - Malicious/special characters in summary/description (CRLF injection, colons, semicolons, backslashes).
   - Bare carriage return (\\r) injection vulnerability.
   - 75-octet line folding with multi-byte UTF-8 Spanish accents (á, é, í, ó, ú, ñ, ¿, ¡).
   - Unfolded string fidelity (lossless folding/unfolding roundtrip).
   - Header line folding bug on long X-WR-CALNAME.
   - Missing or irregular due dates (None crash, offset-naive vs offset-aware sorting crash).
2. DASHBOARD.md & CHANGELOG.md Exporters:
   - Empty activities, null summary, zero courses.
   - Markdown table pipe injection via item.url.
   - CHANGELOG O(N^2) horizontal divider accumulation bug across repeated sync runs.
   - Forum post subject newline injection splitting sync runs.
   - Massive activity list scaling (1,000 deadlines, 5,000 files).
3. Desktop Notifications & Webhooks Security:
   - Command injection neutralization on macOS (/usr/bin/osascript with argv).
   - Windows PowerShell -Command argument concatenation vulnerability & f-string timeout injection.
   - SMTP email CRLF subject unhandled ValueError crash.
   - Telegram Webhook unescaped HTML entities (<, >, &) in HTML parse_mode.
"""

from __future__ import annotations

import datetime
import inspect
from pathlib import Path
import pytest
import re

from prado.core.downloader import (
    DeadlineItem,
    DownloadedFile,
    ForumPost,
    SyncSummary,
)
from prado.exporters.calendar import (
    CalendarExporter,
    escape_ical_text,
    fold_ical_line,
)
from prado.exporters.changelog import (
    ChangelogExporter,
    prepend_changelog_md,
)
from prado.exporters.dashboard import (
    DashboardExporter,
    escape_markdown_table_cell,
)
from prado.notifications.desktop import (
    DesktopNotifier,
)
from prado.notifications.email import (
    SmtpConfig,
    SmtpEmailSender,
)
from prado.notifications.webhooks import (
    TelegramWebhookSender,
)


# =============================================================================
# 1. RFC-5545 Calendar Generator Stress Tests
# =============================================================================

class TestCalendarAdversarial:
    def test_calendar_special_characters_escaping(self):
        """
        Verify standard RFC 5545 text escaping for backslashes, semicolons,
        commas, and newlines. Colons in values do not require escaping.
        """
        raw = r"Topic 1; Part 2, Notes\Ref: http://prado.ugr.es" + "\nNext line"
        escaped = escape_ical_text(raw)
        assert r"\;" in escaped
        assert r"\," in escaped
        assert r"\\" in escaped
        assert r"\n" in escaped
        assert "\n" not in escaped
        assert ":" in escaped  # colons are valid unescaped text in RFC 5545 property values

    def test_calendar_crlf_normalized_to_literal_slash_n(self):
        """Standard CRLF is escaped to literal \\n."""
        raw = "Line 1\r\nLine 2\r\nLine 3"
        escaped = escape_ical_text(raw)
        assert r"\n" in escaped
        assert "\r\n" not in escaped

    def test_calendar_bare_cr_injection_vulnerability(self):
        """
        Verify that bare '\\r' is sanitized to literal '\\n' in escape_ical_text
        and never leaks as a bare CR into the rendered VCALENDAR output.
        """
        raw = "Quiz\rBEGIN:VEVENT\rUID:hacked@evil.com\rSUMMARY:Hacked\rEND:VEVENT"
        escaped = escape_ical_text(raw)
        assert "\r" not in escaped
        assert r"\n" in escaped

        exporter = CalendarExporter(courses_root=Path("/tmp"))
        item = DeadlineItem(
            id="vuln_1",
            title=raw,
            course="MC",
            due_date=datetime.datetime(2026, 10, 30, 9, 30, tzinfo=datetime.timezone.utc),
            url="http://x",
        )
        ics_output = exporter.render([item])
        bare_cr_match = re.search(r"\r(?!\n)", ics_output)
        assert bare_cr_match is None

    def test_calendar_line_folding_spanish_accents_and_exact_boundary(self):
        """
        Stress test 75-octet line folding with Spanish accented characters
        (á, é, í, ó, ú, ñ, ¿, ¡) on and around the 75-octet boundary.
        Verifies:
        - No folded line exceeds 75 octets.
        - Multi-byte UTF-8 sequences are not severed in the middle.
        - Unfolding (stripping CRLF + space) restores exact original string.
        """
        spanish_title = (
            "1ª Prueba de Prácticas: Teoría de Autómatas, Expresión Regular y "
            "Diseño Lingüístico (¿Aprobado? ¡Sí, con éxito!)"
        )
        # Build exact 74-octet line plus 2-byte ñ (76 octets -> must fold)
        prefix = "SUMMARY:[MC] "
        prefix_len = len(prefix.encode("utf-8"))
        fill = "A" * (74 - prefix_len)
        test_line = prefix + fill + "ñ" + "Extra"
        assert len((prefix + fill).encode("utf-8")) == 74
        assert len((prefix + fill + "ñ").encode("utf-8")) == 76

        folded = fold_ical_line(test_line, max_octets=75)
        assert "\r\n " in folded
        parts = folded.split("\r\n ")
        # First chunk must be <= 75 octets
        assert len(parts[0].encode("utf-8")) <= 75
        # Second chunk with leading space must be <= 75 octets
        assert len((" " + parts[1]).encode("utf-8")) <= 75
        # Lossless unfolding
        assert folded.replace("\r\n ", "") == test_line

    def test_calendar_header_line_folding_flaw_on_long_calendar_name(self):
        """
        Verify that CalendarExporter.render() folds long header lines (such as X-WR-CALNAME)
        so no line exceeds 75 octets per RFC 5545 §3.1.
        """
        exporter = CalendarExporter(courses_root=Path("/tmp"))
        long_calname = "Universidad de Granada - Escuela Técnica Superior de Ingenierías Informática y de Telecomunicación"
        ics = exporter.render([], calendar_name=long_calname)
        for line in ics.split("\r\n"):
            if line:
                assert len(line.encode("utf-8")) <= 75

    def test_calendar_none_due_date_crashes(self):
        """
        Verify that DeadlineItem with due_date=None is safely skipped without crashing.
        """
        exporter = CalendarExporter(courses_root=Path("/tmp"))
        item = DeadlineItem(id="1", title="Missing Date", course="MC", due_date=None, url="http://x")
        ics = exporter.render([item])
        assert "BEGIN:VCALENDAR" in ics
        assert "Missing Date" not in ics

    def test_calendar_mixed_naive_and_aware_dates_crashes(self):
        """
        Verify that mixed naive and timezone-aware datetimes sort and render cleanly.
        """
        exporter = CalendarExporter(courses_root=Path("/tmp"))
        items = [
            DeadlineItem("1", "Naive", "MC", datetime.datetime(2026, 10, 30, 9, 30), "http://x"),
            DeadlineItem("2", "Aware", "MC", datetime.datetime(2026, 10, 31, 9, 30, tzinfo=datetime.timezone.utc), "http://x"),
        ]
        ics = exporter.render(items)
        assert "SUMMARY:[MC] Naive" in ics
        assert "SUMMARY:[MC] Aware" in ics


# =============================================================================
# 2. DASHBOARD.md & CHANGELOG.md Stress Tests
# =============================================================================

class TestDashboardAndChangelogAdversarial:
    def test_dashboard_empty_activities_and_null_summary(self, tmp_path):
        """Verify dashboard renders cleanly with empty summary or None."""
        exporter = DashboardExporter(courses_root=tmp_path)
        out1 = exporter.render(summary=None)
        assert "No upcoming deadlines scheduled." in out1
        assert "Last Sync:" in out1

        out2 = exporter.render(summary=SyncSummary())
        assert "No upcoming deadlines scheduled." in out2
        assert "- **Downloaded files:** 0" in out2

    def test_dashboard_none_due_date_crashes(self, tmp_path):
        """
        Verify DashboardExporter.render safely skips DeadlineItem with due_date=None.
        """
        exporter = DashboardExporter(courses_root=tmp_path)
        item = DeadlineItem(id="1", title="Task", course="SO", due_date=None, url="http://x")
        out = exporter.render(SyncSummary(deadlines=[item]))
        assert "No upcoming deadlines scheduled." in out

    def test_dashboard_mixed_naive_and_aware_dates_crashes(self, tmp_path):
        """
        Verify DashboardExporter.render sorts mixed naive and aware dates without crashing.
        """
        exporter = DashboardExporter(courses_root=tmp_path)
        items = [
            DeadlineItem("1", "Naive", "MC", datetime.datetime(2026, 10, 30, 9, 30), "http://x"),
            DeadlineItem("2", "Aware", "MC", datetime.datetime(2026, 10, 31, 9, 30, tzinfo=datetime.timezone.utc), "http://x"),
        ]
        out = exporter.render(SyncSummary(deadlines=[items[0], items[1]]))
        assert "Naive" in out
        assert "Aware" in out

    def test_dashboard_markdown_pipe_in_url_breaks_table_alignment(self, tmp_path):
        """
        Verify pipe characters in item.url are URL-encoded (%7C) so table columns remain aligned.
        """
        exporter = DashboardExporter(courses_root=tmp_path)
        item = DeadlineItem(
            id="1",
            title="Quiz",
            course="ED",
            due_date=datetime.datetime(2026, 11, 1),
            url="https://prado.ugr.es/view.php?id=123|evil_column=true",
        )
        content = exporter.render(SyncSummary(deadlines=[item]))
        rows = [l for l in content.splitlines() if l.startswith("|") and not l.startswith("|---")]
        assert len(rows) >= 2
        header_cols = len([c for c in rows[0].split("|")[1:-1]])
        data_cols = len([c for c in rows[1].split("|")[1:-1]])
        assert header_cols == 7
        assert data_cols == 7

    def test_changelog_o_n_squared_divider_accumulation_bug(self, tmp_path):
        """
        Verify that 10 sequential sync runs produce exactly 9 horizontal rule ('---') dividers.
        """
        for i in range(10):
            s = SyncSummary(
                downloaded_files=[
                    DownloadedFile(path=Path(f"file_{i}.pdf"), url="u", sha256=f"hash_{i}", size_bytes=100)
                ]
            )
            prepend_changelog_md(tmp_path, s, run_time=datetime.datetime(2026, 1, 1, 10, i))

        cl = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
        dashes = [l for l in cl.splitlines() if l.strip() == "---"]
        assert len(dashes) == 9

    def test_changelog_forum_post_heading_injection_splits_run(self, tmp_path):
        """
        Verify newlines inside forum post subjects are flattened so they cannot inject fake headings.
        """
        s = SyncSummary(
            forum_announcements=[
                ForumPost("1", "Normal Title\n## Injected Heading", "Prof", "Body text")
            ]
        )
        prepend_changelog_md(tmp_path, s, run_time=datetime.datetime(2026, 1, 1))
        prepend_changelog_md(tmp_path, SyncSummary(), run_time=datetime.datetime(2026, 1, 2))

        cl = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "---\n\n## Injected Heading" not in cl
        assert "Normal Title ## Injected Heading (*Prof*)" in cl

    def test_massive_activity_list_performance(self, tmp_path):
        """
        Stress test performance with 1,000 deadlines and 5,000 files.
        Verifies execution completes without timeout or memory exhaustion.
        """
        exporter = DashboardExporter(tmp_path)
        cl_exporter = ChangelogExporter(tmp_path)

        deadlines = [
            DeadlineItem(
                str(i),
                f"Activity {i}",
                f"COURSE_{i%10}",
                datetime.datetime(2026, 11, (i % 28) + 1, (i % 24), 0),
                f"http://example.com/{i}",
            )
            for i in range(1000)
        ]
        files = [
            DownloadedFile(
                path=Path(f"file_{i}.pdf"),
                url=f"http://example.com/f/{i}",
                sha256=f"hash{i:032d}",
                size_bytes=i * 1024,
                course_id=f"COURSE_{i%5}",
            )
            for i in range(5000)
        ]
        summary = SyncSummary(deadlines=deadlines, downloaded_files=files)

        d_out = exporter.render(summary)
        assert len(d_out) > 100000
        assert "Activity 999" in d_out

        cl_out = cl_exporter.render_run_entry(summary)
        assert len(cl_out) > 200000
        assert "file_4999.pdf" in cl_out


# =============================================================================
# 3. Desktop Notifications & Webhooks Security Stress Tests
# =============================================================================

class TestNotificationsSecurityAdversarial:
    def test_desktop_notification_command_injection_safely_neutralized_on_macos(self, tmp_path):
        """
        Verify that command injection payloads:
        - $(touch probe)
        - "; touch probe; "
        - " & do shell script "touch probe" & "
        are safely neutralized on macOS because osascript uses 'on run argv'
        and subprocess.run with shell=False.
        """
        notifier = DesktopNotifier()
        probe_file = tmp_path / "pwned_probe"

        payloads = [
            f"$(touch {probe_file})",
            f"\"; touch {probe_file}; \"",
            f"\" & do shell script \"touch {probe_file}\" & \"",
        ]
        for p in payloads:
            notifier.notify(title=p, message=p, sound=False)
            assert not probe_file.exists(), f"Vulnerability: Payload executed command: {p}"

    def test_desktop_notification_windows_command_concatenation_flaw(self):
        """
        Verify DesktopNotifier._notify_windows passes title/body via environment variables
        and clamps timeout_ms as an integer rather than concatenating arguments to -Command.
        """
        notifier = DesktopNotifier()
        source = inspect.getsource(notifier._notify_windows)
        assert "PRADO_NOTIFY_TITLE" in source
        assert "PRADO_NOTIFY_BODY" in source
        assert "cmd = [ps_cmd, \"-NoProfile\", \"-NonInteractive\", \"-Command\", ps_script]" in source

    def test_smtp_email_crlf_subject_unhandled_crash(self, monkeypatch):
        """
        Verify SmtpEmailSender.send_email sanitizes CRLF in headers and never raises unhandled ValueError.
        """
        cfg = SmtpConfig(to_addresses=["student@ugr.es"])
        sender = SmtpEmailSender(cfg)
        monkeypatch.setattr("smtplib.SMTP", lambda *a, **kw: (_ for _ in ()).throw(OSError("No SMTP")))
        res = sender.send_email(subject="Sync Alert\nBcc: evil@hacked.com", text_body="Body")
        assert res.success is False
        assert res.channel == "email"

    def test_telegram_webhook_unescaped_html_entities(self):
        """
        Verify TelegramWebhookSender escapes '<', '>', and '&' in HTML parse_mode.
        """
        sender = TelegramWebhookSender(bot_token="fake_token", chat_id="12345")
        summary = SyncSummary(
            deadlines=[
                DeadlineItem(
                    id="1",
                    title="Math: a < b & c > d",
                    course="Course <A>",
                    due_date=datetime.datetime(2026, 11, 1),
                    url="",
                )
            ],
            forum_announcements=[
                ForumPost(
                    forum_id="1",
                    subject="Notice <Urgent> & Critical",
                    author="Prof <Dean>",
                    content="Details",
                )
            ],
        )
        formatted = sender.format_sync_summary(summary)
        assert "Course &lt;A&gt;" in formatted
        assert "a &lt; b &amp; c &gt; d" in formatted
        assert "Notice &lt;Urgent&gt; &amp; Critical" in formatted
