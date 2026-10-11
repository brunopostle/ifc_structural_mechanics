"""Support conditions are given in the connection's axes, not the global ones."""

import io

from ifc_structural_mechanics.analysis.boundary_condition_handling import (
    get_constrained_dofs,
    get_released_rotations,
    support_is_skew,
    write_boundary_conditions,
)
from ifc_structural_mechanics.domain.structural_connection import RigidConnection
from ifc_structural_mechanics.domain.structural_model import StructuralModel

FIXED, FREE = 1e20, 0.0
# Line support along global Y, as IFC describes it: x along the edge
ALONG_Y = [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]]
SKEW = [[0.6, 0.8, 0.0], [-0.8, 0.6, 0.0], [0.0, 0.0, 1.0]]


def _support(fixity, local_axes=None, members=("m1",)):
    connection = RigidConnection("s", [0.0, 0.0, 0.0])
    connection.set_stiffness_properties(
        dict(zip(("dx", "dy", "dz", "drx", "dry", "drz"), fixity))
    )
    connection.local_axes = local_axes
    for member in members:
        connection.connect_member(member)
    return connection


class TestConstrainedDofsInLocalAxes:
    def test_global_axes_by_default(self):
        support = _support((FIXED, FIXED, FIXED, FIXED, FREE, FREE))
        assert get_constrained_dofs(support) == [1, 2, 3, 4]

    def test_rotation_about_an_edge_along_y_is_global_dof_5(self):
        """drx of a line support is rotation about the line itself."""
        support = _support((FIXED, FIXED, FIXED, FIXED, FREE, FREE), ALONG_Y)
        assert get_constrained_dofs(support) == [1, 2, 3, 5]

    def test_translations_are_permuted_too(self):
        # local y is global Z, so only the vertical translation is held
        support = _support((FREE, FIXED, FREE, FREE, FREE, FREE), ALONG_Y)
        assert get_constrained_dofs(support) == [3]

    def test_reversed_axis_is_the_same_dof(self):
        axes = [[0.0, -1.0, 0.0], [0.0, 0.0, 1.0], [-1.0, 0.0, 0.0]]
        support = _support((FIXED, FIXED, FIXED, FIXED, FREE, FREE), axes)
        assert get_constrained_dofs(support) == [1, 2, 3, 5]


class TestSkewSupports:
    def test_uniform_condition_is_not_skew(self):
        """A pin is a pin in any axes."""
        support = _support((FIXED, FIXED, FIXED, FREE, FREE, FREE), SKEW)
        assert not support_is_skew(support)
        assert get_constrained_dofs(support) == [1, 2, 3]

    def test_partial_condition_in_rotated_axes_is_skew(self):
        support = _support((FIXED, FREE, FIXED, FREE, FREE, FREE), SKEW)
        assert support_is_skew(support)

    def test_skew_support_is_reported(self):
        model = StructuralModel(id="model")
        model.connections.append(_support((FIXED, FREE, FIXED, FREE, FREE, FREE), SKEW))
        write_boundary_conditions(io.StringIO(), model, {}, {}, {1: (0.0, 0.0, 0.0)})
        warnings = [w["message"] for w in model.analysis_warnings]
        assert len(warnings) == 1
        assert "Skew supports are not modelled" in warnings[0]


class TestMemberSideReleaseAtASupport:
    """A support cannot restrain a rotation its only member is released in."""

    # Column along global Z: local x is its axis
    COLUMN = [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

    def _fixed_base(self, released, axes):
        support = _support((FIXED,) * 6)
        support.released_dofs_by_member = {"m1": released}
        support.release_axes_by_member = {"m1": axes}
        return support

    def test_release_is_turned_into_global_dofs(self):
        support = self._fixed_base([5, 6], self.COLUMN)
        assert get_released_rotations(support, "m1") == [4, 5]

    def test_bending_release_leaves_torsion_restrained(self):
        support = self._fixed_base([5, 6], self.COLUMN)
        assert get_constrained_dofs(support) == [1, 2, 3, 6]

    def test_full_release_needs_no_axes(self):
        support = self._fixed_base([4, 5, 6], SKEW)
        assert get_released_rotations(support, "m1") == [4, 5, 6]
        assert get_constrained_dofs(support) == [1, 2, 3]

    def test_partial_release_in_skew_axes_cannot_be_expressed(self):
        support = self._fixed_base([5], SKEW)
        assert get_released_rotations(support, "m1") is None
        assert get_constrained_dofs(support) == [1, 2, 3, 4, 5, 6]

    def test_member_without_release(self):
        support = _support((FIXED,) * 6)
        assert get_released_rotations(support, "m1") == []

    def test_release_is_ignored_where_two_members_meet(self):
        """Between members a release is a hinge in the joint, not in the support."""
        support = _support((FIXED,) * 6, members=("m1", "m2"))
        support.released_dofs_by_member = {"m1": [4, 5, 6]}
        assert get_constrained_dofs(support) == [1, 2, 3, 4, 5, 6]
