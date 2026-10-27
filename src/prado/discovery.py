"""
Top-level re-export alias for prado.core.discovery.
"""
from __future__ import annotations

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

__all__ = [
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
]
