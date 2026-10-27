"""
Unit tests for CourseRouter and folder routing / subgroup engine.
"""
from __future__ import annotations

from pathlib import Path
import pytest

from prado.config import SyncConfig
from prado.core.parser import CourseActivity, FileAttachment
from prado.core.router import (
    CourseRouter,
    RoutingDecision,
    detect_subgroup_in_text,
    sanitize_path_segment,
)
from prado.routing import (
    CourseRouter as CRTopLevel,
    detect_subgroup_in_text as detect_subgroup_top_level,
    sanitize_path_segment as sanitize_top_level,
)


class TestSanitizePathSegment:
    def test_forbidden_characters_replaced(self):
        raw = 'Tema 1: Eficiencia / Algoritmos * "¿Qué es?" <100%|OK>'
        sanitized = sanitize_path_segment(raw)
        for char in '/\\:*?"<>|':
            assert char not in sanitized
        assert "Tema 1_ Eficiencia _ Algoritmos _ _¿Qué es_ _100%_OK_" in sanitized

    def test_windows_reserved_names_prefixed(self):
        for reserved in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT1"):
            assert sanitize_path_segment(reserved) == f"_{reserved}"
            assert sanitize_path_segment(f"{reserved}.txt") == f"_{reserved}.txt"

    def test_trailing_dots_and_spaces_stripped(self):
        assert sanitize_path_segment("Tema 1...") == "Tema 1"
        assert sanitize_path_segment("Notes   ") == "Notes"
        assert sanitize_path_segment("  .Draft.  ") == "Draft"

    def test_length_truncation_for_max_path(self):
        long_title = "A" * 100
        sanitized = sanitize_path_segment(long_title, max_length=64)
        assert len(sanitized) == 64

    def test_empty_string_fallback(self):
        assert sanitize_path_segment("") == "unnamed"
        assert sanitize_path_segment("   ...  ") == "unnamed"

    def test_backslash_replaced(self):
        """Verify backslash is replaced and does not remain in sanitized string."""
        raw = r"..\..\Windows\System32\cmd.exe"
        sanitized = sanitize_path_segment(raw)
        assert "\\" not in sanitized
        assert "/" not in sanitized
        assert "Windows_System32_cmd.exe" in sanitized

    def test_windows_reserved_names_compound_extensions(self):
        """Verify Windows reserved device names are prefixed even with compound extensions."""
        assert sanitize_path_segment("CON.tar.gz") == "_CON.tar.gz"
        assert sanitize_path_segment("AUX.tar.bz2") == "_AUX.tar.bz2"
        assert sanitize_path_segment("con.tar.gz") == "_con.tar.gz"
        assert sanitize_path_segment("aux.tar.bz2") == "_aux.tar.bz2"
        assert sanitize_path_segment("COM1.tar.xz") == "_COM1.tar.xz"
        assert sanitize_path_segment("NUL.tar.zst") == "_NUL.tar.zst"
        assert sanitize_path_segment("PRN.backup.pdf") == "_PRN.backup.pdf"

    def test_extension_preservation_on_truncation(self):
        """Verify smart truncation preserves extension up to 16 chars while truncating stem."""
        # 1. Standard single extension (.pdf)
        long_pdf = "A" * 126 + ".pdf"
        s_pdf = sanitize_path_segment(long_pdf, max_length=128)
        assert len(s_pdf) == 128
        assert s_pdf.endswith(".pdf")
        assert s_pdf == "A" * 124 + ".pdf"

        # 2. Compound extension (.tar.gz)
        long_tar = "B" * 130 + ".tar.gz"
        s_tar = sanitize_path_segment(long_tar, max_length=128)
        assert len(s_tar) == 128
        assert s_tar.endswith(".tar.gz")
        assert s_tar == "B" * 121 + ".tar.gz"

        # 3. Descriptive sentence with dots (not an extension)
        long_title = "Chapter 1. Introduction to Advanced Machine Learning and Algorithms"
        s_title = sanitize_path_segment(long_title, max_length=64)
        assert len(s_title) <= 64
        assert not s_title.endswith(".")
        assert not s_title.endswith(" ")

        # 4. Long fake extension (> 16 chars) is not preserved
        fake_ext = "file." + "x" * 20
        s_fake = sanitize_path_segment(fake_ext, max_length=15)
        assert len(s_fake) <= 15

        # 5. Truncation that would produce a reserved name (CONSOLE.txt -> CON.txt)
        s_cons = sanitize_path_segment("CONSOLE.txt", max_length=7)
        assert len(s_cons) <= 7
        assert s_cons.endswith(".txt")
        assert not s_cons.upper().startswith("CON.")


class TestSubgroupDetection:
    def test_detect_single_group(self):
        assert detect_subgroup_in_text("Prácticas (Grupo C2)") == ["C2"]
        assert detect_subgroup_in_text("Laboratorio E3") == ["E3"]

    def test_detect_multiple_groups(self):
        groups = detect_subgroup_in_text("Prácticas (Grupos C1, C2 y C3)")
        assert groups == ["C1", "C2", "C3"]

    def test_boundary_no_partial_matching(self):
        # C2 must NOT match C20
        assert detect_subgroup_in_text("Prácticas (Grupo C20)") == ["C20"]
        assert "C2" not in detect_subgroup_in_text("Prácticas (Grupo C20)")


class TestMirrorPreset:
    def test_mirror_preset_routing(self):
        cfg = SyncConfig(preset="mirror")
        router = CourseRouter(cfg)
        act = CourseActivity(
            id="1",
            course_id="15819",
            section_id="section-1",
            section_name="Tema 1: Eficiencia / Algoritmos",
            mod_type="resource",
            title="Diapositivas Tema 1",
            url="https://prado.ugr.es/view.php?id=1",
        )
        file = FileAttachment(name="Tema_1.pdf", url="https://prado.ugr.es/file.pdf")
        decision = router.route_activity(act, file=file, course_slug="ED_C")

        assert decision.action == "download"
        assert decision.target_rel_path == Path("Tema 1_ Eficiencia _ Algoritmos") / "Tema_1.pdf"


class TestSmartPreset:
    def test_smart_general_section(self):
        router = CourseRouter(SyncConfig(preset="smart"))
        act = CourseActivity(
            id="101",
            course_id="15819",
            section_id="section-0",
            section_name="General",
            mod_type="forum",
            title="Avisos del Profesor",
            url="https://prado.ugr.es",
        )
        decision = router.route_activity(act, file=None, course_slug="ED_C")
        assert decision.action == "download"
        assert decision.target_rel_path == Path("General") / "Avisos del Profesor.pdf"

    def test_smart_theory_keywords(self):
        router = CourseRouter(SyncConfig(preset="smart"))
        act = CourseActivity(
            id="102",
            course_id="15819",
            section_id="section-1",
            section_name="Tema 1: Complejidad",
            mod_type="resource",
            title="Diapositivas Teóricas",
            url="https://prado.ugr.es",
        )
        file = FileAttachment(name="Tema1_slides.pdf", url="https://prado.ugr.es")
        decision = router.route_activity(act, file=file, course_slug="ED_C")
        assert decision.action == "download"
        assert decision.target_rel_path == Path("Teoria") / "Tema1_slides.pdf"

    def test_smart_practice_with_subunit(self):
        router = CourseRouter(SyncConfig(preset="smart"))
        act = CourseActivity(
            id="103",
            course_id="15819",
            section_id="section-2",
            section_name="Prácticas",
            mod_type="assign",
            title="Guion Práctica 2 - Redes Neuronales",
            url="https://prado.ugr.es",
        )
        file = FileAttachment(name="P2_guion.pdf", url="https://prado.ugr.es")
        decision = router.route_activity(act, file=file, course_slug="VC_A")
        assert decision.action == "download"
        assert decision.target_rel_path == Path("Practicas") / "P2" / "P2_guion.pdf"

    def test_smart_law_faculty_taxonomy(self):
        router = CourseRouter(SyncConfig(preset="smart"))
        act = CourseActivity(
            id="104",
            course_id="999",
            section_id="section-1",
            section_name="Casos Prácticos y Jurisprudencia",
            mod_type="resource",
            title="Dictamen Civil 1",
            url="https://prado.ugr.es",
        )
        file = FileAttachment(name="Dictamen_1.docx", url="https://prado.ugr.es")
        decision = router.route_activity(act, file=file, course_slug="DER_CIVIL")
        assert decision.action == "download"
        assert decision.target_rel_path == Path("Practicas") / "Dictamen_1.docx"

    def test_smart_medicine_faculty_taxonomy(self):
        router = CourseRouter(SyncConfig(preset="smart"))
        act = CourseActivity(
            id="105",
            course_id="998",
            section_id="section-1",
            section_name="Seminario de Casos Clínicos",
            mod_type="resource",
            title="Caso Clínico Urgencias",
            url="https://prado.ugr.es",
        )
        file = FileAttachment(name="Caso_1.pdf", url="https://prado.ugr.es")
        decision = router.route_activity(act, file=file, course_slug="MED_CLINICA")
        assert decision.action == "download"
        assert decision.target_rel_path == Path("Practicas") / "Caso_1.pdf"


class TestSubgroupPolicies:
    def test_student_active_group_matches(self):
        cfg = SyncConfig(preset="smart", subgroups={"15819": "C2"})
        router = CourseRouter(cfg)
        act = CourseActivity(
            id="106",
            course_id="15819",
            section_id="section-3",
            section_name="Prácticas (Grupo C2)",
            mod_type="assign",
            title="Entrega P1",
            url="https://prado.ugr.es",
        )
        decision = router.route_activity(act, file=None, course_slug="ED_C")
        assert decision.action == "download"
        assert decision.is_subgroup is True

    def test_inactive_group_archive_policy(self):
        cfg = SyncConfig(preset="smart", subgroups={"15819": "C2"})
        router = CourseRouter(cfg)
        act = CourseActivity(
            id="107",
            course_id="15819",
            section_id="section-4",
            section_name="Prácticas (Grupos C1 y C3)",
            mod_type="resource",
            title="Material C1_C3",
            url="https://prado.ugr.es",
        )
        file = FileAttachment(name="extra.pdf", url="https://prado.ugr.es")
        decision = router.route_activity(act, file=file, course_slug="ED_C", subgroup_policy="archive")
        assert decision.action == "archive"
        assert decision.target_rel_path == Path("_subgroups_archive") / "C1_C3" / "extra.pdf"

    def test_inactive_group_ignore_policy(self):
        cfg = SyncConfig(preset="smart", subgroups={"15819": "C2"})
        router = CourseRouter(cfg)
        act = CourseActivity(
            id="108",
            course_id="15819",
            section_id="section-4",
            section_name="Prácticas (Grupos C1 y C3)",
            mod_type="resource",
            title="Material C1_C3",
            url="https://prado.ugr.es",
        )
        decision = router.route_activity(act, file=None, course_slug="ED_C", subgroup_policy="ignore")
        assert decision.action == "skip"

    def test_common_section_always_included(self):
        cfg = SyncConfig(preset="smart", subgroups={"15819": "C2"})
        router = CourseRouter(cfg)
        act = CourseActivity(
            id="109",
            course_id="15819",
            section_id="section-0",
            section_name="General - Avisos Comunes",
            mod_type="forum",
            title="Avisos",
            url="https://prado.ugr.es",
        )
        decision = router.route_activity(act, file=None, course_slug="ED_C")
        assert decision.action == "download"
        assert decision.is_subgroup is False


class TestTopLevelReExports:
    def test_re_exports_match(self):
        assert CRTopLevel is CourseRouter
        assert detect_subgroup_top_level is detect_subgroup_in_text
        assert sanitize_top_level is sanitize_path_segment
