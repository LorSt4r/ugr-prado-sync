"""
SQLite state database and tracking engine for PradoOS.

Tracks enrolled courses, downloaded files, original SHA-256 hashes, remote URLs,
timestamps, student modifications, and mid-semester adoption flags.
Stored in ~/.config/prado/state.db (mode 0600 on POSIX), strictly isolated
from user course workspaces.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from prado.config import ensure_secure_dir, get_state_db_path
from prado.exceptions import PradoError


@dataclass
class CourseRecord:
    """Metadata record for an enrolled Moodle course in the state database."""
    course_id: int
    fullname: str
    shortname: Optional[str] = None
    idnumber: Optional[str] = None
    category: Optional[str] = None
    is_active: int = 1
    last_synced_at: Optional[str] = None


@dataclass
class FileRecord:
    """Tracking record for a downloaded or adopted academic file."""
    path: str  # Relative path to courses_root
    course_id: Optional[int] = None
    resource_id: Optional[int] = None
    remote_url: Optional[str] = None
    original_hash: str = ""
    current_hash: Optional[str] = None
    file_size: int = 0
    local_mtime: Optional[float] = None
    server_mtime: Optional[float] = None
    last_synced_at: Optional[str] = None
    is_adopted: int = 0
    is_modified: int = 0
    student_modified: int = 0


class StateDatabase:
    """
    SQLite state tracking manager for PradoOS.

    Enforces WAL journal mode, 5000ms busy timeout, foreign key enforcement,
    and 0600 POSIX file permissions.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else get_state_db_path()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        ensure_secure_dir(self.db_path.parent)
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            with conn:
                # Metadata table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS meta (
                        key TEXT PRIMARY KEY,
                        val TEXT
                    );
                """)
                conn.execute("INSERT OR IGNORE INTO meta VALUES ('version', '1.0');")

                # Courses table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS courses (
                        course_id INTEGER PRIMARY KEY,
                        fullname TEXT NOT NULL,
                        shortname TEXT,
                        idnumber TEXT,
                        category TEXT,
                        is_active INTEGER DEFAULT 1,
                        last_synced_at TEXT
                    );
                """)

                # Files table (authoritative file tracker)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS files (
                        path TEXT PRIMARY KEY,
                        course_id INTEGER,
                        resource_id INTEGER,
                        remote_url TEXT,
                        original_hash TEXT NOT NULL,
                        current_hash TEXT,
                        file_size INTEGER,
                        local_mtime REAL,
                        server_mtime REAL,
                        last_synced_at TEXT,
                        is_adopted INTEGER DEFAULT 0,
                        is_modified INTEGER DEFAULT 0,
                        student_modified INTEGER DEFAULT 0,
                        FOREIGN KEY (course_id) REFERENCES courses(course_id)
                    );
                """)

                # Resources compatibility table (used across test assertions)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS resources (
                        resource_id INTEGER PRIMARY KEY,
                        course_id INTEGER,
                        title TEXT,
                        path TEXT,
                        original_sha256 TEXT,
                        student_modified INTEGER DEFAULT 0,
                        is_adopted INTEGER DEFAULT 0,
                        FOREIGN KEY (course_id) REFERENCES courses(course_id)
                    );
                """)
        finally:
            conn.close()

        # Enforce 0600 file permissions on POSIX platforms
        if os.name != "nt" and self.db_path.exists():
            try:
                os.chmod(self.db_path, 0o600)
            except OSError:
                pass

    def upsert_course(self, course: CourseRecord) -> None:
        """Inserts or updates an enrolled course record."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    INSERT INTO courses (
                        course_id, fullname, shortname, idnumber, category, is_active, last_synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(course_id) DO UPDATE SET
                        fullname = excluded.fullname,
                        shortname = excluded.shortname,
                        idnumber = excluded.idnumber,
                        category = excluded.category,
                        is_active = excluded.is_active,
                        last_synced_at = excluded.last_synced_at;
                """, (
                    course.course_id,
                    course.fullname,
                    course.shortname,
                    course.idnumber,
                    course.category,
                    course.is_active,
                    course.last_synced_at or datetime.datetime.now().isoformat(),
                ))
        finally:
            conn.close()

    def get_course(self, course_id: int) -> Optional[CourseRecord]:
        """Retrieves a course record by course_id."""
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM courses WHERE course_id = ?", (course_id,))
            row = cur.fetchone()
            if not row:
                return None
            return CourseRecord(
                course_id=row["course_id"],
                fullname=row["fullname"],
                shortname=row["shortname"],
                idnumber=row["idnumber"],
                category=row["category"],
                is_active=row["is_active"],
                last_synced_at=row["last_synced_at"],
            )
        finally:
            conn.close()

    def set_course_active(self, course_id: int, is_active: bool) -> None:
        """Toggles the is_active status of a course."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE courses SET is_active = ? WHERE course_id = ?",
                    (1 if is_active else 0, course_id),
                )
        finally:
            conn.close()

    def list_active_courses(self) -> List[CourseRecord]:
        """Returns all courses marked active."""
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM courses WHERE is_active = 1")
            rows = cur.fetchall()
            return [
                CourseRecord(
                    course_id=r["course_id"],
                    fullname=r["fullname"],
                    shortname=r["shortname"],
                    idnumber=r["idnumber"],
                    category=r["category"],
                    is_active=r["is_active"],
                    last_synced_at=r["last_synced_at"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def list_all_courses(self) -> List[CourseRecord]:
        """Returns all discovered courses regardless of active status."""
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM courses")
            rows = cur.fetchall()
            return [
                CourseRecord(
                    course_id=r["course_id"],
                    fullname=r["fullname"],
                    shortname=r["shortname"],
                    idnumber=r["idnumber"],
                    category=r["category"],
                    is_active=r["is_active"],
                    last_synced_at=r["last_synced_at"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def upsert_file(self, record: FileRecord) -> None:
        """Inserts or updates a file tracking record and synchronizes resources table."""
        conn = self._get_connection()
        try:
            with conn:
                # Ensure foreign key target exists if course_id is provided
                if record.course_id is not None:
                    cur = conn.execute("SELECT 1 FROM courses WHERE course_id = ?", (record.course_id,))
                    if not cur.fetchone():
                        conn.execute(
                            "INSERT OR IGNORE INTO courses (course_id, fullname, is_active) VALUES (?, ?, 1)",
                            (record.course_id, f"Course {record.course_id}"),
                        )

                mod_flag = max(record.is_modified, record.student_modified)
                conn.execute("""
                    INSERT INTO files (
                        path, course_id, resource_id, remote_url, original_hash,
                        current_hash, file_size, local_mtime, server_mtime,
                        last_synced_at, is_adopted, is_modified, student_modified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        course_id = excluded.course_id,
                        resource_id = excluded.resource_id,
                        remote_url = excluded.remote_url,
                        original_hash = excluded.original_hash,
                        current_hash = excluded.current_hash,
                        file_size = excluded.file_size,
                        local_mtime = excluded.local_mtime,
                        server_mtime = excluded.server_mtime,
                        last_synced_at = excluded.last_synced_at,
                        is_adopted = excluded.is_adopted,
                        is_modified = excluded.is_modified,
                        student_modified = excluded.student_modified;
                """, (
                    record.path,
                    record.course_id,
                    record.resource_id,
                    record.remote_url,
                    record.original_hash,
                    record.current_hash,
                    record.file_size,
                    record.local_mtime,
                    record.server_mtime,
                    record.last_synced_at or datetime.datetime.now().isoformat(),
                    record.is_adopted,
                    mod_flag,
                    mod_flag,
                ))

                if record.resource_id is not None:
                    conn.execute("""
                        INSERT INTO resources (
                            resource_id, course_id, title, path, original_sha256, student_modified, is_adopted
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(resource_id) DO UPDATE SET
                            path = excluded.path,
                            original_sha256 = excluded.original_sha256,
                            student_modified = excluded.student_modified,
                            is_adopted = excluded.is_adopted;
                    """, (
                        record.resource_id,
                        record.course_id,
                        Path(record.path).name,
                        record.path,
                        record.original_hash,
                        mod_flag,
                        record.is_adopted,
                    ))
        finally:
            conn.close()

    def get_file(self, rel_path: str) -> Optional[FileRecord]:
        """Retrieves a file tracking record by relative path."""
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM files WHERE path = ?", (rel_path,))
            row = cur.fetchone()
            if not row:
                return None
            return FileRecord(
                path=row["path"],
                course_id=row["course_id"],
                resource_id=row["resource_id"],
                remote_url=row["remote_url"],
                original_hash=row["original_hash"],
                current_hash=row["current_hash"],
                file_size=row["file_size"],
                local_mtime=row["local_mtime"],
                server_mtime=row["server_mtime"],
                last_synced_at=row["last_synced_at"],
                is_adopted=row["is_adopted"],
                is_modified=row["is_modified"],
                student_modified=row["student_modified"],
            )
        finally:
            conn.close()

    def get_file_by_resource_id(self, resource_id: int) -> Optional[FileRecord]:
        """Retrieves a file record by Moodle resource_id."""
        conn = self._get_connection()
        try:
            cur = conn.execute("SELECT * FROM files WHERE resource_id = ?", (resource_id,))
            row = cur.fetchone()
            if not row:
                return None
            return FileRecord(
                path=row["path"],
                course_id=row["course_id"],
                resource_id=row["resource_id"],
                remote_url=row["remote_url"],
                original_hash=row["original_hash"],
                current_hash=row["current_hash"],
                file_size=row["file_size"],
                local_mtime=row["local_mtime"],
                server_mtime=row["server_mtime"],
                last_synced_at=row["last_synced_at"],
                is_adopted=row["is_adopted"],
                is_modified=row["is_modified"],
                student_modified=row["student_modified"],
            )
        finally:
            conn.close()

    def mark_modified(self, rel_path: str, modified: bool = True) -> None:
        """Sets the student modification flag for a tracked file."""
        val = 1 if modified else 0
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    "UPDATE files SET student_modified = ?, is_modified = ? WHERE path = ?",
                    (val, val, rel_path),
                )
                conn.execute(
                    "UPDATE resources SET student_modified = ? WHERE path = ?",
                    (val, rel_path),
                )
        finally:
            conn.close()

    def mark_adopted(self, rel_path: str, original_hash: str) -> None:
        """Marks a file as adopted with its verified original hash."""
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    UPDATE files SET
                        is_adopted = 1,
                        original_hash = ?,
                        student_modified = 0,
                        is_modified = 0
                    WHERE path = ?
                """, (original_hash, rel_path))
                conn.execute("""
                    UPDATE resources SET
                        is_adopted = 1,
                        original_sha256 = ?,
                        student_modified = 0
                    WHERE path = ?
                """, (original_hash, rel_path))
        finally:
            conn.close()

    def list_files(self, course_id: Optional[int] = None) -> List[FileRecord]:
        """Lists tracked files, optionally filtered by course_id."""
        conn = self._get_connection()
        try:
            if course_id is not None:
                cur = conn.execute("SELECT * FROM files WHERE course_id = ?", (course_id,))
            else:
                cur = conn.execute("SELECT * FROM files")
            rows = cur.fetchall()
            return [
                FileRecord(
                    path=r["path"],
                    course_id=r["course_id"],
                    resource_id=r["resource_id"],
                    remote_url=r["remote_url"],
                    original_hash=r["original_hash"],
                    current_hash=r["current_hash"],
                    file_size=r["file_size"],
                    local_mtime=r["local_mtime"],
                    server_mtime=r["server_mtime"],
                    last_synced_at=r["last_synced_at"],
                    is_adopted=r["is_adopted"],
                    is_modified=r["is_modified"],
                    student_modified=r["student_modified"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def close(self) -> None:
        """Closes any active resources (no-op for connection-per-call architecture)."""
        pass

    def __enter__(self) -> StateDatabase:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
