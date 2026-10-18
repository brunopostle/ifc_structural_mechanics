"""Reading an analysis for drawing (vi9, aiz.102)."""

import os

import numpy as np
import pytest

from ifc_structural_mechanics.api.structural_analysis import analyze_ifc
from ifc_structural_mechanics.visualization.output_files import (
    VTK_LINE,
    VTK_QUADRATIC_EDGE,
    VTK_QUADRATIC_TRIANGLE,
    VTK_TRIANGLE,
    AnalysisOutput,
    InputMesh,
)

EXAMPLES = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "examples", "analysis-models"
)
BEAM_01 = os.path.join(EXAMPLES, "ifcFiles", "beam_01.ifc")
SLAB_01 = os.path.join(EXAMPLES, "ifcFiles", "slab_01.ifc")
CANTILEVER_01 = os.path.join(EXAMPLES, "ifcFiles", "cantilever_01.ifc")

INPUT = """** a hand-written input
*NODE
10, 0., 0., 0.
20, 2., 0., 0.
15, 1., 0., 0.
30, 0., 1., 0.
40, 1., 1., 0.
45, 1., 0.5, 0.
35, 0., 0.5, 0.
*ELEMENT, TYPE=B32R, ELSET=BEAMS
1, 10, 15, 20
*ELEMENT, TYPE=S6, ELSET=SHELLS
2, 10, 15, 40, 30,
45, 35
*ELEMENT, TYPE=B31, ELSET=LINK
3, 20, 40
*ELEMENT, TYPE=SPRING1, ELSET=SPRING
4, 30
** Member beam-guid
*ELSET, ELSET=MEMBER_M1
1
** Member slab-guid
*ELSET, ELSET=MEMBER_M2
2
*ELSET, ELSET=EALL
1, 2
*NSET, NSET=BC_support-guid
10, 30
*STEP
*STATIC
*CLOAD
20, 3, -100.
20, 3, -50.
15, 1, 10.
15, 5, 999.
*END STEP
*STEP
*STATIC
*CLOAD, OP=NEW
BC_support-guid, 2, 7.
*END STEP
"""


@pytest.fixture
def input_mesh(tmp_path):
    path = tmp_path / "analysis.inp"
    path.write_text(INPUT)
    return InputMesh(str(path))


class TestInputMesh:
    def test_nodes_in_the_order_of_their_numbers(self, input_mesh):
        assert list(input_mesh.node_ids) == [10, 15, 20, 30, 35, 40, 45]
        assert input_mesh.points[input_mesh.index(15)] == pytest.approx([1, 0, 0])

    def test_cells_in_vtk_order(self, input_mesh):
        """CalculiX lists a beam (start, middle, end), VTK (start, end, middle)."""
        assert input_mesh.elements[1] == (VTK_QUADRATIC_EDGE, [10, 20, 15])
        assert input_mesh.elements[2] == (
            VTK_QUADRATIC_TRIANGLE,
            [10, 15, 40, 30, 45, 35],
        )
        assert input_mesh.elements[3] == (VTK_LINE, [20, 40])
        assert 4 not in input_mesh.elements

    def test_members_by_the_comment_before_their_set(self, input_mesh):
        assert input_mesh.member_elements == {"beam-guid": [1], "slab-guid": [2]}
        assert input_mesh.node_sets["BC_support-guid"] == [10, 30]

    def test_nodal_forces_per_step(self, input_mesh):
        """Forces only, added up per node; a set name stands for its nodes."""
        first, second = input_mesh.step_loads
        assert first[20] == pytest.approx([0, 0, -150])
        assert first[15] == pytest.approx([10, 0, 0])
        assert sorted(second) == [10, 30]
        assert second[30] == pytest.approx([0, 7, 0])

    def test_element_with_no_cell_is_refused(self, tmp_path):
        path = tmp_path / "analysis.inp"
        path.write_text(INPUT.replace("TYPE=B31", "TYPE=C3D8"))
        with pytest.raises(ValueError, match="C3D8"):
            InputMesh(str(path))


def _analyse(path, directory, **kwargs) -> AnalysisOutput:
    result = analyze_ifc(ifc_path=path, output_dir=str(directory), **kwargs)
    assert result["status"] == "success", result.get("errors")
    return AnalysisOutput(str(directory))


@pytest.fixture(scope="module")
def beam_01(tmp_path_factory):
    return _analyse(BEAM_01, tmp_path_factory.mktemp("beam_01"), mesh_size=0.5)


def _drawn_nodes(output: AnalysisOutput) -> set:
    return {
        output.mesh.index(n)
        for elements in output.mesh.member_elements.values()
        for e in elements
        for n in output.mesh.elements[e][1]
    }


def _check_displacements(output: AnalysisOutput, case: str) -> None:
    """Every node drawn has results, and the largest movement is that of
    results.json, which reads it on the faces of the sections: a little
    more than on the axis."""
    assert _drawn_nodes(output) <= set(output._pairs[0])
    largest = float(np.linalg.norm(output.displacement(case), axis=1).max())
    expected = output.results["global_displacements"]["by_load_case"][case][
        "max_displacement_m"
    ]
    assert largest == pytest.approx(expected, rel=0.02)
    assert largest <= expected * (1 + 1e-6)


class TestElementTypes:
    def test_quadratic_beams(self, beam_01):
        cell_types = {
            beam_01.mesh.elements[e][0]
            for e in beam_01.mesh.member_elements[beam_01.members()[0]["id"]]
        }
        assert cell_types == {VTK_QUADRATIC_EDGE}
        _check_displacements(beam_01, "Dead")

    def test_linear_beams(self, tmp_path):
        output = _analyse(BEAM_01, tmp_path, mesh_size=0.5, element_order=1)
        assert {cell for cell, _ in output.mesh.elements.values()} == {VTK_LINE}
        _check_displacements(output, "Dead")

    @pytest.mark.parametrize(
        "order, cell", [(2, VTK_QUADRATIC_TRIANGLE), (1, VTK_TRIANGLE)]
    )
    def test_shells(self, tmp_path, order, cell):
        output = _analyse(
            SLAB_01, tmp_path, mesh_size=0.5, gravity=True, element_order=order
        )
        (member,) = output.members("surface")
        cells = {
            output.mesh.elements[e][0]
            for e in output.mesh.member_elements[member["id"]]
        }
        assert cells == {cell}
        _check_displacements(output, "Gravity")

    def test_user_elements(self, tmp_path):
        """U1 elements are not expanded: their nodes keep their numbers."""
        from tests.validation.test_pipeline_benchmarks import (
            _beam_01,
            _give_beam_01_an_i_profile,
        )

        model = _beam_01()
        _give_beam_01_an_i_profile(model)
        path = str(tmp_path / "i_beam.ifc")
        model.write(path)
        output = _analyse(
            path, tmp_path / "out", mesh_size=0.5, open_sections="user_element"
        )
        _check_displacements(output, "Dead")


class TestFields:
    def test_combination_is_its_cases_times_their_factors(self, beam_01):
        (name, factors), *_ = beam_01.load_combinations.items()
        expected = sum(f * beam_01.displacement(case) for case, f in factors.items())
        combined = beam_01.displacement(combination=name)
        assert combined == pytest.approx(expected)
        largest = float(np.linalg.norm(combined, axis=1).max())
        assert largest == pytest.approx(
            beam_01.results["global_displacements"]["by_load_combination"][name][
                "max_displacement_m"
            ],
            rel=0.02,
        )

    def test_von_mises_is_the_largest_over_the_section(self, beam_01):
        stress = beam_01.von_mises("Dead")
        assert stress.max() > 0
        assert set(np.nonzero(stress)[0]) <= set(beam_01._pairs[0])

    def test_applied_loads_and_self_weight(self, beam_01):
        loads = beam_01.applied_loads("Dead")
        total = np.sum(list(loads.values()), axis=0)
        assert total == pytest.approx([0, 0, -20000])
        assert beam_01.self_weight("Dead", None)

    def test_unknown_case_is_refused(self, beam_01):
        with pytest.raises(ValueError, match="Live"):
            beam_01.displacement("Live")
        with pytest.raises(ValueError, match="mode"):
            beam_01.displacement(mode=1)

    def test_diagrams_start_at_the_first_point_of_the_member(self, beam_01):
        (member,) = beam_01.members("curve")
        start = beam_01.member_start(member)
        assert start == pytest.approx([0.0, 4.0, 4.0])

    def test_supports_by_their_node_sets(self, beam_01):
        found = beam_01.support_nodes()
        assert len(found) == 2
        positions = sorted(
            tuple(beam_01.mesh.points[rows[0]]) for rows in found.values()
        )
        assert positions == [(0.0, 4.0, 4.0), (4.0, 4.0, 4.0)]


def test_mode_shapes(tmp_path):
    output = _analyse(
        CANTILEVER_01, tmp_path, mesh_size=0.5, analysis_type="modal", num_modes=3
    )
    assert len(output.modes) == 3
    first, second = output.displacement(mode=1), output.displacement(mode=2)
    assert np.abs(first).max() > 0
    assert not np.allclose(first, second)
    with pytest.raises(ValueError, match="No mode 4"):
        output.displacement(mode=4)


def test_missing_files_are_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="analysis.inp"):
        AnalysisOutput(str(tmp_path))


class TestPicture:
    """Drawn off screen; skipped where PyVista cannot render."""

    @pytest.fixture(autouse=True)
    def _can_render(self):
        pv = pytest.importorskip("pyvista")
        try:
            plotter = pv.Plotter(off_screen=True, window_size=[64, 64])
            plotter.screenshot()
            plotter.close()
        except Exception as error:  # noqa: BLE001 - any failure means no rendering
            pytest.skip(f"PyVista cannot render here: {error}")

    @pytest.mark.parametrize(
        "options",
        [
            {},
            {"field": "von_mises", "edges": True},
            {"field": "Mf1", "reactions": True, "loads": True},
            {"combination": "DCon1", "field": "Vf1"},
        ],
    )
    def test_writes_a_png(self, beam_01, tmp_path, options):
        from ifc_structural_mechanics.visualization.plot import plot

        path = str(tmp_path / "picture.png")
        assert (
            plot(beam_01.directory, screenshot=path, window_size=(400, 300), **options)
            == path
        )
        with open(path, "rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n"

    def test_command(self, beam_01, tmp_path):
        from click.testing import CliRunner

        from ifc_structural_mechanics.cli.commands import cli

        path = str(tmp_path / "picture.png")
        result = CliRunner().invoke(
            cli,
            [
                "plot",
                beam_01.directory,
                "--field",
                "Mf1",
                "--reactions",
                "--screenshot",
                path,
                "--size",
                "400x300",
            ],
        )
        assert result.exit_code == 0, result.output
        assert os.path.getsize(path) > 0

    def test_command_reports_a_case_it_does_not_have(self, beam_01):
        from click.testing import CliRunner

        from ifc_structural_mechanics.cli.commands import cli

        result = CliRunner().invoke(
            cli, ["plot", beam_01.directory, "--case", "Live", "--screenshot", "x.png"]
        )
        assert result.exit_code != 0
        assert "No load case 'Live'" in result.output
