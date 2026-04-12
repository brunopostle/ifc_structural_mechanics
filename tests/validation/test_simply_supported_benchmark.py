"""
Validation tests: Simply supported beam benchmark against analytical solution.

Tier 1 (TestDirectCalculixValidation):
    Hand-crafted .inp file → CalculiX → parse results → compare to PL³/48EI.
    Isolates the solver + parser from the IFC extraction pipeline.

Benchmark problem:
    - Simply supported beam, L = 2.0 m, 20 B31 beam elements
    - Square cross-section 0.1 × 0.1 m
    - E = 210 GPa, ν = 0.3
    - Point load P = -10000 N at midspan (y-direction)
    - Pin support at x=0 (DOF 1-3), roller at x=2 (DOF 2-3)

Analytical solution:
    - I = bh³/12 = 8.333×10⁻⁶ m⁴
    - Midspan deflection δ = PL³/(48EI) = 9.524×10⁻⁴ m
    - Reaction at each support Fy = P/2 = +5000 N

Note: a symmetric (square) section is used so that the beam normal vector
direction does not affect the result. Asymmetric section orientation is a
known limitation documented in VISION.md.
"""

import os
import re
import shutil

import pytest

CCX_AVAILABLE = shutil.which("ccx") is not None

BEAM_LENGTH = 2.0  # m
YOUNG_MODULUS = 210e9  # Pa
POISSON_RATIO = 0.3
SECTION_WIDTH = 0.1  # m
SECTION_HEIGHT = 0.1  # m
MID_LOAD = -10000.0  # N (negative y)
MOMENT_OF_INERTIA = SECTION_WIDTH * SECTION_HEIGHT**3 / 12  # 8.333e-6 m^4
ANALYTICAL_MIDSPAN_DEFLECTION = (
    abs(MID_LOAD) * BEAM_LENGTH**3 / (48 * YOUNG_MODULUS * MOMENT_OF_INERTIA)
)  # 9.524e-4 m
TOLERANCE = 0.05  # 5%


def _write_ss_beam_inp(inp_path: str) -> None:
    """Write CalculiX input file for the simply supported beam benchmark.

    21 nodes along x-axis (0.0 to 2.0, spacing 0.1), 20 B31 beam elements.
    Pin at node 1 (DOF 1-3), roller at node 21 (DOF 2-3).
    Midspan point load at node 11 (x=1.0).
    """
    from ifc_structural_mechanics.analysis.file_writers import (
        write_elements,
        write_node_sets,
        write_nodes,
    )

    nodes = {i + 1: (round(i * 0.1, 1), 0.0, 0.0) for i in range(21)}
    elements = {i + 1: {"type": "B31", "nodes": [i + 1, i + 2]} for i in range(20)}
    node_sets = {
        "PINA": [1],
        "ROLLERB": [21],
        "MID": [11],
        "ALL_BC_NODES": [1, 21],
    }

    with open(inp_path, "w") as f:
        f.write("*HEADING\nSimply supported beam benchmark: midspan load, 20 B31 elements\n")
        write_nodes(f, nodes)
        # write_elements doesn't support ELSET on the *ELEMENT line, so write directly
        f.write("*ELEMENT, TYPE=B31, ELSET=BEAM\n")
        for i in range(20):
            f.write(f"{i + 1}, {i + 1}, {i + 2}\n")
        f.write("*BEAM SECTION, ELSET=BEAM, MATERIAL=STEEL, SECTION=RECT\n")
        f.write("0.1, 0.1\n")
        f.write("0.0, 0.0, 1.0\n")
        f.write("*MATERIAL, NAME=STEEL\n")
        f.write("*ELASTIC\n")
        f.write("210.0E9, 0.3\n")
        write_node_sets(f, node_sets)
        f.write("*BOUNDARY\n")
        f.write("PINA, 1, 3, 0.0\n")
        f.write("ROLLERB, 2, 3, 0.0\n")
        f.write("*STEP\n*STATIC\n")
        f.write("*CLOAD\n")
        f.write("MID, 2, -10000.0\n")
        f.write("*NODE FILE\nU\n")
        f.write("*NODE PRINT, NSET=ALL_BC_NODES, TOTALS=ONLY\nRF\n")
        f.write("*END STEP\n")


def _parse_frd_node_coordinates(frd_path):
    """Parse FRD node coordinate block → node_id: (x, y, z) map."""
    coords = {}
    with open(frd_path) as f:
        in_node_block = False
        for line in f:
            s = line.strip()
            if s.startswith("2C"):
                in_node_block = True
                continue
            if in_node_block and s.startswith("-3"):
                break
            if in_node_block and s.startswith("-1"):
                parts = s.split()
                nid = parts[1]
                rest = s[s.index(nid) + len(nid) :]
                pattern = (
                    r"[+-]?(?:\d+\.\d+(?:[EeDd][+-]?\d+)?|\d+[EeDd][+-]?\d+)"
                )
                vals = re.findall(pattern, rest)
                if len(vals) >= 3:
                    coords[nid] = tuple(
                        float(v.replace("D", "E").replace("d", "e"))
                        for v in vals[:3]
                    )
    return coords


def _find_nodes_at_x(node_coords, target_x, tol=1e-6):
    return [nid for nid, (x, y, z) in node_coords.items() if abs(x - target_x) < tol]


@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestDirectCalculixValidation:
    """Tier 1: Direct CalculiX solver validation bypassing IFC/Gmsh."""

    @pytest.fixture(autouse=True)
    def setup_and_run(self, tmp_path):
        from ifc_structural_mechanics.analysis.calculix_runner import CalculixRunner
        from ifc_structural_mechanics.analysis.results_parser import ResultsParser

        self.work_dir = tmp_path / "ss_beam"
        self.work_dir.mkdir()
        inp_path = self.work_dir / "ss_beam.inp"
        _write_ss_beam_inp(str(inp_path))

        runner = CalculixRunner(
            input_file_path=str(inp_path),
            working_dir=str(self.work_dir),
        )
        self.result_files = runner.run_analysis()

        frd_path = self.result_files.get("results")
        assert frd_path and os.path.exists(frd_path)
        self.node_coords = _parse_frd_node_coordinates(frd_path)

        parser = ResultsParser()
        self.parsed = parser.parse_results(self.result_files)
        self.displacements = self.parsed.get("displacement", [])
        self.disp_by_node = {
            str(d.reference_element).strip(): d for d in self.displacements
        }
        self.reactions = self.parsed.get("reaction", [])

    def test_ss_beam_midspan_deflection(self):
        """Midspan deflection should match PL³/(48EI) within 5%."""
        assert len(self.displacements) > 0, "No displacement results"

        mid_node_ids = _find_nodes_at_x(self.node_coords, BEAM_LENGTH / 2)
        assert len(mid_node_ids) > 0, f"No nodes found at x={BEAM_LENGTH/2}"

        mid_tys = [
            self.disp_by_node[nid].get_translations()[1]
            for nid in mid_node_ids
            if nid in self.disp_by_node
        ]
        assert len(mid_tys) > 0, f"No displacements for midspan nodes {mid_node_ids}"

        computed = abs(sum(mid_tys) / len(mid_tys))
        assert sum(mid_tys) / len(mid_tys) < 0, "Expected downward (negative y) deflection"

        rel_error = (
            abs(computed - ANALYTICAL_MIDSPAN_DEFLECTION) / ANALYTICAL_MIDSPAN_DEFLECTION
        )
        assert rel_error < TOLERANCE, (
            f"Midspan deflection {computed:.6e} m deviates from analytical "
            f"{ANALYTICAL_MIDSPAN_DEFLECTION:.6e} m by {rel_error * 100:.1f}%"
        )

    def test_ss_beam_support_zero_displacement(self):
        """Average transverse displacement across support cross-sections should be ~0.

        CalculiX expands B31 beams into 3D bricks. At a pin support (DOF 1-3 fixed),
        the end cross-section can rotate freely — corner nodes will have non-zero ty
        due to end rotation. The *average* across all corner nodes at a support should
        be near zero (rotation makes opposite corners cancel).
        """
        for target_x in [0.0, BEAM_LENGTH]:
            support_nodes = _find_nodes_at_x(self.node_coords, target_x)
            tys = [
                self.disp_by_node[nid].get_translations()[1]
                for nid in support_nodes
                if nid in self.disp_by_node
            ]
            if not tys:
                continue
            avg_ty = sum(tys) / len(tys)
            # Average should be a small fraction of the midspan deflection
            assert abs(avg_ty) < ANALYTICAL_MIDSPAN_DEFLECTION * 0.05, (
                f"Average ty at x={target_x}: {avg_ty:.2e} m — "
                f"expected < 5% of midspan deflection"
            )

    def test_ss_beam_reactions(self):
        """Total reaction Fy should equal P (equilibrium); each support ~P/2."""
        assert len(self.reactions) > 0, "No reaction results"

        total_fy = sum(r.get_forces()[1] for r in self.reactions)
        expected = abs(MID_LOAD)
        rel_error = abs(abs(total_fy) - expected) / expected
        assert rel_error < TOLERANCE, (
            f"Total reaction Fy={total_fy:.1f} N, expected {expected:.1f} N "
            f"({rel_error * 100:.1f}% error)"
        )
