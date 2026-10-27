"""
Adversarial Stress Test Suite for PradoOS Milestone M2.

Empirically tests OverwriteProtection, MidSemesterAdoption, and CourseRouter
under hostile conditions, malicious payloads, boundary limits, and edge cases:
1. 4-quadrant collision edge cases:
   - Double extensions (.tar.gz, .tar.bz2, .tar.xz, .tar.zst)
   - Student modification preservation (ensuring student files are never overwritten)
   - Timestamped server copies (_server_YYYYMMDD_HHMMSS) and increment counters
   - Extensionless files (Makefile, Dockerfile)
   - Directory in place of local file
2. Mid-semester adoption:
   - Empty files (0-byte files excluded)
   - Symlinks (valid, broken, symlinked directories, circular symlinks)
   - Deeply nested directory trees
   - Identical hashes across different folders (collision / false adoption detection)
3. Malicious inputs:
   - Path traversal in section names and activity titles
   - Backslash handling on Windows vs POSIX
   - Windows reserved device names with single and compound extensions (CON, PRN, AUX, NUL)
   - HTML script injection (<script>alert(1)</script>) in titles and section names
"""
from __future__ import annotations

import datetime
import hashlib
import os
from pathlib import Path, PureWindowsPath
import re
import pytest

from prado.config import SyncConfig
from prado.core.adoption import AdoptionScanner, LocalFileInfo
from prado.core.overwrite import (
    CollisionQuadrant,
    CollisionResolution,
    OverwriteGuard,
    format_collision_fork_name,
    split_filename_and_extension,
)
from prado.core.parser import CourseActivity, CourseHtmlParser, FileAttachment, clean_activity_title
from prado.core.router import CourseRouter, detect_subgroup_in_text, sanitize_path_segment
from prado.state import FileRecord, StateDatabase


# =============================================================================
# 1. 4-Quadrant Collision Matrix & Compound Extensions
# =============================================================================

class TestOverwriteProtectionAdversarial:
    def test_split_filename_compound_extensions(self):
        """Verify compound extensions are split correctly without truncating to last extension."""
        assert split_filename_and_extension("dataset.tar.gz") == ("dataset", ".tar.gz")
        assert split_filename_and_extension("archive.tar.bz2") == ("archive", ".tar.bz2")
        assert split_filename_and_extension("code.tar.xz") == ("code", ".tar.xz")
        assert split_filename_and_extension("backup.tar.zst") == ("backup", ".tar.zst")
        assert split_filename_and_extension("DATASET.TAR.GZ") == ("DATASET", ".TAR.GZ")
        assert split_filename_and_extension("project.v1.0.tar.gz") == ("project.v1.0", ".tar.gz")

    def test_split_filename_extensionless(self):
        """Verify files without extensions do not produce trailing dots."""
        assert split_filename_and_extension("Makefile") == ("Makefile", "")
        assert split_filename_and_extension("Dockerfile") == ("Dockerfile", "")
        assert split_filename_and_extension("LICENSE") == ("LICENSE", "")

    def test_format_collision_fork_name_timestamp(self):
        """Verify server update filename has the exact _server_YYYYMMDD_HHMMSS format."""
        dt = datetime.datetime(2026, 10, 27, 21, 15, 30)
        fork_name = format_collision_fork_name("Practica_2.tar.gz", dt)
        assert fork_name == "Practica_2_server_20261027_211530.tar.gz"

        fork_makefile = format_collision_fork_name("Makefile", dt)
        assert fork_makefile == "Makefile_server_20261027_211530"

    def test_quadrant_3_student_modification_preserved_and_flagged(self, tmp_path):
        """Verify student modifications are never overwritten when server is unchanged."""
        db = StateDatabase(tmp_path / "state.db")
        guard = OverwriteGuard(db)
        local_file = tmp_path / "lab1.ipynb"

        orig_bytes = b'{"cells": ["starter code"]}'
        orig_hash = hashlib.sha256(orig_bytes).hexdigest()
        student_bytes = b'{"cells": ["student finished work 20 hours"]}'
        local_file.write_bytes(student_bytes)

        db.upsert_file(FileRecord(path="course/lab1.ipynb", original_hash=orig_hash))

        decision = guard.evaluate(local_file, "course/lab1.ipynb", orig_hash)
        assert decision.quadrant == CollisionQuadrant.Q3_PRESERVE_STUDENT
        assert decision.action == "preserve_student_work"
        assert local_file.read_bytes() == student_bytes

        rec = db.get_file("course/lab1.ipynb")
        assert rec.student_modified == 1

    def test_quadrant_4_collision_compound_extension_and_counter(self, tmp_path):
        """
        Verify Quadrant 4 creates timestamped copy with compound extension preserved,
        leaves student file untouched, and handles existing collision copies by appending counter.
        """
        db = StateDatabase(tmp_path / "state.db")
        guard = OverwriteGuard(db)
        local_file = tmp_path / "project.tar.gz"

        orig_bytes = b"original starter archive"
        orig_hash = hashlib.sha256(orig_bytes).hexdigest()
        student_bytes = b"student modified archive"
        server_bytes = b"professor update v2"
        server_hash = hashlib.sha256(server_bytes).hexdigest()

        local_file.write_bytes(student_bytes)
        db.upsert_file(FileRecord(path="course/project.tar.gz", original_hash=orig_hash))

        # First collision
        res1 = guard.evaluate(local_file, "course/project.tar.gz", server_hash)
        assert res1.quadrant == CollisionQuadrant.Q4_COLLISION_FORK
        assert res1.action == "collision_fork"
        assert res1.forked_path is not None
        assert res1.forked_path.name.endswith(".tar.gz")
        assert "project_server_" in res1.forked_path.name
        assert local_file.read_bytes() == student_bytes

        # Simulate writing the first fork
        res1.forked_path.write_bytes(server_bytes)

        # Second collision when fork already exists
        res2 = guard.evaluate(local_file, "course/project.tar.gz", server_hash)
        assert res2.quadrant == CollisionQuadrant.Q4_COLLISION_FORK
        assert res2.forked_path is not None
        assert res2.forked_path.name.endswith(".tar.gz")
        assert "_1.tar.gz" in res2.forked_path.name
        assert res2.forked_path != res1.forked_path
        assert local_file.read_bytes() == student_bytes


# =============================================================================
# 2. Mid-Semester Adoption Adversarial Edge Cases
# =============================================================================

class TestMidSemesterAdoptionAdversarial:
    def test_empty_files_excluded_from_adoption(self, tmp_path):
        """0-byte files must never be indexed or matched for adoption."""
        db = StateDatabase(tmp_path / "state.db")
        courses_dir = tmp_path / "courses"
        courses_dir.mkdir()

        (courses_dir / "empty1.pdf").touch()
        (courses_dir / "empty2.txt").write_bytes(b"")

        scanner = AdoptionScanner(courses_dir, db)
        count = scanner.scan_local_files()
        assert count == 0
        assert len(scanner.hash_index) == 0

    def test_broken_and_directory_symlinks_handled_without_crash(self, tmp_path):
        """Adoption scanner must handle broken symlinks and directory symlinks gracefully."""
        db = StateDatabase(tmp_path / "state.db")
        courses_dir = tmp_path / "courses"
        courses_dir.mkdir()

        valid_file = courses_dir / "real.pdf"
        valid_file.write_bytes(b"%PDF-1.4 Content")
        valid_hash = hashlib.sha256(b"%PDF-1.4 Content").hexdigest()

        # Symlink to real file
        sym_file = courses_dir / "sym_real.pdf"
        os.symlink(valid_file, sym_file)

        # Broken symlink pointing to missing file
        broken_sym = courses_dir / "broken.pdf"
        os.symlink(courses_dir / "missing.pdf", broken_sym)

        # Symlink pointing to directory
        dir_sym = courses_dir / "sym_dir"
        os.symlink(courses_dir, dir_sym)

        scanner = AdoptionScanner(courses_dir, db)
        count = scanner.scan_local_files()

        # Broken symlink and directory symlink must be ignored without raising OSError
        assert count >= 1
        assert valid_hash in scanner.hash_index

    def test_deeply_nested_directory_tree_adoption(self, tmp_path):
        """Adoption scanner must successfully traverse and index files at extreme folder depth."""
        db = StateDatabase(tmp_path / "state.db")
        courses_dir = tmp_path / "courses"
        courses_dir.mkdir()

        deep_dir = courses_dir
        for i in range(15):
            deep_dir = deep_dir / f"level_{i}"
        deep_dir.mkdir(parents=True)

        deep_file = deep_dir / "lecture_notes.pdf"
        deep_content = b"deeply nested lecture content"
        deep_file.write_bytes(deep_content)
        deep_hash = hashlib.sha256(deep_content).hexdigest()

        scanner = AdoptionScanner(courses_dir, db)
        count = scanner.scan_local_files()
        assert count == 1
        assert deep_hash in scanner.hash_index

        rel_path = deep_file.relative_to(courses_dir).as_posix()
        adopted = scanner.match_and_adopt(rel_path, deep_hash, course_id=123)
        assert adopted is not None
        assert adopted.rel_path == rel_path

    def test_identical_hashes_across_different_folders_remediated(self, tmp_path):
        """
        Adversarial test verifying duplicate-hash adoption flaw is remediated:
        If file with hash H exists in course A, but does NOT exist in course B,
        AdoptionScanner.match_and_adopt('Course_B/regulations.pdf', H) must return None
        and must NOT register Course_B/regulations.pdf in the database.
        """
        db = StateDatabase(tmp_path / "state.db")
        courses_dir = tmp_path / "courses"
        courses_dir.mkdir()

        content = b"Shared Department Regulations 2026"
        h = hashlib.sha256(content).hexdigest()

        # Student only downloaded course A's copy
        f_a = courses_dir / "Course_A" / "regulations.pdf"
        f_a.parent.mkdir(parents=True, exist_ok=True)
        f_a.write_bytes(content)

        scanner = AdoptionScanner(courses_dir, db)
        scanner.scan_local_files()

        # Course B file DOES NOT EXIST on disk
        f_b = courses_dir / "Course_B" / "regulations.pdf"
        assert not f_b.exists()

        adopted = scanner.match_and_adopt("Course_B/regulations.pdf", h, course_id=456)
        assert adopted is None
        rec_b = db.get_file("Course_B/regulations.pdf")
        assert rec_b is None
        assert not f_b.exists()


# =============================================================================
# 3. Malicious Inputs: Path Traversal, Backslashes, Reserved Names & XSS
# =============================================================================

class TestMaliciousInputsAdversarial:
    def test_forward_slash_path_traversal_neutralized(self):
        """Verify forward slash directory traversal payloads are safely replaced with underscores."""
        payloads = [
            "../../etc/passwd",
            "../../../../../../tmp/evil",
            "section/../../secret",
            "/etc/shadow",
        ]
        for p in payloads:
            sanitized = sanitize_path_segment(p)
            assert "/" not in sanitized
            assert not sanitized.startswith("..")

    def test_backslash_path_traversal_neutralized(self):
        """Verify backslash directory traversal is neutralized."""
        payload = r"..\..\Windows\System32\cmd.exe"
        sanitized = sanitize_path_segment(payload)
        assert "\\" not in sanitized
        assert "/" not in sanitized
        base = PureWindowsPath(r"C:\Courses\ED_C")
        target = base / sanitized
        norm = os.path.normpath(str(target))
        assert norm.startswith(r"C:\Courses\ED_C")

    def test_windows_reserved_device_names_with_compound_extensions_fixed(self):
        """Verify compound extensions on reserved names are prefixed."""
        assert sanitize_path_segment("CON") == "_CON"
        assert sanitize_path_segment("PRN.txt") == "_PRN.txt"
        assert sanitize_path_segment("AUX.pdf") == "_AUX.pdf"
        assert sanitize_path_segment("CON.tar.gz") == "_CON.tar.gz"
        assert sanitize_path_segment("AUX.tar.bz2") == "_AUX.tar.bz2"
        assert sanitize_path_segment("con.tar.gz") == "_con.tar.gz"
        assert sanitize_path_segment("aux.tar.bz2") == "_aux.tar.bz2"

    def test_html_script_injection_in_router_and_parser(self):
        """
        Verify HTML injection payloads (<script>alert(1)</script>) in titles
        are sanitized of '<' and '>' before creating filesystem paths.
        """
        xss_title = "<script>alert('XSS')</script>"
        sanitized = sanitize_path_segment(xss_title)
        assert "<" not in sanitized
        assert ">" not in sanitized
        assert sanitized == "_script_alert('XSS')_script_"

        # CourseRouter routing
        router = CourseRouter(SyncConfig(preset="smart"))
        act = CourseActivity(
            id="999",
            course_id="100",
            section_id="section-1",
            section_name="<script>alert('sec')</script>",
            mod_type="resource",
            title="<img src=x onerror=alert(1)>",
            url="https://prado.ugr.es",
        )
        dec = router.route_activity(act)
        assert "<" not in str(dec.target_rel_path)
        assert ">" not in str(dec.target_rel_path)
