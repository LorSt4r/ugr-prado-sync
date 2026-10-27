"""
Unit tests for Mid-Semester Adoption scanner.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import pytest

from prado.core.adoption import AdoptionScanner, LocalFileInfo
from prado.state import StateDatabase


class TestAdoptionScanner:
    def test_prescan_indexes_existing_files(self, tmp_path):
        db_path = tmp_path / "state.db"
        state_db = StateDatabase(db_path)
        courses_dir = tmp_path / "courses"
        courses_dir.mkdir()

        # Create sample files
        f1 = courses_dir / "ED_C" / "Teoria" / "Tema_1.pdf"
        f1.parent.mkdir(parents=True, exist_ok=True)
        c1 = b"%PDF-1.4 Tema 1 Content"
        f1.write_bytes(c1)
        h1 = hashlib.sha256(c1).hexdigest()

        f2 = courses_dir / "ED_C" / "Practicas" / "Guion_1.pdf"
        f2.parent.mkdir(parents=True, exist_ok=True)
        c2 = b"%PDF-1.4 Guion 1 Content"
        f2.write_bytes(c2)
        h2 = hashlib.sha256(c2).hexdigest()

        scanner = AdoptionScanner(courses_root=courses_dir, state_db=state_db)
        count = scanner.scan_local_files()

        assert count == 2
        assert h1 in scanner.hash_index
        assert h2 in scanner.hash_index
        assert scanner.hash_index[h1].rel_path == "ED_C/Teoria/Tema_1.pdf"

    def test_ignore_hidden_and_zero_byte_files(self, tmp_path):
        db_path = tmp_path / "state.db"
        state_db = StateDatabase(db_path)
        courses_dir = tmp_path / "courses"
        courses_dir.mkdir()

        # Regular file
        f_reg = courses_dir / "valid.pdf"
        f_reg.write_bytes(b"valid content")

        # Zero-byte file
        f_zero = courses_dir / "empty.pdf"
        f_zero.touch()

        # Hidden file (.DS_Store)
        f_hidden = courses_dir / ".DS_Store"
        f_hidden.write_bytes(b"macos metadata")

        # File in hidden directory
        git_dir = courses_dir / ".git" / "objects"
        git_dir.mkdir(parents=True, exist_ok=True)
        f_git = git_dir / "commit_obj"
        f_git.write_bytes(b"git data")

        scanner = AdoptionScanner(courses_root=courses_dir, state_db=state_db)
        count = scanner.scan_local_files()

        assert count == 1
        assert len(scanner.hash_index) == 1
        reg_hash = hashlib.sha256(b"valid content").hexdigest()
        assert reg_hash in scanner.hash_index

    def test_match_and_adopt_preserves_disk_mtime(self, tmp_path):
        db_path = tmp_path / "state.db"
        state_db = StateDatabase(db_path)
        courses_dir = tmp_path / "courses"
        courses_dir.mkdir()

        pdf_path = courses_dir / "ED_C" / "Teoria" / "Tema_1.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        content = b"%PDF-1.4 Already downloaded weeks ago"
        pdf_path.write_bytes(content)
        initial_mtime = pdf_path.stat().st_mtime
        server_hash = hashlib.sha256(content).hexdigest()

        scanner = AdoptionScanner(courses_root=courses_dir, state_db=state_db)
        scanner.scan_local_files()

        adopted = scanner.match_and_adopt(
            rel_path="ED_C/Teoria/Tema_1.pdf",
            server_hash=server_hash,
            course_id=15819,
        )

        assert adopted is not None
        assert adopted.sha256 == server_hash
        # Verify 0 disk writes: mtime must be unchanged!
        assert pdf_path.stat().st_mtime == initial_mtime

        # Verify state database registration
        rec = state_db.get_file("ED_C/Teoria/Tema_1.pdf")
        assert rec is not None
        assert rec.is_adopted == 1
        assert rec.original_hash == server_hash
        assert rec.student_modified == 0

    def test_non_matching_hash_returns_none(self, tmp_path):
        db_path = tmp_path / "state.db"
        state_db = StateDatabase(db_path)
        courses_dir = tmp_path / "courses"
        courses_dir.mkdir()

        f = courses_dir / "file.pdf"
        f.write_bytes(b"local content")

        scanner = AdoptionScanner(courses_root=courses_dir, state_db=state_db)
        scanner.scan_local_files()

        different_server_hash = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        res = scanner.match_and_adopt("file.pdf", different_server_hash)
        assert res is None
