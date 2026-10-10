"""Axes of support conditions and member-side releases, read from structure_01."""

import os

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.analysis.boundary_condition_handling import (  # noqa: E402
    get_constrained_dofs,
    get_released_rotations,
)
from ifc_structural_mechanics.ifc.connections_extractor import (  # noqa: E402
    ConnectionsExtractor,
)

STRUCTURE = os.path.join("examples", "analysis-models", "ifcFiles", "structure_01.ifc")

pytestmark = pytest.mark.skipif(
    not os.path.exists(STRUCTURE), reason="example models submodule missing"
)

WALL_BASE = "23RzRvjKn8ShwJhkKFN1Ew"
SLAB_ON_WALL = "0ZaxF2PWvBXhifWDnUHnLy"
COLUMN_01_BASE = "3WBDi6os95XhE$8EzpwpbI"
COLUMN_02_BASE = "1jYp7Sgz9FXxB_e1tB9r7v"
SLAB = "1$jJrOdiH0nvjT6U$k3$lL"
COLUMN_01 = "3T5bCykkv89wwlZFZHhR1M"


@pytest.fixture(scope="module")
def connections():
    extractor = ConnectionsExtractor(ifcopenshell.open(STRUCTURE))
    return {c.id: c for c in extractor.extract_all_connections()}


def test_line_support_axes_follow_its_edge(connections):
    """Local x runs along the edge (global Y); Axis (global X) is local z."""
    assert connections[WALL_BASE].local_axes == [
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
    ]


def test_point_support_axes_come_from_its_coordinate_system(connections):
    """RefDirection (global Y) is local x; Axis (global X) is local z."""
    support = connections[COLUMN_02_BASE]
    assert support.local_axes == [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]]
    assert get_constrained_dofs(support) == [1, 2, 3, 4, 5, 6]


def test_wall_base_is_held_about_its_own_edge(connections):
    """T,T,T,T,F,F in the edge's axes: rotation about global Y, not X."""
    assert get_constrained_dofs(connections[WALL_BASE]) == [1, 2, 3, 5]


def test_edge_condition_releases_are_read(connections):
    """IfcBoundaryEdgeCondition names its stiffnesses ...ByLengthX."""
    joint = connections[SLAB_ON_WALL]
    assert joint.released_dofs_by_member == {SLAB: [4, 5, 6]}
    assert get_released_rotations(joint, SLAB) == [4, 5, 6]


def test_column_release_is_in_the_axes_of_its_relation(connections):
    """Relation x is the column axis (global Z): dry and drz are global X and Y."""
    base = connections[COLUMN_01_BASE]
    assert base.released_dofs_by_member == {COLUMN_01: [5, 6]}
    assert base.release_axes_by_member[COLUMN_01][0] == [0.0, 0.0, 1.0]
    assert get_released_rotations(base, COLUMN_01) == [4, 5]
    assert get_constrained_dofs(base) == [1, 2, 3, 6]
