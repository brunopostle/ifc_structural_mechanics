"""A model is supported where the file says, or the analysis stops.

The support writer used to fix every node at y = 0 when it found no support,
leave out a support that had no mesh node near it, put a line support with no
node on its edge at the edge's midpoint, and treat a connection of type
"rigid" holding one member as a fixed support whether or not it had a support
condition.
"""

import io

import pytest

from ifc_structural_mechanics.analysis.boundary_condition_handling import (
    find_connection_support_nodes,
    get_constrained_dofs,
    write_boundary_conditions,
)
from ifc_structural_mechanics.domain.structural_connection import (
    PointConnection,
    RigidConnection,
)
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.utils.error_handling import AnalysisError
from tests.helpers import fixed_support

# A beam along x with a node at y = 0, which the old fallback would have fixed
NODES = {1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0), 3: (2.0, 0.0, 0.0)}


def _write(*connections):
    model = StructuralModel(id="model")
    model.connections.extend(connections)
    out = io.StringIO()
    node_sets = {}
    write_boundary_conditions(out, model, node_sets, {}, NODES)
    return out.getvalue(), node_sets, model


class TestSupports:
    def test_support_is_written_on_its_node(self):
        text, node_sets, _ = _write(fixed_support((2, 0, 0), "m1"))
        assert node_sets["BC_support"] == [3]
        assert node_sets["ALL_BC_NODES"] == [3]
        assert "BC_support, 1, 6" in text

    def test_model_without_supports_is_an_error(self):
        """It used to be fixed at every node with y = 0."""
        with pytest.raises(AnalysisError, match="has no supports"):
            _write()

    def test_joint_is_not_a_support(self):
        joint = RigidConnection("joint", [1.0, 0.0, 0.0])
        joint.connect_member("m1")
        joint.connect_member("m2")
        with pytest.raises(AnalysisError, match="has no supports"):
            _write(joint)

    def test_support_away_from_the_mesh_is_an_error(self):
        """It used to be left out, and the analysis run without it."""
        with pytest.raises(AnalysisError, match="lost.*no node within 0.1 m"):
            _write(
                fixed_support((0, 0, 0), "m1"),
                fixed_support((1, 5, 0), "m2", connection_id="lost"),
            )

    def test_support_holding_nothing_is_reported_and_left_out(self):
        loose = fixed_support((1, 5, 0), "m1", connection_id="loose")
        loose.disconnect_member("m1")
        text, node_sets, model = _write(fixed_support((0, 0, 0), "m1"), loose)
        assert "BC_loose" not in node_sets
        (warning,) = model.analysis_warnings
        assert "1 support(s) are connected to no member" in warning["message"]
        assert "loose" in warning["message"]


class TestWhatASupportIs:
    def test_connection_without_a_condition_restrains_nothing(self):
        """Its type used to decide: "rigid" with one member was fully fixed."""
        connection = RigidConnection("c", [0.0, 0.0, 0.0])
        connection.connect_member("m1")
        assert get_constrained_dofs(connection) == []

    def test_point_connection_with_a_condition_is_a_support(self):
        connection = PointConnection("c", [0.0, 0.0, 0.0])
        connection.connect_member("m1")
        connection.set_stiffness_properties({"dx": 1e20, "dy": 1e20, "dz": 1e20})
        assert get_constrained_dofs(connection) == [1, 2, 3]


class TestLineSupport:
    def _line(self, start, end):
        support = fixed_support((1, 0, 0), "m1")
        support.edge = [list(start), list(end)]
        return support

    def test_nodes_on_the_edge_are_restrained(self):
        support = self._line((0, 0, 0), (2, 0, 0))
        assert find_connection_support_nodes(support, NODES) == [1, 2, 3]

    def test_edge_with_no_node_on_it_is_no_support(self):
        """Its midpoint used to be taken as a point support instead."""
        support = self._line((1, -1, 0.5), (1, 1, 0.5))
        assert find_connection_support_nodes(support, NODES) == []
        with pytest.raises(AnalysisError, match="cannot be applied"):
            _write(support)


class TestSupportHoldsItsOwnMembers:
    """Beam and shell meshes keep a node each at one point (aiz.97)."""

    # Node 4 is a slab's, at the beam's end node 1
    COINCIDENT = {**NODES, 4: (0.0, 0.0, 0.0), 5: (1.0, 0.0, 0.0)}

    def test_point_support_leaves_other_members_alone(self):
        support = fixed_support((0, 0, 0), "m1")
        held = {support.id: {1, 2, 3}}
        assert find_connection_support_nodes(support, self.COINCIDENT, held) == [1]

    def test_without_its_members_nodes_it_holds_all(self):
        support = fixed_support((0, 0, 0), "m1")
        assert find_connection_support_nodes(support, self.COINCIDENT) == [1, 4]
        # A member stopping short of it, joined by a link, has no node there
        held = {support.id: {2, 3}}
        assert find_connection_support_nodes(support, self.COINCIDENT, held) == [
            1,
            4,
        ]

    def test_line_support_leaves_other_members_alone(self):
        support = fixed_support((1, 0, 0), "m1")
        support.edge = [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
        held = {support.id: {4, 5}}
        assert find_connection_support_nodes(support, self.COINCIDENT, held) == [
            4,
            5,
        ]
