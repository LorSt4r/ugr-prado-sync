"""
Top-level re-export alias for prado.core.router.
"""
from __future__ import annotations

from prado.core.router import (
    GENERAL_KEYWORDS,
    PRACTICE_KEYWORDS,
    THEORY_KEYWORDS,
    WINDOWS_RESERVED_NAMES,
    CourseRouter,
    RoutingDecision,
    detect_subgroup_in_text,
    sanitize_path_segment,
)

__all__ = [
    "CourseRouter",
    "GENERAL_KEYWORDS",
    "PRACTICE_KEYWORDS",
    "RoutingDecision",
    "THEORY_KEYWORDS",
    "WINDOWS_RESERVED_NAMES",
    "detect_subgroup_in_text",
    "sanitize_path_segment",
]
