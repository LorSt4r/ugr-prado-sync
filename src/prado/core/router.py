"""
Folder routing engine and subgroup archiving manager for PradoOS.

Supports PRADO Mirror (Moodle section structure) and Smart Theory/Practice
academic taxonomies (catering to STEM, Law, Medicine, and Humanities faculties)
with cross-platform path sanitization and granular lab subgroup policies.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Dict, List, Optional, Set, Tuple

from prado.config import SyncConfig
from prado.core.parser import CourseActivity, FileAttachment


WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

WINDOWS_RESERVED_REGEX = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$",
    re.IGNORECASE,
)

FORBIDDEN_CHARS_REGEX = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')

COMPOUND_EXTENSIONS = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst")

THEORY_KEYWORDS = [
    "teoría", "teoria", "theory", "tema", "temas", "topic",
    "diapositivas", "transparencias", "slides", "apuntes", "notes",
    "presentación", "presentacion", "presentation", "lección", "leccion",
    "lecture", "clases teóricas", "clase de teoría",
]

PRACTICE_KEYWORDS = [
    "práctica", "practica", "prácticas", "practicas", "practice",
    "lab", "laboratorio", "laboratory", "guion", "guión", "guia", "guía",
    "ejercicios", "exercises", "relación", "relacion", "boletín", "boletin",
    "boletines", "problemas", "taller", "talleres", "workshop",
    "proyecto", "project", "código", "codigo", "fuentes", "notebook",
    # Law & Humanities faculties
    "caso práctico", "casos prácticos", "jurisprudencia", "dictamen", "dictámenes",
    # Medicine & Health Sciences
    "caso clínico", "casos clínicos", "práctica clínica", "rotatorio", "urgencias",
    "lecturas", "seminario", "seminarios",
]

GENERAL_KEYWORDS = [
    "general", "guía docente", "guia docente", "avisos", "novedades",
    "presentación del curso", "información", "bienvenida",
]


def sanitize_path_segment(segment: str, max_length: int = 64) -> str:
    r"""
    Sanitizes directory or file name for 100% POSIX and Windows compatibility.
    - Replaces / \ : * ? " < > | and control chars with '_'
    - Collapses tabs/newlines into single spaces
    - Strips leading and trailing dots and spaces
    - Prefixes Windows reserved words (CON, PRN, etc., with single or compound extensions) with '_'
    - Smart truncates to max_length to avoid Windows MAX_PATH violations,
      preserving file extension (up to 16 chars) while truncating only the stem
    """
    if not segment:
        return "unnamed"

    # Replace tabs/newlines first
    cleaned = re.sub(r"[\t\n\r]+", " ", segment).strip()
    cleaned = FORBIDDEN_CHARS_REGEX.sub("_", cleaned).strip(". ")
    if not cleaned:
        return "unnamed"

    # Prefix Windows reserved device names (CON, AUX, COM1, etc. with any extension)
    if WINDOWS_RESERVED_REGEX.match(cleaned):
        cleaned = f"_{cleaned}"

    # Smart truncation enforcing max_length while preserving file extensions
    if len(cleaned) > max_length:
        lower = cleaned.lower()
        comp_ext = None
        for ce in COMPOUND_EXTENSIONS:
            if lower.endswith(ce):
                comp_ext = cleaned[-len(ce):]
                stem = cleaned[:-len(ce)]
                break

        if comp_ext is not None:
            ext = comp_ext
        else:
            stem, ext = os.path.splitext(cleaned)

        # Check if ext is a plausible file extension (<= 16 chars, starts with '.', no whitespace)
        if 1 < len(ext) <= 16 and ext.startswith(".") and not any(c.isspace() for c in ext):
            stem_budget = max_length - len(ext)
            if stem_budget > 0:
                truncated_stem = stem[:stem_budget].rstrip(". ")
                if not truncated_stem:
                    truncated_stem = stem[:stem_budget]
                cleaned = f"{truncated_stem}{ext}"
            else:
                cleaned = cleaned[:max_length].rstrip(". ")
        else:
            cleaned = cleaned[:max_length].rstrip(". ")

        # Re-check Windows reserved device names in case truncation produced one (e.g. CONSOLE.txt -> CON.txt)
        if WINDOWS_RESERVED_REGEX.match(cleaned):
            lower = cleaned.lower()
            comp_ext = None
            for ce in COMPOUND_EXTENSIONS:
                if lower.endswith(ce):
                    comp_ext = cleaned[-len(ce):]
                    stem = cleaned[:-len(ce)]
                    break
            if comp_ext is not None:
                ext = comp_ext
            else:
                stem, ext = os.path.splitext(cleaned)

            if 1 < len(ext) <= 16 and ext.startswith(".") and not any(c.isspace() for c in ext):
                new_budget = max_length - len(ext) - 1
                if new_budget > 0:
                    trimmed_stem = stem[:new_budget].rstrip(". ")
                    cleaned = f"_{trimmed_stem}{ext}"
                else:
                    cleaned = f"_{cleaned[:max_length - 1]}"
            else:
                cleaned = f"_{cleaned[:max_length - 1]}"

    return cleaned or "unnamed"


def detect_subgroup_in_text(text: str) -> List[str]:
    """
    Extracts lab subgroup identifiers (e.g. C1, C2, C3, E3, A1) with strict word boundaries.
    Guarantees 'C2' never matches 'C20'.
    """
    matches = re.findall(r"\b([A-Za-z]\d{1,2})\b", text)
    return list(dict.fromkeys(matches))


@dataclass
class RoutingDecision:
    """The computed destination path and action for an activity or file."""
    target_rel_path: Path
    is_subgroup: bool
    subgroup_tag: Optional[str]
    action: str  # "download", "archive", "skip"
    reason: str


class CourseRouter:
    """Computes destination filesystem paths and subgroup filtering policies."""

    def __init__(self, config: Optional[SyncConfig] = None):
        self.config = config or SyncConfig()
        self.preset = self.config.preset.lower() if self.config.preset else "smart"
        self.subgroups = self.config.subgroups or {}

    def route_activity(
        self,
        activity: CourseActivity,
        file: Optional[FileAttachment] = None,
        course_slug: str = "COURSE",
        subgroup_policy: str = "archive",
    ) -> RoutingDecision:
        """
        Determines the target relative path and sync action for an activity or attachment.
        """
        resolved_policy = subgroup_policy if subgroup_policy in ("archive", "ignore", "include") else "archive"

        filename = file.name if file else f"{activity.title}.pdf"
        sanitized_filename = sanitize_path_segment(filename, max_length=128)

        # 1. Subgroup Analysis
        student_group = self.subgroups.get(activity.course_id) or self.subgroups.get(course_slug)
        combined_text = f"{activity.section_name} {activity.title}"
        detected_groups = detect_subgroup_in_text(combined_text)

        is_subgroup_item = len(detected_groups) > 0
        subgroup_tag = "_".join(detected_groups) if detected_groups else None

        # Check for inactive subgroup handling
        if student_group and is_subgroup_item:
            has_student_group = bool(re.search(rf"\b{re.escape(student_group)}\b", combined_text, re.IGNORECASE))
            if not has_student_group:
                tag = subgroup_tag or "other"
                if resolved_policy == "ignore":
                    return RoutingDecision(
                        target_rel_path=Path("_subgroups_archive") / tag / sanitized_filename,
                        is_subgroup=True,
                        subgroup_tag=subgroup_tag,
                        action="skip",
                        reason=f"Inactive subgroup '{tag}' skipped by policy.",
                    )
                elif resolved_policy == "archive":
                    target_dir = Path("_subgroups_archive") / tag
                    return RoutingDecision(
                        target_rel_path=target_dir / sanitized_filename,
                        is_subgroup=True,
                        subgroup_tag=subgroup_tag,
                        action="archive",
                        reason=f"Inactive subgroup '{tag}' archived.",
                    )

        # 2. PRADO Mirror Preset
        if self.preset == "mirror":
            sec_folder = sanitize_path_segment(activity.section_name, max_length=64)
            return RoutingDecision(
                target_rel_path=Path(sec_folder) / sanitized_filename,
                is_subgroup=is_subgroup_item,
                subgroup_tag=subgroup_tag,
                action="download",
                reason="Mirror preset: mapped to sanitized section folder.",
            )

        # 3. Smart Theory/Practice Preset
        text_lower = combined_text.lower()

        # Check General Section
        if any(k in text_lower for k in GENERAL_KEYWORDS) or activity.section_id == "section-0":
            return RoutingDecision(
                target_rel_path=Path("General") / sanitized_filename,
                is_subgroup=is_subgroup_item,
                subgroup_tag=subgroup_tag,
                action="download",
                reason="Smart preset: routed to General.",
            )

        # Check Practice
        is_practice = any(k in text_lower for k in PRACTICE_KEYWORDS) or activity.mod_type in ("assign",)
        if is_practice:
            p_match = re.search(r"\b(?:p|pr[áa]ctica|practica)\s*0?(\d+)\b", text_lower)
            if p_match:
                sub_folder = f"P{p_match.group(1)}"
                target_path = Path("Practicas") / sub_folder / sanitized_filename
            else:
                target_path = Path("Practicas") / sanitized_filename

            return RoutingDecision(
                target_rel_path=target_path,
                is_subgroup=is_subgroup_item,
                subgroup_tag=subgroup_tag,
                action="download",
                reason="Smart preset: routed to Practicas.",
            )

        # Check Theory
        is_theory = any(k in text_lower for k in THEORY_KEYWORDS) or activity.mod_type in ("resource",)
        if is_theory:
            target_path = Path("Teoria") / sanitized_filename
            return RoutingDecision(
                target_rel_path=target_path,
                is_subgroup=is_subgroup_item,
                subgroup_tag=subgroup_tag,
                action="download",
                reason="Smart preset: routed to Teoria.",
            )

        # Default fallback to Teoria
        target_path = Path("Teoria") / sanitized_filename
        return RoutingDecision(
            target_rel_path=target_path,
            is_subgroup=is_subgroup_item,
            subgroup_tag=subgroup_tag,
            action="download",
            reason="Smart preset: fallback default to Teoria.",
        )
