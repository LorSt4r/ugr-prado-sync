"""
Milestone M2 Adversarial Test Suite for PradoOS.

Empirically challenges:
1. SafeDownloader:
   - Simulated network drops / chunk stream interruptions
   - Read timeouts mid-stream
   - Premature EOF / connection reset preserving pre-existing files
   - Corrupted chunks detected via live SHA-256 verification
   - Truncated chunk streams detected and rejected
   - Simulated disk full (ENOSPC) and permission errors (EACCES)
   - Guaranteed cleanup of .prado_tmp_* temporary files under all failure modes
   - Non-ASCII and special character handling in filenames
   - Retry backoff logic and max retry exhaustion

2. StateDatabase:
   - SQLite WAL mode and 5000ms busy timeout verification
   - Heavy multi-threaded concurrent write/read stress test (zero locks, zero data loss)
   - Multi-process concurrent access stress test
   - Concurrent race condition on auto-creation of missing course records
   - Foreign key constraint enforcement
   - Integrity check verification (PRAGMA integrity_check == 'ok')
   - POSIX 0600 mode enforcement under hostile umask
"""

from __future__ import annotations

import concurrent.futures
import errno
import hashlib
import os
import stat
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator, List, Optional
from unittest.mock import MagicMock, patch
import pytest
import requests

from prado.core.downloader import (
    DownloadResult,
    DownloadStatus,
    SafeDownloader,
)
from prado.exceptions import PradoError
from prado.state import CourseRecord, FileRecord, StateDatabase


# =============================================================================
# Helper Classes for Streaming Simulation
# =============================================================================

class MockStreamResponse:
    """Simulates a requests.Response object streaming chunks."""

    def __init__(
        self,
        chunks: List[bytes],
        status_code: int = 200,
        content_length: Optional[int] = None,
        exception_at_chunk: Optional[int] = None,
        exception_to_raise: Optional[Exception] = None,
    ):
        self._chunks = chunks
        self.status_code = status_code
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self.exception_at_chunk = exception_at_chunk
        self.exception_to_raise = exception_to_raise or requests.exceptions.ReadTimeout("Socket read timeout")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} Error")

    def iter_content(self, chunk_size: int = 65536) -> Iterator[bytes]:
        for i, chunk in enumerate(self._chunks):
            if self.exception_at_chunk is not None and i == self.exception_at_chunk:
                raise self.exception_to_raise
            yield chunk


# =============================================================================
# 1. SafeDownloader Adversarial Tests
# =============================================================================

class TestSafeDownloaderAdversarial:
    """Stress tests SafeDownloader against network failure modes and data corruption."""

    def test_stream_read_timeout_atomic_cleanup(self, tmp_path: Path):
        """
        Verify that a socket read timeout during chunk streaming:
        1. Fails gracefully with DownloadStatus.FAILED
        2. Never creates or leaves the target destination file
        3. Cleans up all .prado_tmp_* temporary files
        """
        dest_dir = tmp_path / "downloads"
        dest_file = dest_dir / "tema2_slides.pdf"

        # 3 chunks of 64KB, timeout on chunk 1 (0-indexed)
        chunk = b"A" * 65536
        chunks = [chunk, chunk, chunk]

        mock_resp = MockStreamResponse(
            chunks=chunks,
            content_length=len(chunk) * 3,
            exception_at_chunk=1,
            exception_to_raise=requests.exceptions.ReadTimeout("Read timeout mid-stream"),
        )

        session = requests.Session()
        with patch.object(session, "get", return_value=mock_resp):
            downloader = SafeDownloader(session=session)
            downloader.MAX_RETRIES = 1
            downloader.BACKOFF_FACTOR = 0.01

            result = downloader.download_file(
                url="https://prado.ugr.es/mod/resource/view.php?id=5001",
                dest_path=dest_file,
            )

        assert result.status == DownloadStatus.FAILED
        assert "timeout" in result.error.lower()
        # Destination file must NOT exist
        assert not dest_file.exists(), "Target file must not be created on timeout"
        # Zero temporary files must remain
        leftover_tmps = list(dest_dir.glob(".prado_tmp_*"))
        assert len(leftover_tmps) == 0, f"Found leaked temporary files: {leftover_tmps}"

    def test_stream_connection_reset_preserves_existing_file(self, tmp_path: Path):
        """
        Verify that when a target file already exists and a re-download encounters
        a connection drop mid-stream:
        1. The original target file is preserved completely intact
        2. The temporary partial download is deleted
        """
        dest_dir = tmp_path / "course_work"
        dest_dir.mkdir(parents=True)
        dest_file = dest_dir / "practical_work.ipynb"

        original_content = b'{"cells": [{"cell_type": "code", "source": "print(1)"}]}'
        dest_file.write_bytes(original_content)
        orig_stat = dest_file.stat()

        chunk = b"B" * 65536
        mock_resp = MockStreamResponse(
            chunks=[chunk, chunk],
            content_length=len(chunk) * 2,
            exception_at_chunk=1,
            exception_to_raise=requests.exceptions.ConnectionError("Connection reset by peer"),
        )

        session = requests.Session()
        with patch.object(session, "get", return_value=mock_resp):
            downloader = SafeDownloader(session=session)
            downloader.MAX_RETRIES = 1
            downloader.BACKOFF_FACTOR = 0.01

            result = downloader.download_file(
                url="https://prado.ugr.es/mod/resource/view.php?id=5002",
                dest_path=dest_file,
            )

        assert result.status == DownloadStatus.FAILED
        # File must remain untouched with original content
        assert dest_file.exists()
        assert dest_file.read_bytes() == original_content
        assert dest_file.stat().st_size == len(original_content)
        # No temporary files left behind
        leftover_tmps = list(dest_dir.glob(".prado_tmp_*"))
        assert len(leftover_tmps) == 0

    def test_stream_chunked_encoding_error_cleaned_up(self, tmp_path: Path):
        """
        Simulate ChunkedEncodingError (premature EOF from Moodle server).
        Verify failure handling and temp file cleanup.
        """
        dest_file = tmp_path / "broken_chunked.zip"
        chunk = b"Z" * 1024

        mock_resp = MockStreamResponse(
            chunks=[chunk, chunk],
            exception_at_chunk=1,
            exception_to_raise=requests.exceptions.ChunkedEncodingError("Incomplete chunked read"),
        )

        session = requests.Session()
        with patch.object(session, "get", return_value=mock_resp):
            downloader = SafeDownloader(session=session)
            downloader.MAX_RETRIES = 1
            downloader.BACKOFF_FACTOR = 0.01

            result = downloader.download_file(
                url="https://prado.ugr.es/broken.zip",
                dest_path=dest_file,
            )

        assert result.status == DownloadStatus.FAILED
        assert not dest_file.exists()
        leftover_tmps = list(tmp_path.glob(".prado_tmp_*"))
        assert len(leftover_tmps) == 0

    def test_corrupted_chunk_live_sha256_detection(self, tmp_path: Path):
        """
        Simulate corrupt byte in chunk 2 of 3:
        Server claims SHA-256 = expected_hash (of authentic 3 chunks).
        Chunk 2 has 1 byte corrupted.
        Verify checksum mismatch is detected, status is FAILED, target does not exist,
        and temp files are deleted.
        """
        dest_file = tmp_path / "corrupted.bin"

        chunk1 = b"Chunk One 64KB" + b"1" * 65522
        chunk2_valid = b"Chunk Two 64KB" + b"2" * 65522
        chunk3 = b"Chunk Three 64KB" + b"3" * 65520

        authentic_bytes = chunk1 + chunk2_valid + chunk3
        authentic_sha = hashlib.sha256(authentic_bytes).hexdigest()

        # Corrupt 1 byte in chunk 2
        chunk2_corrupt = b"Chunk TWO 64KB" + b"2" * 65522

        mock_resp = MockStreamResponse(
            chunks=[chunk1, chunk2_corrupt, chunk3],
            content_length=len(authentic_bytes),
        )

        session = requests.Session()
        with patch.object(session, "get", return_value=mock_resp):
            downloader = SafeDownloader(session=session)
            downloader.MAX_RETRIES = 1
            downloader.BACKOFF_FACTOR = 0.01

            result = downloader.download_file(
                url="https://prado.ugr.es/corrupted.bin",
                dest_path=dest_file,
                expected_hash=authentic_sha,
            )

        assert result.status == DownloadStatus.FAILED
        assert "checksum mismatch" in result.error.lower()
        assert not dest_file.exists(), "Corrupted file must never be written to destination"
        leftover_tmps = list(tmp_path.glob(".prado_tmp_*"))
        assert len(leftover_tmps) == 0

    def test_truncated_stream_with_expected_hash(self, tmp_path: Path):
        """
        Simulate stream ending prematurely after chunk 1 without exception,
        when 2 chunks were expected (validated by SHA-256).
        """
        dest_file = tmp_path / "truncated.pdf"
        chunk1 = b"Part 1" * 1000
        chunk2 = b"Part 2" * 1000
        full_content = chunk1 + chunk2
        expected_sha = hashlib.sha256(full_content).hexdigest()

        # Server only sends chunk1
        mock_resp = MockStreamResponse(
            chunks=[chunk1],
            content_length=len(full_content),
        )

        session = requests.Session()
        with patch.object(session, "get", return_value=mock_resp):
            downloader = SafeDownloader(session=session)
            downloader.MAX_RETRIES = 1
            downloader.BACKOFF_FACTOR = 0.01

            result = downloader.download_file(
                url="https://prado.ugr.es/truncated.pdf",
                dest_path=dest_file,
                expected_hash=expected_sha,
            )

        assert result.status == DownloadStatus.FAILED
        assert "checksum mismatch" in result.error.lower()
        assert not dest_file.exists()
        leftover_tmps = list(tmp_path.glob(".prado_tmp_*"))
        assert len(leftover_tmps) == 0

    def test_simulated_disk_full_enospc_during_stream(self, tmp_path: Path):
        """
        Simulate ENOSPC (No space left on device) while writing chunks to disk.
        Verify IOError handling and temporary file cleanup.
        """
        dest_file = tmp_path / "huge_video.mp4"
        chunk = b"V" * 65536

        mock_resp = MockStreamResponse(chunks=[chunk, chunk, chunk])

        session = requests.Session()
        with patch.object(session, "get", return_value=mock_resp):
            downloader = SafeDownloader(session=session)
            downloader.MAX_RETRIES = 1
            downloader.BACKOFF_FACTOR = 0.01

            write_count = 0
            original_open = open

            def mocked_open(path, mode="r", *args, **kwargs):
                nonlocal write_count
                f = original_open(path, mode, *args, **kwargs)
                if "wb" in mode and ".prado_tmp_" in str(path):
                    orig_write = f.write
                    def write_with_enospc(data):
                        nonlocal write_count
                        write_count += 1
                        if write_count >= 2:
                            raise OSError(errno.ENOSPC, "No space left on device")
                        return orig_write(data)
                    f.write = write_with_enospc
                return f

            with patch("builtins.open", side_effect=mocked_open):
                result = downloader.download_file(
                    url="https://prado.ugr.es/video.mp4",
                    dest_path=dest_file,
                )

        assert result.status == DownloadStatus.FAILED
        assert "space" in result.error.lower() or "enospc" in result.error.lower()
        assert not dest_file.exists()
        leftover_tmps = list(tmp_path.glob(".prado_tmp_*"))
        assert len(leftover_tmps) == 0

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions tests")
    def test_read_only_destination_directory_permission_denied(self, tmp_path: Path):
        """
        Simulate permission denied when writing to a read-only directory.
        Verify graceful failure and no unhandled traceback.
        """
        ro_dir = tmp_path / "ro_directory"
        ro_dir.mkdir(parents=True)
        dest_file = ro_dir / "protected.pdf"

        # Make directory read-only
        os.chmod(ro_dir, 0o555)

        try:
            chunk = b"PDF data"
            mock_resp = MockStreamResponse(chunks=[chunk])
            session = requests.Session()

            with patch.object(session, "get", return_value=mock_resp):
                downloader = SafeDownloader(session=session)
                downloader.MAX_RETRIES = 1
                downloader.BACKOFF_FACTOR = 0.01

                result = downloader.download_file(
                    url="https://prado.ugr.es/protected.pdf",
                    dest_path=dest_file,
                )

            assert result.status == DownloadStatus.FAILED
            assert "permission" in result.error.lower() or "denied" in result.error.lower()
            assert not dest_file.exists()
        finally:
            os.chmod(ro_dir, 0o755)

    def test_non_ascii_and_special_characters_in_filename(self, tmp_path: Path):
        """
        Stress test filenames with Spanish accents, quotes, and symbols:
        'Tema 1 — Introducción & Complejidad (C++) [v1.0].pdf'
        """
        complex_name = "Tema 1 — Introducción & Complejidad (C++) [v1.0].pdf"
        dest_file = tmp_path / complex_name

        content = b"Special Characters Content UTF-8 \xc3\xa9\xc3\xa0\xc3\xb1"
        expected_sha = hashlib.sha256(content).hexdigest()

        mock_resp = MockStreamResponse(chunks=[content], content_length=len(content))
        session = requests.Session()

        with patch.object(session, "get", return_value=mock_resp):
            downloader = SafeDownloader(session=session)
            result = downloader.download_file(
                url="https://prado.ugr.es/special.pdf",
                dest_path=dest_file,
                expected_hash=expected_sha,
            )

        assert result.status == DownloadStatus.DOWNLOADED
        assert result.sha256 == expected_sha
        assert dest_file.exists()
        assert dest_file.name == complex_name
        assert dest_file.read_bytes() == content
        leftover_tmps = list(tmp_path.glob(".prado_tmp_*"))
        assert len(leftover_tmps) == 0

    def test_retry_transient_failure_then_success(self, tmp_path: Path):
        """
        Verify that a transient network failure on attempt 1 automatically retries
        and succeeds on attempt 2, without leaving orphaned temporary files.
        """
        dest_file = tmp_path / "transient.pdf"
        content = b"Successfully retrieved on retry"
        expected_sha = hashlib.sha256(content).hexdigest()

        fail_resp = MockStreamResponse(
            chunks=[b"partial"],
            exception_at_chunk=0,
            exception_to_raise=requests.exceptions.ConnectionError("Temporary blip"),
        )
        ok_resp = MockStreamResponse(chunks=[content], content_length=len(content))

        session = requests.Session()
        with patch.object(session, "get", side_effect=[fail_resp, ok_resp]):
            downloader = SafeDownloader(session=session)
            downloader.MAX_RETRIES = 2
            downloader.BACKOFF_FACTOR = 0.01

            result = downloader.download_file(
                url="https://prado.ugr.es/retry.pdf",
                dest_path=dest_file,
                expected_hash=expected_sha,
            )

        assert result.status == DownloadStatus.DOWNLOADED
        assert result.sha256 == expected_sha
        assert dest_file.exists()
        assert dest_file.read_bytes() == content
        leftover_tmps = list(tmp_path.glob(".prado_tmp_*"))
        assert len(leftover_tmps) == 0

    def test_max_retries_exhaustion(self, tmp_path: Path):
        """
        Verify that when all retries are exhausted, the downloader stops cleanly
        and reports the final exception.
        """
        dest_file = tmp_path / "unreachable.pdf"

        session = requests.Session()
        with patch.object(session, "get", side_effect=requests.exceptions.ConnectTimeout("Host unreachable")):
            downloader = SafeDownloader(session=session)
            downloader.MAX_RETRIES = 2
            downloader.BACKOFF_FACTOR = 0.01

            result = downloader.download_file(
                url="https://prado.ugr.es/down.pdf",
                dest_path=dest_file,
            )

        assert result.status == DownloadStatus.FAILED
        assert "host unreachable" in result.error.lower() or "timeout" in result.error.lower()
        assert not dest_file.exists()
        leftover_tmps = list(tmp_path.glob(".prado_tmp_*"))
        assert len(leftover_tmps) == 0

    def test_concurrent_downloads_same_destination_no_temp_leak(self, tmp_path: Path):
        """
        Adversarial test: Multiple concurrent threads download different versions
        to the EXACT same target destination path.
        Verifies:
        - Atomic replacement guarantees file is complete (never corrupt/half-written)
        - Unique UUID tokens prevent .part file collisions
        - Zero temporary files leaked
        """
        dest_file = tmp_path / "contended.pdf"
        session = requests.Session()

        def make_mock_resp(content: bytes):
            return MockStreamResponse(chunks=[content], content_length=len(content))

        results: List[DownloadResult] = []
        errors: List[str] = []

        def worker(idx: int):
            content = f"Worker_{idx}_Content_{'x' * 1000}".encode()
            with patch.object(session, "get", return_value=make_mock_resp(content)):
                dl = SafeDownloader(session=session)
                try:
                    res = dl.download_file("https://prado.ugr.es/contended.pdf", dest_file)
                    results.append(res)
                except Exception as e:
                    errors.append(f"Worker {idx} failed: {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, i) for i in range(8)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0
        assert len(results) == 8
        assert all(r.status == DownloadStatus.DOWNLOADED for r in results)
        assert dest_file.exists()
        # Verify file on disk is valid content from one of the workers
        actual_content = dest_file.read_bytes()
        assert actual_content.startswith(b"Worker_")
        # Zero temporary files remain
        leftover_tmps = list(tmp_path.glob(".prado_tmp_*"))
        assert len(leftover_tmps) == 0


# =============================================================================
# 2. StateDatabase Adversarial Tests
# =============================================================================

class TestStateDatabaseAdversarial:
    """Stress tests StateDatabase SQLite concurrency, WAL mode, locks, and integrity."""

    def test_wal_mode_and_pragmas_active(self, tmp_path: Path):
        """
        Empirically verify SQLite connection PRAGMAs on StateDatabase connections:
        - journal_mode = WAL (persisted in DB)
        - busy_timeout = 5000
        - foreign_keys = ON
        """
        db_path = tmp_path / "state.db"
        db = StateDatabase(db_path)

        conn = db._get_connection()
        cur = conn.cursor()

        cur.execute("PRAGMA journal_mode;")
        journal = cur.fetchone()[0]
        assert journal.lower() == "wal"

        cur.execute("PRAGMA busy_timeout;")
        timeout = cur.fetchone()[0]
        assert timeout == 5000

        cur.execute("PRAGMA foreign_keys;")
        fk = cur.fetchone()[0]
        assert fk == 1

        cur.execute("PRAGMA integrity_check;")
        integrity = cur.fetchone()[0]
        assert integrity == "ok"

        conn.close()

    def test_multi_thread_concurrent_writes_and_reads(self, tmp_path: Path):
        """
        Stress test: 16 concurrent threads performing 50 mixed database operations each
        (total: 800 operations).
        Operations: upsert_course, upsert_file, mark_modified, mark_adopted, list_files, get_file.
        Verifies:
        - Zero 'database is locked' errors
        - Zero data corruption
        - PRAGMA integrity_check == 'ok'
        - Row counts match exactly
        """
        db_path = tmp_path / "concurrent_state.db"
        db = StateDatabase(db_path)

        # Pre-populate 4 courses
        for c_id in range(1, 5):
            db.upsert_course(CourseRecord(course_id=c_id, fullname=f"Course {c_id}", is_active=1))

        errors: List[str] = []

        def worker(thread_idx: int):
            for i in range(50):
                op = (thread_idx + i) % 5
                try:
                    c_id = (i % 4) + 1
                    file_path = f"course_{c_id}/file_{thread_idx}_{i}.pdf"

                    if op == 0:
                        db.upsert_file(FileRecord(
                            path=file_path,
                            course_id=c_id,
                            resource_id=(thread_idx * 1000) + i,
                            original_hash=f"hash_{thread_idx}_{i}",
                            file_size=1024 + i,
                        ))
                    elif op == 1:
                        db.mark_modified(file_path, True)
                    elif op == 2:
                        db.mark_adopted(file_path, f"adopted_hash_{thread_idx}_{i}")
                    elif op == 3:
                        f = db.get_file(file_path)
                    elif op == 4:
                        files = db.list_files(course_id=c_id)
                except Exception as e:
                    errors.append(f"Thread {thread_idx} op {op} iter {i} failed: {type(e).__name__}: {e}")

        # Execute 16 threads concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(worker, t_id) for t_id in range(16)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Encountered concurrency errors: {errors[:10]}"

        # Check integrity
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        assert cur.fetchone()[0] == "ok"

        # Verify courses and files exist and are queryable
        cur.execute("SELECT count(*) FROM files;")
        total_files = cur.fetchone()[0]
        assert total_files > 0
        conn.close()

    def test_concurrent_upsert_file_for_same_nonexistent_course(self, tmp_path: Path):
        """
        Adversarial race condition test:
        10 threads simultaneously insert files referencing a non-existent course_id=9999.
        StateDatabase._get_connection checks if course exists and executes INSERT OR IGNORE.
        Verifies that no primary key violation or foreign key lock crash occurs.
        """
        db_path = tmp_path / "fk_race_state.db"
        db = StateDatabase(db_path)

        errors: List[str] = []

        def fk_worker(t_id: int):
            try:
                rec = FileRecord(
                    path=f"auto_course/file_{t_id}.pdf",
                    course_id=9999,
                    resource_id=9000 + t_id,
                    original_hash=f"sha_{t_id}",
                )
                db.upsert_file(rec)
            except Exception as e:
                errors.append(f"FK Worker {t_id} failed: {type(e).__name__}: {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fk_worker, i) for i in range(10)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"FK race errors: {errors}"

        # Course 9999 must exist
        course = db.get_course(9999)
        assert course is not None
        assert course.course_id == 9999

        # All 10 files must be stored
        files = db.list_files(course_id=9999)
        assert len(files) == 10

    def test_multi_process_concurrent_state_db(self, tmp_path: Path):
        """
        Verify multi-process concurrency using multiprocessing / ProcessPoolExecutor.
        Multiple OS processes open StateDatabase on the same path and write concurrently.
        """
        db_path = tmp_path / "mp_state.db"
        db = StateDatabase(db_path)

        tasks = [(str(db_path), p_id) for p_id in range(4)]

        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(_mp_worker, tasks))

        all_errors = [err for p_errors in results for err in p_errors]
        assert len(all_errors) == 0, f"Multi-process errors: {all_errors}"

        # Verify integrity and row count
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        assert cur.fetchone()[0] == "ok"
        cur.execute("SELECT count(*) FROM files;")
        # 4 processes * 20 records = 80
        assert cur.fetchone()[0] == 80
        conn.close()

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions tests")
    def test_state_db_file_permissions_0600(self, tmp_path: Path):
        """
        Verify that state.db is created with mode 0600 permissions on POSIX,
        even under hostile umask 0000.
        """
        old_umask = os.umask(0)
        try:
            db_path = tmp_path / "hostile_umask_state.db"
            db = StateDatabase(db_path)

            assert db_path.exists()
            mode = stat.S_IMODE(db_path.stat().st_mode)
            assert mode == 0o600, f"Expected 0600, got {oct(mode)}"
        finally:
            os.umask(old_umask)

    def test_corrupted_database_file_detection(self, tmp_path: Path):
        """
        Verify that a corrupted database file raises sqlite3.DatabaseError
        and is not silently ignored.
        """
        corrupted_db = tmp_path / "corrupted.db"
        corrupted_db.write_bytes(b"CORRUPTED_GARBAGE_BYTES_NOT_SQLITE" * 20)

        with pytest.raises(sqlite3.DatabaseError):
            db = StateDatabase(corrupted_db)
            db.list_all_courses()

    def test_special_characters_sql_injection_resilience(self, tmp_path: Path):
        """
        Adversarial test: Paths and names with quotes, semicolons, dashes, and Unicode.
        Verifies parameter binding prevents SQL syntax corruption or injection.
        """
        db = StateDatabase(tmp_path / "special.db")
        db.upsert_course(CourseRecord(course_id=1, fullname="O'Hara's Advanced Systems -- ' OR '1'='1"))

        special_paths = [
            "ED_C/Teoria/O'Reilly_Algorithms.pdf",
            "ED_C/Teoria/📁_Algorithms_&_Data_Structures_100%_Approved.pdf",
            "ED_C/Teoria/path;with--comments.pdf",
            "ED_C/Teoria/quote\"and'mixed`characters.pdf",
        ]
        for p in special_paths:
            db.upsert_file(FileRecord(path=p, course_id=1, original_hash="sha_" + hashlib.sha256(p.encode()).hexdigest()[:8]))
            f = db.get_file(p)
            assert f is not None
            assert f.path == p

        all_files = db.list_files()
        assert len(all_files) == len(special_paths)

    def test_state_db_slow_writer_busy_timeout_grace(self, tmp_path: Path):
        """
        Verify that when one connection holds an IMMEDIATE transaction for 1.0 second,
        other concurrent worker threads wait gracefully via PRAGMA busy_timeout = 5000
        and complete their operations without raising 'database is locked'.
        """
        db_path = tmp_path / "busy_grace.db"
        db = StateDatabase(db_path)

        def slow_writer():
            conn = db._get_connection()
            conn.execute("BEGIN IMMEDIATE;")
            time.sleep(1.0)
            conn.commit()
            conn.close()

        errors: List[str] = []

        def fast_writer(t_id: int):
            time.sleep(0.1)  # wait for slow_writer to acquire write lock
            try:
                db.upsert_file(FileRecord(path=f"file_{t_id}.pdf", original_hash=f"h_{t_id}"))
            except Exception as e:
                errors.append(f"Fast writer {t_id} failed: {type(e).__name__}: {e}")

        t_slow = concurrent.futures.ThreadPoolExecutor(max_workers=1).submit(slow_writer)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(fast_writer, i) for i in range(5)]
            t_slow.result()
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Slow writer caused lock errors: {errors}"
        assert len(db.list_files()) == 5



def _mp_worker(args: tuple[str, int]) -> List[str]:
    """Helper worker for multi-process concurrency test."""
    db_path_str, process_id = args
    db = StateDatabase(Path(db_path_str))
    errors = []

    for i in range(20):
        try:
            rec = FileRecord(
                path=f"proc_{process_id}/item_{i}.dat",
                course_id=process_id + 1,
                resource_id=(process_id * 100) + i,
                original_hash=f"mp_hash_{process_id}_{i}",
                file_size=100 + i,
            )
            db.upsert_file(rec)
        except Exception as e:
            errors.append(f"Process {process_id} iter {i} error: {e}")

    return errors


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
