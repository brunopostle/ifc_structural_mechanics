"""What the input writer and the result parser keep for the reactions."""

import io

import numpy as np
import pytest

from ifc_structural_mechanics.analysis.boundary_condition_handling import (
    _StepLoadRecorder,
    _weight_on_nodes,
    write_analysis_steps,
    write_boundary_conditions,
)
from ifc_structural_mechanics.analysis.results_parser import ResultsParser
from ifc_structural_mechanics.domain.load import LoadGroup, PointLoad
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from tests.helpers import fixed_support

NODES = {1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0), 3: (2.0, 0.0, 0.0)}
ELEMENTS = {10: {"type": "B32R", "nodes": [1, 2, 3]}}
DENSITY, WIDTH, DEPTH = 2500.0, 0.2, 0.3


def _model():
    model = StructuralModel(id="model")
    model.add_member(
        CurveMember(
            id="beam",
            geometry=[[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
            material=Material(
                id="c",
                name="Concrete",
                density=DENSITY,
                elastic_modulus=30e9,
                poisson_ratio=0.2,
            ),
            section=Section.create_rectangular_section("s", "r", WIDTH, DEPTH),
        )
    )
    model.analysis_element_to_member = {10: "beam"}
    model.add_connection(fixed_support((0, 0, 0), "beam"))
    write_boundary_conditions(io.StringIO(), model, {}, {}, NODES)
    return model


class TestSupportNodes:
    def test_writer_records_what_each_support_restrains(self):
        model = _model()

        assert model.support_nodes == {
            "support": {"nodes": {1: (0.0, 0.0, 0.0)}, "dofs": [1, 2, 3, 4, 5, 6]}
        }

    def test_step_asks_for_the_force_on_each_support_node(self):
        model = _model()
        out = io.StringIO()

        write_analysis_steps(out, model, node_coords=NODES, elements_data=ELEMENTS)

        assert "*NODE PRINT, NSET=ALL_BC_NODES, TOTALS=YES\nRF\n" in out.getvalue()


class TestStepLoadRecorder:
    def test_everything_is_passed_on_unchanged(self):
        out = io.StringIO()
        recorder = _StepLoadRecorder(out)
        text = "*STEP\n*CLOAD\n4, 3, -1.5e+02\n*END STEP\n"

        for piece in (text[:9], text[9:20], text[20:]):
            recorder.write(piece)

        assert out.getvalue() == text
        assert recorder.steps == [{"nodal": {4: [0.0, 0.0, -150.0]}, "gravity": None}]

    def test_loads_on_one_node_add_up_and_steps_are_kept_apart(self):
        """CalculiX adds repeated *CLOAD lines on one node (measured)."""
        recorder = _StepLoadRecorder(io.StringIO())
        recorder.write(
            "*STEP\n*STATIC\n1.0, 1.0\n*CLOAD, OP=NEW\n*DLOAD, OP=NEW\n"
            "** Load Case: Dead\n*CLOAD\n4, 3, -100.\n4, 1, 7.\n*CLOAD\n4, 3, -50.\n"
            "*NODE FILE\nU\n*END STEP\n"
            "*STEP\n*STATIC\n*DLOAD\nEALL, GRAV, 9.81, 0.0, 0.0, -1.0\n*END STEP\n"
        )

        first, second = recorder.steps
        assert first == {"nodal": {4: [7.0, 0.0, -150.0]}, "gravity": None}
        assert second["nodal"] == {}
        assert list(second["gravity"]) == [0.0, 0.0, -9.81]

    def test_moments_are_not_forces(self):
        recorder = _StepLoadRecorder(io.StringIO())
        recorder.write("*STEP\n*CLOAD\n4, 5, 30.\n*END STEP\n")

        assert recorder.steps[0]["nodal"] == {}


class TestLoadsOnSupportNodes:
    def test_point_load_on_a_support_node_is_recorded_per_step(self):
        model = _model()
        down = [0.0, 0.0, -1.0]
        on_support = PointLoad("p1", 100.0, down, [0.0, 0.0, 0.0])
        elsewhere = PointLoad("p2", 40.0, down, [2.0, 0.0, 0.0])
        for name, load in (("Dead", on_support), ("Live", elsewhere)):
            group = LoadGroup(name, name=name)
            group.is_load_case = True
            group.add_load(load)
            model.add_load_group(group)

        write_analysis_steps(
            io.StringIO(), model, node_coords=NODES, elements_data=ELEMENTS
        )

        assert model.support_node_loads == [{1: [0.0, 0.0, -100.0]}, {}]

    def test_self_weight_reaching_a_support_node(self):
        """A sixth of the end element's weight on a quadratic beam.

        Measured on a cantilever: the solver's reaction is short by exactly
        this at any mesh size.
        """
        model = _model()

        write_analysis_steps(
            io.StringIO(),
            model,
            node_coords=NODES,
            elements_data=ELEMENTS,
            gravity=True,
        )

        (loads,) = model.support_node_loads
        weight = DENSITY * WIDTH * DEPTH * 9.81 * 2.0
        assert loads[1] == pytest.approx([0.0, 0.0, -weight / 6])

    def test_weight_shares_of_linear_and_quadratic_beams(self):
        model = _model()
        down = np.array([0.0, 0.0, -10.0])
        per_metre = DENSITY * WIDTH * DEPTH * 10.0

        quadratic = _weight_on_nodes(model, ELEMENTS, NODES, {1, 2}, down)
        linear = _weight_on_nodes(
            model, {10: {"type": "B31", "nodes": [1, 3]}}, NODES, {1, 2}, down
        )

        assert quadratic[1][2] == pytest.approx(-per_metre * 2.0 / 6)
        assert quadratic[2][2] == pytest.approx(-per_metre * 2.0 * 2 / 3)
        assert linear[1][2] == pytest.approx(-per_metre * 2.0 / 2)
        assert 2 not in linear

    def test_member_without_density_weighs_nothing(self):
        model = _model()
        model.get_member("beam").material.density = None

        assert _weight_on_nodes(model, ELEMENTS, NODES, {1}, np.ones(3)) == {}


class TestNodeForcesFromDat:
    DAT = """
                        S T E P       1


                                INCREMENT     1


 forces (fx,fy,fz) for set ALL_BC_NODES and time  0.1000000E+01

         1 -7.000000E+01  2.978173E-14 -2.198773E-13
         5  7.000000E+01  7.569246E-14  4.522154E+01

 total force (fx,fy,fz) for set ALL_BC_NODES and time  0.1000000E+01

        0.000000E+00  1.054742E-13  4.522154E+01

                        S T E P       2


 forces (fx,fy,fz) for set ALL_BC_NODES and time  0.2000000E+01

         1  0.000000E+00  0.000000E+00  1.000000E+01
         5  0.000000E+00  0.000000E+00  2.000000E+01

 total force (fx,fy,fz) for set ALL_BC_NODES and time  0.2000000E+01

        0.000000E+00  0.000000E+00  3.000000E+01
"""

    def _parse(self, tmp_path, names):
        path = tmp_path / "analysis.dat"
        path.write_text(self.DAT)
        return ResultsParser(load_case_names=names).parse_node_forces(str(path))

    def test_one_record_per_step_with_its_load_case(self, tmp_path):
        first, second = self._parse(tmp_path, ["Dead", "Live"])

        assert first["load_case"] == "Dead"
        assert first["forces"][1] == pytest.approx([-70.0, 0.0, 0.0], abs=1e-9)
        assert first["forces"][5] == pytest.approx([70.0, 0.0, 45.22154], abs=1e-9)
        assert second == {
            "load_case": "Live",
            "forces": {1: [0.0, 0.0, 10.0], 5: [0.0, 0.0, 20.0]},
        }

    def test_totals_are_not_taken_for_a_node(self, tmp_path):
        first, _ = self._parse(tmp_path, None)

        assert first["load_case"] == "step_1"
        assert set(first["forces"]) == {1, 5}

    def test_missing_file_has_no_forces(self, tmp_path):
        parser = ResultsParser()

        assert parser.parse_node_forces(str(tmp_path / "none.dat")) == []
