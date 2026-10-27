"""
Top-level re-export alias for prado.core.downloader.
"""
from __future__ import annotations

from prado.core.downloader import (
    AdoptedFile,
    ConflictFile,
    DeadlineItem,
    DownloadedFile,
    DownloadResult,
    DownloadStatus,
    ForumPost,
    MIME_TO_EXTENSION,
    SafeDownloader,
    SyncSummary,
    parse_content_disposition,
    resolve_destination_path,
)

__all__ = [
    "AdoptedFile",
    "ConflictFile",
    "DeadlineItem",
    "DownloadedFile",
    "DownloadResult",
    "DownloadStatus",
    "ForumPost",
    "MIME_TO_EXTENSION",
    "SafeDownloader",
    "SyncSummary",
    "parse_content_disposition",
    "resolve_destination_path",
]
