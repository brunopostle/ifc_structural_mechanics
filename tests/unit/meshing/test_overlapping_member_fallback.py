"""Tests for overlapping-member spatial fallback and section deduplication."""

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
from ifc_structural_mechanics.domain.structural_model import (  # noqa: E402
    StructuralModel,
)
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


class TestResolveOverlappingElementSets:
    """_resolve_overlapping_element_sets() ownership resolution for members
    sharing mesh elements via the overlapping-geometry fallback.

    This is the single source-of-truth resolution step: it mutates
    self.element_sets directly so every downstream consumer (raw *ELSET
    cards, orientation grouping, nodal thickness, node-membership
    registration, section writing) sees a consistent, non-overlapping
    assignment — rather than each consumer re-implementing its own
    deduplication (which previously caused mismatches, e.g. beads issue 51j).
    """

    def test_full_overlap_second_member_loses_all_elements(self, caplog):
        """Two members with identical element sets: the first keeps them,
        the second ends up with none."""
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
        writer._get_short_id = lambda mid: mid
        writer._resolve_overlapping_element_sets = (
            UnifiedCalculixWriter._resolve_overlapping_element_sets.__get__(writer)
        )

        with caplog.at_level(logging.WARNING):
            writer._resolve_overlapping_element_sets()

        assert writer.element_sets["MEMBER_ma"] == [10, 11]
        assert writer.element_sets["MEMBER_mb"] == []
        assert any("already claimed" in r.message.lower() for r in caplog.records)

    def test_partial_overlap_keeps_unclaimed_elements(self, caplog):
        """A member sharing only SOME elements with an earlier member keeps
        its remaining, unclaimed elements (regression for beads issue 51j —
        the whole member used to lose ALL its elements on any overlap)."""
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
            id="mb", geometry=[[0, 0, 0], [2, 0, 0]], material=mat, section=sec
        )
        model.add_member(ma)
        model.add_member(mb)

        writer = MagicMock(spec=UnifiedCalculixWriter)
        writer.domain_model = model
        writer.element_sets = {
            "MEMBER_ma": [10],
            "MEMBER_mb": [10, 11, 12],  # shares element 10 with ma
        }
        writer._get_short_id = lambda mid: mid
        writer._resolve_overlapping_element_sets = (
            UnifiedCalculixWriter._resolve_overlapping_element_sets.__get__(writer)
        )

        with caplog.at_level(logging.WARNING):
            writer._resolve_overlapping_element_sets()

        assert writer.element_sets["MEMBER_ma"] == [10]
        assert writer.element_sets["MEMBER_mb"] == [11, 12]

    def test_no_overlap_leaves_sets_untouched(self):
        """Members with disjoint element sets are unaffected."""
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
            id="mb", geometry=[[1, 0, 0], [2, 0, 0]], material=mat, section=sec
        )
        model.add_member(ma)
        model.add_member(mb)

        writer = MagicMock(spec=UnifiedCalculixWriter)
        writer.domain_model = model
        writer.element_sets = {
            "MEMBER_ma": [10, 11],
            "MEMBER_mb": [12, 13],
        }
        writer._get_short_id = lambda mid: mid
        writer._resolve_overlapping_element_sets = (
            UnifiedCalculixWriter._resolve_overlapping_element_sets.__get__(writer)
        )

        writer._resolve_overlapping_element_sets()

        assert writer.element_sets["MEMBER_ma"] == [10, 11]
        assert writer.element_sets["MEMBER_mb"] == [12, 13]


class TestU1RetypeStripsSharedElements:
    """_identify_and_retype_u1_members() must not leave elements it retyped to
    U1 dangling in an overlapping non-U1 member's element_sets entry.

    Regression for beads issue 51j: a RECT member sharing mesh elements with
    an I-section (U1) member — via MeshMapper's overlapping-geometry fallback
    — kept those elements in its own *BEAM SECTION ELSET even after they were
    retyped to U1. Since _write_elements() never writes U1-typed elements
    (they're written only inside _write_sections() for the U1 owner), and the
    dedup guard in _write_sections() could skip the U1 owner's whole section
    when it lost the race to claim the shared element first, the element
    ended up referenced by a *BEAM SECTION card but never defined by any
    *ELEMENT card — CalculiX rejected the file with 'not a beam element'.
    """

    def test_shared_element_removed_from_native_member_set(self):
        mat = Material(
            id="m1", name="S", density=7850.0, elastic_modulus=210e9, poisson_ratio=0.3
        )
        rect_sec = Section.create_rectangular_section(
            id="s1", name="R", width=0.3, height=0.45
        )
        i_sec = Section.create_i_section(
            id="s2",
            name="I",
            width=0.2,
            height=0.4,
            web_thickness=0.01,
            flange_thickness=0.02,
        )
        native = CurveMember(
            id="native", geometry=[[0, 0, 0], [1, 0, 0]], material=mat, section=rect_sec
        )
        u1_member = CurveMember(
            id="u1", geometry=[[0, 0, 0], [1, 0, 0]], material=mat, section=i_sec
        )
        model = StructuralModel(id="test")
        model.add_member(native)
        model.add_member(u1_member)

        writer = MagicMock(spec=UnifiedCalculixWriter)
        writer.domain_model = model
        writer.elements = {
            10: {"type": "B31", "nodes": [1, 2]},
            11: {"type": "B31", "nodes": [2, 3]},
        }
        # Elements 10 and 11 are shared between both members, as produced by
        # MeshMapper's shared-element-assignment overlap fallback.
        writer.element_sets = {
            "MEMBER_native": [10, 11],
            "MEMBER_u1": [10, 11],
        }
        writer._u1_members = set()
        writer._u1_element_sets = set()
        writer._get_short_id = lambda mid: mid
        writer._needs_user_element = UnifiedCalculixWriter._needs_user_element
        writer._identify_and_retype_u1_members = (
            UnifiedCalculixWriter._identify_and_retype_u1_members.__get__(writer)
        )

        writer._identify_and_retype_u1_members()

        assert writer.elements[10]["type"] == "U1"
        assert writer.elements[11]["type"] == "U1"
        # The native (RECT) member must no longer claim elements retyped to
        # U1 for the overlapping member.
        assert writer.element_sets["MEMBER_native"] == []
        assert writer.element_sets["MEMBER_u1"] == [10, 11]

    def test_non_shared_native_elements_are_untouched(self):
        """Elements unique to a native member (no overlap) keep their type."""
        mat = Material(
            id="m1", name="S", density=7850.0, elastic_modulus=210e9, poisson_ratio=0.3
        )
        rect_sec = Section.create_rectangular_section(
            id="s1", name="R", width=0.3, height=0.45
        )
        i_sec = Section.create_i_section(
            id="s2",
            name="I",
            width=0.2,
            height=0.4,
            web_thickness=0.01,
            flange_thickness=0.02,
        )
        native = CurveMember(
            id="native", geometry=[[0, 0, 0], [1, 0, 0]], material=mat, section=rect_sec
        )
        u1_member = CurveMember(
            id="u1", geometry=[[1, 0, 0], [2, 0, 0]], material=mat, section=i_sec
        )
        model = StructuralModel(id="test")
        model.add_member(native)
        model.add_member(u1_member)

        writer = MagicMock(spec=UnifiedCalculixWriter)
        writer.domain_model = model
        writer.elements = {
            10: {"type": "B31", "nodes": [1, 2]},
            20: {"type": "B31", "nodes": [2, 3]},
        }
        writer.element_sets = {
            "MEMBER_native": [10],  # no overlap with u1_member
            "MEMBER_u1": [20],
        }
        writer._u1_members = set()
        writer._u1_element_sets = set()
        writer._get_short_id = lambda mid: mid
        writer._needs_user_element = UnifiedCalculixWriter._needs_user_element
        writer._identify_and_retype_u1_members = (
            UnifiedCalculixWriter._identify_and_retype_u1_members.__get__(writer)
        )

        writer._identify_and_retype_u1_members()

        assert writer.elements[10]["type"] == "B31"
        assert writer.element_sets["MEMBER_native"] == [10]
