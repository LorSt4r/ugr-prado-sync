"""
Unit tests for CourseHtmlParser and activity extraction engine.
"""
from __future__ import annotations

import datetime
import pytest

from prado.core.parser import (
    ActivityType,
    CourseActivity,
    CourseHtmlParser,
    FileAttachment,
    ParsedCourse,
    SectionInfo,
    clean_activity_title,
    parse_moodle_date,
)
from prado.parser import (
    CourseActivity as CATopLevel,
    CourseHtmlParser as CHPTopLevel,
    clean_activity_title as clean_top_level,
    parse_moodle_date as parse_date_top_level,
)


class TestActivityTitleCleaning:
    def test_clean_html_entities(self):
        raw = "Tema 1: Eficiencia &amp; An&aacute;lisis de Algoritmos"
        cleaned = clean_activity_title(raw)
        assert cleaned == "Tema 1: Eficiencia & Análisis de Algoritmos"

    def test_strip_accessibility_suffixes(self):
        suffixes = [
            ("Tema 1 Diapositivas Archivo", "Tema 1 Diapositivas"),
            ("Guiones de Prácticas Carpeta", "Guiones de Prácticas"),
            ("Entrega Práctica 1 Tarea", "Entrega Práctica 1"),
            ("Avisos y Novedades Foro", "Avisos y Novedades"),
            ("Guía Docente URL", "Guía Docente"),
            ("Slides Chapter 1 File", "Slides Chapter 1"),
            ("Code Starter Folder", "Code Starter"),
            ("Lab 1 Submission Assignment", "Lab 1 Submission"),
        ]
        for raw, expected in suffixes:
            assert clean_activity_title(raw) == expected

    def test_clean_whitespace_and_empty(self):
        assert clean_activity_title("   \t  \n  ") == ""
        assert clean_activity_title(None) == ""
        assert clean_activity_title("Normal Title") == "Normal Title"


class TestDateParsing:
    def test_parse_spanish_dates(self):
        dt1 = parse_moodle_date("lunes, 14 de diciembre de 2026, 23:59")
        assert dt1 == datetime.datetime(2026, 12, 14, 23, 59)

        dt2 = parse_moodle_date("14 de diciembre de 2026")
        assert dt2 == datetime.datetime(2026, 12, 14, 0, 0)

        dt3 = parse_moodle_date("martes, 27 de octubre de 2026, 19:30")
        assert dt3 == datetime.datetime(2026, 10, 27, 19, 30)

        dt4 = parse_moodle_date("viernes, 30 de octubre de 2026, 09:30")
        assert dt4 == datetime.datetime(2026, 10, 30, 9, 30)

    def test_parse_english_dates(self):
        dt1 = parse_moodle_date("Monday, 14 December 2026, 11:59 PM")
        assert dt1 == datetime.datetime(2026, 12, 14, 23, 59)

        dt2 = parse_moodle_date("Friday, 30 October 2026, 9:30 AM")
        assert dt2 == datetime.datetime(2026, 10, 30, 9, 30)

    def test_parse_invalid_or_empty_dates(self):
        assert parse_moodle_date("") is None
        assert parse_moodle_date(None) is None
        assert parse_moodle_date("Sin fecha de entrega") is None


class TestCoursePageParsing:
    def test_parse_full_course_page(self, sample_html_fixtures):
        html = sample_html_fixtures["moodle_course_15819"]
        parsed = CourseHtmlParser.parse_course_page(
            html_content=html,
            course_id="15819",
            base_url="https://pradogrado2627.ugr.es",
        )
        assert isinstance(parsed, ParsedCourse)
        assert parsed.course_id == "15819"
        assert len(parsed.sections) == 5

        # Check section 0 (General)
        sec0 = parsed.sections[0]
        assert sec0.id == "section-0"
        assert len(sec0.activities) >= 1

        # Check section 1 (Tema 1)
        sec1 = parsed.sections[1]
        assert sec1.id == "section-1"
        assert "Tema 1" in sec1.name
        assert any(a.mod_type == "resource" for a in sec1.activities)

        # Check activities list has distinct IDs
        act_ids = [a.id for a in parsed.activities]
        assert len(act_ids) == len(set(act_ids))
        assert "107913" in act_ids

    def test_parse_empty_course_page(self):
        parsed = CourseHtmlParser.parse_course_page(
            html_content="<html><body><p>Empty</p></body></html>",
            course_id="999",
        )
        assert parsed.course_id == "999"
        assert len(parsed.sections) == 0
        assert len(parsed.activities) == 0


class TestAssignmentParsing:
    def test_parse_assignment_due_date_and_attachments(self, sample_html_fixtures):
        html = sample_html_fixtures["moodle_assign_107917"]
        act = CourseActivity(
            id="107917",
            course_id="15819",
            section_id="section-3",
            section_name="Prácticas (Grupo C2)",
            mod_type="assign",
            title="Entrega Práctica 1",
            url="https://pradogrado2627.ugr.es/mod/assign/view.php?id=107917",
        )
        enriched = CourseHtmlParser.parse_assignment_page(
            html_content=html,
            activity=act,
            base_url="https://pradogrado2627.ugr.es",
        )
        assert enriched.due_date is not None
        assert enriched.due_date.year == 2026
        assert enriched.due_date.month == 12
        assert enriched.due_date.day == 14
        assert len(enriched.attachments) >= 1
        assert "Practica_1_starter.ipynb" in enriched.attachments[0].name
        assert "forcedownload=1" in enriched.attachments[0].download_url


class TestFolderParsing:
    def test_parse_folder_multiple_files(self, sample_html_fixtures):
        html = sample_html_fixtures["moodle_folder_107914"]
        act = CourseActivity(
            id="107914",
            course_id="15819",
            section_id="section-2",
            section_name="Tema 2: Árboles",
            mod_type="folder",
            title="Material Adicional Árboles",
            url="https://pradogrado2627.ugr.es/mod/folder/view.php?id=107914",
        )
        files = CourseHtmlParser.parse_folder_page(
            html_content=html,
            activity=act,
            base_url="https://pradogrado2627.ugr.es",
        )
        assert len(files) == 2
        names = [f.name for f in files]
        assert any("arboles_avl.pdf" in n for n in names)
        assert any("arboles_b.pdf" in n for n in names)
        assert all("forcedownload=1" in f.download_url for f in files)


class TestForumParsing:
    def test_parse_forum_announcements(self, sample_html_fixtures):
        html = sample_html_fixtures["moodle_forum_107901"]
        act = CourseActivity(
            id="107901",
            course_id="15819",
            section_id="section-0",
            section_name="General",
            mod_type="forum",
            title="Avisos y Novedades",
            url="https://pradogrado2627.ugr.es/mod/forum/view.php?id=107901",
        )
        posts = CourseHtmlParser.parse_forum_announcements(
            html_content=html,
            activity=act,
            base_url="https://pradogrado2627.ugr.es",
        )
        assert len(posts) >= 1
        assert "Calendario de Prácticas" in posts[0]["subject"]
        assert "García Silvente" in posts[0]["author"]
        assert len(posts[0]["content"]) > 0


class TestTopLevelReExports:
    def test_re_exports_match(self):
        assert CATopLevel is CourseActivity
        assert CHPTopLevel is CourseHtmlParser
        assert clean_top_level is clean_activity_title
        assert parse_date_top_level is parse_moodle_date
