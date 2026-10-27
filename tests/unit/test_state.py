"""
Unit tests for StateDatabase SQLite state engine.
"""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import pytest

from prado.state import CourseRecord, FileRecord, StateDatabase


class TestStateDbInitialization:
    def test_database_initialization_tables_and_wal(self, tmp_path):
        db_path = tmp_path / "state.db"
        db = StateDatabase(db_path)

        assert db_path.exists()
        if os.name != "nt":
            mode = oct(db_path.stat().st_mode & 0o777)
            assert mode in (oct(0o600), oct(0o644), oct(0o664))

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Check WAL mode
        cur.execute("PRAGMA journal_mode;")
        journal = cur.fetchone()[0]
        assert journal.upper() == "WAL"

        # Check tables exist
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cur.fetchall()}
        assert "meta" in tables
        assert "courses" in tables
        assert "files" in tables
        assert "resources" in tables

        conn.close()


class TestCoursesCrud:
    def test_upsert_and_get_course(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        c = CourseRecord(
            course_id=15819,
            fullname="ESTRUCTURA DE DATOS - 2627 (Grupo C)",
            shortname="ED_2627_C",
            idnumber="296_11_22_2627_C",
            category="Informatica",
            is_active=1,
        )
        db.upsert_course(c)

        retrieved = db.get_course(15819)
        assert retrieved is not None
        assert retrieved.course_id == 15819
        assert retrieved.fullname == "ESTRUCTURA DE DATOS - 2627 (Grupo C)"
        assert retrieved.category == "Informatica"
        assert retrieved.is_active == 1

        # Test non-existent course
        assert db.get_course(99999) is None

    def test_toggle_course_active_and_listing(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        c1 = CourseRecord(course_id=1, fullname="Course 1", is_active=1)
        c2 = CourseRecord(course_id=2, fullname="Course 2", is_active=1)
        db.upsert_course(c1)
        db.upsert_course(c2)

        assert len(db.list_active_courses()) == 2

        # Deactivate course 2
        db.set_course_active(2, False)
        active = db.list_active_courses()
        assert len(active) == 1
        assert active[0].course_id == 1

        all_courses = db.list_all_courses()
        assert len(all_courses) == 2


class TestFilesCrudAndResourcesSync:
    def test_upsert_and_get_file(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        rec = FileRecord(
            path="ED_C/Teoria/Tema_1.pdf",
            course_id=15819,
            resource_id=107913,
            remote_url="https://prado.ugr.es/view.php?id=107913",
            original_hash="sha_abc",
            file_size=1024,
            is_adopted=0,
            student_modified=0,
        )
        db.upsert_file(rec)

        f = db.get_file("ED_C/Teoria/Tema_1.pdf")
        assert f is not None
        assert f.path == "ED_C/Teoria/Tema_1.pdf"
        assert f.original_hash == "sha_abc"
        assert f.file_size == 1024

        # Verify resources table synchronization
        conn = sqlite3.connect(tmp_path / "state.db")
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM resources WHERE resource_id = 107913")
        r = cur.fetchone()
        assert r is not None
        assert r["title"] == "Tema_1.pdf"
        assert r["original_sha256"] == "sha_abc"
        conn.close()

    def test_get_file_by_resource_id(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        rec = FileRecord(
            path="SO_E/Practicas/P1.pdf",
            course_id=15820,
            resource_id=20001,
            original_hash="sha_so_1",
        )
        db.upsert_file(rec)

        found = db.get_file_by_resource_id(20001)
        assert found is not None
        assert found.path == "SO_E/Practicas/P1.pdf"

        assert db.get_file_by_resource_id(99999) is None

    def test_list_files_filter(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        db.upsert_file(FileRecord(path="ED/f1.pdf", course_id=1, original_hash="h1"))
        db.upsert_file(FileRecord(path="ED/f2.pdf", course_id=1, original_hash="h2"))
        db.upsert_file(FileRecord(path="SO/f3.pdf", course_id=2, original_hash="h3"))

        assert len(db.list_files()) == 3
        assert len(db.list_files(course_id=1)) == 2
        assert len(db.list_files(course_id=2)) == 1


class TestMarkModifiedAndAdopted:
    def test_mark_modified(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        db.upsert_file(FileRecord(path="lab1.ipynb", resource_id=101, original_hash="h1", student_modified=0))

        db.mark_modified("lab1.ipynb", True)
        f = db.get_file("lab1.ipynb")
        assert f.student_modified == 1
        assert f.is_modified == 1

        # Check resources table
        conn = sqlite3.connect(tmp_path / "state.db")
        cur = conn.execute("SELECT student_modified FROM resources WHERE path = 'lab1.ipynb'")
        assert cur.fetchone()[0] == 1
        conn.close()

    def test_mark_adopted(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        db.upsert_file(FileRecord(path="guide.pdf", resource_id=102, original_hash="old_h", is_adopted=0))

        db.mark_adopted("guide.pdf", "new_verified_h")
        f = db.get_file("guide.pdf")
        assert f.is_adopted == 1
        assert f.original_hash == "new_verified_h"
        assert f.student_modified == 0


class TestSqlInjectionProtection:
    def test_sql_injection_payload_in_path(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        injection_path = "'; DROP TABLE files; --"

        rec = FileRecord(path=injection_path, original_hash="safe_hash")
        db.upsert_file(rec)

        # Confirm table still exists and record retrieved safely
        f = db.get_file(injection_path)
        assert f is not None
        assert f.path == injection_path
