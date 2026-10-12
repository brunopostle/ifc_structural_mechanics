"""Distributed loads become nodal forces in their own global direction."""

import io

import numpy as np
import pytest

from ifc_structural_mechanics.analysis.boundary_condition_handling import (
    _distributed_load_to_nodal_forces,
    _global_force_vector,
    _load_to_nodal_moments,
    _point_load_lines,
    _varying_line_load_to_nodal_forces,
    _write_validated_loads_within_step,
)
from ifc_structural_mechanics.analysis.results_parser import ResultsParser
from ifc_structural_mechanics.domain.load import (
    AreaLoad,
    LineLoad,
    LoadGroup,
    PointLoad,
)
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.export.results_exporter import ResultsExporter
from ifc_structural_mechanics.utils.error_handling import AnalysisError

NODES = {
    1: (0.0, 0.0, 0.0),
    2: (2.0, 0.0, 0.0),
    3: (1.0, 0.0, 0.0),
    4: (2.0, 2.0, 0.0),
    5: (0.0, 2.0, 0.0),
    6: (2.0, 1.0, 0.0),
    7: (1.0, 2.0, 0.0),
    8: (0.0, 1.0, 0.0),
    9: (1.0, 1.0, 0.0),
}


def _forces(element, vector=(0.0, 0.0, -10.0)):
    return _distributed_load_to_nodal_forces(
        "SET", vector, {"SET": [1]}, {1: element}, NODES
    )


def _total(cloads):
    return np.sum(list(cloads.values()), axis=0)


class TestNodalShares:
    """Work-equivalent nodal forces for a uniform load, per element type."""

    def test_two_node_beam(self):
        cloads = _forces({"type": "B31", "nodes": [1, 2]})
        assert cloads == {1: [0.0, 0.0, -10.0], 2: [0.0, 0.0, -10.0]}

    def test_three_node_beam_puts_two_thirds_on_the_middle(self):
        cloads = _forces({"type": "B32R", "nodes": [1, 3, 2]})
        assert cloads[3][2] == pytest.approx(-20.0 * 2 / 3)
        assert cloads[1][2] == pytest.approx(-20.0 / 6)
        assert _total(cloads)[2] == pytest.approx(-20.0)

    def test_linear_triangle(self):
        cloads = _forces({"type": "S3", "nodes": [1, 2, 4]})
        assert all(f[2] == pytest.approx(-20.0 / 3) for f in cloads.values())

    def test_quadratic_triangle_loads_only_its_mid_side_nodes(self):
        cloads = _forces({"type": "S6", "nodes": [1, 2, 4, 3, 6, 9]})
        assert sorted(cloads) == [3, 6, 9]
        assert _total(cloads)[2] == pytest.approx(-20.0)  # area 2 m2

    def test_quadratic_quadrilateral_pulls_back_at_its_corners(self):
        cloads = _forces({"type": "S8", "nodes": [1, 2, 4, 5, 3, 6, 7, 8]})
        assert cloads[1][2] == pytest.approx(40.0 / 12)
        assert cloads[3][2] == pytest.approx(-40.0 / 3)
        assert _total(cloads)[2] == pytest.approx(-40.0)  # area 4 m2

    def test_direction_is_kept(self):
        cloads = _forces({"type": "B31", "nodes": [1, 2]}, vector=(0.0, 3.0, 0.0))
        assert _total(cloads) == pytest.approx([0.0, 6.0, 0.0])

    def test_zero_load_writes_nothing(self):
        assert _forces({"type": "B31", "nodes": [1, 2]}, vector=(0, 0, 0)) == {}


# A 2 m beam along X: one quadratic element, or two linear ones
QUADRATIC = {1: {"type": "B32R", "nodes": [1, 3, 2]}}
LINEAR = {1: {"type": "B31", "nodes": [1, 3]}, 2: {"type": "B31", "nodes": [3, 2]}}
DOWN = np.array([0.0, 0.0, -1.0])


def _varying(samples, elements=None, start=(0.0, 0.0, 0.0), end=(2.0, 0.0, 0.0)):
    elements = elements or QUADRATIC
    return _varying_line_load_to_nodal_forces(
        "SET",
        [(at, value * DOWN) for at, value in samples],
        start,
        end,
        {"SET": list(elements)},
        elements,
        NODES,
    )


def _moment_about_the_start(cloads):
    return sum(NODES[node][0] * force[2] for node, force in cloads.items())


class TestLoadThatVariesAlongItsMember:
    """Nodal forces of a load given by samples: linear between, none outside."""

    def test_constant_samples_are_the_uniform_load(self):
        for elements in (QUADRATIC, LINEAR):
            varying = _varying([(0.0, 10.0), (2.0, 10.0)], elements)
            uniform = _distributed_load_to_nodal_forces(
                "SET", 10.0 * DOWN, {"SET": list(elements)}, elements, NODES
            )
            assert varying.keys() == uniform.keys()
            for node in uniform:
                assert varying[node] == pytest.approx(uniform[node])

    def test_triangular_load_on_a_quadratic_element(self):
        """0 to 30 N/m over 2 m: nothing at the start, 20 and 10 N further on."""
        cloads = _varying([(0.0, 0.0), (2.0, 30.0)])
        assert 1 not in cloads
        assert cloads[3][2] == pytest.approx(-20.0)
        assert cloads[2][2] == pytest.approx(-10.0)

    def test_triangular_load_on_linear_elements(self):
        """Its total, and its moment: the resultant is two thirds along."""
        cloads = _varying([(0.0, 0.0), (2.0, 30.0)], LINEAR)
        assert _total(cloads)[2] == pytest.approx(-30.0)
        assert _moment_about_the_start(cloads) == pytest.approx(-30.0 * 4 / 3)

    @pytest.mark.parametrize("elements", [QUADRATIC, LINEAR])
    def test_load_on_part_of_the_member_starting_inside_an_element(self, elements):
        """10 N/m from 0.5 to 1.7 m: 12 N, acting at 1.1 m."""
        cloads = _varying([(0.5, 10.0), (1.7, 10.0)], elements)
        assert _total(cloads)[2] == pytest.approx(-12.0)
        assert _moment_about_the_start(cloads) == pytest.approx(-12.0 * 1.1)

    def test_stretches_with_a_step_between_them(self):
        """Two samples at one place: 10 N/m up to 1 m, 40 N/m after it."""
        cloads = _varying([(0.0, 10.0), (1.0, 10.0), (1.0, 40.0), (2.0, 40.0)], LINEAR)
        assert cloads[1][2] == pytest.approx(-5.0)
        assert cloads[3][2] == pytest.approx(-25.0)
        assert cloads[2][2] == pytest.approx(-20.0)

    def test_locations_are_measured_from_the_start_of_the_load_line(self):
        """Whichever way the elements happen to run."""
        reversed_elements = {1: {"type": "B32R", "nodes": [2, 3, 1]}}
        cloads = _varying([(0.0, 0.0), (2.0, 30.0)], reversed_elements)
        assert cloads[2][2] == pytest.approx(-10.0)
        cloads = _varying(
            [(0.0, 0.0), (2.0, 30.0)], start=(2.0, 0.0, 0.0), end=(0.0, 0.0, 0.0)
        )
        assert cloads[1][2] == pytest.approx(-10.0)
        assert 2 not in cloads

    def test_direction_may_change_along_the_member(self):
        cloads = _varying_line_load_to_nodal_forces(
            "SET",
            [(0.0, np.array([6.0, 0.0, 0.0])), (2.0, np.array([0.0, 0.0, -6.0]))],
            (0.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            {"SET": [1]},
            QUADRATIC,
            NODES,
        )
        assert _total(cloads) == pytest.approx([6.0, 0.0, -6.0])


def _beam_model(load):
    """A beam along X whose section 1 axis is vertical, so local 2 is horizontal."""
    model = StructuralModel(id="model")
    beam = CurveMember(
        id="beam",
        geometry=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        material=Material(
            id="steel",
            name="Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
        ),
        section=Section.create_rectangular_section(
            id="sec", name="sec", width=0.2, height=0.3
        ),
    )
    beam.local_axis = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    model.add_member(beam)
    load.member_reference = "beam"
    group = LoadGroup(id="g", name="Live")
    group.add_load(load)
    model.load_groups.append(group)
    return model


def _line_load(vector):
    return LineLoad(
        id="q",
        magnitude=np.array(vector, dtype=float),
        direction=np.array(vector, dtype=float),
        start_position=(0.0, 0.0, 0.0),
        end_position=(2.0, 0.0, 0.0),
    )


def _written(model):
    out = io.StringIO()
    _write_validated_loads_within_step(
        out,
        model,
        short_id_map={"beam": "M1"},
        element_sets={"MEMBER_M1": [1]},
        node_coords=NODES,
        elements_data={1: {"type": "B32R", "nodes": [1, 3, 2]}},
    )
    return out.getvalue()


class TestStepWriter:
    def test_vertical_line_load_is_written_as_vertical_nodal_forces(self):
        """Not as *DLOAD P2, which acts along the beam's local 2 axis."""
        text = _written(_beam_model(_line_load((0.0, 0.0, -1000.0))))

        assert "P2" not in text
        cload = text.split("*CLOAD\n")[1].strip().splitlines()
        assert [line.split(", ")[:2] for line in cload] == [
            ["1", "3"],
            ["2", "3"],
            ["3", "3"],
        ]
        assert sum(float(line.split(", ")[2]) for line in cload) == pytest.approx(
            -2000.0
        )

    def test_load_in_member_axes_is_rotated(self):
        load = _line_load((0.0, 0.0, -1000.0))
        load.coordinate_system = "local"
        model = _beam_model(load)
        # Member rolled a quarter turn: its local z points along global Y
        model.get_member("beam").local_axis = (
            (1.0, 0.0, 0.0),
            (0.0, 0.0, -1.0),
            (0.0, 1.0, 0.0),
        )
        assert _global_force_vector(load, model) == pytest.approx([0.0, -1000.0, 0.0])

    def test_global_load_ignores_member_axes(self):
        load = _line_load((0.0, 0.0, -1000.0))
        assert _global_force_vector(load, _beam_model(load)) == pytest.approx(
            [0.0, 0.0, -1000.0]
        )

    def test_load_with_samples_is_written_from_them(self):
        load = _line_load((0.0, 0.0, -500.0))
        load.samples = [(1.0, np.array([0.0, 0.0, -1000.0]))] * 2
        load.samples[1] = (2.0, np.array([0.0, 0.0, -1000.0]))
        text = _written(_beam_model(load))

        cload = text.split("*CLOAD\n")[1].strip().splitlines()
        assert sum(float(line.split(", ")[2]) for line in cload) == pytest.approx(
            -1000.0
        )

    def test_samples_in_member_axes_are_rotated(self):
        load = _line_load((0.0, 0.0, -500.0))
        load.samples = [
            (0.0, np.array([0.0, 0.0, 0.0])),
            (2.0, np.array([0.0, 0.0, -1000.0])),
        ]
        load.coordinate_system = "local"
        model = _beam_model(load)
        model.get_member("beam").local_axis = (
            (1.0, 0.0, 0.0),
            (0.0, 0.0, -1.0),
            (0.0, 1.0, 0.0),
        )
        cload = _written(model).split("*CLOAD\n")[1].strip().splitlines()
        assert {line.split(", ")[1] for line in cload} == {"2"}
        assert sum(float(line.split(", ")[2]) for line in cload) == pytest.approx(
            -1000.0
        )

    def test_area_load_goes_through_the_same_path(self):
        load = AreaLoad(
            id="p",
            magnitude=np.array([0.0, 0.0, -500.0]),
            direction=np.array([0.0, 0.0, -1.0]),
            surface_reference="beam",
        )
        model = _beam_model(_line_load((0.0, 0.0, -1.0)))
        model.load_groups[0].loads[:] = [load]
        out = io.StringIO()
        _write_validated_loads_within_step(
            out,
            model,
            short_id_map={"beam": "M1"},
            element_sets={"MEMBER_M1": [1]},
            node_coords=NODES,
            elements_data={1: {"type": "S3", "nodes": [1, 2, 4]}},
        )
        text = out.getvalue()
        assert ", P," not in text
        cload = text.split("*CLOAD\n")[1].strip().splitlines()
        assert sum(float(line.split(", ")[2]) for line in cload) == pytest.approx(
            -1000.0
        )


DAT = """
                        S T E P       1

 total force (fx,fy,fz) for set ALL_BC_NODES and time  0.1000000E+01

       -2.097383E-05  4.207686E-05  3.001662E+07

                        S T E P       2

 total force (fx,fy,fz) for set ALL_BC_NODES and time  0.2000000E+01

        3.203054E-05 -9.716333E-06  6.028327E+07
"""


class TestAppliedMoments:
    """A moment goes on rotations 4 to 6 of the nodes of a curve member."""

    BEAM = {1: {"type": "B32R", "nodes": [1, 3, 2]}}
    SLAB = {2: {"type": "S6", "nodes": [1, 2, 4, 3, 6, 9]}}

    def _point(self, position, moment, force=(0.0, 0.0, 0.0)):
        load = PointLoad("p", list(force), [0.0, 0.0, -1.0], list(position))
        load.moment = np.array(moment, dtype=float)
        return load

    def test_point_moment_is_written_beside_its_force(self):
        load = self._point((2.0, 0.0, 0.0), (0.0, 250.0, -40.0), (0.0, 0.0, -10.0))
        lines = _point_load_lines(load, NODES, StructuralModel(id="m"), self.BEAM)
        assert lines == [
            "2, 3, -1.000000e+01\n",
            "2, 5, 2.500000e+02\n",
            "2, 6, -4.000000e+01\n",
        ]

    def test_point_moment_on_a_surface_member_is_an_error(self):
        """A node of shells alone has no rotation about their normal."""
        load = self._point((2.0, 2.0, 0.0), (0.0, 250.0, 0.0))
        elements = {**self.BEAM, **self.SLAB}
        with pytest.raises(AnalysisError, match="p applies a moment where there is"):
            _point_load_lines(load, NODES, StructuralModel(id="m"), elements)

    def test_moment_per_length_is_shared_out_as_a_force_is(self):
        load = _line_load((0.0, 0.0, 0.0))
        load.moment = np.array([30.0, 0.0, 0.0])
        model = _beam_model(load)
        moments = _load_to_nodal_moments(
            load, "SET", model, {"SET": [1]}, self.BEAM, NODES
        )
        assert moments[3] == pytest.approx([40.0, 0.0, 0.0])
        assert moments[1] == pytest.approx([10.0, 0.0, 0.0])
        text = _written(model)
        assert "** Distributed moments (equivalent nodal moments)" in text
        assert "3, 4, 4.000000e+01" in text

    def test_moment_per_length_in_member_axes_is_rotated(self):
        load = _line_load((0.0, 0.0, 0.0))
        load.moment = np.array([0.0, 0.0, 30.0])
        load.coordinate_system = "local"
        model = _beam_model(load)
        model.get_member("beam").local_axis = (
            (1.0, 0.0, 0.0),
            (0.0, 0.0, -1.0),
            (0.0, 1.0, 0.0),
        )
        moments = _load_to_nodal_moments(
            load, "SET", model, {"SET": [1]}, self.BEAM, NODES
        )
        assert _total(moments) == pytest.approx([0.0, 60.0, 0.0])

    def test_load_without_a_moment_writes_none(self):
        load = _line_load((0.0, 0.0, -1000.0))
        assert "Distributed moments" not in _written(_beam_model(load))


class TestReactionsPerLoadCase:
    def _totals(self, names):
        parser = ResultsParser(StructuralModel(id="m"), load_case_names=names)
        return parser._parse_total_reactions(DAT.splitlines())

    def test_one_total_per_step(self):
        totals = self._totals(["Live", "Extra_dead"])
        assert [t.metadata["load_case"] for t in totals] == ["Live", "Extra_dead"]
        assert [t.get_forces()[2] for t in totals] == [3.001662e07, 6.028327e07]

    def test_unnamed_steps_are_numbered(self):
        assert [t.metadata["load_case"] for t in self._totals(None)] == [
            "step_1",
            "step_2",
        ]

    def test_export_lists_each_case_and_no_common_total(self):
        totals = self._totals(["Live", "Extra_dead"])
        exporter = ResultsExporter(StructuralModel(id="m"), {"reaction": totals})
        reactions = exporter._global_reactions()
        assert reactions["by_load_case"]["Extra_dead"]["fz_N"] == 6.028327e07
        assert "total" not in reactions

    def test_single_case_keeps_its_total(self):
        totals = self._totals(["Live"])[:1]
        exporter = ResultsExporter(StructuralModel(id="m"), {"reaction": totals})
        reactions = exporter._global_reactions()
        assert reactions["total"] == reactions["by_load_case"]["Live"]
