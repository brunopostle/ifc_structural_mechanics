"""Support conditions are given in the connection's axes, not the global ones."""

import io

import numpy as np
import pytest

from ifc_structural_mechanics.analysis.boundary_condition_handling import (
    get_constrained_dofs,
    get_released_rotations,
    released_rotation_axes,
    rotation_arm,
    support_equations,
    support_is_skew,
    support_restraint,
    write_boundary_conditions,
)
from ifc_structural_mechanics.domain.structural_connection import RigidConnection
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.utils.error_handling import AnalysisError

FIXED, FREE = 1e20, 0.0
# Line support along global Y, as IFC describes it: x along the edge
ALONG_Y = [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]]
SKEW = [[0.6, 0.8, 0.0], [-0.8, 0.6, 0.0], [0.0, 0.0, 1.0]]
# Local z along the diagonal of the global axes
DIAGONAL = [
    [2**-0.5, -(2**-0.5), 0.0],
    [6**-0.5, 6**-0.5, -2 * 6**-0.5],
    [3**-0.5, 3**-0.5, 3**-0.5],
]


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

    def test_skew_translation_is_an_equation_between_global_ones(self):
        """Held along (0.6, 0.8, 0) and along Z: Z is a DOF, the other is not."""
        support = _support((FIXED, FREE, FIXED, FREE, FREE, FREE), SKEW)
        assert get_constrained_dofs(support) == [3]
        (terms,) = support_equations(support, 7)
        # The larger coefficient comes first: CalculiX eliminates that DOF
        assert [(node, dof) for node, dof, _ in terms] == [(7, 2), (7, 1)]
        assert [coef for _, _, coef in terms] == pytest.approx([1.0, 0.75])

    def test_two_skew_translations_do_not_depend_on_each_other(self):
        # The free axis is the diagonal: no global direction is held outright
        support = _support((FIXED, FIXED, FREE, FREE, FREE, FREE), DIAGONAL)
        assert get_constrained_dofs(support) == []
        equations = support_equations(support, 1)
        dependent = [terms[0][1] for terms in equations]
        assert len(set(dependent)) == 2
        for terms in equations:
            assert not {dof for _, dof, _ in terms[1:]} & set(dependent)
        # Both leave movement along the free axis alone
        free = np.array(DIAGONAL)[2]
        for terms in equations:
            assert sum(c * free[dof - 1] for _, dof, c in terms) == pytest.approx(0)

    def test_skew_support_is_written_without_a_warning(self):
        model = StructuralModel(id="model")
        model.connections.append(_support((FIXED, FREE, FIXED, FREE, FREE, FREE), SKEW))
        out = io.StringIO()
        dependent = write_boundary_conditions(out, model, {}, {}, {1: (0.0, 0.0, 0.0)})
        assert not getattr(model, "analysis_warnings", [])
        assert "*BOUNDARY\nBC_s, 3, 3\n" in out.getvalue()
        assert "*EQUATION\n2\n1,2,1,1,1,0.75\n" in out.getvalue()
        assert dependent == {(1, 2)}
        record = model.support_nodes["s"]
        assert record["dofs"] == [3]
        assert len(record["translations"]) == 2


class TestSkewRotations:
    """Held with the tip of an arm: beam and shell nodes have no rotations."""

    def test_one_axis_held(self):
        support = _support((FIXED, FIXED, FIXED, FIXED, FREE, FREE), SKEW)
        assert support_is_skew(support)
        # None of the rotations is a *BOUNDARY
        assert get_constrained_dofs(support) == [1, 2, 3]
        arm, across = rotation_arm(support_restraint(support)[1])
        held = np.array(SKEW[0])
        assert abs(arm @ held) < 1e-9
        assert len(across) == 1
        # Holding the tip there stops rotation about the held axis only
        assert abs(np.cross(arm, across[0]) @ held) == pytest.approx(1.0)

    def test_two_axes_held(self):
        support = _support((FIXED, FIXED, FIXED, FIXED, FREE, FIXED), SKEW)
        arm, across = rotation_arm(support_restraint(support)[1])
        assert abs(arm @ np.array(SKEW[1])) == pytest.approx(1.0)
        assert len(across) == 2
        assert np.allclose(across @ arm, 0.0)

    def test_tip_is_tied_to_the_ground_when_the_node_cannot_move(self):
        support = _support((FIXED, FIXED, FIXED, FIXED, FREE, FREE), SKEW)
        (terms,) = support_equations(support, 1, arm_tip=9)
        assert {node for node, _, _ in terms} == {9}

    def test_tip_is_tied_to_the_node_when_it_can(self):
        support = _support((FIXED, FREE, FIXED, FIXED, FREE, FREE), SKEW)
        equations = support_equations(support, 1, arm_tip=9)
        tie = [terms for terms in equations if terms[0][0] == 9]
        assert len(tie) == 1
        by_node = {node: 0.0 for node in (1, 9)}
        for node, _, coefficient in tie[0]:
            by_node[node] += coefficient
        assert by_node[1] == pytest.approx(-by_node[9])

    def test_shell_node_is_held_about_its_normal_too(self):
        """It has no rotation there, and the arm would swing about it."""
        support = _support((FIXED, FIXED, FIXED, FIXED, FREE, FREE), SKEW)
        normal = [0.0, 0.0, 1.0]
        arm, across = rotation_arm(support_restraint(support)[1], normal)
        assert abs(arm @ np.array(SKEW[1])) == pytest.approx(1.0)
        assert len(across) == 2

    def test_shell_node_with_nothing_left_free_needs_no_arm(self):
        support = _support((FIXED, FIXED, FIXED, FIXED, FIXED, FREE), DIAGONAL)
        normal = [0.0, 0.0, 1.0]
        assert rotation_arm(support_restraint(support)[1], normal) is None
        equations = support_equations(support, 1, drilling=normal)
        assert equations == [[(1, 4, 1.0)], [(1, 5, 1.0)], [(1, 6, 1.0)]]

    def test_rotations_about_global_axes_need_no_arm(self):
        support = _support((FIXED, FIXED, FIXED, FIXED, FREE, FREE), ALONG_Y)
        assert rotation_arm(support_restraint(support)[1]) is None

    def test_no_arm_stops_the_analysis(self):
        model = StructuralModel(id="model")
        model.connections.append(
            _support((FIXED, FIXED, FIXED, FIXED, FREE, FREE), SKEW)
        )
        with pytest.raises(AnalysisError, match="not parallel to a global one"):
            write_boundary_conditions(
                io.StringIO(), model, {}, {}, {1: (0.0, 0.0, 0.0)}
            )

    def test_arm_tip_is_a_support_node(self):
        model = StructuralModel(id="model")
        model.connections.append(
            _support((FIXED, FIXED, FIXED, FIXED, FREE, FREE), SKEW)
        )
        node_sets: dict = {}
        write_boundary_conditions(
            io.StringIO(),
            model,
            node_sets,
            {},
            {1: (0.0, 0.0, 0.0)},
            rotation_arms={"s": {1: (9, (0.0, 0.0, 0.25), None)}},
        )
        assert node_sets["ALL_BC_NODES"] == [1, 9]
        assert node_sets["BC_s"] == [1]
        assert set(model.support_nodes["s"]["nodes"]) == {1, 9}


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

    def test_partial_release_in_skew_axes_leaves_the_other_rotations_held(self):
        support = self._fixed_base([5], SKEW)
        # It has no global DOF numbers, but it has an axis
        assert get_released_rotations(support, "m1") is None
        assert released_rotation_axes(support, "m1").tolist() == [SKEW[1]]
        assert get_constrained_dofs(support) == [1, 2, 3]
        held = support_restraint(support)[1]
        assert len(held) == 2
        assert np.allclose(held @ np.array(SKEW[1]), 0.0)

    def test_member_without_release(self):
        support = _support((FIXED,) * 6)
        assert get_released_rotations(support, "m1") == []

    def test_release_is_ignored_where_two_members_meet(self):
        """Between members a release is a hinge in the joint, not in the support."""
        support = _support((FIXED,) * 6, members=("m1", "m2"))
        support.released_dofs_by_member = {"m1": [4, 5, 6]}
        assert get_constrained_dofs(support) == [1, 2, 3, 4, 5, 6]
