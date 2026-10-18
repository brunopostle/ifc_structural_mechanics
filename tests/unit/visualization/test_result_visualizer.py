"""Loading a CalculiX mesh and its results for drawing (aiz.102)."""

import json
import os

import numpy as np
import pytest

pv = pytest.importorskip("pyvista")

from ifc_structural_mechanics.analysis.results_parser import (  # noqa: E402
    ResultsParser,
)
from ifc_structural_mechanics.api.structural_analysis import (  # noqa: E402
    analyze_ifc,
)
from ifc_structural_mechanics.ifc.extractor import Extractor  # noqa: E402
from ifc_structural_mechanics.visualization.result_visualizer import (  # noqa: E402
    ResultVisualizer,
    read_calculix_mesh,
)

BEAM_01 = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "examples",
    "analysis-models",
    "ifcFiles",
    "beam_01.ifc",
)

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
*STEP
*STATIC
*END STEP
"""


class TestReadCalculixMesh:
    def test_nodes_in_the_order_of_their_numbers(self, tmp_path):
        path = tmp_path / "model.inp"
        path.write_text(INPUT)
        node_ids, points, _, _ = read_calculix_mesh(str(path))
        assert list(node_ids) == [10, 15, 20, 30, 35, 40, 45]
        assert points[1] == pytest.approx([1.0, 0.0, 0.0])

    def test_quadratic_beam_has_its_middle_node_last(self, tmp_path):
        """CalculiX lists (start, middle, end), VTK wants (start, end, middle)."""
        path = tmp_path / "model.inp"
        path.write_text(INPUT)
        node_ids, _, cells, elements = read_calculix_mesh(str(path))
        number = {i: int(n) for i, n in enumerate(node_ids)}
        (edge,) = cells[pv.CellType.QUADRATIC_EDGE]
        assert [number[i] for i in edge] == [10, 20, 15]
        (triangle,) = cells[pv.CellType.QUADRATIC_TRIANGLE]
        assert [number[i] for i in triangle] == [10, 15, 40, 30, 45, 35]
        (link,) = cells[pv.CellType.LINE]
        assert [number[i] for i in link] == [20, 40]
        assert sorted(elements) == [1, 2, 3]

    def test_element_with_no_cell_is_refused(self, tmp_path):
        path = tmp_path / "model.inp"
        path.write_text(INPUT.replace("TYPE=B31", "TYPE=C3D8"))
        with pytest.raises(ValueError, match="C3D8"):
            read_calculix_mesh(str(path))


def test_quadratic_beam_draws_with_its_deflection(tmp_path):
    """beam_01 as analysed by default, B32R: every node has its results, and
    the largest movement is that of results.json."""
    result = analyze_ifc(ifc_path=BEAM_01, output_dir=str(tmp_path))
    assert result["status"] == "success", result.get("errors")
    model = Extractor(BEAM_01).extract_model()
    parsed = ResultsParser(domain_model=model).parse_results(
        {"results": str(tmp_path / "analysis.frd")}
    )

    viz = ResultVisualizer(model)
    mesh = viz.load_mesh_from_frd(
        str(tmp_path / "analysis.frd"), str(tmp_path / "analysis.inp")
    )
    assert mesh.n_points == len(viz._inp_node_to_frd_node)
    displaced = viz.apply_displacement_field(
        displacement_results=parsed["displacement"]
    )

    with open(tmp_path / "results.json") as fh:
        envelope = json.load(fh)["global_displacements"]["envelope"]
    largest = float(np.max(displaced["Displacement (mm)"])) / 1000.0
    # On the axis, where results.json has the faces of the section
    assert largest == pytest.approx(envelope["max_displacement_m"], rel=0.01)
    assert largest <= envelope["max_displacement_m"]
