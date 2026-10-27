"""
Overwrite collision guard and 4-quadrant decision matrix for PradoOS.

Protects student local modifications from being overwritten by professor updates.
When a student has modified a file and the professor re-uploads an update,
the student's version is preserved untouched, and the professor's version
is saved alongside as {stem}_server_{YYYYMMDD_HHMMSS}{ext}.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime
from enum import Enum
import hashlib
import os
from pathlib import Path
from typing import Optional, Tuple

from prado.state import FileRecord, StateDatabase


class CollisionQuadrant(str, Enum):
    Q1_UP_TO_DATE = "up_to_date"
    Q2_SAFE_REPLACE = "safe_in_place_replace"
    Q3_PRESERVE_STUDENT = "preserve_student_work"
    Q4_COLLISION_FORK = "collision_fork"
    DOWNLOAD_NEW = "download_new"
    ADOPT = "adopt"


@dataclass
class CollisionResolution:
    """Outcome of collision matrix evaluation."""
    quadrant: CollisionQuadrant
    action: str  # "skip", "safe_in_place_replace", "preserve_student_work", "collision_fork", "download", "up_to_date"
    dest_path: Path
    forked_path: Optional[Path] = None
    reason: str = ""


def split_filename_and_extension(filename: str) -> Tuple[str, str]:
    """
    Splits filename into (stem, ext), handling compound extensions and extensionless files.
    - 'archive.tar.gz' -> ('archive', '.tar.gz')
    - 'data.tar.bz2' -> ('data', '.tar.bz2')
    - 'Makefile' -> ('Makefile', '')
    - 'lab1.ipynb' -> ('lab1', '.ipynb')
    """
    compound_exts = [".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst"]
    for c_ext in compound_exts:
        if filename.lower().endswith(c_ext):
            return filename[:-len(c_ext)], filename[-len(c_ext):]

    stem, ext = os.path.splitext(filename)
    return stem, ext


def format_collision_fork_name(filename: str, dt: Optional[datetime.datetime] = None) -> str:
    """
    Formats the collision server update filename:
    {stem}_server_{YYYYMMDD_HHMMSS}{ext}
    """
    if dt is None:
        dt = datetime.datetime.now()
    stem, ext = split_filename_and_extension(filename)
    ts = dt.strftime("%Y%m%d_%H%M%S")
    return f"{stem}_server_{ts}{ext}"


class OverwriteGuard:
    """
    Evaluates file collision status and enforces the 4-Quadrant Overwrite Matrix.
    """

    def __init__(self, state_db: StateDatabase):
        self.state_db = state_db

    def evaluate(
        self,
        local_abs_path: Path,
        rel_path: str,
        server_hash: str,
    ) -> CollisionResolution:
        """
        Determines the appropriate collision action based on:
        H_orig, H_local, H_server
        """
        if not local_abs_path.exists():
            return CollisionResolution(
                quadrant=CollisionQuadrant.DOWNLOAD_NEW,
                action="download",
                dest_path=local_abs_path,
                reason="File does not exist locally; fresh download.",
            )

        # Check if local_abs_path is a directory to prevent unhandled IsADirectoryError.
        # An existing directory cannot be read as bytes or overwritten by a file download.
        # Preserve the local directory and fork the incoming server update alongside.
        if local_abs_path.is_dir():
            forked_name = format_collision_fork_name(local_abs_path.name)
            forked_path = local_abs_path.parent / forked_name

            counter = 1
            while forked_path.exists():
                stem, ext = split_filename_and_extension(local_abs_path.name)
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                forked_path = local_abs_path.parent / f"{stem}_server_{ts}_{counter}{ext}"
                counter += 1

            return CollisionResolution(
                quadrant=CollisionQuadrant.Q4_COLLISION_FORK,
                action="collision_fork",
                dest_path=local_abs_path,
                forked_path=forked_path,
                reason=(
                    f"Target path '{local_abs_path.name}' is an existing directory; "
                    f"preserving directory and forking server update to {forked_path.name}."
                ),
            )

        try:
            local_bytes = local_abs_path.read_bytes()
        except (IsADirectoryError, PermissionError, OSError) as e:
            forked_name = format_collision_fork_name(local_abs_path.name)
            forked_path = local_abs_path.parent / forked_name
            counter = 1
            while forked_path.exists():
                stem, ext = split_filename_and_extension(local_abs_path.name)
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                forked_path = local_abs_path.parent / f"{stem}_server_{ts}_{counter}{ext}"
                counter += 1
            return CollisionResolution(
                quadrant=CollisionQuadrant.Q4_COLLISION_FORK,
                action="collision_fork",
                dest_path=local_abs_path,
                forked_path=forked_path,
                reason=(
                    f"Unable to read local file ({e}); "
                    f"preserving local path and forking server update to {forked_path.name}."
                ),
            )

        local_hash = hashlib.sha256(local_bytes).hexdigest()

        rec = self.state_db.get_file(rel_path)

        if not rec:
            if local_hash == server_hash:
                return CollisionResolution(
                    quadrant=CollisionQuadrant.ADOPT,
                    action="skip",
                    dest_path=local_abs_path,
                    reason="Existing local file matches server hash; candidate for adoption.",
                )
            else:
                forked_name = format_collision_fork_name(local_abs_path.name)
                forked_path = local_abs_path.parent / forked_name
                return CollisionResolution(
                    quadrant=CollisionQuadrant.Q4_COLLISION_FORK,
                    action="collision_fork",
                    dest_path=local_abs_path,
                    forked_path=forked_path,
                    reason="Untracked local file with different hash; preserve local file and fork server update.",
                )

        orig_hash = rec.original_hash
        is_local_unmodified = (local_hash == orig_hash)
        is_server_unchanged = (server_hash == orig_hash)

        if is_local_unmodified and is_server_unchanged:
            # Quadrant 1: Both unchanged
            return CollisionResolution(
                quadrant=CollisionQuadrant.Q1_UP_TO_DATE,
                action="up_to_date",
                dest_path=local_abs_path,
                reason="Local file and server file are identical to original download; up to date.",
            )

        elif is_local_unmodified and not is_server_unchanged:
            # Quadrant 2: Server updated, student hasn't touched local file
            return CollisionResolution(
                quadrant=CollisionQuadrant.Q2_SAFE_REPLACE,
                action="safe_in_place_replace",
                dest_path=local_abs_path,
                reason="Server has updated version; safe to replace in place because local file is unmodified.",
            )

        elif not is_local_unmodified and is_server_unchanged:
            # Quadrant 3: Student modified file, server file unchanged
            self.state_db.mark_modified(rel_path, True)
            return CollisionResolution(
                quadrant=CollisionQuadrant.Q3_PRESERVE_STUDENT,
                action="preserve_student_work",
                dest_path=local_abs_path,
                reason="Student modified file locally; server has not changed. Preserving student work.",
            )

        else:
            # Quadrant 4: Collision! Both student and server modified file
            self.state_db.mark_modified(rel_path, True)
            forked_name = format_collision_fork_name(local_abs_path.name)
            forked_path = local_abs_path.parent / forked_name

            counter = 1
            while forked_path.exists():
                stem, ext = split_filename_and_extension(local_abs_path.name)
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                forked_path = local_abs_path.parent / f"{stem}_server_{ts}_{counter}{ext}"
                counter += 1

            return CollisionResolution(
                quadrant=CollisionQuadrant.Q4_COLLISION_FORK,
                action="collision_fork",
                dest_path=local_abs_path,
                forked_path=forked_path,
                reason=f"COLLISION: Local file edited by student and server file updated. Forked to {forked_path.name}.",
            )
