"""Tests for the beam-normal orthogonalisation safety net (ifc_structural_mechanics-pia).

The native B31 path (_write_beam_section_for_set) must never write a beam
normal that is parallel to the beam axis — CalculiX needs it perpendicular
to build a valid local coordinate system.  _write_beam_section_general (the
U1/GENERAL path) already guarded against this; this safety net extends the
same guard, via a shared helper, to the native RECT/CIRC/PIPE/BOX path.
"""

import io
from unittest.mock import MagicMock

import numpy as np

from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)


def _make_mat():
    return Material(
        id="mat1",
        name="Steel",
        density=7850.0,
        elastic_modulus=210e9,
        poisson_ratio=0.3,
    )


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


def _rect_member(geometry, section_type="rectangular"):
    sec = Section(
        id="r1",
        name="Rect",
        section_type=section_type,
        area=0.01,
        dimensions={"width": 0.1, "height": 0.1},
    )
    return CurveMember(id="m1", geometry=geometry, material=_make_mat(), section=sec)


def _normal_line(buf_text: str) -> np.ndarray:
    lines = [ln.strip() for ln in buf_text.splitlines() if ln.strip()]
    idx = next(i for i, ln in enumerate(lines) if ln.startswith("*BEAM SECTION"))
    normal_line = lines[idx + 2]
    return np.array([float(v) for v in normal_line.split(",")])


class TestNativeBeamNormalOrthogonalisation:
    def test_parallel_normal_is_corrected(self):
        """A beam normal parallel to the beam axis must be rewritten perpendicular."""
        member = _rect_member([[0, 0, 0], [5, 0, 0]])
        writer = _make_writer(member)
        buf = io.StringIO()
        parallel_normal = (1.0, 0.0, 0.0)  # == beam axis direction

        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", parallel_normal
        )

        normal = _normal_line(buf.getvalue())
        beam_axis = np.array([1.0, 0.0, 0.0])
        assert abs(np.linalg.norm(normal) - 1.0) < 1e-6
        assert abs(np.dot(normal, beam_axis)) < 1e-6

    def test_already_perpendicular_normal_is_unchanged(self):
        """A normal already perpendicular to the axis passes through untouched."""
        member = _rect_member([[0, 0, 0], [5, 0, 0]])
        writer = _make_writer(member)
        buf = io.StringIO()
        perpendicular_normal = (0.0, 1.0, 0.0)

        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", perpendicular_normal
        )

        normal = _normal_line(buf.getvalue())
        assert np.allclose(normal, [0.0, 1.0, 0.0], atol=1e-6)

    def test_vertical_column_default_normal_is_corrected(self):
        """Vertical column (axis == Z) with a normal defaulting to Z is fixed."""
        member = _rect_member([[0, 0, 0], [0, 0, 3]])
        writer = _make_writer(member)
        buf = io.StringIO()
        parallel_normal = (0.0, 0.0, 1.0)

        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", parallel_normal
        )

        normal = _normal_line(buf.getvalue())
        beam_axis = np.array([0.0, 0.0, 1.0])
        assert abs(np.linalg.norm(normal) - 1.0) < 1e-6
        assert abs(np.dot(normal, beam_axis)) < 1e-6
