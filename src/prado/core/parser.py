"""
HTML activity parser and content extraction engine for PradoOS.

Parses Moodle course section hierarchies (li#section-N, div.course-section),
activities (mod/resource, mod/folder, mod/assign, mod/forum, mod/url),
deadlines, starter code briefs, and forum announcements.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import html
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import urllib.parse

from bs4 import BeautifulSoup


class ActivityType(str, Enum):
    RESOURCE = "resource"      # mod/resource (single downloadable file)
    FOLDER = "folder"          # mod/folder (multi-file directory)
    ASSIGN = "assign"          # mod/assign (assignment with deadline & briefs)
    FORUM = "forum"            # mod/forum (news announcements or discussion)
    URL = "url"                # mod/url (external link or syllabus guide)
    PAGE = "page"              # mod/page (embedded HTML page)
    QUIZ = "quiz"              # mod/quiz (online questionnaire)
    OTHER = "other"


@dataclass
class FileAttachment:
    """Represents a downloadable file attached to an activity or within a folder."""
    name: str
    url: str
    size_bytes: Optional[int] = None
    mimetype: Optional[str] = None
    relative_path: Optional[str] = None
    download_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "size_bytes": self.size_bytes,
            "mimetype": self.mimetype,
            "relative_path": self.relative_path,
            "download_url": self.download_url,
        }


@dataclass
class CourseActivity:
    """Canonical representation of a Moodle activity extracted from HTML."""
    id: str                                      # Course module ID (cmid), e.g. "107913"
    course_id: str                               # Moodle course ID, e.g. "15819"
    section_id: str                              # e.g. "section-1"
    section_name: str                            # e.g. "Tema 1: Eficiencia de Algoritmos"
    mod_type: str                                # "resource", "folder", "assign", "forum", "url"
    title: str                                   # Sanitized title
    url: str                                     # Activity view URL
    description: str = ""                        # Brief intro/description text
    due_date: Optional[datetime.datetime] = None # Submission deadline (mod/assign)
    submission_status: Optional[str] = None      # "Sin entregar", "Entregado", etc.
    attachments: List[FileAttachment] = field(default_factory=list)
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "course_id": self.course_id,
            "section_id": self.section_id,
            "section_name": self.section_name,
            "mod_type": self.mod_type,
            "title": self.title,
            "url": self.url,
            "description": self.description,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "submission_status": self.submission_status,
            "attachments": [a.to_dict() for a in self.attachments],
            "extra_metadata": self.extra_metadata,
        }


@dataclass
class SectionInfo:
    """Represents a topic or weekly section in a course."""
    id: str                                      # e.g. "section-1"
    section_num: int                             # e.g. 1
    name: str                                    # e.g. "Tema 1: Eficiencia de Algoritmos"
    summary: str = ""
    activities: List[CourseActivity] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "section_num": self.section_num,
            "name": self.name,
            "summary": self.summary,
            "activities": [a.to_dict() for a in self.activities],
        }


@dataclass
class ParsedCourse:
    """Container for all parsed content from a course page."""
    course_id: str
    course_title: str
    sections: List[SectionInfo] = field(default_factory=list)
    activities: List[CourseActivity] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "course_id": self.course_id,
            "course_title": self.course_title,
            "sections": [s.to_dict() for s in self.sections],
            "activities": [a.to_dict() for a in self.activities],
        }


ACCESSIBILITY_SUFFIX_REGEX = re.compile(
    r"\s+(?:Archivo|File|Carpeta|Folder|Tarea|Assignment|Foro|Forum|URL|Enlace|Link|Documento|Document|Página|Page|Cuestionario|Quiz)\s*$",
    re.IGNORECASE
)

SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

ENGLISH_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def clean_activity_title(raw_title: str) -> str:
    """
    Decodes HTML entities, collapses whitespaces, and removes Moodle accessibility suffixes.
    Example: 'Tema 1 - Diapositivas &amp; Apuntes Archivo' -> 'Tema 1 - Diapositivas & Apuntes'
    """
    if not raw_title:
        return ""
    text = html.unescape(raw_title)
    text = re.sub(r"[\s\u200b\ufeff]+", " ", text).strip()
    text = ACCESSIBILITY_SUFFIX_REGEX.sub("", text).strip()
    return text


def parse_moodle_date(date_str: str) -> Optional[datetime.datetime]:
    """
    Parses Spanish and English Moodle dates into Python datetime objects deterministically
    without reliance on system C-locale.
    """
    if not date_str:
        return None
    cleaned = date_str.strip().lower()

    # Spanish format: [weekday,] D de M de Y[, H:M]
    es_match = re.search(
        r"(?:(?:lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo),\s*)?"
        r"(\d{1,2})\s+de\s+([a-zA-ZáéíóúÁÉÍÓÚ]+)\s+de\s+(\d{4})"
        r"(?:,?\s+(\d{1,2}):(\d{2}))?",
        cleaned
    )
    if es_match:
        day = int(es_match.group(1))
        month_name = es_match.group(2).lower()
        year = int(es_match.group(3))
        hour = int(es_match.group(4)) if es_match.group(4) is not None else 0
        minute = int(es_match.group(5)) if es_match.group(5) is not None else 0
        month = SPANISH_MONTHS.get(month_name)
        if month:
            return datetime.datetime(year, month, day, hour, minute)

    # English format: [weekday,] D Month Y[, H:M (AM|PM)?]
    en_match = re.search(
        r"(?:(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),\s*)?"
        r"(\d{1,2})\s+([a-zA-Z]+)\s+(\d{4})"
        r"(?:,?\s+(\d{1,2}):(\d{2})(?:\s*(am|pm))?)?",
        cleaned
    )
    if en_match:
        day = int(en_match.group(1))
        month_name = en_match.group(2).lower()
        year = int(en_match.group(3))
        hour = int(en_match.group(4)) if en_match.group(4) is not None else 0
        minute = int(en_match.group(5)) if en_match.group(5) is not None else 0
        meridiem = en_match.group(6)
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        month = ENGLISH_MONTHS.get(month_name)
        if month:
            return datetime.datetime(year, month, day, hour, minute)

    return None


class CourseHtmlParser:
    """Pure, robust Moodle course and activity HTML parser."""

    @staticmethod
    def parse_course_page(
        html_content: str,
        course_id: str,
        base_url: str = "https://pradogrado2627.ugr.es"
    ) -> ParsedCourse:
        soup = BeautifulSoup(html_content, "html.parser")

        title_tag = soup.find(["h1", "title"])
        course_title = clean_activity_title(title_tag.get_text()) if title_tag else f"Course {course_id}"

        # Find all sections (li#section-N or div.course-section)
        section_elems = soup.find_all(["li", "div"], id=re.compile(r"^section-\d+$"))
        sections: List[SectionInfo] = []
        all_activities: List[CourseActivity] = []
        seen_cmids = set()

        for sec_el in section_elems:
            sec_id_attr = sec_el.get("id", "section-0")
            sec_num_match = re.search(r"\d+", sec_id_attr)
            sec_num = int(sec_num_match.group(0)) if sec_num_match else 0

            # Find section name
            header_el = sec_el.find(["h3", "h4", "div"], class_=re.compile(r"sectionname|section-title"))
            if header_el:
                raw_name = header_el.get_text(" ", strip=True)
            elif sec_el.get("aria-label"):
                raw_name = sec_el["aria-label"]
            else:
                raw_name = f"Section {sec_num}" if sec_num > 0 else "General"
            sec_name = clean_activity_title(raw_name)

            sec_activities: List[CourseActivity] = []

            # Find all activities within the section
            act_elems = sec_el.find_all(["li", "div"], class_=re.compile(r"\bmodtype_|\bactivity-item\b"))
            for act_el in act_elems:
                anchor = act_el.find("a", href=True)
                if not anchor:
                    continue

                href = urllib.parse.urljoin(base_url, anchor["href"])
                raw_title = anchor.get_text(" ", strip=True)
                title = clean_activity_title(raw_title)
                if not title:
                    continue

                mod_type = "other"
                mod_match = re.search(r"\bmodtype_([a-zA-Z0-9_]+)\b", " ".join(act_el.get("class", [])))
                if mod_match:
                    mod_type = mod_match.group(1).lower()
                else:
                    for t in ("resource", "folder", "assign", "forum", "url", "page", "quiz"):
                        if f"/mod/{t}/" in href:
                            mod_type = t
                            break

                cmid = None
                cmid_match = re.search(r"[?&]id=(\d+)", href)
                if cmid_match:
                    cmid = cmid_match.group(1)
                elif act_el.get("id") and "module-" in act_el["id"]:
                    cmid = act_el["id"].replace("module-", "")
                else:
                    cmid = hashlib.sha256(href.encode("utf-8")).hexdigest()[:12]

                if cmid in seen_cmids:
                    continue
                seen_cmids.add(cmid)

                activity = CourseActivity(
                    id=cmid,
                    course_id=str(course_id),
                    section_id=sec_id_attr,
                    section_name=sec_name,
                    mod_type=mod_type,
                    title=title,
                    url=href,
                )
                sec_activities.append(activity)
                all_activities.append(activity)

            sections.append(SectionInfo(
                id=sec_id_attr,
                section_num=sec_num,
                name=sec_name,
                activities=sec_activities
            ))

        return ParsedCourse(
            course_id=str(course_id),
            course_title=course_title,
            sections=sections,
            activities=all_activities
        )

    @staticmethod
    def parse_assignment_page(
        html_content: str,
        activity: CourseActivity,
        base_url: str = "https://pradogrado2627.ugr.es"
    ) -> CourseActivity:
        """Parses assignment details: due dates, submission status, and starter/brief file attachments."""
        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Deadlines from data-region="activity-dates"
        dates_div = soup.find(["div", "section"], attrs={"data-region": "activity-dates"})
        if dates_div:
            for line in dates_div.stripped_strings:
                if any(k in line.lower() for k in ("cierre", "fecha de entrega", "due", "cutoff")):
                    activity.due_date = parse_moodle_date(line)
                    if activity.due_date:
                        break

        # Fallback to submission status table
        if not activity.due_date:
            table = soup.find("table", class_=re.compile(r"submissionstatustable|generaltable"))
            if table:
                for row in table.find_all("tr"):
                    cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                    if len(cells) >= 2:
                        header, val = cells[0].lower(), cells[1]
                        if any(k in header for k in ("fecha de entrega", "due date")):
                            activity.due_date = parse_moodle_date(val)
                        elif any(k in header for k in ("estado de la entrega", "submission status")):
                            activity.submission_status = val

        # 2. Attachments (starter code, notebooks, brief PDFs)
        attachments: List[FileAttachment] = []
        intro_div = soup.find(["div", "section"], class_=re.compile(r"introattachment|introattachments")) or soup.find(id="intro")
        search_scope = intro_div if intro_div else soup

        for a in search_scope.find_all("a", href=True):
            href = urllib.parse.urljoin(base_url, a["href"])
            if "/pluginfile.php/" in href:
                clean_url = href.split("?")[0]
                fname = urllib.parse.unquote(clean_url.split("/")[-1])
                if fname and not fname.startswith(".~lock.") and not fname.endswith("#"):
                    attachments.append(FileAttachment(
                        name=fname,
                        url=clean_url,
                        download_url=f"{clean_url}?forcedownload=1"
                    ))

        activity.attachments = attachments
        return activity

    @staticmethod
    def parse_folder_page(
        html_content: str,
        activity: CourseActivity,
        base_url: str = "https://pradogrado2627.ugr.es"
    ) -> List[FileAttachment]:
        """Parses individual downloadable files inside a multi-file folder activity."""
        soup = BeautifulSoup(html_content, "html.parser")
        attachments: List[FileAttachment] = []
        seen_urls = set()

        for a in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(base_url, a["href"])
            if "/pluginfile.php/" in href:
                clean_url = href.split("?")[0]
                if clean_url in seen_urls:
                    continue
                seen_urls.add(clean_url)

                fname = a.get_text(" ", strip=True) or urllib.parse.unquote(clean_url.split("/")[-1])
                fname = clean_activity_title(fname)
                if fname and not fname.startswith(".~lock."):
                    attachments.append(FileAttachment(
                        name=fname,
                        url=clean_url,
                        download_url=f"{clean_url}?forcedownload=1"
                    ))

        activity.attachments = attachments
        return attachments

    @staticmethod
    def parse_forum_announcements(
        html_content: str,
        activity: CourseActivity,
        base_url: str = "https://pradogrado2627.ugr.es"
    ) -> List[Dict[str, Any]]:
        """Parses announcements / discussion topics from a forum activity."""
        soup = BeautifulSoup(html_content, "html.parser")
        discussions = []

        posts = soup.find_all("article", class_=re.compile(r"forum-post-container|forumpost"))
        if posts:
            for post in posts:
                subj_el = post.find(["h3", "h4", "div"], class_=re.compile(r"post-subject|subject"))
                subject = clean_activity_title(subj_el.get_text(" ", strip=True)) if subj_el else "Announcement"

                author_el = post.find(["div", "span"], class_=re.compile(r"author|author-date"))
                author = author_el.get_text(" ", strip=True) if author_el else ""

                content_el = post.find(["div", "section"], class_=re.compile(r"post-content|posting"))
                content = content_el.get_text("\n", strip=True) if content_el else ""

                discussions.append({
                    "forum_id": activity.id,
                    "subject": subject,
                    "author": author,
                    "content": content,
                })
        else:
            seen_discuss_urls = set()
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/mod/forum/discuss.php?d=" in href and "#" not in href:
                    d_url = urllib.parse.urljoin(base_url, href).split("#")[0]
                    if d_url in seen_discuss_urls:
                        continue
                    subj_text = clean_activity_title(a.get_text(" ", strip=True))
                    if not subj_text:
                        continue
                    seen_discuss_urls.add(d_url)
                    discussions.append({
                        "forum_id": activity.id,
                        "subject": subj_text,
                        "url": d_url,
                    })

        return discussions
