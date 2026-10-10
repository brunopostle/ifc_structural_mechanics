"""Distributed loads become nodal forces in their own global direction."""

import io

import numpy as np
import pytest

from ifc_structural_mechanics.analysis.boundary_condition_handling import (
    _distributed_load_to_nodal_forces,
    _global_force_vector,
    _write_validated_loads_within_step,
)
from ifc_structural_mechanics.analysis.results_parser import ResultsParser
from ifc_structural_mechanics.domain.load import AreaLoad, LineLoad, LoadGroup
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.export.results_exporter import ResultsExporter

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
