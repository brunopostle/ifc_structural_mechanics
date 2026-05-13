"""Tests for topology-based connection node finding in _find_connection_nodes_at_location().

The key improvement over the old proximity-only approach: when a member's geometry
endpoints are known, the writer targets the closest endpoint (not the connection
position itself) and uses a tight 10 mm tolerance.  This prevents false matches
for closely-spaced but unconnected members.
"""

import sys
import types
from unittest.mock import MagicMock

import numpy as np

# ---------------------------------------------------------------------------
# Stub gmsh sub-modules so the writer can be imported without libGLU.so.1
# ---------------------------------------------------------------------------


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

from ifc_structural_mechanics.domain.structural_member import CurveMember  # noqa: E402
from ifc_structural_mechanics.domain.structural_model import (  # noqa: E402
    StructuralModel,
)
from ifc_structural_mechanics.meshing.unified_calculix_writer import (  # noqa: E402
    UnifiedCalculixWriter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_writer(members, nodes, elements, element_sets):
    """Build a minimal UnifiedCalculixWriter stub."""
    model = StructuralModel(id="test")
    for m in members:
        model.add_member(m)

    writer = MagicMock(spec=UnifiedCalculixWriter)
    writer.domain_model = model
    writer.nodes = nodes
    writer.elements = elements
    writer.element_sets = element_sets
    writer.short_id_map = {}
    writer.short_id_counter = 0
    writer._get_short_id = UnifiedCalculixWriter._get_short_id.__get__(writer)
    writer._get_member_endpoints = UnifiedCalculixWriter._get_member_endpoints.__get__(
        writer
    )
    writer._find_connection_nodes_at_location = (
        UnifiedCalculixWriter._find_connection_nodes_at_location.__get__(writer)
    )
    return writer


def _curve_member(member_id, start, end):
    """Create a CurveMember with two geometry endpoints."""
    m = MagicMock(spec=CurveMember)
    m.id = member_id
    m.entity_type = "curve"
    m.geometry = [list(start), list(end)]
    return m


def _conn(position):
    c = MagicMock()
    c.id = "conn1"
    c.position = list(position)
    return c


# ---------------------------------------------------------------------------
# Basic endpoint-based matching
# ---------------------------------------------------------------------------


class TestEndpointTargeting:
    """Node is found by targeting the member endpoint, not the connection position."""

    def test_node_at_member_endpoint_is_found(self):
        """Node exactly at member end should match even when connection is offset."""
        # Member runs from (0,0,0) to (5,0,0)
        # Connection is at (0,0,0) — same as start endpoint
        # Mesh node 1 is at (0.000,0,0) — should be found
        m = _curve_member("m1", [0, 0, 0], [5, 0, 0])
        writer = _make_writer(
            members=[m],
            nodes={1: np.array([0.0, 0.0, 0.0]), 2: np.array([5.0, 0.0, 0.0])},
            elements={10: {"type": "B31", "nodes": [1, 2]}},
            element_sets={"MEMBER_M1": [10]},
        )

        pairs = writer._find_connection_nodes_at_location(_conn([0, 0, 0]), ["m1"])

        assert len(pairs) == 1
        mid, nid = pairs[0]
        assert mid == "m1"
        assert nid == 1

    def test_picks_end_node_not_start_when_closer(self):
        """Connection at the far end → end node is returned."""
        m = _curve_member("m1", [0, 0, 0], [5, 0, 0])
        writer = _make_writer(
            members=[m],
            nodes={1: np.array([0.0, 0.0, 0.0]), 2: np.array([5.0, 0.0, 0.0])},
            elements={10: {"type": "B31", "nodes": [1, 2]}},
            element_sets={"MEMBER_M1": [10]},
        )

        pairs = writer._find_connection_nodes_at_location(_conn([5, 0, 0]), ["m1"])

        assert len(pairs) == 1
        assert pairs[0][1] == 2  # node at (5,0,0)

    def test_connection_offset_from_endpoint_still_matches(self):
        """Connection position is 200 mm away from beam end — endpoint matching still works."""
        # Beam end at (0,0,0); connection at (0.2,0,0) (200 mm offset — column face)
        m = _curve_member("m1", [0, 0, 0], [5, 0, 0])
        writer = _make_writer(
            members=[m],
            nodes={
                1: np.array([0.0, 0.0, 0.0]),
                2: np.array([5.0, 0.0, 0.0]),
                3: np.array([2.5, 0.0, 0.0]),  # mid-span node
            },
            elements={10: {"type": "B31", "nodes": [1, 3, 2]}},
            element_sets={"MEMBER_M1": [10]},
        )

        pairs = writer._find_connection_nodes_at_location(_conn([0.2, 0, 0]), ["m1"])

        # Endpoint (0,0,0) is 200 mm from connection — within 10 mm tolerance of node 1
        assert len(pairs) == 1
        assert pairs[0][1] == 1  # closest node to endpoint (0,0,0)


# ---------------------------------------------------------------------------
# Unconnected nearby member is not matched
# ---------------------------------------------------------------------------


class TestNearbyUnconnectedMemberNotMatched:
    """A member physically close but NOT in member_ids should not contribute nodes."""

    def test_only_queried_members_produce_pairs(self):
        """Only m1 is queried; m2 is a nearby unconnected member (not in member_ids)."""
        m1 = _curve_member("m1", [0, 0, 0], [5, 0, 0])
        m2 = _curve_member("m2", [0.05, 0, 0], [5.05, 0, 0])  # 50 mm offset

        writer = _make_writer(
            members=[m1, m2],
            nodes={
                1: np.array([0.0, 0.0, 0.0]),
                2: np.array([5.0, 0.0, 0.0]),
                3: np.array([0.05, 0.0, 0.0]),  # m2 start node — 50 mm from conn
                4: np.array([5.05, 0.0, 0.0]),
            },
            elements={
                10: {"type": "B31", "nodes": [1, 2]},
                11: {"type": "B31", "nodes": [3, 4]},
            },
            element_sets={"MEMBER_M1": [10], "MEMBER_M2": [11]},
        )

        # Only ask about m1; m2 should not be touched
        pairs = writer._find_connection_nodes_at_location(_conn([0, 0, 0]), ["m1"])

        member_ids_returned = [mid for mid, _ in pairs]
        assert "m2" not in member_ids_returned
        assert "m1" in member_ids_returned


# ---------------------------------------------------------------------------
# Tight tolerance prevents wrong node selection within a member
# ---------------------------------------------------------------------------


class TestTightTolerancePreventsWrongNode:
    def test_interior_node_not_selected_when_endpoint_node_exists(self):
        """Interior mesh node closer to connection pos than endpoint node is ignored."""
        # Member from (0,0,0) to (10,0,0)
        # Connection at (0,0,0) → endpoint is (0,0,0), node 1 is there
        # Node 3 is an interior node at (0.3,0,0) — would win under the old 0.5m search
        m = _curve_member("m1", [0, 0, 0], [10, 0, 0])
        writer = _make_writer(
            members=[m],
            nodes={
                1: np.array([0.0, 0.0, 0.0]),  # exact endpoint node
                2: np.array([10.0, 0.0, 0.0]),
                3: np.array([0.3, 0.0, 0.0]),  # interior node, closer to conn pos
            },
            elements={10: {"type": "B31", "nodes": [1, 3, 2]}},
            element_sets={"MEMBER_M1": [10]},
        )

        # Connection at (-0.1, 0, 0) — 100 mm from endpoint, so endpoint (0,0,0)
        # is 100 mm away.  Node 3 at (0.3,0,0) is 400 mm away from connection.
        # The tight-tolerance search targets endpoint (0,0,0) → finds node 1 (0 mm away).
        pairs = writer._find_connection_nodes_at_location(_conn([-0.1, 0, 0]), ["m1"])

        assert len(pairs) == 1
        assert pairs[0][1] == 1


# ---------------------------------------------------------------------------
# Fallback when no geometry is available
# ---------------------------------------------------------------------------


class TestFallbackWithoutGeometry:
    def test_no_geometry_falls_back_to_loose_tolerance(self):
        """Member with no geometry → 0.5 m proximity search still works."""
        m = MagicMock()
        m.id = "m1"
        m.entity_type = "curve"
        m.geometry = None  # no geometry

        model = StructuralModel(id="test")
        model.add_member(m)

        writer = MagicMock(spec=UnifiedCalculixWriter)
        writer.domain_model = model
        writer.nodes = {
            1: np.array([0.0, 0.0, 0.0]),
            2: np.array([5.0, 0.0, 0.0]),
        }
        writer.elements = {10: {"type": "B31", "nodes": [1, 2]}}
        writer.element_sets = {"MEMBER_M1": [10]}
        writer.short_id_map = {}
        writer.short_id_counter = 0
        writer._get_short_id = UnifiedCalculixWriter._get_short_id.__get__(writer)
        writer._get_member_endpoints = (
            UnifiedCalculixWriter._get_member_endpoints.__get__(writer)
        )
        writer._find_connection_nodes_at_location = (
            UnifiedCalculixWriter._find_connection_nodes_at_location.__get__(writer)
        )

        # Connection 300 mm from node 1; old 500 mm tolerance would match
        pairs = writer._find_connection_nodes_at_location(_conn([0.3, 0, 0]), ["m1"])

        assert len(pairs) == 1
        assert pairs[0][1] == 1


# ---------------------------------------------------------------------------
# _get_member_endpoints unit tests
# ---------------------------------------------------------------------------


class TestGetMemberEndpoints:
    def _writer_with_member(self, member_id, geometry):
        m = MagicMock()
        m.id = member_id
        m.geometry = geometry
        model = StructuralModel(id="t")
        model.add_member(m)

        writer = MagicMock(spec=UnifiedCalculixWriter)
        writer.domain_model = model
        writer._get_member_endpoints = (
            UnifiedCalculixWriter._get_member_endpoints.__get__(writer)
        )
        return writer

    def test_returns_none_for_no_geometry(self):
        writer = self._writer_with_member("m1", None)
        assert writer._get_member_endpoints("m1") is None

    def test_returns_none_for_single_point_geometry(self):
        writer = self._writer_with_member("m1", [[0, 0, 0]])
        assert writer._get_member_endpoints("m1") is None

    def test_returns_start_and_end_for_two_point_geometry(self):
        writer = self._writer_with_member("m1", [[1, 2, 3], [4, 5, 6]])
        result = writer._get_member_endpoints("m1")
        assert result is not None
        start, end = result
        np.testing.assert_array_almost_equal(start, [1, 2, 3])
        np.testing.assert_array_almost_equal(end, [4, 5, 6])

    def test_returns_first_and_last_for_multi_point_geometry(self):
        writer = self._writer_with_member("m1", [[0, 0, 0], [1, 0, 0], [2, 0, 0]])
        result = writer._get_member_endpoints("m1")
        assert result is not None
        start, end = result
        np.testing.assert_array_almost_equal(start, [0, 0, 0])
        np.testing.assert_array_almost_equal(end, [2, 0, 0])

    def test_result_is_cached(self):
        writer = self._writer_with_member("m1", [[0, 0, 0], [1, 0, 0]])
        result1 = writer._get_member_endpoints("m1")
        result2 = writer._get_member_endpoints("m1")
        assert result1 is result2  # same object from cache

    def test_returns_none_for_unknown_member(self):
        writer = self._writer_with_member("m1", [[0, 0, 0], [1, 0, 0]])
        assert writer._get_member_endpoints("nonexistent") is None
