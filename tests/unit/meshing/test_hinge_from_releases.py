"""Tests for partial-release end-conditions in _write_point_connection()."""

import io
import re
import sys
import types
from unittest.mock import MagicMock

import numpy as np


# Stub gmsh and the sub-modules that import it before importing the real
# meshing package.  We do NOT stub the meshing package itself so that the
# real UnifiedCalculixWriter class can be loaded.
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
    _stub(
        "ifc_structural_mechanics.meshing.gmsh_runner",
        GmshRunner=MagicMock(),
    )

if "ifc_structural_mechanics.meshing.gmsh_utils" not in sys.modules:
    _stub("ifc_structural_mechanics.meshing.gmsh_utils")

from ifc_structural_mechanics.domain.structural_connection import (  # noqa: E402
    PointConnection,
    StructuralConnection,
)
from ifc_structural_mechanics.domain.structural_model import (  # noqa: E402
    StructuralModel,
)
from ifc_structural_mechanics.meshing.unified_calculix_writer import (  # noqa: E402
    UnifiedCalculixWriter,
)

_MEMBER_IDS = ["m1", "m2"]


def _make_writer_stub(node_pairs=None):
    """Return a UnifiedCalculixWriter method stub with two nodes at origin."""
    writer = MagicMock(spec=UnifiedCalculixWriter)
    writer.nodes = {
        1: np.array([0.0, 0.0, 0.0]),
        2: np.array([0.0, 0.0, 0.0]),  # same position → same connection point
    }
    writer.elements = {10: {"type": "B31", "nodes": [1, 2]}}
    writer.element_sets = {
        "MEMBER_m1": [10],
        "MEMBER_m2": [10],
    }
    writer._get_short_id = lambda mid: mid
    # Default: return (member_id, node_id) pairs
    pairs = node_pairs or [("m1", 1), ("m2", 2)]
    writer._find_connection_nodes_at_location = MagicMock(return_value=pairs)
    writer._check_rotational_dofs_at_nodes = MagicMock(return_value=True)
    writer._write_point_connection = (
        UnifiedCalculixWriter._write_point_connection.__get__(writer)
    )
    return writer


def _conn(released_dofs_by_member=None):
    conn = StructuralConnection(id="conn1", connection_type="point")
    conn.position = (0.0, 0.0, 0.0)
    conn.connected_members = list(_MEMBER_IDS)
    if released_dofs_by_member:
        conn.released_dofs_by_member = released_dofs_by_member
    return conn


def _extract_equation_dofs(text: str):
    """Return list of all DOFs (1-6) written in *EQUATION data lines."""
    dofs = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip() == "*EQUATION":
            i += 2  # skip term-count line
            if i < len(lines):
                nums = re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", lines[i])
                for j in range(1, len(nums), 3):
                    try:
                        d = int(nums[j])
                        if 1 <= d <= 6:
                            dofs.append(d)
                    except (ValueError, IndexError):
                        pass
        i += 1
    return dofs


# ---------------------------------------------------------------------------
# Separate nodes are only ever pinned: CalculiX ignores *EQUATION on DOF 4-6
# of beam and shell nodes, so no rotational equations are written.
# ---------------------------------------------------------------------------


class TestSeparateNodesArePinned:
    def _write(self):
        writer = _make_writer_stub()
        conn = _conn()
        buf = io.StringIO()
        writer._write_point_connection(
            buf, conn, _MEMBER_IDS, set(), released_dofs_by_member={}
        )
        return buf.getvalue()

    def test_only_translations_coupled(self):
        text = self._write()
        dofs = _extract_equation_dofs(text)
        assert set(dofs) == {1, 2, 3}

    def test_labelled_rigid(self):
        text = self._write()
        assert "RIGID" in text


# ---------------------------------------------------------------------------
# Full pin (all three rotation DOFs released for all members)
# ---------------------------------------------------------------------------


class TestFullPinReleases:
    def _write(self):
        writer = _make_writer_stub()
        conn = _conn(released_dofs_by_member={"m1": [4, 5, 6], "m2": [4, 5, 6]})
        released = conn.released_dofs_by_member
        buf = io.StringIO()
        writer._write_point_connection(
            buf, conn, _MEMBER_IDS, set(), released_dofs_by_member=released
        )
        return buf.getvalue()

    def test_no_rotational_equations(self):
        text = self._write()
        dofs = _extract_equation_dofs(text)
        rotational = [d for d in dofs if d in (4, 5, 6)]
        assert rotational == [], f"Unexpected rotation DOFs: {rotational}\n{text}"

    def test_translations_still_coupled(self):
        text = self._write()
        dofs = _extract_equation_dofs(text)
        assert 1 in dofs and 2 in dofs and 3 in dofs

    def test_labelled_partial_hinge(self):
        text = self._write()
        assert "HINGE" in text or "PARTIAL" in text


# ---------------------------------------------------------------------------
# Partial release — cannot be represented, so it becomes a full pin with a
# warning to the user.
# ---------------------------------------------------------------------------


class TestPartialRelease:
    def _write(self, released):
        writer = _make_writer_stub()
        conn = _conn(released_dofs_by_member=released)
        buf = io.StringIO()
        writer._write_point_connection(
            buf, conn, _MEMBER_IDS, set(), released_dofs_by_member=released
        )
        return writer, buf.getvalue()

    def test_no_rotational_equations(self):
        _, text = self._write({"m1": [4]})
        assert set(_extract_equation_dofs(text)) == {1, 2, 3}

    def test_user_is_warned(self):
        writer, _ = self._write({"m1": [6]})
        writer._warn_user.assert_called_once()
        message = writer._warn_user.call_args[0][0]
        assert "m1" in message and "partial" in message

    def test_full_release_does_not_warn(self):
        writer, _ = self._write({"m1": [4, 5, 6]})
        writer._warn_user.assert_not_called()


# ---------------------------------------------------------------------------
# Rigid connections: coincident nodes of unreleased members are merged
# ---------------------------------------------------------------------------


def _merge_stub(positions, pairs, released=None, entity_type="point"):
    """Writer stub with one node per member and a single two-member connection."""
    writer = MagicMock(spec=UnifiedCalculixWriter)
    writer.nodes = {n: tuple(p) for n, p in positions.items()}
    writer.elements = {
        10: {"type": "B31", "nodes": [1, 3]},
        20: {"type": "S3", "nodes": [2, 4, 5]},
    }
    writer.node_sets = {"SET": [1, 2]}
    writer._u1_members = set()
    writer._COINCIDENT_TOL = UnifiedCalculixWriter._COINCIDENT_TOL
    writer._MAX_RIGID_LINK = UnifiedCalculixWriter._MAX_RIGID_LINK
    writer._find_connection_nodes_at_location = MagicMock(return_value=pairs)
    conn = _conn(released_dofs_by_member=released)
    conn.entity_type = entity_type
    writer.domain_model = MagicMock()
    writer.domain_model.connections = [conn]
    writer._merge_rigid_connection_nodes = (
        UnifiedCalculixWriter._merge_rigid_connection_nodes.__get__(writer)
    )
    return writer


_POSITIONS = {
    1: (0.0, 0.0, 0.0),
    2: (0.0, 0.0, 0.0),
    3: (1.0, 0.0, 0.0),
    4: (0.0, 1.0, 0.0),
    5: (1.0, 1.0, 0.0),
}


class TestMergeRigidConnectionNodes:
    def test_coincident_nodes_are_merged(self):
        writer = _merge_stub(_POSITIONS, [("m1", 1), ("m2", 2)])
        writer._merge_rigid_connection_nodes()
        assert writer.elements[20]["nodes"] == [1, 4, 5]
        assert 2 not in writer.nodes
        assert writer.node_sets["SET"] == [1]
        writer._warn_user.assert_not_called()

    def test_node_short_of_the_joint_gets_a_rigid_link(self):
        """A member ending 0.3 m from the joint is bridged, not merged."""
        positions = dict(_POSITIONS)
        positions[2] = (0.0, 0.3, 0.0)
        writer = _merge_stub(positions, [("m1", 1), ("m2", 2)])
        writer._merge_rigid_connection_nodes()
        assert writer.elements[20]["nodes"] == [2, 4, 5]
        assert 2 in writer.nodes
        assert [(a, b) for _, a, b in writer._rigid_links] == [(1, 2)]
        assert writer._rigid_links[0][0] > max(writer.elements)
        writer._warn_user.assert_not_called()

    def test_node_far_from_the_joint_is_left_pinned_with_warning(self):
        positions = dict(_POSITIONS)
        positions[2] = (0.0, 5.0, 0.0)
        writer = _merge_stub(positions, [("m1", 1), ("m2", 2)])
        writer._merge_rigid_connection_nodes()
        assert writer._rigid_links == []
        writer._warn_user.assert_called_once()

    def test_released_member_is_not_merged(self):
        writer = _merge_stub(
            _POSITIONS, [("m1", 1), ("m2", 2)], released={"m2": [4, 5, 6]}
        )
        writer._merge_rigid_connection_nodes()
        assert writer.elements[20]["nodes"] == [2, 4, 5]
        writer._find_connection_nodes_at_location.assert_not_called()


# ---------------------------------------------------------------------------
# _write_connections() dispatch: released_dofs_by_member is forwarded
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_released_dofs_passed_to_write_point_connection(self):
        model = StructuralModel(id="test")
        writer = MagicMock(spec=UnifiedCalculixWriter)
        writer.domain_model = model
        writer._write_point_connection = MagicMock()
        writer._write_connections = UnifiedCalculixWriter._write_connections.__get__(
            writer
        )

        conn = PointConnection("conn1", [0.0, 0.0, 0.0])
        conn.released_dofs_by_member = {"m1": [4, 5]}
        conn.connect_member("m1")
        conn.connect_member("m2")
        model.connections.append(conn)

        writer._write_connections(io.StringIO(), set())

        writer._write_point_connection.assert_called_once()
        kwargs = writer._write_point_connection.call_args[1]
        assert "released_dofs_by_member" in kwargs
        assert kwargs["released_dofs_by_member"] == {"m1": [4, 5]}

    def test_empty_releases_for_rigid_connection(self):
        """Rigid connection (no releases) passes empty dict."""
        model = StructuralModel(id="test")
        writer = MagicMock(spec=UnifiedCalculixWriter)
        writer.domain_model = model
        writer._write_point_connection = MagicMock()
        writer._write_connections = UnifiedCalculixWriter._write_connections.__get__(
            writer
        )

        conn = PointConnection("conn_rigid", [0.0, 0.0, 0.0])
        conn.connect_member("m1")
        conn.connect_member("m2")
        model.connections.append(conn)

        writer._write_connections(io.StringIO(), set())

        kwargs = writer._write_point_connection.call_args[1]
        assert kwargs.get("released_dofs_by_member") == {}
