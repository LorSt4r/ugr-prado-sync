"""
Unit tests for CourseDiscovery and metadata extraction engine.
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch
import pytest
import requests

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
from prado.discovery import CourseDiscovery as CDTopLevel, Course as CTopLevel
from prado.exceptions import AuthenticationRequiredError


class TestCourseDataClass:
    def test_course_instantiation_defaults(self):
        c = Course(id=15819, fullname="ESTRUCTURA DE DATOS - 2627 (Grupo C)")
        assert c.id == 15819
        assert c.fullname == "ESTRUCTURA DE DATOS - 2627 (Grupo C)"
        assert c.slug == "ED_C"
        assert c.visible is True
        assert c.hidden is False
        assert c.is_active is True
        assert c.is_enrolled_and_active is True

    def test_course_to_dict_and_from_dict_roundtrip(self):
        c = Course(
            id=15820,
            fullname="SISTEMAS OPERATIVOS - 2627 (Grupo E)",
            shortname="SO_2627_E",
            idnumber="296_11_23_2627_E",
            startdate=1788739200,
            enddate=1820275200,
            coursecategory="Grado en Ingenieria Informatica",
            isfavourite=True,
        )
        d = c.to_dict()
        assert d["id"] == 15820
        assert d["slug"] == "SO_E"
        assert d["isfavourite"] is True

        c2 = Course.from_dict(d)
        assert c2.id == c.id
        assert c2.fullname == c.fullname
        assert c2.slug == c.slug
        assert c2.coursecategory == c.coursecategory
        assert c2.isfavourite is True

    def test_course_is_enrolled_and_active(self):
        c1 = Course(id=1, fullname="Course 1", visible=True, hidden=False, is_active=True)
        assert c1.is_enrolled_and_active is True

        c2 = Course(id=2, fullname="Course 2", visible=False, hidden=False, is_active=True)
        assert c2.is_enrolled_and_active is False

        c3 = Course(id=3, fullname="Course 3", visible=True, hidden=True, is_active=True)
        assert c3.is_enrolled_and_active is False

        c4 = Course(id=4, fullname="Course 4", visible=True, hidden=False, is_active=False)
        assert c4.is_enrolled_and_active is False


class TestSlugDerivation:
    def test_slug_standard_ugr_names(self):
        assert derive_course_slug("ESTRUCTURA DE DATOS - 2627 (Grupo C)") == "ED_C"
        assert derive_course_slug("SISTEMAS OPERATIVOS - 2627 (Grupo E)") == "SO_E"
        assert derive_course_slug("MODELOS DE COMPUTACIÓN - 2627 (Grupo B)") == "MC_B"
        assert derive_course_slug("TEORÍA DE LA INFORMACIÓN Y CODIFICACIÓN - 2627 (Grupo A)") == "TIC_A"
        assert derive_course_slug("VISIÓN POR COMPUTADOR - 2627 (Grupo A)") == "VC_A"

    def test_slug_with_comun(self):
        assert derive_course_slug("SISTEMAS OPERATIVOS - 2627 (COMÚN)") == "SO_COMUN"
        assert derive_course_slug("ESTRUCTURA DE DATOS - 2627 (COMUN)") == "ED_COMUN"

    def test_slug_fallback_and_sanitization(self):
        assert derive_course_slug("C++", shortname="COURSE-CPP_ADV") == "CPP_ADV"
        sanitized = derive_course_slug("???", shortname="")
        assert len(sanitized) > 0


class TestSemesterDetection:
    def test_semester_detection_from_epoch_autumn(self):
        # Sept 2026 to Feb 2027 -> Semester 1
        start = int(datetime.datetime(2026, 9, 15).timestamp())
        end = int(datetime.datetime(2027, 2, 10).timestamp())
        assert detect_semester_from_course(start, end) == CourseSemester.SEMESTER_1

    def test_semester_detection_from_epoch_spring(self):
        # Feb 2027 to June 2027 -> Semester 2
        start = int(datetime.datetime(2027, 2, 15).timestamp())
        end = int(datetime.datetime(2027, 6, 30).timestamp())
        assert detect_semester_from_course(start, end) == CourseSemester.SEMESTER_2

    def test_semester_detection_from_epoch_annual(self):
        # Sept 2026 to June 2027 -> Annual (0)
        start = int(datetime.datetime(2026, 9, 15).timestamp())
        end = int(datetime.datetime(2027, 6, 30).timestamp())
        assert detect_semester_from_course(start, end) == CourseSemester.ANNUAL

    def test_semester_detection_from_text_patterns(self):
        assert detect_semester_from_course(None, None, fullname="Derecho Civil 1C") == CourseSemester.SEMESTER_1
        assert detect_semester_from_course(None, None, fullname="Derecho Penal (2º Semestre)") == CourseSemester.SEMESTER_2
        assert detect_semester_from_course(None, None, fullname="Trabajo Fin de Grado (Anual)") == CourseSemester.ANNUAL
        assert detect_semester_from_course(None, None, fullname="Curso General") is None


class TestCourseFilter:
    def test_filter_by_semester(self):
        c1 = Course(id=1, fullname="C1", semester=1)
        c2 = Course(id=2, fullname="C2", semester=2)
        c3 = Course(id=3, fullname="C3", semester=0)  # Annual matches both

        f_sem1 = CourseFilter(semester=1)
        res = f_sem1.apply([c1, c2, c3])
        assert len(res) == 2
        assert c1 in res
        assert c3 in res
        assert c2 not in res

    def test_filter_hidden_and_inactive(self):
        c_act = Course(id=1, fullname="Active", visible=True, hidden=False, is_active=True)
        c_hid = Course(id=2, fullname="Hidden", visible=True, hidden=True, is_active=True)
        c_inact = Course(id=3, fullname="Inactive", visible=True, hidden=False, is_active=False)

        f_default = CourseFilter()
        res = f_default.apply([c_act, c_hid, c_inact])
        assert len(res) == 1
        assert res[0].id == 1

        f_incl_hidden = CourseFilter(include_hidden=True, active_only=False)
        res2 = f_incl_hidden.apply([c_act, c_hid, c_inact])
        assert len(res2) == 3

    def test_filter_active_map_override(self):
        c1 = Course(id=15819, fullname="Course 1", slug="ED_C")
        c2 = Course(id=15820, fullname="Course 2", slug="SO_E")

        f = CourseFilter(active_map={"ED_C": False, "15820": True})
        res = f.apply([c1, c2])
        assert len(res) == 1
        assert res[0].id == 15820
        assert c1.is_active is False

    def test_filter_subgroups_population(self):
        c1 = Course(id=15819, fullname="Course 1", slug="ED_C")
        f = CourseFilter(subgroup_map={"ED_C": "C2"})
        res = f.apply([c1])
        assert res[0].subgroup == "C2"


class TestSesskeyExtraction:
    def test_extract_sesskey_from_m_cfg(self):
        html = '<script>var M = {cfg: {sesskey: "sesskey_12345", wwwroot: "https://prado.ugr.es"}};</script>'
        cd = CourseDiscovery(session=requests.Session(), base_url="https://prado.ugr.es")
        assert cd.extract_sesskey(html) == "sesskey_12345"

    def test_extract_sesskey_from_logout_link(self):
        html = '<a href="https://prado.ugr.es/login/logout.php?sesskey=logout_sess_999">Cerrar sesion</a>'
        cd = CourseDiscovery(session=requests.Session(), base_url="https://prado.ugr.es")
        assert cd.extract_sesskey(html) == "logout_sess_999"

    def test_extract_sesskey_from_hidden_input(self):
        html = '<input type="hidden" name="sesskey" value="input_sess_888">'
        cd = CourseDiscovery(session=requests.Session(), base_url="https://prado.ugr.es")
        assert cd.extract_sesskey(html) == "input_sess_888"

    def test_extract_sesskey_missing_returns_none(self):
        html = '<div><p>No sesskey here</p></div>'
        cd = CourseDiscovery(session=requests.Session(), base_url="https://prado.ugr.es")
        assert cd.extract_sesskey(html) is None


class TestAjaxDiscovery:
    def test_parse_ajax_response_success(self, sample_html_fixtures):
        cd = CourseDiscovery(session=requests.Session(), base_url="https://pradogrado2627.ugr.es")
        payload = [{"data": {"courses": sample_html_fixtures["moodle_ajax_courses"]}}]
        courses = cd.parse_ajax_response(payload)
        assert len(courses) == 5
        assert courses[0].id == 15819
        assert courses[0].slug == "ED_C"
        assert courses[1].id == 15820
        assert courses[1].slug == "SO_E"

    def test_parse_ajax_response_error_payload(self):
        cd = CourseDiscovery(session=requests.Session())
        payload = [{"error": True, "exception": {"message": "Invalid session"}}]
        with pytest.raises(AjaxDiscoveryError) as exc_info:
            cd.parse_ajax_response(payload)
        assert "Invalid session" in str(exc_info.value)

    def test_parse_ajax_response_malformed(self):
        cd = CourseDiscovery(session=requests.Session())
        with pytest.raises(AjaxDiscoveryError):
            cd.parse_ajax_response([])
        with pytest.raises(AjaxDiscoveryError):
            cd.parse_ajax_response([{"data": None}])

    def test_ajax_discovery_network_error_triggers_dom_fallback(self):
        session = requests.Session()
        cd = CourseDiscovery(session=session, base_url="https://pradogrado2627.ugr.es")

        # Mock post to raise network error, get to return valid dashboard DOM
        dashboard_html = """
        <div class="course-info-container">
            <a href="https://pradogrado2627.ugr.es/course/view.php?id=15819" class="coursename">
                ESTRUCTURA DE DATOS - 2627 (Grupo C)
            </a>
        </div>
        """
        with patch.object(session, "post", side_effect=requests.RequestException("Timeout")):
            with patch.object(session, "get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.text = dashboard_html
                mock_resp.url = "https://pradogrado2627.ugr.es/my/courses.php"
                mock_get.return_value = mock_resp

                courses = cd.discover_courses()
                assert len(courses) == 1
                assert courses[0].id == 15819


class TestDomDiscovery:
    def test_parse_dom_html_dashboard(self, sample_html_fixtures):
        cd = CourseDiscovery(session=requests.Session(), base_url="https://pradogrado2627.ugr.es")
        html = sample_html_fixtures["moodle_dashboard"]
        courses = cd.parse_dom_html(html)
        assert len(courses) == 5
        ids = [c.id for c in courses]
        assert 15819 in ids
        assert 15820 in ids

    def test_parse_dom_deduplication(self):
        html = """
        <a href="/course/view.php?id=123">Course 123</a>
        <a href="/course/view.php?id=123">Course 123 duplicate</a>
        <a href="/course/view.php?id=456">Course 456</a>
        """
        cd = CourseDiscovery(session=requests.Session(), base_url="https://prado.ugr.es")
        courses = cd.parse_dom_html(html)
        assert len(courses) == 2
        assert {c.id for c in courses} == {123, 456}

    def test_parse_dom_empty_raises_dom_parsing_error(self):
        cd = CourseDiscovery(session=requests.Session(), base_url="https://prado.ugr.es")
        with pytest.raises(DomParsingError):
            cd.parse_dom_html("<html><body><p>No courses</p></body></html>")


class TestSessionRedirects:
    def test_redirect_to_idp_raises_auth_required(self):
        cd = CourseDiscovery(session=requests.Session())
        with pytest.raises(AuthenticationRequiredError):
            cd._check_redirect_for_auth("https://idp.ugr.es/idp/profile/SAML2/Redirect/SSO")

    def test_redirect_to_mfa_raises_auth_required(self):
        cd = CourseDiscovery(session=requests.Session())
        with pytest.raises(AuthenticationRequiredError):
            cd._check_redirect_for_auth("https://pradogrado2627.ugr.es/admin/tool/mfa/auth.php")

    def test_redirect_to_login_raises_auth_required(self):
        cd = CourseDiscovery(session=requests.Session())
        with pytest.raises(AuthenticationRequiredError):
            cd._check_redirect_for_auth("https://pradogrado2627.ugr.es/login/index.php")


class TestTopLevelReExports:
    def test_top_level_re_exports(self):
        assert CDTopLevel is CourseDiscovery
        assert CTopLevel is Course
