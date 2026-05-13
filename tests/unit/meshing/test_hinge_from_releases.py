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
# Rigid connection (no releases) — DOF 1-6 all coupled
# ---------------------------------------------------------------------------


class TestRigidConnection:
    def _write(self):
        writer = _make_writer_stub()
        conn = _conn()
        buf = io.StringIO()
        writer._write_point_connection(
            buf, conn, _MEMBER_IDS, set(), released_dofs_by_member={}
        )
        return buf.getvalue()

    def test_all_six_dofs_coupled(self):
        text = self._write()
        dofs = _extract_equation_dofs(text)
        assert set(dofs) == {1, 2, 3, 4, 5, 6}

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
# Partial pin — one member has only one rotation axis released
# ---------------------------------------------------------------------------


class TestPartialPin:
    def _write(self, released):
        writer = _make_writer_stub()
        conn = _conn(released_dofs_by_member=released)
        buf = io.StringIO()
        writer._write_point_connection(
            buf, conn, _MEMBER_IDS, set(), released_dofs_by_member=released
        )
        return buf.getvalue()

    def test_only_released_dof_is_absent(self):
        """m1 releases DOF 4; m2 is rigid — DOF 4 should NOT appear, 5 and 6 should."""
        text = self._write({"m1": [4]})
        dofs = _extract_equation_dofs(text)
        assert 4 not in dofs, f"DOF 4 should be free but appeared: {dofs}"
        assert 5 in dofs and 6 in dofs

    def test_z_only_release(self):
        """Only Z-rotation (DOF 6) released for m1; m2 rigid → DOF 6 absent."""
        text = self._write({"m1": [6]})
        dofs = _extract_equation_dofs(text)
        assert 6 not in dofs
        assert 4 in dofs and 5 in dofs

    def test_both_members_release_same_axis(self):
        """Both members release DOF 5 → no DOF 5 equation."""
        text = self._write({"m1": [5], "m2": [5]})
        dofs = _extract_equation_dofs(text)
        assert 5 not in dofs
        assert 4 in dofs and 6 in dofs

    def test_only_one_member_releases_dof_still_couples_the_other(self):
        """m1 releases DOF 4; m2 does not → two nodes are not coupled on DOF 4."""
        # With only m1 releasing DOF 4, there is only 1 node left in the
        # coupled set for DOF 4, so no equation should appear.
        text = self._write({"m1": [4]})
        dofs = _extract_equation_dofs(text)
        assert (
            4 not in dofs
        ), "DOF 4 equation should not appear when only one of two nodes is coupled"


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
