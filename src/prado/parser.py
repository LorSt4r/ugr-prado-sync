"""
Top-level re-export alias for prado.core.parser.
"""
from __future__ import annotations

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

__all__ = [
    "ActivityType",
    "CourseActivity",
    "CourseHtmlParser",
    "FileAttachment",
    "ParsedCourse",
    "SectionInfo",
    "clean_activity_title",
    "parse_moodle_date",
]
