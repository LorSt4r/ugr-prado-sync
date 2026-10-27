"""
Mid-semester adoption engine for PradoOS.

Scans local course folders for pre-existing student downloads, indexes them
by relative path, SHA-256 hash, and size, matches them against Moodle server
files, and registers them into the state database without re-downloading or
modifying file modification timestamps.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional

from prado.state import FileRecord, StateDatabase


@dataclass
class LocalFileInfo:
    """Metadata for an existing local file discovered during pre-scan."""
    abs_path: Path
    rel_path: str
    size: int
    sha256: str
    mtime: float

    @property
    def local_path(self) -> Path:
        """Semantic alias for abs_path providing disk path verification."""
        return self.abs_path


class AdoptionScanner:
    """
    Scans course roots, indexes existing files, and links matching server resources.
    Enforces strict physical disk existence and course boundary containment.
    """

    def __init__(self, courses_root: Path, state_db: StateDatabase):
        self.courses_root = Path(courses_root)
        self.state_db = state_db
        # Primary lookup: normalized relative path -> LocalFileInfo
        self.path_index: Dict[str, LocalFileInfo] = {}
        # Hash lookup (maintains backward compatibility with tests accessing .hash_index)
        self.hash_index: Dict[str, LocalFileInfo] = {}
        # Multi-file hash index: SHA-256 -> list of all matching files
        self.files_by_hash: Dict[str, List[LocalFileInfo]] = {}
        # File size index: size in bytes -> list of matching files
        self.size_index: Dict[int, List[LocalFileInfo]] = {}

    def scan_local_files(self) -> int:
        """
        Recursively scans courses_root, ignoring hidden files (.DS_Store, .git)
        and zero-byte files. Builds in-memory lookup index.
        Returns total number of non-empty files indexed.
        """
        self.path_index.clear()
        self.hash_index.clear()
        self.files_by_hash.clear()
        self.size_index.clear()

        if not self.courses_root.exists():
            return 0

        indexed_count = 0
        for entry in self.courses_root.rglob("*"):
            if not entry.is_file():
                continue

            # Skip broken or non-file symlinks
            try:
                if entry.is_symlink() and not entry.resolve().is_file():
                    continue
            except (OSError, RuntimeError):
                continue

            # Ignore hidden files or files in hidden folders (.DS_Store, .git)
            try:
                rel_parts = entry.relative_to(self.courses_root).parts
            except ValueError:
                continue

            if any(part.startswith(".") for part in rel_parts):
                continue

            try:
                st = entry.stat()
                # Exclude 0-byte files from adoption
                if st.st_size == 0:
                    continue

                rel_path_str = Path(*rel_parts).as_posix()
                file_bytes = entry.read_bytes()
                h = hashlib.sha256(file_bytes).hexdigest()

                info = LocalFileInfo(
                    abs_path=entry,
                    rel_path=rel_path_str,
                    size=st.st_size,
                    sha256=h,
                    mtime=st.st_mtime,
                )

                self.path_index[rel_path_str] = info
                self.hash_index[h] = info
                self.files_by_hash.setdefault(h, []).append(info)
                self.size_index.setdefault(st.st_size, []).append(info)
                indexed_count += 1
            except OSError:
                continue

        return indexed_count

    def match_and_adopt(
        self,
        rel_path: str,
        server_hash: str,
        course_id: Optional[int] = None,
        remote_url: Optional[str] = None,
    ) -> Optional[LocalFileInfo]:
        """
        Checks if a file with server_hash already exists locally at destination rel_path.

        Enforces strict safety and boundary invariants:
        1. Destination existence: The file MUST physically exist on disk at
           (self.courses_root / rel_path). If absent, adoption is rejected (returns None)
           so the sync engine can perform a genuine download.
        2. Course boundary: Adoption candidates must belong to the exact course hierarchy
           (matching the top-level course directory segment). Identical hashes in other
           courses are strictly forbidden from causing false adoption.
        3. Content verification: The physical file at destination must match server_hash
           byte-for-byte (SHA-256) and have non-zero size.
        4. State DB tracking: When adopted, registers record with is_adopted = 1
           and leaves the local file on disk completely untouched (0 disk writes).

        Returns LocalFileInfo if adopted, None if no match or check fails.
        """
        # Normalize relative path to POSIX style
        norm_path = Path(rel_path)
        norm_rel = norm_path.as_posix()
        parts = norm_path.parts

        if not parts:
            return None

        # Verify destination path containment within courses_root (anti-traversal)
        dest_abs_path = (self.courses_root / norm_path).resolve()
        courses_root_resolved = self.courses_root.resolve()
        try:
            dest_abs_path.relative_to(courses_root_resolved)
        except ValueError:
            return None

        # 1. Physical disk existence check at destination:
        # A file can ONLY be adopted in-place if it physically exists at the target path.
        if not dest_abs_path.is_file():
            return None

        # 2. Course boundary verification:
        # Target course slug is the top-level path segment (e.g. "ED_C", "Course_B")
        target_course_slug = parts[0]

        # Look up candidate file metadata
        match = self.path_index.get(norm_rel)

        if match is not None:
            # Enforce course boundary on indexed candidate
            match_parts = Path(match.rel_path).parts
            if not match_parts or match_parts[0] != target_course_slug:
                return None

            # Verify local_path exists on disk
            if not match.local_path.exists() or not match.local_path.is_file():
                return None

            # Verify file hasn't been modified since pre-scan
            try:
                st = dest_abs_path.stat()
                if st.st_size == 0:
                    return None
                if st.st_size != match.size or st.st_mtime != match.mtime:
                    # File was modified on disk; recalculate hash
                    actual_hash = hashlib.sha256(dest_abs_path.read_bytes()).hexdigest()
                    if actual_hash != server_hash:
                        return None
                    match = LocalFileInfo(
                        abs_path=dest_abs_path,
                        rel_path=norm_rel,
                        size=st.st_size,
                        sha256=actual_hash,
                        mtime=st.st_mtime,
                    )
            except OSError:
                return None
        else:
            # File was not in path_index (e.g., added after scan_local_files or scan skipped).
            # Verify directly from physical file on disk:
            try:
                st = dest_abs_path.stat()
                if st.st_size == 0:
                    return None
                actual_hash = hashlib.sha256(dest_abs_path.read_bytes()).hexdigest()
                if actual_hash != server_hash:
                    return None
                match = LocalFileInfo(
                    abs_path=dest_abs_path,
                    rel_path=norm_rel,
                    size=st.st_size,
                    sha256=actual_hash,
                    mtime=st.st_mtime,
                )
            except OSError:
                return None

        # Verify hash match against server
        if match.sha256 != server_hash:
            return None

        # Final verification: verify match.local_path exists on disk
        if not match.local_path.exists() or not match.local_path.is_file():
            return None

        # Final verification: candidate must belong to the exact destination course
        candidate_parts = Path(match.rel_path).parts
        if not candidate_parts or candidate_parts[0] != target_course_slug:
            return None

        # Register adoption in state database
        rec = FileRecord(
            path=norm_rel,
            course_id=course_id,
            remote_url=remote_url,
            original_hash=server_hash,
            current_hash=server_hash,
            file_size=match.size,
            local_mtime=match.mtime,
            is_adopted=1,
            is_modified=0,
            student_modified=0,
        )
        self.state_db.upsert_file(rec)
        return match
