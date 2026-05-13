"""Tests for overlapping-member spatial fallback and section deduplication."""

import io
import logging
import sys
import types
from unittest.mock import MagicMock

import numpy as np


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


if "gmsh" not in sys.modules:
    _stub("gmsh")

if "ifc_structural_mechanics.meshing.gmsh_geometry" not in sys.modules:
    _stub(
        "ifc_structural_mechanics.meshing.gmsh_geometry",
        GmshGeometryConverter=MagicMock(),
        convert_model=MagicMock(),
    )

if "ifc_structural_mechanics.meshing.gmsh_runner" not in sys.modules:
    _stub("ifc_structural_mechanics.meshing.gmsh_runner", GmshRunner=MagicMock())

if "ifc_structural_mechanics.meshing.gmsh_utils" not in sys.modules:
    _stub("ifc_structural_mechanics.meshing.gmsh_utils")

from ifc_structural_mechanics.domain.property import Material, Section  # noqa: E402
from ifc_structural_mechanics.domain.structural_member import CurveMember  # noqa: E402
from ifc_structural_mechanics.domain.structural_model import StructuralModel  # noqa: E402
from ifc_structural_mechanics.meshing.mesh_mapper import MeshMapper  # noqa: E402
from ifc_structural_mechanics.meshing.unified_calculix_writer import (  # noqa: E402
    UnifiedCalculixWriter,
)

_NODES = {
    1: np.array([0.0, 0.0, 0.0]),
    2: np.array([1.0, 0.0, 0.0]),
    3: np.array([0.5, 0.0, 0.0]),
}
_ELEMENTS = {
    10: {"type": "B31", "nodes": [1, 2]},
    11: {"type": "B31", "nodes": [2, 3]},
}


def _make_curve_member(id_, start, end, mat=None, sec=None):
    if mat is None:
        mat = Material(
            id="mat1",
            name="Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
        )
    if sec is None:
        sec = Section.create_rectangular_section(
            id="sec1", name="R", width=0.1, height=0.2
        )
    return CurveMember(id=id_, geometry=[start, end], material=mat, section=sec)


def _make_mapper_with_two_members(member_a, member_b):
    """Build a MeshMapper with two members and a minimal mesh."""
    model = StructuralModel(id="test")
    model.add_member(member_a)
    model.add_member(member_b)
    model.register_analysis_elements = MagicMock()

    def get_short_id(mid):
        return mid[:8].replace("-", "")

    return MeshMapper(
        elements=dict(_ELEMENTS),
        nodes=dict(_NODES),
        domain_model=model,
        element_physical_group={},
        physical_group_names={},
        get_short_id=get_short_id,
    )


class TestSpatialFallback:
    """MeshMapper._assign_spatially() with allow_sharing flag."""

    def test_no_sharing_leaves_empty_member(self):
        """Without sharing, a member whose elements are all assigned stays empty."""
        ma = _make_curve_member("member_a", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        mb = _make_curve_member(
            "member_b", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]
        )  # overlapping
        mapper = _make_mapper_with_two_members(ma, mb)

        # Assign all elements to member_a first
        assigned = {10, 11}
        mapper.element_sets["MEMBER_member_a"] = [10, 11]
        mapper.defined_element_sets.add("MEMBER_member_a")

        mapper._assign_spatially([mb], assigned, allow_sharing=False)

        assert "MEMBER_member_b" not in mapper.element_sets

    def test_sharing_gives_overlapping_member_elements(self):
        """With sharing, an overlapping member gets the same elements."""
        ma = _make_curve_member("member_a", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        mb = _make_curve_member("member_b", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        mapper = _make_mapper_with_two_members(ma, mb)

        assigned = {10, 11}
        mapper.element_sets["MEMBER_member_a"] = [10, 11]
        mapper.defined_element_sets.add("MEMBER_member_a")

        mapper._assign_spatially([mb], assigned, allow_sharing=True)

        assert "MEMBER_member_b" in mapper.element_sets
        assert len(mapper.element_sets["MEMBER_member_b"]) > 0

    def test_sharing_logs_warning(self, caplog):
        """allow_sharing=True logs a warning about shared elements."""
        ma = _make_curve_member("member_a", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        mb = _make_curve_member("member_b", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        mapper = _make_mapper_with_two_members(ma, mb)

        assigned = {10, 11}
        mapper.element_sets["MEMBER_member_a"] = [10, 11]
        mapper.defined_element_sets.add("MEMBER_member_a")

        with caplog.at_level(logging.WARNING):
            mapper._assign_spatially([mb], assigned, allow_sharing=True)

        assert any("sharing" in r.message.lower() for r in caplog.records)


class TestSectionDeduplication:
    """_write_sections() deduplication guard for overlapping members."""

    def test_duplicate_section_skipped(self, caplog):
        """When two members share elements, only the first section is written."""
        model = StructuralModel(id="test")
        mat = Material(
            id="m1", name="S", density=7850.0, elastic_modulus=210e9, poisson_ratio=0.3
        )
        sec = Section.create_rectangular_section(
            id="s1", name="R", width=0.1, height=0.2
        )
        ma = CurveMember(
            id="ma", geometry=[[0, 0, 0], [1, 0, 0]], material=mat, section=sec
        )
        mb = CurveMember(
            id="mb", geometry=[[0, 0, 0], [1, 0, 0]], material=mat, section=sec
        )
        model.add_member(ma)
        model.add_member(mb)

        writer = MagicMock(spec=UnifiedCalculixWriter)
        writer.domain_model = model
        writer.element_sets = {
            "MEMBER_ma": [10, 11],
            "MEMBER_mb": [10, 11],  # same elements — overlap
        }
        writer.defined_element_sets = {"MEMBER_ma", "MEMBER_mb"}
        writer._u1_members = set()  # no U1 elements in this test
        writer._get_short_id = lambda mid: mid
        writer._split_beam_sets_by_orientation = MagicMock(return_value={})
        writer._get_beam_normal = MagicMock(return_value=(0.0, 1.0, 0.0))
        writer._write_beam_section_for_set = MagicMock()
        writer._write_sections = UnifiedCalculixWriter._write_sections.__get__(writer)

        buf = io.StringIO()
        with caplog.at_level(logging.WARNING):
            writer._write_sections(buf)

        # Only one section should have been written (ma); mb is skipped
        assert writer._write_beam_section_for_set.call_count == 1
        assert any(
            "overlap" in r.message.lower() or "already" in r.message.lower()
            for r in caplog.records
        )
