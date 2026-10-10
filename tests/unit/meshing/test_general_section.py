"""Tests for the output requests of a step and for U1 general sections."""

import io
from unittest.mock import MagicMock

from ifc_structural_mechanics.analysis.boundary_condition_handling import (
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
    writer._compute_beam_axis = UnifiedCalculixWriter._compute_beam_axis.__get__(writer)
    writer._orthogonal_beam_normal = (
        UnifiedCalculixWriter._orthogonal_beam_normal.__get__(writer)
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
# _write_step_output_requests
# ---------------------------------------------------------------------------


class TestStepOutputRequests:
    def test_section_forces_are_not_requested(self):
        """They are integrated from the stresses; see analysis/section_forces."""
        buf = io.StringIO()
        _write_step_output_requests(buf)
        text = buf.getvalue()
        assert "SF" not in text
        assert "SECTION FORCES" not in text

    def test_node_file_and_end_step_written(self):
        buf = io.StringIO()
        _write_step_output_requests(buf)
        assert "*NODE FILE" in buf.getvalue()
        assert "*END STEP" in buf.getvalue()

    def test_s_e_suppressed_for_u1_elements(self):
        """has_u1_elements=True → no *EL FILE S, E (U1 segfaults on stress output)."""
        buf = io.StringIO()
        _write_step_output_requests(buf, has_u1_elements=True)
        text = buf.getvalue()
        assert "S, E" not in text

    def test_s_e_written_without_u1(self):
        """Default (no U1) → *EL FILE S, E is written."""
        buf = io.StringIO()
        _write_step_output_requests(buf, has_u1_elements=False)
        assert "S, E" in buf.getvalue()
