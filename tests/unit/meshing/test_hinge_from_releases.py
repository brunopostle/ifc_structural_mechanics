"""Tests for is_hinge=True path in _write_point_connection()."""

import io
import re
from unittest.mock import MagicMock

import numpy as np

from ifc_structural_mechanics.domain.structural_connection import StructuralConnection
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)


def _make_conn(has_end_releases: bool = True) -> StructuralConnection:
    conn = StructuralConnection(id="conn1", connection_type="point")
    conn.position = (0.0, 0.0, 0.0)
    conn.has_end_releases = has_end_releases
    conn.connected_members = ["m1", "m2"]
    return conn


def _make_writer_stub():
    model = StructuralModel(id="test")
    writer = MagicMock(spec=UnifiedCalculixWriter)
    writer.domain_model = model
    writer.nodes = {
        1: np.array([0.0, 0.0, 0.0]),
        2: np.array([1.0, 0.0, 0.0]),
    }
    writer.elements = {
        10: {"type": "B31", "nodes": [1, 2]},
    }
    writer.element_sets = {
        "MEMBER_m1": [10],
        "MEMBER_m2": [10],
    }
    writer._get_short_id = lambda mid: mid
    writer._find_connection_nodes_at_location = MagicMock(return_value=[1, 2])
    writer._check_rotational_dofs_at_nodes = MagicMock(return_value=True)
    writer._write_point_connection = (
        UnifiedCalculixWriter._write_point_connection.__get__(writer)
    )
    return writer


def _get_equations(text: str):
    """Extract all DOF numbers that appear in *EQUATION lines."""
    dofs = []
    in_eq = False
    for line in text.splitlines():
        s = line.strip()
        if s == "*EQUATION":
            in_eq = True
            continue
        if in_eq and s.startswith("*"):
            in_eq = False
        if in_eq and s:
            # Data line format: n_terms\n node, dof, coeff \n node, dof, coeff
            # or: node, dof, coeff, node, dof, coeff
            nums = re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", s)
            # DOFs are typically small integers (1-6); collect those ≤ 6
            for i in range(1, len(nums), 3):
                try:
                    dof = int(nums[i])
                    if 1 <= dof <= 6:
                        dofs.append(dof)
                except (ValueError, IndexError):
                    pass
    return dofs


class TestHingeFromEndReleases:
    """_write_point_connection() with is_hinge=True only constrains translations."""

    def _write(self, is_hinge: bool) -> str:
        writer = _make_writer_stub()
        conn = _make_conn(has_end_releases=is_hinge)
        buf = io.StringIO()
        writer._write_point_connection(
            buf, conn, ["m1", "m2"], set(), is_hinge=is_hinge
        )
        return buf.getvalue()

    def test_hinge_has_no_rotational_equations(self):
        """is_hinge=True must not produce equations for DOFs 4, 5, or 6."""
        text = self._write(is_hinge=True)
        if "*EQUATION" in text:
            dofs = _get_equations(text)
            rotational = [d for d in dofs if d in (4, 5, 6)]
            assert (
                rotational == []
            ), f"Rotational DOFs {rotational} found in hinge equations:\n{text}"

    def test_hinge_label_in_output(self):
        """Hinge connection should be labelled differently from rigid."""
        text = self._write(is_hinge=True)
        assert "HINGE" in text or "hinge" in text.lower()

    def test_point_connection_dispatch_uses_has_end_releases(self):
        """_write_connections() passes has_end_releases as is_hinge for point connections."""
        from ifc_structural_mechanics.domain.structural_connection import (
            PointConnection,
        )
        from ifc_structural_mechanics.domain.structural_model import StructuralModel

        model = StructuralModel(id="test")
        writer = MagicMock(spec=UnifiedCalculixWriter)
        writer.domain_model = model
        writer._write_point_connection = MagicMock()
        writer._write_rigid_connection = MagicMock()
        writer._write_connections = UnifiedCalculixWriter._write_connections.__get__(
            writer
        )

        conn = PointConnection("conn1", (0, 0, 0))
        conn.has_end_releases = True
        conn.connect_member("m1")
        conn.connect_member("m2")
        model.connections.append(conn)

        bc_dofs = set()
        writer._write_connections(io.StringIO(), bc_dofs)

        writer._write_point_connection.assert_called_once()
        call_kwargs = writer._write_point_connection.call_args
        # is_hinge should be True
        assert call_kwargs[1].get("is_hinge") is True or (
            len(call_kwargs[0]) >= 4 and call_kwargs[0][-1] is True
        )
