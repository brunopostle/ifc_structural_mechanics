"""Section forces integrated from the nodal stresses of an expanded beam element."""

import numpy as np
import pytest

from ifc_structural_mechanics.analysis.results_parser import ResultsParser
from ifc_structural_mechanics.analysis.section_forces import element_section_forces
from ifc_structural_mechanics.domain.result import StressResult
from ifc_structural_mechanics.domain.structural_model import StructuralModel

DEPTH, WIDTH, LENGTH = 0.4, 0.2, 1.0
AREA = DEPTH * WIDTH
I1 = WIDTH * DEPTH**3 / 12  # stress varying over the depth
I2 = DEPTH * WIDTH**3 / 12


def _frame(axis, direction_1):
    t = np.array(axis, dtype=float)
    t /= np.linalg.norm(t)
    e1 = np.array(direction_1, dtype=float)
    e1 -= np.dot(e1, t) * t
    e1 /= np.linalg.norm(e1)
    return t, e1, np.cross(t, e1)


def _element(axis=(1, 0, 0), direction_1=(0, 0, 1), quadratic=True, origin=(3, -2, 5)):
    """Nodes of one expanded element: ``{id: (position, (x, y, z) local)}``.

    Eight nodes on each end face and four at the middle for a quadratic
    element, as CalculiX's C3D20; four on each end face for a linear one.
    """
    t, e1, e2 = _frame(axis, direction_1)
    corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    mids = [(0, -1), (1, 0), (0, 1), (-1, 0)]
    layout = [
        (-0.5, corners + (mids if quadratic else [])),
        (0.5, corners + (mids if quadratic else [])),
    ]
    if quadratic:
        layout.insert(1, (0.0, corners))
    nodes = {}
    for along, face in layout:
        for a, b in face:
            local = (along * LENGTH, a * DEPTH / 2, b * WIDTH / 2)
            position = np.array(origin) + local[0] * t + local[1] * e1 + local[2] * e2
            nodes[100 + len(nodes)] = (position, local)
    return nodes, (t, e1, e2)


def _stresses(nodes, frame, field):
    """Global stress components at each node from a field in section axes.

    ``field(x, y, z)`` returns ``(sigma_tt, tau_t1, tau_t2)``.
    """
    t, e1, e2 = frame
    rotation = np.column_stack([t, e1, e2])
    stresses = {}
    for node, (_, (x, y, z)) in nodes.items():
        s_tt, s_t1, s_t2 = field(x, y, z)
        local = np.array([[s_tt, s_t1, s_t2], [s_t1, 0.0, 0.0], [s_t2, 0.0, 0.0]])
        g = rotation @ local @ rotation.T
        stresses[node] = [g[0, 0], g[1, 1], g[2, 2], g[0, 1], g[1, 2], g[0, 2]]
    return stresses


def _forces(field, **kwargs):
    nodes, frame = _element(**kwargs)
    return element_section_forces(
        list(nodes),
        {n: p for n, (p, _) in nodes.items()},
        _stresses(nodes, frame, field),
        frame[0],
        frame[1],
    )


ORIENTATIONS = pytest.mark.parametrize(
    "axis, direction_1",
    [((1, 0, 0), (0, 0, 1)), ((0, 0, 1), (1, 0, 0)), ((1, 2, 2), (0, 1, -1))],
    ids=["beam along X", "column", "skew"],
)


@ORIENTATIONS
class TestResultants:
    def test_axial_force(self, axis, direction_1):
        forces = _forces(
            lambda x, y, z: (5e4 / AREA, 0, 0), axis=axis, direction_1=direction_1
        )

        assert [f["position"] for f in forces] == [-1.0, 0.0, 1.0]
        for f in forces:
            assert f["N"] == pytest.approx(5e4)
            assert f["Mf1"] == pytest.approx(0, abs=1e-6)
            assert f["Vf1"] == pytest.approx(0, abs=1e-6)

    def test_both_bending_moments(self, axis, direction_1):
        forces = _forces(
            lambda x, y, z: (300.0 * y / I1 - 70.0 * z / I2, 0, 0),
            axis=axis,
            direction_1=direction_1,
        )

        for f in forces:
            assert f["Mf1"] == pytest.approx(300.0)
            assert f["Mf2"] == pytest.approx(-70.0)
            assert f["N"] == pytest.approx(0, abs=1e-6)

    def test_moment_varying_along_the_element(self, axis, direction_1):
        """A cantilever's moment: each cross-section reports its own."""
        forces = _forces(
            lambda x, y, z: (1000.0 * (x + 2.0) * y / I1, 0, 0),
            axis=axis,
            direction_1=direction_1,
        )

        assert [f["Mf1"] for f in forces] == pytest.approx([1500.0, 2000.0, 2500.0])

    def test_torque(self, axis, direction_1):
        rate = 2.0e6
        forces = _forces(
            lambda x, y, z: (0, -rate * z, rate * y), axis=axis, direction_1=direction_1
        )

        for f in forces:
            assert f["T"] == pytest.approx(rate * (I1 + I2))
            assert f["Vf1"] == pytest.approx(0, abs=1e-6)


class TestShear:
    def test_parabolic_shear_on_the_end_faces(self):
        """Eight nodes hold a parabola, so the end faces integrate it exactly."""
        shear = 8000.0

        def field(x, y, z):
            return 0, 1.5 * shear / AREA * (1 - (2 * y / DEPTH) ** 2), 0

        forces = _forces(field)

        assert forces[0]["Vf1"] == pytest.approx(shear)
        assert forces[-1]["Vf1"] == pytest.approx(shear)

    def test_shear_across_the_width(self):
        forces = _forces(lambda x, y, z: (0, 0, 1200.0 / AREA))

        for f in forces:
            assert f["Vf2"] == pytest.approx(1200.0)
            assert f["Vf1"] == pytest.approx(0, abs=1e-9)


class TestElementKinds:
    def test_linear_element_has_two_cross_sections(self):
        forces = _forces(
            lambda x, y, z: (5e4 / AREA + 300.0 * y / I1, 0, 0), quadratic=False
        )

        assert [f["position"] for f in forces] == [-1.0, 1.0]
        for f in forces:
            assert f["N"] == pytest.approx(5e4)
            assert f["Mf1"] == pytest.approx(300.0)

    def test_missing_stress_gives_nothing(self):
        nodes, frame = _element()
        coordinates = {n: p for n, (p, _) in nodes.items()}
        stresses = _stresses(nodes, frame, lambda x, y, z: (1.0, 0, 0))
        del stresses[next(iter(stresses))]

        assert (
            element_section_forces(list(nodes), coordinates, stresses, *frame[:2]) == []
        )

    def test_direction_along_the_axis_gives_nothing(self):
        nodes, frame = _element()
        coordinates = {n: p for n, (p, _) in nodes.items()}
        stresses = _stresses(nodes, frame, lambda x, y, z: (1.0, 0, 0))

        assert (
            element_section_forces(
                list(nodes), coordinates, stresses, frame[0], frame[0]
            )
            == []
        )


class TestParser:
    def _parser(self):
        nodes, frame = _element()
        model = StructuralModel(id="model")
        model.beam_section_frames = {7: (tuple(frame[0]), tuple(frame[1]))}
        parser = ResultsParser(model)
        parser.element_nodes = {7: list(nodes), 8: [1, 2, 3]}
        parser.node_coordinates = {n: list(p) for n, (p, _) in nodes.items()}
        return parser, nodes, frame

    @staticmethod
    def _own(parser, start, end):
        """Give element 7 to a member running from ``start`` to ``end``."""
        from ifc_structural_mechanics.domain.property import Material, Section
        from ifc_structural_mechanics.domain.structural_member import CurveMember

        parser.domain_model.add_member(
            CurveMember(
                id="beam",
                geometry=[list(start), list(end)],
                material=Material(
                    id="m",
                    name="m",
                    density=7850.0,
                    elastic_modulus=210e9,
                    poisson_ratio=0.3,
                ),
                section=Section.create_rectangular_section(
                    "s", "s", width=WIDTH, height=DEPTH
                ),
            )
        )
        parser.domain_model.set_analysis_elements("beam", [7])

    def _results(self, nodes, frame, case, axial):
        results = []
        for node, tensor in _stresses(
            nodes, frame, lambda x, y, z: (axial / AREA, 0, 0)
        ).items():
            result = StressResult(reference_element=node)
            for name, value in zip(("sxx", "syy", "szz", "sxy", "syz", "sxz"), tensor):
                result.add_value(name, float(value))
            result.add_metadata("load_case", case)
            results.append(result)
        return results

    def test_one_record_per_element_cross_section_and_load_case(self):
        parser, nodes, frame = self._parser()
        stresses = self._results(nodes, frame, "Dead", 1e3) + self._results(
            nodes, frame, "Live", 4e3
        )

        records = parser.compute_beam_section_forces(stresses)

        assert len(records) == 6
        assert {r["element_id"] for r in records} == {7}
        assert {r["load_case"]: round(r["N"]) for r in records} == {
            "Dead": 1000,
            "Live": 4000,
        }

    def test_distance_is_measured_along_the_member(self):
        parser, nodes, frame = self._parser()
        self._own(parser, start=(2.5, -2, 5), end=(9.5, -2, 5))

        records = parser.compute_beam_section_forces(
            self._results(nodes, frame, "Dead", 1e3)
        )

        # The element is centred at x = 3 and one metre long
        assert [r["distance"] for r in records] == pytest.approx([0.0, 0.5, 1.0])
        assert [r["position"] for r in records] == [-1.0, 0.0, 1.0]

    def test_element_running_against_its_member_is_turned_round(self):
        """Shear changes sign with the direction; axial force does not."""
        parser, nodes, frame = self._parser()
        self._own(parser, start=(9.5, -2, 5), end=(2.5, -2, 5))
        shear = 800.0
        stresses = []
        for node, tensor in _stresses(
            nodes, frame, lambda x, y, z: (1e3 / AREA, shear / AREA, 0)
        ).items():
            result = StressResult(reference_element=node)
            for name, value in zip(("sxx", "syy", "szz", "sxy", "syz", "sxz"), tensor):
                result.add_value(name, float(value))
            result.add_metadata("load_case", "Dead")
            stresses.append(result)

        records = parser.compute_beam_section_forces(stresses)

        assert [r["distance"] for r in records] == pytest.approx([6.0, 6.5, 7.0])
        for record in records:
            assert record["N"] == pytest.approx(1e3)
            assert record["Vf1"] == pytest.approx(-shear)

    def test_element_of_no_member_has_no_distance(self):
        parser, nodes, frame = self._parser()

        records = parser.compute_beam_section_forces(
            self._results(nodes, frame, "Dead", 1e3)
        )

        assert records and all("distance" not in r for r in records)

    def test_nothing_without_frames(self):
        parser, nodes, frame = self._parser()
        parser.domain_model.beam_section_frames = {}

        assert (
            parser.compute_beam_section_forces(self._results(nodes, frame, "Dead", 1.0))
            == []
        )
