"""Tests for which of two overlapping members keeps the elements they share."""

import io
import logging
import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest


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

from ifc_structural_mechanics.domain.property import Material, Section  # noqa: E402
from ifc_structural_mechanics.domain.structural_connection import (  # noqa: E402
    RigidConnection,
)
from ifc_structural_mechanics.domain.structural_member import CurveMember  # noqa: E402
from ifc_structural_mechanics.domain.structural_model import (  # noqa: E402
    StructuralModel,
)
from ifc_structural_mechanics.meshing.unified_calculix_writer import (  # noqa: E402
    UnifiedCalculixWriter,
)
from ifc_structural_mechanics.utils.error_handling import (  # noqa: E402
    AnalysisError,
    MeshingError,
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
        # The user is told, in the results and not only in the log
        (message,) = [
            call.args[1]
            for call in writer._warn_user.call_args_list
            if call.args[0] == "W-MSH-001"
        ]
        assert "1 member(s) overlap another member" in message
        assert "mb" in message

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


def _joint_of_two_beams():
    """Beams along x from 0 to 1 and from 1 to 2, joined at x = 1."""
    model = StructuralModel(id="test")
    model.add_member(_make_curve_member("ma", [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]))
    model.add_member(_make_curve_member("mb", [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]))
    joint = RigidConnection("joint", [1.0, 0.0, 0.0])
    joint.connect_member("ma")
    joint.connect_member("mb")
    model.add_connection(joint)

    writer = UnifiedCalculixWriter(domain_model=model)
    writer.nodes = {1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0), 3: (2.0, 0.0, 0.0)}
    writer.elements = {
        10: {"type": "B31", "nodes": [1, 2]},
        11: {"type": "B31", "nodes": [2, 3]},
    }
    short = {m: writer._get_short_id(m) for m in ("ma", "mb")}
    writer.element_sets = {
        f"MEMBER_{short['ma']}": [10],
        f"MEMBER_{short['mb']}": [11],
    }
    return writer, joint, short


class TestMembersReachTheirConnections:
    """A member is joined at the node it has at its connection (`aiz.87`)."""

    def test_members_with_a_node_at_the_joint_pass(self):
        writer, _, _ = _joint_of_two_beams()
        writer._check_members_reach_their_connections()

    def test_member_with_no_node_at_the_joint_stops_the_analysis(self):
        """Its last element was given to another member: 0.4 m is missing."""
        writer, _, short = _joint_of_two_beams()
        writer.nodes[4] = (1.4, 0.0, 0.0)
        writer.elements[11]["nodes"] = [4, 3]
        with pytest.raises(MeshingError, match="mb at joint"):
            writer._check_members_reach_their_connections()

    def test_overlapped_member_is_found_by_the_elements_in_its_geometry(self):
        """The elements of `mb` are analysed as another member's."""
        writer, joint, short = _joint_of_two_beams()
        writer._geometry_element_sets = {
            name: list(elements) for name, elements in writer.element_sets.items()
        }
        writer.element_sets[f"MEMBER_{short['mb']}"] = []
        assert writer._find_connection_nodes_at_location(joint, ["mb"]) == [("mb", 2)]
        writer._check_members_reach_their_connections()


class TestJointsThatJoinNothing:
    """A joint is made or the analysis stops (`94g.12`); it once warned."""

    def test_connection_with_no_node_of_its_members_stops_the_analysis(self):
        writer, joint, short = _joint_of_two_beams()
        for member in ("ma", "mb"):
            writer.element_sets[f"MEMBER_{short[member]}"] = []
        with pytest.raises(MeshingError) as raised:
            writer._write_point_connection(io.StringIO(), joint, ["ma", "mb"], set())
        assert raised.value.code == "E-JNT-001"
        assert set(raised.value.ifc_guids) == {"joint", "ma", "mb"}

    def test_joint_of_a_kind_that_cannot_be_modelled_stops_the_analysis(self):
        writer, joint, _ = _joint_of_two_beams()
        joint.entity_type = "spring"
        with pytest.raises(AnalysisError) as raised:
            writer._write_connections(io.StringIO(), set())
        assert raised.value.code == "E-JNT-004"


class TestLoadsOfAnOverlappedMember:
    """Its loads go on the elements in its geometry (`94g.12`).

    They were once left out with a warning (W-LOD-009).
    """

    def test_curve_member_gets_the_elements_in_its_geometry(self):
        writer, _, short = _joint_of_two_beams()
        writer._geometry_element_sets = {
            name: list(elements) for name, elements in writer.element_sets.items()
        }
        writer.element_sets[f"MEMBER_{short['mb']}"] = []
        sets = writer._load_element_sets()
        assert sets[f"MEMBER_{short['mb']}"] == [11]
        assert writer.element_sets[f"MEMBER_{short['mb']}"] == []

    def test_member_with_its_own_elements_keeps_them(self):
        writer, _, short = _joint_of_two_beams()
        writer._geometry_element_sets = {
            name: list(elements) for name, elements in writer.element_sets.items()
        }
        assert writer._load_element_sets() == writer.element_sets


class TestU1RetypeStripsSharedElements:
    """_identify_and_retype_u1_members() must not leave elements it retyped to
    U1 dangling in an overlapping non-U1 member's element_sets entry.

    Regression for beads issue 51j: a RECT member sharing mesh elements with
    an I-section (U1) member — where the two overlap
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
        # MeshMapper gives the elements of a shared physical group to both.
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
