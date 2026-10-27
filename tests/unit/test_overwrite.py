"""
Unit tests for OverwriteGuard and 4-quadrant collision decision matrix.
"""
from __future__ import annotations

import datetime
import hashlib
from pathlib import Path
import pytest

from prado.core.overwrite import (
    CollisionQuadrant,
    CollisionResolution,
    OverwriteGuard,
    format_collision_fork_name,
    split_filename_and_extension,
)
from prado.state import FileRecord, StateDatabase


class TestSplitFilenameAndExtension:
    def test_compound_extensions(self):
        assert split_filename_and_extension("archive.tar.gz") == ("archive", ".tar.gz")
        assert split_filename_and_extension("backup.tar.bz2") == ("backup", ".tar.bz2")
        assert split_filename_and_extension("data.tar.xz") == ("data", ".tar.xz")

    def test_extensionless_files(self):
        assert split_filename_and_extension("Makefile") == ("Makefile", "")
        assert split_filename_and_extension("Dockerfile") == ("Dockerfile", "")
        assert split_filename_and_extension("LICENSE") == ("LICENSE", "")

    def test_standard_extensions(self):
        assert split_filename_and_extension("Practica_2.ipynb") == ("Practica_2", ".ipynb")
        assert split_filename_and_extension("Tema_1.pdf") == ("Tema_1", ".pdf")
        assert split_filename_and_extension("main.cpp") == ("main", ".cpp")


class TestFormatCollisionForkName:
    def test_format_with_specific_datetime(self):
        dt = datetime.datetime(2026, 10, 27, 19, 30, 0)
        assert format_collision_fork_name("lab1.docx", dt) == "lab1_server_20261027_193000.docx"
        assert format_collision_fork_name("dataset.tar.gz", dt) == "dataset_server_20261027_193000.tar.gz"
        assert format_collision_fork_name("Makefile", dt) == "Makefile_server_20261027_193000"


class Test4QuadrantMatrix:
    def test_quadrant_1_unmodified_both_up_to_date(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        guard = OverwriteGuard(db)
        local_file = tmp_path / "Tema_1.pdf"
        content = b"%PDF-1.4 Initial content"
        local_file.write_bytes(content)
        h = hashlib.sha256(content).hexdigest()

        db.upsert_file(FileRecord(path="ED_C/Teoria/Tema_1.pdf", original_hash=h, current_hash=h))

        decision = guard.evaluate(
            local_abs_path=local_file,
            rel_path="ED_C/Teoria/Tema_1.pdf",
            server_hash=h,
        )

        assert decision.quadrant == CollisionQuadrant.Q1_UP_TO_DATE
        assert decision.action == "up_to_date"

    def test_quadrant_2_local_unmodified_server_updated_safe_replace(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        guard = OverwriteGuard(db)
        local_file = tmp_path / "Tema_1.pdf"
        content_v1 = b"%PDF-1.4 Version 1"
        local_file.write_bytes(content_v1)
        h_v1 = hashlib.sha256(content_v1).hexdigest()

        db.upsert_file(FileRecord(path="ED_C/Teoria/Tema_1.pdf", original_hash=h_v1, current_hash=h_v1))

        content_v2 = b"%PDF-1.4 Version 2 Professor Fix"
        h_v2 = hashlib.sha256(content_v2).hexdigest()

        decision = guard.evaluate(
            local_abs_path=local_file,
            rel_path="ED_C/Teoria/Tema_1.pdf",
            server_hash=h_v2,
        )

        assert decision.quadrant == CollisionQuadrant.Q2_SAFE_REPLACE
        assert decision.action == "safe_in_place_replace"

    def test_quadrant_3_local_modified_server_unchanged_preserve_student(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        guard = OverwriteGuard(db)
        local_file = tmp_path / "Practica_1.ipynb"
        orig_content = b'{"cells": ["original starter"]}'
        orig_hash = hashlib.sha256(orig_content).hexdigest()

        # Student worked on assignment locally
        student_content = b'{"cells": ["student solution 15 hours work"]}'
        local_file.write_bytes(student_content)

        db.upsert_file(FileRecord(path="ED_C/Practicas/Practica_1.ipynb", original_hash=orig_hash, current_hash=orig_hash))

        decision = guard.evaluate(
            local_abs_path=local_file,
            rel_path="ED_C/Practicas/Practica_1.ipynb",
            server_hash=orig_hash,  # Server unchanged
        )

        assert decision.quadrant == CollisionQuadrant.Q3_PRESERVE_STUDENT
        assert decision.action == "preserve_student_work"
        # Verify student modification flag is set in state db
        rec = db.get_file("ED_C/Practicas/Practica_1.ipynb")
        assert rec.student_modified == 1

    def test_quadrant_4_collision_saves_timestamped_copy(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        guard = OverwriteGuard(db)
        local_file = tmp_path / "Practica_2.ipynb"

        orig_content = b'{"cells": ["original starter"]}'
        orig_hash = hashlib.sha256(orig_content).hexdigest()

        student_content = b'{"cells": ["student valuable code"]}'
        local_file.write_bytes(student_content)

        db.upsert_file(FileRecord(path="VC_A/Practicas/Practica_2.ipynb", original_hash=orig_hash))

        server_updated = b'{"cells": ["professor typo update"]}'
        server_hash = hashlib.sha256(server_updated).hexdigest()

        decision = guard.evaluate(
            local_abs_path=local_file,
            rel_path="VC_A/Practicas/Practica_2.ipynb",
            server_hash=server_hash,
        )

        assert decision.quadrant == CollisionQuadrant.Q4_COLLISION_FORK
        assert decision.action == "collision_fork"
        assert decision.forked_path is not None
        assert "Practica_2_server_" in decision.forked_path.name
        assert decision.forked_path.name.endswith(".ipynb")
        # Ensure student file remains untouched!
        assert local_file.read_bytes() == student_content

    def test_file_not_found_fresh_download(self, tmp_path):
        db = StateDatabase(tmp_path / "state.db")
        guard = OverwriteGuard(db)
        local_file = tmp_path / "nonexistent.pdf"

        decision = guard.evaluate(
            local_abs_path=local_file,
            rel_path="ED_C/Teoria/nonexistent.pdf",
            server_hash="somehash",
        )

        assert decision.quadrant == CollisionQuadrant.DOWNLOAD_NEW
        assert decision.action == "download"

    def test_directory_collision_fork(self, tmp_path):
        """Verify that an existing directory at local_abs_path does not trigger IsADirectoryError and forks safely."""
        db = StateDatabase(tmp_path / "state.db")
        guard = OverwriteGuard(db)
        local_dir = tmp_path / "Practica_1.pdf"
        local_dir.mkdir()

        decision = guard.evaluate(
            local_abs_path=local_dir,
            rel_path="ED_C/Practicas/Practica_1.pdf",
            server_hash="serverhash123",
        )

        assert decision.quadrant == CollisionQuadrant.Q4_COLLISION_FORK
        assert decision.action == "collision_fork"
        assert decision.forked_path is not None
        assert decision.forked_path.name.startswith("Practica_1_server_")
        assert decision.forked_path.name.endswith(".pdf")
        assert local_dir.is_dir()
