"""Tests for PIPE and BOX section writing in _write_beam_section_for_set()."""

import io
from unittest.mock import MagicMock


from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)


def _make_writer(member):
    """Create a minimal UnifiedCalculixWriter containing a single curve member."""
    model = StructuralModel(id="test_model")
    model.add_member(member)
    writer = MagicMock(spec=UnifiedCalculixWriter)
    writer.domain_model = model
    writer._write_beam_section_for_set = (
        UnifiedCalculixWriter._write_beam_section_for_set.__get__(writer)
    )
    return writer


def _make_mat():
    return Material(
        id="mat1",
        name="Steel",
        density=7850.0,
        elastic_modulus=210e9,
        poisson_ratio=0.3,
    )


BEAM_NORMAL = (0.0, 1.0, 0.0)


class TestPipeSectionWriting:
    """_write_beam_section_for_set() with section_type='pipe'."""

    def _member_and_section(self, outer_r=0.03, inner_r=0.027):
        sec = Section(
            id="sec1",
            name="Pipe",
            section_type="pipe",
            area=3.14 * (outer_r**2 - inner_r**2),
            dimensions={"outer_radius": outer_r, "inner_radius": inner_r},
        )
        member = CurveMember(
            id="m1", geometry=[[0, 0, 0], [1, 0, 0]], material=_make_mat(), section=sec
        )
        return member, sec

    def test_section_equals_pipe(self):
        member, _ = self._member_and_section()
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", BEAM_NORMAL
        )
        assert "SECTION=PIPE" in buf.getvalue()

    def test_pipe_radii_on_data_line(self):
        outer_r, inner_r = 0.03015, 0.027  # realistic tube
        member, _ = self._member_and_section(outer_r=outer_r, inner_r=inner_r)
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", BEAM_NORMAL
        )
        text = buf.getvalue()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        # Data line immediately after *BEAM SECTION line
        section_line_idx = next(i for i, l in enumerate(lines) if "SECTION=PIPE" in l)
        data_line = lines[section_line_idx + 1]
        parts = [float(x) for x in data_line.split(",")]
        assert abs(parts[0] - outer_r) < 1e-6
        assert abs(parts[1] - inner_r) < 1e-6

    def test_not_rect_for_pipe(self):
        member, _ = self._member_and_section()
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m1", "mat1", BEAM_NORMAL
        )
        assert "SECTION=RECT" not in buf.getvalue()


class TestBoxSectionWriting:
    """_write_beam_section_for_set() with section_type='box'."""

    def _member_and_section(self, w=0.1, h=0.2, t=0.005):
        area = w * h - (w - 2 * t) * (h - 2 * t)
        sec = Section(
            id="sec2",
            name="Box",
            section_type="box",
            area=area,
            dimensions={"width": w, "height": h, "wall_thickness": t},
        )
        member = CurveMember(
            id="m2", geometry=[[0, 0, 0], [1, 0, 0]], material=_make_mat(), section=sec
        )
        return member, sec

    def test_section_equals_box(self):
        member, _ = self._member_and_section()
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m2", "mat1", BEAM_NORMAL
        )
        assert "SECTION=BOX" in buf.getvalue()

    def test_box_dimensions_on_data_line(self):
        w, h, t = 0.1, 0.2, 0.005
        member, _ = self._member_and_section(w=w, h=h, t=t)
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m2", "mat1", BEAM_NORMAL
        )
        text = buf.getvalue()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        section_line_idx = next(i for i, l in enumerate(lines) if "SECTION=BOX" in l)
        data_line = lines[section_line_idx + 1]
        parts = [float(x) for x in data_line.split(",")]
        # CalculiX BOX: a (height), b (width), t1 t2 t3 t4
        assert abs(parts[0] - h) < 1e-6
        assert abs(parts[1] - w) < 1e-6
        assert abs(parts[2] - t) < 1e-6
        assert abs(parts[3] - t) < 1e-6
        assert abs(parts[4] - t) < 1e-6
        assert abs(parts[5] - t) < 1e-6

    def test_not_rect_for_box(self):
        member, _ = self._member_and_section()
        writer = _make_writer(member)
        buf = io.StringIO()
        writer._write_beam_section_for_set(
            buf, member, "MEMBER_m2", "mat1", BEAM_NORMAL
        )
        assert "SECTION=RECT" not in buf.getvalue()
