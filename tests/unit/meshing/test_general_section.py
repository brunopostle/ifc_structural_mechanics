"""Tests for SECTION=GENERAL writing for non-standard profiles (I, T, L, C).

These tests verify that _write_beam_section_for_set() emits SECTION=GENERAL
with correct A, I11, I12, I22, IT values instead of the approximate
equivalent-RECT fallback, and that _find_beam_elset() and the SF output
request behave correctly.
"""

import io
from unittest.mock import MagicMock

from ifc_structural_mechanics.analysis.boundary_condition_handling import (
    _find_beam_elset,
    _write_step_output_requests,
)
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mat():
    return Material(
        id="mat1",
        name="Steel",
        density=7850.0,
        elastic_modulus=210e9,
        poisson_ratio=0.3,
    )


BEAM_NORMAL = (0.0, 1.0, 0.0)


def _make_writer(member):
    model = StructuralModel(id="test_model")
    model.add_member(member)
    writer = MagicMock(spec=UnifiedCalculixWriter)
    writer.domain_model = model
    writer._write_beam_section_for_set = (
        UnifiedCalculixWriter._write_beam_section_for_set.__get__(writer)
    )
    return writer


def _i_section(b=0.2, h=0.4, tw=0.01, tf=0.015):
    area = b * h - (b - tw) * (h - 2 * tf)
    return Section(
        id="i_sec",
        name="HEA200",
        section_type="i",
        area=area,
        dimensions={
            "width": b,
            "height": h,
            "web_thickness": tw,
            "flange_thickness": tf,
        },
    )


def _i_member():
    sec = _i_section()
    return CurveMember(
        id="m1",
        geometry=[[0, 0, 0], [5, 0, 0]],
        material=_make_mat(),
        section=sec,
    )


# ---------------------------------------------------------------------------
# SECTION=GENERAL output
# ---------------------------------------------------------------------------


class TestGeneralSectionWriting:
    """_write_beam_section_for_set() emits SECTION=GENERAL for I-sections."""

    def test_i_section_uses_general(self):
        member = _i_member()
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", BEAM_NORMAL
        )
        assert "SECTION=GENERAL" in buf.getvalue()

    def test_i_section_not_rect(self):
        member = _i_member()
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", BEAM_NORMAL
        )
        assert "SECTION=RECT" not in buf.getvalue()

    def test_general_data_line_has_five_values(self):
        """SECTION=GENERAL data line: A, I11, I12, I22, IT."""
        member = _i_member()
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", BEAM_NORMAL
        )
        lines = [ln.strip() for ln in buf.getvalue().splitlines() if ln.strip()]
        idx = next(i for i, ln in enumerate(lines) if "SECTION=GENERAL" in ln)
        data_parts = [p.strip() for p in lines[idx + 1].split(",")]
        assert len(data_parts) == 5

    def test_general_area_matches_section(self):
        sec = _i_section(b=0.2, h=0.4, tw=0.01, tf=0.015)
        member = CurveMember(
            id="m1",
            geometry=[[0, 0, 0], [5, 0, 0]],
            material=_make_mat(),
            section=sec,
        )
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", BEAM_NORMAL
        )
        lines = [ln.strip() for ln in buf.getvalue().splitlines() if ln.strip()]
        idx = next(i for i, ln in enumerate(lines) if "SECTION=GENERAL" in ln)
        a_written = float(lines[idx + 1].split(",")[0])
        assert abs(a_written - sec.area) / sec.area < 1e-4

    def test_general_iy_matches_section(self):
        sec = _i_section()
        member = CurveMember(
            id="m1",
            geometry=[[0, 0, 0], [5, 0, 0]],
            material=_make_mat(),
            section=sec,
        )
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", BEAM_NORMAL
        )
        lines = [ln.strip() for ln in buf.getvalue().splitlines() if ln.strip()]
        idx = next(i for i, ln in enumerate(lines) if "SECTION=GENERAL" in ln)
        vals = [float(p) for p in lines[idx + 1].split(",")]
        assert abs(vals[1] - sec.moment_of_inertia_y) / sec.moment_of_inertia_y < 1e-4

    def test_general_product_of_inertia_is_zero_for_symmetric(self):
        """I12 = 0 for a doubly-symmetric I-section."""
        member = _i_member()
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", BEAM_NORMAL
        )
        lines = [ln.strip() for ln in buf.getvalue().splitlines() if ln.strip()]
        idx = next(i for i, ln in enumerate(lines) if "SECTION=GENERAL" in ln)
        vals = [float(p) for p in lines[idx + 1].split(",")]
        assert vals[2] == 0.0  # I12 = 0

    def test_c_section_uses_general(self):
        sec = Section(
            id="c_sec",
            name="C-Section",
            section_type="c",
            area=0.005,
            dimensions={
                "width": 0.1,
                "height": 0.2,
                "web_thickness": 0.008,
                "flange_thickness": 0.012,
            },
        )
        member = CurveMember(
            id="m2",
            geometry=[[0, 0, 0], [3, 0, 0]],
            material=_make_mat(),
            section=sec,
        )
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m2", "mat1", BEAM_NORMAL
        )
        assert "SECTION=GENERAL" in buf.getvalue()


# ---------------------------------------------------------------------------
# _find_beam_elset
# ---------------------------------------------------------------------------


class TestFindBeamElset:
    def test_returns_line2_set(self):
        element_sets = {"ELSET_LINE2": [1, 2, 3], "ELSET_TRIANGLE6": [4, 5]}
        assert _find_beam_elset(element_sets) == "ELSET_LINE2"

    def test_returns_line_set(self):
        element_sets = {"ELSET_LINE": [1, 2], "ELSET_QUAD8": [3, 4]}
        assert _find_beam_elset(element_sets) == "ELSET_LINE"

    def test_returns_none_for_shell_only(self):
        element_sets = {"ELSET_TRIANGLE6": [1, 2], "ELSET_QUAD8": [3]}
        assert _find_beam_elset(element_sets) is None

    def test_returns_none_for_empty_dict(self):
        assert _find_beam_elset({}) is None

    def test_returns_none_for_none(self):
        assert _find_beam_elset(None) is None

    def test_skips_empty_beam_set(self):
        """An ELSET_LINE with no elements should not be returned."""
        element_sets = {"ELSET_LINE": [], "ELSET_TRIANGLE6": [1]}
        assert _find_beam_elset(element_sets) is None


# ---------------------------------------------------------------------------
# _write_step_output_requests with/without beam_elset
# ---------------------------------------------------------------------------


class TestStepOutputRequests:
    def test_sf_written_when_beam_elset_provided(self):
        buf = io.StringIO()
        _write_step_output_requests(buf, beam_elset="ELSET_LINE2")
        text = buf.getvalue()
        assert "EL FILE" in text
        assert "ELSET=ELSET_LINE2" in text
        assert "SF" in text

    def test_sf_not_written_without_beam_elset(self):
        buf = io.StringIO()
        _write_step_output_requests(buf, beam_elset=None)
        text = buf.getvalue()
        assert "SF" not in text

    def test_node_file_always_written(self):
        for beam_elset in (None, "ELSET_LINE"):
            buf = io.StringIO()
            _write_step_output_requests(buf, beam_elset=beam_elset)
            assert "*NODE FILE" in buf.getvalue()

    def test_end_step_always_written(self):
        buf = io.StringIO()
        _write_step_output_requests(buf, beam_elset=None)
        assert "*END STEP" in buf.getvalue()
