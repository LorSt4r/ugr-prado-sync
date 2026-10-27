"""
PradoOS Core Synchronization Engine.

Contains auto-discovery, Moodle HTML activity parsing, dual folder routing,
safe chunked streaming downloader, mid-semester adoption, and overwrite protection.
"""
from __future__ import annotations

from prado.core.adoption import AdoptionScanner, LocalFileInfo
from prado.core.discovery import (
    AjaxDiscoveryError,
    Course,
    CourseDiscovery,
    CourseFilter,
    CourseSemester,
    DiscoveryError,
    DomParsingError,
    NoCoursesFoundError,
    derive_course_slug,
    detect_semester_from_course,
)
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
from prado.core.overwrite import (
    CollisionQuadrant,
    CollisionResolution,
    OverwriteGuard,
    format_collision_fork_name,
    split_filename_and_extension,
)
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
from prado.core.router import (
    CourseRouter,
    RoutingDecision,
    detect_subgroup_in_text,
    sanitize_path_segment,
)

__all__ = [
    # Adoption
    "AdoptionScanner",
    "LocalFileInfo",
    # Discovery
    "AjaxDiscoveryError",
    "Course",
    "CourseDiscovery",
    "CourseFilter",
    "CourseSemester",
    "DiscoveryError",
    "DomParsingError",
    "NoCoursesFoundError",
    "derive_course_slug",
    "detect_semester_from_course",
    # Downloader
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
    # Overwrite Protection
    "CollisionQuadrant",
    "CollisionResolution",
    "OverwriteGuard",
    "format_collision_fork_name",
    "split_filename_and_extension",
    # Parser
    "ActivityType",
    "CourseActivity",
    "CourseHtmlParser",
    "FileAttachment",
    "ParsedCourse",
    "SectionInfo",
    "clean_activity_title",
    "parse_moodle_date",
    # Router
    "CourseRouter",
    "RoutingDecision",
    "detect_subgroup_in_text",
    "sanitize_path_segment",
]
