"""Tests for non-standard section handling and U1 beam element output.

Architecture (as of Phase 2):
- Non-standard sections (I, T, L, C, arbitrary) are handled by U1 elements
  via _write_beam_section_general() (uses *BEAM SECTION SECTION=GENERAL).
- _write_beam_section_for_set() is only called for B31 elements with standard
  sections (RECT/CIRC/PIPE/BOX).  Non-standard profiles that somehow reach
  this path fall back to an equivalent RECT (preserves A and Iy).
- When U1 elements are present the writer adds BEAM_B31 to element_sets
  (possibly empty) as a sentinel so that _find_beam_elset() knows not to
  fall back to ELSET_LINE* (which would include U1 elements that crash on SF).
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


class TestNonStandardSectionFallback:
    """_write_beam_section_for_set() falls back to RECT for non-standard profiles.

    Non-standard sections are now handled by U1 elements via
    _write_beam_section_general().  If an I/T/L/C section somehow reaches
    _write_beam_section_for_set() (B31 path), it must not silently produce
    wrong output — it uses an equivalent RECT so the analysis at least runs.
    """

    def test_i_section_falls_back_to_rect(self):
        """Non-standard section in B31 path uses SECTION=RECT fallback."""
        member = _i_member()
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", BEAM_NORMAL
        )
        assert "SECTION=RECT" in buf.getvalue()

    def test_i_section_fallback_rect_preserves_area(self):
        """Equivalent RECT area ≈ original section area."""
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
        # Data line after *BEAM SECTION … SECTION=RECT is "width, height"
        lines = [ln.strip() for ln in buf.getvalue().splitlines() if ln.strip()]
        idx = next(i for i, ln in enumerate(lines) if "SECTION=RECT" in ln)
        w, h = (float(v) for v in lines[idx + 1].split(","))
        rect_area = w * h
        assert abs(rect_area - sec.area) / sec.area < 1e-4


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

    # ---- BEAM_B31 sentinel tests (U1 element support) ----

    def test_beam_b31_non_empty_returned(self):
        """Mixed B31+U1 model: BEAM_B31 is non-empty → return it for SF output."""
        element_sets = {
            "BEAM_B31": [1, 2],
            "ELSET_LINE": [1, 2, 3, 4],  # U1 + B31 mixed
        }
        assert _find_beam_elset(element_sets) == "BEAM_B31"

    def test_beam_b31_empty_returns_none(self):
        """All-U1 model: BEAM_B31 present but empty → None (skip SF output)."""
        element_sets = {
            "BEAM_B31": [],  # sentinel: U1 elements exist, no B31
            "ELSET_LINE": [1, 2, 3],  # all U1 elements
        }
        assert _find_beam_elset(element_sets) is None

    def test_beam_b31_empty_does_not_fall_through_to_line(self):
        """BEAM_B31=[] must suppress the ELSET_LINE fallback (prevents SF crash)."""
        element_sets = {
            "BEAM_B31": [],
            "ELSET_LINE2": [10, 11, 12],  # would be returned without sentinel
        }
        # Must be None, not "ELSET_LINE2"
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

    def test_s_e_suppressed_for_u1_elements(self):
        """has_u1_elements=True → no *EL FILE S, E (U1 segfaults on stress output)."""
        buf = io.StringIO()
        _write_step_output_requests(buf, beam_elset=None, has_u1_elements=True)
        text = buf.getvalue()
        assert "S, E" not in text

    def test_s_e_written_without_u1(self):
        """Default (no U1) → *EL FILE S, E is written."""
        buf = io.StringIO()
        _write_step_output_requests(buf, beam_elset=None, has_u1_elements=False)
        assert "S, E" in buf.getvalue()
