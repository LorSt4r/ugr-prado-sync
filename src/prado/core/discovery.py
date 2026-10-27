"""
Course auto-discovery and metadata extraction engine for PradoOS.

Discovers enrolled Moodle courses via AJAX service (core_course_get_enrolled_courses
or timeline classification) with automatic fallback to DOM scraping on /my/courses.php
and /my/. Provides robust slug derivation, term/semester classification, and filtering.
"""
from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from enum import IntEnum
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
import requests

from prado.auth.session import MoodleSessionManager
from prado.config import get_default_moodle_url
from prado.exceptions import AuthenticationRequiredError, PradoError


class DiscoveryError(PradoError):
    """Base exception for course auto-discovery failures."""
    pass


class AjaxDiscoveryError(DiscoveryError):
    """Raised when Moodle AJAX webservice call fails, triggering DOM fallback."""
    pass


class DomParsingError(DiscoveryError):
    """Raised when DOM scraping fails to extract any valid course links."""
    pass


class NoCoursesFoundError(DiscoveryError):
    """Raised when no enrolled courses are found after both AJAX and DOM attempts."""
    pass


class CourseSemester(IntEnum):
    """Academic semester / term enumeration."""
    ANNUAL = 0
    SEMESTER_1 = 1  # Primer Cuatrimestre / Otoño
    SEMESTER_2 = 2  # Segundo Cuatrimestre / Primavera
    UNKNOWN = -1


SPANISH_STOP_WORDS = {
    "DE", "DEL", "LA", "LAS", "LOS", "EL", "Y", "POR", "CON", "PARA", "EN", "AL", "A"
}


def derive_course_slug(fullname: str, shortname: str = "", idnumber: str = "") -> str:
    """
    Derives clean, standard filesystem slug (e.g. 'ED_C', 'SO_E', 'TIC_A')
    from course fullname, shortname, and group patterns.
    """
    name = fullname.strip()

    # 1. Extract group tag if present: (Grupo X), Grupo X, or (COMÚN)
    group_tag = ""
    group_m = re.search(r"\(?\bGrupo\s*([A-Za-z0-9]+)\b\)?", name, re.IGNORECASE)
    if group_m:
        group_tag = f"_{group_m.group(1).upper()}"
    elif re.search(r"\bCOM[UÚ]N\b", name, re.IGNORECASE):
        group_tag = "_COMUN"

    # 2. Extract acronym from uppercase/titlecase words
    clean_title = re.sub(r"-\s*\d{4}.*", "", name)  # strip '- 2627 ...'
    clean_title = re.sub(r"\(.*?\)", "", clean_title)  # strip parentheses

    words = re.findall(r"[A-ZÁÉÍÓÚÑa-záéíóúñ]+", clean_title)
    acronym_chars: List[str] = []
    for w in words:
        w_upper = w.upper()
        if len(w) > 2 and w_upper not in SPANISH_STOP_WORDS:
            acronym_chars.append(w_upper[0])

    acronym = "".join(acronym_chars[:4])
    if acronym:
        return f"{acronym}{group_tag}"

    # 3. Fallback to shortname suffix or sanitized name
    if shortname:
        parts = shortname.split("-")
        if len(parts) > 1 and len(parts[-1]) <= 20:
            return parts[-1].strip().replace(" ", "_")

    sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
    return sanitized[:24] if sanitized else "COURSE"


def detect_semester_from_course(
    startdate: Optional[int],
    enddate: Optional[int],
    fullname: str = "",
    idnumber: str = "",
) -> Optional[int]:
    """
    Detects course semester (1 = Autumn, 2 = Spring, 0 = Annual)
    from startdate/enddate epoch timestamps and text patterns.
    """
    if startdate and startdate > 0:
        try:
            start_dt = datetime.datetime.fromtimestamp(startdate)
            end_dt = datetime.datetime.fromtimestamp(enddate) if enddate and enddate > 0 else None

            start_month = start_dt.month
            if start_month in (9, 10, 11):
                if end_dt:
                    if end_dt.month in (1, 2, 3):
                        return CourseSemester.SEMESTER_1
                    if end_dt.month in (5, 6, 7):
                        return CourseSemester.ANNUAL
                return CourseSemester.SEMESTER_1
            elif start_month in (1, 2, 3):
                return CourseSemester.SEMESTER_2
        except (ValueError, OSError):
            pass

    # Inspect text patterns
    combined = f"{fullname} {idnumber}".lower()
    if re.search(r"(?:\b1c\b|1[ºo]\s*c|primer\s*c|1[ºo]\s*sem|primer\s*sem|\bq1\b|\bs1\b)", combined):
        return CourseSemester.SEMESTER_1
    if re.search(r"(?:\b2c\b|2[ºo]\s*c|segundo\s*c|2[ºo]\s*sem|segundo\s*sem|\bq2\b|\bs2\b)", combined):
        return CourseSemester.SEMESTER_2
    if re.search(r"(?:\banual\b|\bannual\b)", combined):
        return CourseSemester.ANNUAL

    return None


@dataclass
class Course:
    """Normalized metadata model representing an enrolled Moodle course."""
    id: int
    fullname: str
    shortname: str = ""
    idnumber: str = ""
    startdate: Optional[int] = None
    enddate: Optional[int] = None
    visible: bool = True
    viewurl: str = ""
    coursecategory: str = ""
    isfavourite: bool = False
    hidden: bool = False
    summary: str = ""
    courseimage: Optional[str] = None
    progress: Optional[int] = None
    enrolledusercount: Optional[int] = None
    slug: str = ""
    semester: Optional[int] = None
    academic_year: str = ""
    is_active: bool = True
    subgroup: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.slug:
            self.slug = derive_course_slug(self.fullname, self.shortname, self.idnumber)
        if self.semester is None:
            self.semester = detect_semester_from_course(
                self.startdate, self.enddate, self.fullname, self.idnumber
            )

    def to_dict(self) -> Dict[str, Any]:
        """Returns JSON-serializable dictionary representation (omits large inline data:image/ SVGs)."""
        d = asdict(self)
        if isinstance(d.get("courseimage"), str) and d["courseimage"].startswith("data:image/"):
            d["courseimage"] = None
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Course:
        """Constructs Course instance from dictionary."""
        known_fields = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    @property
    def is_enrolled_and_active(self) -> bool:
        """Returns True if the course is visible to the student, not hidden, and active."""
        return self.visible and not self.hidden and self.is_active


@dataclass
class CourseFilter:
    """Filtering criteria for discovered courses."""
    semester: Optional[int] = None
    active_only: bool = True
    include_hidden: bool = False
    category: Optional[str] = None
    active_map: Dict[str, bool] = field(default_factory=dict)
    subgroup_map: Dict[str, str] = field(default_factory=dict)

    def matches(self, course: Course) -> bool:
        """Evaluates whether a Course meets the filter criteria."""
        if not self.include_hidden and (course.hidden or not course.visible):
            return False

        if self.active_only and not course.is_active:
            return False

        if self.semester is not None and course.semester is not None:
            # Annual courses (0) match both Semester 1 and Semester 2
            if course.semester != CourseSemester.ANNUAL and course.semester != self.semester:
                return False

        if self.category and self.category.lower() not in course.coursecategory.lower():
            return False

        return True

    def apply(self, courses: List[Course]) -> List[Course]:
        """Applies active toggles, subgroups, and filtering to course list."""
        result: List[Course] = []
        for c in courses:
            c_id_str = str(c.id)
            if c_id_str in self.active_map:
                c.is_active = bool(self.active_map[c_id_str])
            elif c.slug in self.active_map:
                c.is_active = bool(self.active_map[c.slug])

            if c_id_str in self.subgroup_map:
                c.subgroup = self.subgroup_map[c_id_str]
            elif c.slug in self.subgroup_map:
                c.subgroup = self.subgroup_map[c.slug]

            if self.matches(c):
                result.append(c)

        return result


class CourseDiscovery:
    """Orchestrates enrolled course discovery with AJAX and DOM fallback."""

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        session_manager: Optional[MoodleSessionManager] = None,
        session: Optional[requests.Session] = None,
        base_url: Optional[str] = None,
        sesskey: Optional[str] = None,
        timeout: int = 15,
    ) -> None:
        self.session_manager = session_manager
        self._session = session
        resolved_base = base_url or (session_manager.base_url if session_manager else get_default_moodle_url())
        self.base_url = resolved_base.rstrip("/")
        self.sesskey = sesskey
        self.timeout = timeout

    @property
    def session(self) -> requests.Session:
        """Resolves authenticated requests.Session lazily."""
        if self._session is not None:
            return self._session
        if self.session_manager is not None:
            self._session = self.session_manager.get_authenticated_session(self.base_url)
            return self._session
        raise AuthenticationRequiredError("No session or MoodleSessionManager provided.")

    def discover_courses(self, course_filter: Optional[CourseFilter] = None) -> List[Course]:
        """
        Main entry point for course auto-discovery.
        Attempts Moodle AJAX service first; falls back to DOM scraping on failure.
        Applies course_filter if provided.
        """
        courses: List[Course] = []
        try:
            courses = self.discover_via_ajax()
        except Exception:
            courses = self.discover_via_dom()

        if course_filter:
            courses = course_filter.apply(courses)

        return courses

    def extract_sesskey(self, html: Optional[str] = None) -> Optional[str]:
        """Extracts Moodle sesskey from provided HTML or by fetching /my/."""
        if self.sesskey:
            return self.sesskey

        content = html
        if content is None:
            try:
                resp = self.session.get(f"{self.base_url}/my/", timeout=self.timeout)
                self._check_redirect_for_auth(resp.url)
                if resp.status_code == 200:
                    content = resp.text
            except requests.RequestException:
                return None

        if not content:
            return None

        # Pattern 1: M.cfg = {sesskey: "..."} or {"sesskey": "..."}
        m = re.search(r'["\']?sesskey["\']?\s*:\s*["\']([a-zA-Z0-9_]+)["\']', content)
        if m:
            self.sesskey = m.group(1)
            return self.sesskey

        # Pattern 2: logout.php?sesskey=...
        m = re.search(r'logout\.php\?sesskey=([a-zA-Z0-9_]+)', content)
        if m:
            self.sesskey = m.group(1)
            return self.sesskey

        # Pattern 3: input hidden name="sesskey"
        m = re.search(r'name=["\']sesskey["\']\s+value=["\']([a-zA-Z0-9_]+)["\']', content)
        if m:
            self.sesskey = m.group(1)
            return self.sesskey

        return None

    def discover_via_ajax(self) -> List[Course]:
        """
        Queries /lib/ajax/service.php using authenticated session.
        Raises AjaxDiscoveryError if request fails or returns an error response.
        """
        sesskey = self.extract_sesskey() or ""
        ajax_url = (
            f"{self.base_url}/lib/ajax/service.php?"
            f"sesskey={sesskey}&info=core_course_get_enrolled_courses_by_timeline_classification"
        )

        payload = [
            {
                "index": 0,
                "methodname": "core_course_get_enrolled_courses_by_timeline_classification",
                "args": {
                    "offset": 0,
                    "limit": 0,
                    "classification": "all",
                    "sort": "fullname",
                },
            }
        ]

        try:
            resp = self.session.post(
                ajax_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            self._check_redirect_for_auth(resp.url)
            if resp.status_code != 200:
                raise AjaxDiscoveryError(f"Moodle AJAX returned HTTP status {resp.status_code}")

            data = resp.json()
            return self.parse_ajax_response(data)
        except requests.RequestException as e:
            raise AjaxDiscoveryError(f"Network error during Moodle AJAX call: {e}") from e

    def parse_ajax_response(self, data: Any) -> List[Course]:
        """Parses Moodle AJAX JSON response into a list of Course objects."""
        if not isinstance(data, list) or not data:
            raise AjaxDiscoveryError("Malformed Moodle AJAX response: expected non-empty list")

        first_item = data[0]
        if not isinstance(first_item, dict):
            raise AjaxDiscoveryError("Malformed Moodle AJAX item: expected dictionary")

        if first_item.get("error") is True:
            err_msg = first_item.get("exception", {}).get("message", "Unknown Moodle AJAX error")
            raise AjaxDiscoveryError(f"Moodle AJAX error returned: {err_msg}")

        item_data = first_item.get("data")
        raw_courses: List[Dict[str, Any]] = []

        if isinstance(item_data, dict):
            raw_courses = item_data.get("courses", [])
        elif isinstance(item_data, list):
            raw_courses = item_data
        else:
            raise AjaxDiscoveryError("Malformed AJAX data field")

        courses: List[Course] = []
        for rc in raw_courses:
            if not isinstance(rc, dict) or "id" not in rc or "fullname" not in rc:
                continue

            course = Course(
                id=int(rc["id"]),
                fullname=str(rc["fullname"]),
                shortname=str(rc.get("shortname", "")),
                idnumber=str(rc.get("idnumber", "")),
                startdate=rc.get("startdate"),
                enddate=rc.get("enddate"),
                visible=bool(rc.get("visible", True)),
                viewurl=str(rc.get("viewurl", f"{self.base_url}/course/view.php?id={rc['id']}")),
                coursecategory=str(rc.get("coursecategory", "")),
                isfavourite=bool(rc.get("isfavourite", False)),
                hidden=bool(rc.get("hidden", False)),
                summary=str(rc.get("summary", "")),
                courseimage=rc.get("courseimage"),
                progress=rc.get("progress"),
                enrolledusercount=rc.get("enrolledusercount"),
            )
            courses.append(course)

        return courses

    def discover_via_dom(self, html: Optional[str] = None) -> List[Course]:
        """
        Scrapes enrolled courses from /my/courses.php or /my/ HTML.
        Accepts optional html string for offline/mock testing.
        """
        content = html
        if content is None:
            # Try /my/courses.php first
            url_courses = f"{self.base_url}/my/courses.php"
            try:
                resp = self.session.get(url_courses, timeout=self.timeout)
                self._check_redirect_for_auth(resp.url)
                if resp.status_code == 200:
                    content = resp.text
            except requests.RequestException:
                content = None

            # Fallback to /my/
            if not content:
                url_my = f"{self.base_url}/my/"
                try:
                    resp = self.session.get(url_my, timeout=self.timeout)
                    self._check_redirect_for_auth(resp.url)
                    if resp.status_code == 200:
                        content = resp.text
                except requests.RequestException as e:
                    raise DomParsingError(f"Failed to fetch Moodle dashboard: {e}") from e

        if not content:
            raise DomParsingError("Empty HTML received for Moodle dashboard")

        return self.parse_dom_html(content)

    def parse_dom_html(self, html: str) -> List[Course]:
        """Parses HTML DOM and returns deduplicated list of Course objects."""
        soup = BeautifulSoup(html, "html.parser")
        courses_by_id: Dict[int, Course] = {}

        links = soup.find_all("a", href=re.compile(r"/course/view\.php\?id=\d+"))
        for a in links:
            href = a.get("href", "")
            m = re.search(r"[?&]id=(\d+)", href)
            if not m:
                continue

            course_id = int(m.group(1))
            fullname = a.get_text().strip()
            if not fullname or len(fullname) < 3:
                parent = a.find_parent(["div", "li", "h3", "h4"])
                if parent:
                    fullname = parent.get_text().strip()

            fullname = re.sub(r"\s+", " ", fullname).strip()
            if not fullname:
                continue

            container = a.find_parent(class_=re.compile(r"(card|coursebox|course-info-container)"))
            category = ""
            if container:
                cat_elem = container.find(class_=re.compile(r"(category|categoryname)"))
                if cat_elem:
                    category = cat_elem.get_text().strip()

            view_url = urljoin(self.base_url, href)

            if course_id not in courses_by_id:
                courses_by_id[course_id] = Course(
                    id=course_id,
                    fullname=fullname,
                    viewurl=view_url,
                    coursecategory=category,
                )

        if not courses_by_id:
            raise DomParsingError("No course links matching /course/view.php?id=\\d+ found in DOM")

        return list(courses_by_id.values())

    def _check_redirect_for_auth(self, url: str) -> None:
        """Raises AuthenticationRequiredError if redirected to login or IdP."""
        url_lower = url.lower()
        if "idp.ugr.es" in url_lower or "admin/tool/mfa" in url_lower:
            raise AuthenticationRequiredError("Session redirected to IdP / MFA. Re-authentication required.")
        if "/login/" in url_lower and "logout.php" not in url_lower:
            raise AuthenticationRequiredError("Session expired; redirected to login page.")
