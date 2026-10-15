"""Nodal forces of U1 elements from their stiffness (aiz.19)."""

import numpy as np
import pytest

from ifc_structural_mechanics.analysis.user_element_forces import (
    u1_element_forces,
    u1_local_stiffness,
    u1_nodal_forces,
    u1_section_forces,
)

E, NU, A, I11, I22, K = 2.1e11, 0.3, 0.01, 8.0e-6, 3.0e-6, 0.8


def _element(start, end, direction, nodes=(1, 2)):
    return {
        "nodes": nodes,
        "positions": (start, end),
        "direction": direction,
        "modulus": E,
        "poisson": NU,
        "area": A,
        "inertia_11": I11,
        "inertia_22": I22,
        "shear_factor": K,
    }


def test_matrix_is_symmetric():
    matrix = u1_local_stiffness(E, NU, A, I11, I22, K, 0.3)
    assert np.allclose(matrix, matrix.T)


def test_without_shear_deformation_it_is_the_euler_beam():
    """With a shear stiffness far beyond the bending one, the bending terms
    are 12EI/L^3, 6EI/L^2, 4EI/L and 2EI/L."""
    length = 2.0
    matrix = u1_local_stiffness(E, NU, A, I11, I22, 1e9, length)
    # A displacement along local 2 goes with a turn about local 3, one along
    # local 3 with a turn about local 2 the other way
    for inertia, w, r, sign in ((I11, 1, 5, 1.0), (I22, 2, 4, -1.0)):
        ei = E * inertia
        assert matrix[w, w] == pytest.approx(12 * ei / length**3, rel=1e-6)
        assert matrix[w, r] == pytest.approx(sign * 6 * ei / length**2, rel=1e-6)
        assert matrix[r, r] == pytest.approx(4 * ei / length, rel=1e-6)
        assert matrix[r, r + 6] == pytest.approx(2 * ei / length, rel=1e-6)


def test_rigid_movement_gives_no_force():
    """The element is in equilibrium with itself however it is turned."""
    start = np.array([1.0, 2.0, 0.5])
    end = start + np.array([0.3, -0.2, 0.4])
    along = (end - start) / np.linalg.norm(end - start)
    direction = np.cross(along, [0.0, 0.0, 1.0])
    direction /= np.linalg.norm(direction)
    element = _element(start, end, direction)
    shift = np.array([1e-3, -2e-3, 5e-4])
    turn = np.array([2e-3, 1e-3, -3e-3])
    moved = {
        node: np.concatenate([shift + np.cross(turn, point), turn])
        for node, point in ((1, start), (2, end))
    }
    for force in u1_element_forces(element, moved).values():
        assert np.allclose(force, 0.0, atol=1e-6)


def _cantilever(count, length, loads):
    """Solve a cantilever of U1 elements along x, clamped at node 1.

    ``loads`` has six values per node. Returns the elements and the
    displacements of their nodes.
    """
    points = [np.array([length * i / count, 0.0, 0.0]) for i in range(count + 1)]
    elements = {
        i + 1: _element(points[i], points[i + 1], (0.0, 0.0, 1.0), (i + 1, i + 2))
        for i in range(count)
    }
    size = 6 * (count + 1)
    stiffness = np.zeros((size, size))
    for number, element in elements.items():
        local = u1_local_stiffness(E, NU, A, I11, I22, K, length / count)
        axes = np.array([[1.0, 0, 0], [0, 0, 1.0], [0, -1.0, 0]])
        turn = np.kron(np.eye(4), axes)
        dofs = list(range(6 * (number - 1), 6 * (number + 1)))
        stiffness[np.ix_(dofs, dofs)] += turn.T @ local @ turn
    free = list(range(6, size))
    solution = np.zeros(size)
    solution[free] = np.linalg.solve(stiffness[np.ix_(free, free)], loads[free])
    moved = {n + 1: solution[6 * n : 6 * n + 6] for n in range(count + 1)}
    return elements, moved


def test_forces_of_a_cantilever_balance_its_load():
    """Solve a cantilever of U1 elements with this stiffness: the forces
    at the free nodes are the loads and at the root the reaction."""
    count, length, load = 6, 3.0, -1000.0
    loads = np.zeros(6 * (count + 1))
    loads[6 * count + 2] = load
    elements, moved = _cantilever(count, length, loads)
    forces = u1_nodal_forces(elements, moved, [1, 4, count + 1])
    assert forces[count + 1][2] == pytest.approx(load)
    assert np.allclose(forces[4], 0.0, atol=1e-6)
    assert forces[1][2] == pytest.approx(-load)
    # The root holds the moment of the load at the end of the cantilever
    assert forces[1][4] == pytest.approx(load * length)


class TestSectionForces:
    """Section forces at the ends of U1 elements (bgz).

    A cantilever of 3 m along x, its section's 1-direction up, under a load
    of 1000 N/m downwards written as half of each element's share at either
    of its nodes, as the input writer does. A cantilever is statically
    determinate, so at every node the shear is w (L - x) and the moment
    w (L - x)^2 / 2, hogging, however coarse the mesh.
    """

    COUNT, LENGTH, W = 4, 3.0, -1000.0

    def _records(self, axis):
        step = self.LENGTH / self.COUNT
        loads = np.zeros(6 * (self.COUNT + 1))
        share = np.zeros(12)
        share[2] = share[8] = self.W * step / 2
        for number in range(1, self.COUNT + 1):
            loads[6 * (number - 1) : 6 * (number + 1)] += share
        elements, moved = _cantilever(self.COUNT, self.LENGTH, loads)
        return [
            record
            for element in elements.values()
            for record in u1_section_forces(element, moved, share, axis)
        ]

    def test_shear_and_moment_are_those_of_statics(self):
        for record in self._records((1.0, 0.0, 0.0)):
            beyond = self.LENGTH - record["centre"][0]
            # Fibres on top in tension, and the part beyond pulls down
            assert record["Mf1"] == pytest.approx(-self.W * beyond**2 / 2, abs=1e-6)
            assert record["Vf1"] == pytest.approx(self.W * beyond, abs=1e-6)
            for key in ("N", "Vf2", "T", "Mf2"):
                assert record[key] == pytest.approx(0.0, abs=1e-6)
            # About 2 = x cross 1, which is -y here
            assert record["moment"][1] == pytest.approx(record["Mf1"], abs=1e-6)

    def test_positions_follow_the_axis_given(self):
        """Turned round, an element starts at its second node: the moment is
        the same and the shear changes sign."""
        forward = self._records((1.0, 0.0, 0.0))
        # Each element's first node is the nearer the root
        for start, end in zip(forward[::2], forward[1::2]):
            assert (start["position"], end["position"]) == (-1.0, 1.0)
            assert start["centre"][0] < end["centre"][0]
        by_place = {(round(r["centre"][0], 9), r["position"]): r for r in forward}
        for record in self._records((-1.0, 0.0, 0.0)):
            twin = by_place[(round(record["centre"][0], 9), -record["position"])]
            assert record["Mf1"] == pytest.approx(twin["Mf1"], abs=1e-6)
            assert record["Vf1"] == pytest.approx(-twin["Vf1"], abs=1e-6)


class TestWhichForcesAreGiven:
    """The parser keeps whichever forces balance the loads (aiz.19).

    A cantilever of one U1 element along x, clamped at node 1, with a load
    down at node 2. The solver as of 2.23 prints the root force with the
    wrong sign; a version that has put that right prints it as statics has
    it; one with a different U1 element has a stiffness ours does not match.
    """

    LOAD = 1000.0
    LENGTH = 2.0

    def _parse(self, solver_fz: float, stiffness_scale: float = 1.0):
        from types import SimpleNamespace

        from ifc_structural_mechanics.analysis.results_parser import ResultsParser
        from ifc_structural_mechanics.domain.result import (
            DisplacementResult,
            ReactionForceResult,
        )

        start, end = (0.0, 0.0, 0.0), (self.LENGTH, 0.0, 0.0)
        element = _element(start, end, (0.0, 0.0, 1.0))
        # Displacements from the element the solver has; ours may differ
        local = u1_local_stiffness(E, NU, A, I11, I22, K, self.LENGTH)
        axes = np.array([[1.0, 0, 0], [0, 0, 1.0], [0, -1.0, 0]])
        matrix = (np.kron(np.eye(2), axes).T @ local[6:, 6:]) @ np.kron(np.eye(2), axes)
        tip = np.linalg.solve(matrix, [0, 0, -self.LOAD, 0, 0, 0])
        recorded = dict(element, modulus=E * stiffness_scale)
        model = SimpleNamespace(
            user_elements={1: recorded},
            support_node_elements={1: (start, {1: [end]})},
            applied_load_totals=[[0.0, 0.0, -self.LOAD]],
            support_node_loads=[{}],
            analysis_warnings=[],
        )
        displacements = []
        for node, moved in ((1, np.zeros(6)), (2, tip)):
            result = DisplacementResult(reference_element=node)
            result.set_translations(list(moved[:3]))
            result.set_rotations(list(moved[3:]))
            result.add_metadata("load_case", "A")
            displacements.append(result)
        total = ReactionForceResult(reference_element="TOTAL")
        total.set_forces([0.0, 0.0, solver_fz])
        parsed = {
            "displacement": displacements,
            "reaction": [total],
            "support_node_forces": [
                {"load_case": "A", "forces": {1: [0.0, 0.0, solver_fz]}}
            ],
            "support_node_moments": [],
        }
        ResultsParser(model)._correct_user_element_forces(parsed)
        warnings = [w["message"] for w in model.analysis_warnings]
        return parsed, warnings

    def test_wrong_solver_forces_are_replaced(self):
        parsed, warnings = self._parse(solver_fz=-self.LOAD)
        assert parsed["support_node_forces"][0]["forces"][1][2] == pytest.approx(
            self.LOAD
        )
        assert parsed["support_node_moments"][0]["moments"][1][1] == pytest.approx(
            -self.LOAD * self.LENGTH
        )
        assert parsed["reaction"][0].get_forces()[2] == pytest.approx(self.LOAD)
        assert warnings == []

    def test_a_solver_that_was_put_right_is_noticed(self):
        parsed, warnings = self._parse(solver_fz=self.LOAD)
        assert parsed["support_node_forces"][0]["forces"][1][2] == pytest.approx(
            self.LOAD
        )
        (warning,) = warnings
        assert "has put right" in warning

    def test_a_changed_element_keeps_the_solver_forces(self):
        parsed, warnings = self._parse(solver_fz=self.LOAD, stiffness_scale=1.1)
        assert parsed["support_node_forces"][0]["forces"][1] == [0.0, 0.0, self.LOAD]
        assert parsed["support_node_moments"][0]["moments"] == {}
        (warning,) = warnings
        assert "has changed its U1 element" in warning

    def test_when_neither_balances_it_says_so(self):
        parsed, warnings = self._parse(solver_fz=-self.LOAD, stiffness_scale=1.1)
        (warning,) = warnings
        assert "Do not rely on the reactions" in warning
