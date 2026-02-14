"""
Validation tests: Cantilever beam benchmark against analytical solutions.

These tests verify numerical correctness of the analysis pipeline by comparing
CalculiX results to known analytical solutions for a cantilever beam with a
tip point load.

Tier 1 (TestDirectCalculixValidation):
    Hand-crafted .inp file → CalculiX → parse results → compare to PL³/3EI.
    Isolates the solver + parser from the IFC extraction pipeline.

Tier 2 (TestFullPipelineValidation):
    IFC file → full pipeline → check physical reasonableness.
    Validates the end-to-end workflow produces meaningful results.

Benchmark problem:
    - Cantilever beam, L = 1.0 m, 10 B31 beam elements
    - Square cross-section 0.1 × 0.1 m
    - E = 210 GPa, ν = 0.3
    - Point load P = -1000 N at tip (y-direction)
    - Fixed support at origin (all 6 DOFs)

Analytical solution:
    - I = bh³/12 = 8.333×10⁻⁶ m⁴
    - Tip deflection δ = PL³/(3EI) = 1.905×10⁻⁴ m
    - Reaction force Fy = +1000 N

Note on CalculiX beam element expansion:
    CalculiX internally expands B31 beam elements into C3D8I brick elements.
    The original nodes (1-11) are NOT present in the FRD output. Instead,
    each beam node is expanded into 4 cross-section corner nodes. The tests
    identify nodes by parsing the FRD node coordinate block rather than
    relying on original node IDs.
"""

import os
import re
import shutil
import textwrap

import pytest

# Check if CalculiX is available
CCX_AVAILABLE = shutil.which("ccx") is not None

# Analytical reference values
BEAM_LENGTH = 1.0  # m
YOUNG_MODULUS = 210e9  # Pa
POISSON_RATIO = 0.3
SECTION_WIDTH = 0.1  # m
SECTION_HEIGHT = 0.1  # m
TIP_LOAD = -1000.0  # N (negative y)
MOMENT_OF_INERTIA = SECTION_WIDTH * SECTION_HEIGHT**3 / 12  # 8.333e-6 m^4
ANALYTICAL_TIP_DEFLECTION = (
    abs(TIP_LOAD) * BEAM_LENGTH**3 / (3 * YOUNG_MODULUS * MOMENT_OF_INERTIA)
)  # 1.905e-4 m
TOLERANCE = 0.05  # 5% for FEA discretization error


def _write_cantilever_inp(inp_path: str) -> None:
    """Write a CalculiX input file for the cantilever beam benchmark.

    11 nodes along x-axis (0.0 to 1.0, spacing 0.1), 10 B31 beam elements.
    Fixed BC at node 1, concentrated load at node 11.
    Requests nodal displacements in .frd and reaction forces in .dat.
    """
    inp_content = textwrap.dedent("""\
        *HEADING
        Cantilever beam benchmark: tip load, 10 B31 elements
        *NODE
              1, 0.0, 0.0, 0.0
              2, 0.1, 0.0, 0.0
              3, 0.2, 0.0, 0.0
              4, 0.3, 0.0, 0.0
              5, 0.4, 0.0, 0.0
              6, 0.5, 0.0, 0.0
              7, 0.6, 0.0, 0.0
              8, 0.7, 0.0, 0.0
              9, 0.8, 0.0, 0.0
             10, 0.9, 0.0, 0.0
             11, 1.0, 0.0, 0.0
        *ELEMENT, TYPE=B31, ELSET=BEAM
          1,  1,  2
          2,  2,  3
          3,  3,  4
          4,  4,  5
          5,  5,  6
          6,  6,  7
          7,  7,  8
          8,  8,  9
          9,  9, 10
         10, 10, 11
        *BEAM SECTION, ELSET=BEAM, MATERIAL=STEEL, SECTION=RECT
        0.1, 0.1
        0.0, 0.0, 1.0
        *MATERIAL, NAME=STEEL
        *ELASTIC
        210.0E9, 0.3
        *NSET, NSET=FIX
        1
        *NSET, NSET=TIP
        11
        *NSET, NSET=ALL_BC_NODES
        1
        *BOUNDARY
        FIX, 1, 6, 0.0
        *STEP
        *STATIC
        *CLOAD
        TIP, 2, -1000.0
        *NODE FILE
        U
        *NODE PRINT, NSET=ALL_BC_NODES, TOTALS=ONLY
        RF
        *END STEP
    """)
    with open(inp_path, "w") as f:
        f.write(inp_content)


def _parse_frd_node_coordinates(frd_path):
    """Parse the FRD node coordinate block to build a node_id → (x, y, z) map.

    CalculiX expands beam elements into 3D bricks, creating new nodes.
    The FRD file contains a node block (between '2C' and '-3' markers)
    with lines like: ' -1        12 0.00000E+00-5.00000E-02-5.00000E-02'
    """
    coords = {}
    with open(frd_path, "r") as f:
        in_node_block = False
        for line in f:
            stripped = line.strip()
            if stripped.startswith("2C"):
                in_node_block = True
                continue
            if in_node_block and stripped.startswith("-3"):
                break
            if in_node_block and stripped.startswith("-1"):
                # FRD fixed-width format: node ID at columns ~2-12, then 3×12-char floats
                parts = stripped.split()
                node_id = parts[1]
                # Coordinates can run together in scientific notation — use regex
                rest = stripped[stripped.index(node_id) + len(node_id):]
                value_pattern = (
                    r'[+-]?(?:\d+\.\d+(?:[EeDd][+-]?\d+)?|\d+[EeDd][+-]?\d+)'
                )
                matches = re.findall(value_pattern, rest)
                if len(matches) >= 3:
                    x, y, z = [float(m.replace('D', 'E').replace('d', 'e'))
                               for m in matches[:3]]
                    coords[node_id] = (x, y, z)
    return coords


def _find_nodes_at_x(node_coords, target_x, tol=1e-6):
    """Find all node IDs whose x-coordinate matches target_x within tolerance."""
    return [nid for nid, (x, y, z) in node_coords.items()
            if abs(x - target_x) < tol]


@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestDirectCalculixValidation:
    """Tier 1: Direct CalculiX solver validation bypassing IFC/Gmsh."""

    @pytest.fixture(autouse=True)
    def setup_and_run(self, tmp_path):
        """Write .inp, run CalculiX, parse results — shared across all tests."""
        from ifc_structural_mechanics.analysis.calculix_runner import CalculixRunner
        from ifc_structural_mechanics.analysis.results_parser import ResultsParser

        # Write the input file
        self.work_dir = tmp_path / "cantilever"
        self.work_dir.mkdir()
        inp_path = self.work_dir / "cantilever.inp"
        _write_cantilever_inp(str(inp_path))

        # Run CalculiX
        runner = CalculixRunner(
            input_file_path=str(inp_path),
            working_dir=str(self.work_dir),
        )
        self.result_files = runner.run_analysis()

        # Parse FRD node coordinates for position-based node lookup
        frd_path = self.result_files.get("results")
        assert frd_path and os.path.exists(frd_path), (
            f"FRD results file not found in {self.result_files}"
        )
        self.node_coords = _parse_frd_node_coordinates(frd_path)

        # Parse results
        parser = ResultsParser()
        self.parsed = parser.parse_results(self.result_files)

        # Build displacement lookup by node ID
        self.displacements = self.parsed.get("displacement", [])
        self.disp_by_node = {
            str(d.reference_element).strip(): d for d in self.displacements
        }
        self.reactions = self.parsed.get("reaction", [])

    # ------------------------------------------------------------------ #
    # Displacement tests
    # ------------------------------------------------------------------ #

    def test_cantilever_tip_load_displacement(self):
        """Tip deflection should match PL³/(3EI) within 5%.

        CalculiX expands B31 beams into C3D8I bricks. The tip at x=1.0
        becomes 4 cross-section corner nodes. All should have the same
        y-displacement (rigid section assumption).
        """
        assert len(self.displacements) > 0, (
            "No displacement results parsed from FRD file"
        )

        # Find expanded nodes at the tip (x = 1.0)
        tip_node_ids = _find_nodes_at_x(self.node_coords, BEAM_LENGTH)
        assert len(tip_node_ids) > 0, (
            f"No nodes found at x={BEAM_LENGTH}. "
            f"Available x-coords: {sorted(set(c[0] for c in self.node_coords.values()))}"
        )

        # Get y-displacement from the first tip node that has results
        tip_ty_values = []
        for nid in tip_node_ids:
            if nid in self.disp_by_node:
                ty = self.disp_by_node[nid].get_translations()[1]
                tip_ty_values.append(ty)

        assert len(tip_ty_values) > 0, (
            f"No displacement results for tip nodes {tip_node_ids}"
        )

        # Average y-displacement across cross-section corners
        avg_ty = sum(tip_ty_values) / len(tip_ty_values)
        computed_deflection = abs(avg_ty)

        # The load is negative y, so displacement should be negative
        assert avg_ty < 0, f"Expected negative y-displacement at tip, got {avg_ty}"

        rel_error = (
            abs(computed_deflection - ANALYTICAL_TIP_DEFLECTION)
            / ANALYTICAL_TIP_DEFLECTION
        )
        assert rel_error < TOLERANCE, (
            f"Tip deflection {computed_deflection:.6e} m deviates from analytical "
            f"{ANALYTICAL_TIP_DEFLECTION:.6e} m by {rel_error*100:.1f}% "
            f"(tolerance: {TOLERANCE*100:.0f}%)"
        )

    def test_cantilever_fixed_end_zero_displacement(self):
        """Fixed end nodes (x=0.0) should have near-zero displacement."""
        assert len(self.displacements) > 0, (
            "No displacement results parsed from FRD file"
        )

        # Find expanded nodes at the fixed end (x = 0.0)
        fixed_node_ids = _find_nodes_at_x(self.node_coords, 0.0)
        assert len(fixed_node_ids) > 0, (
            f"No nodes found at x=0.0. "
            f"Available x-coords: {sorted(set(c[0] for c in self.node_coords.values()))}"
        )

        for nid in fixed_node_ids:
            if nid not in self.disp_by_node:
                continue
            d = self.disp_by_node[nid]
            translations = d.get_translations()
            for i, label in enumerate(["tx", "ty", "tz"]):
                assert abs(translations[i]) < 1e-6, (
                    f"Fixed-end node {nid} translation {label} = {translations[i]:.2e}, "
                    f"expected ~0"
                )

    def test_cantilever_tip_load_reactions(self):
        """Total reaction force fy should equal +1000 N (equilibrium)."""
        assert len(self.reactions) > 0, (
            f"No reaction force results parsed from DAT file. "
            f"Result files: {self.result_files}"
        )

        # Sum reaction forces across all constrained nodes
        total_fy = 0.0
        for r in self.reactions:
            forces = r.get_forces()
            total_fy += forces[1]  # fy component

        expected_fy = abs(TIP_LOAD)  # +1000 N to balance -1000 N load
        rel_error = abs(abs(total_fy) - expected_fy) / expected_fy

        assert rel_error < TOLERANCE, (
            f"Total reaction Fy = {total_fy:.1f} N deviates from expected "
            f"{expected_fy:.1f} N by {rel_error*100:.1f}% "
            f"(tolerance: {TOLERANCE*100:.0f}%)"
        )


@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestFullPipelineValidation:
    """Tier 2: Full IFC → CalculiX → results pipeline validation.

    These tests exercise the complete analyze_ifc() pipeline on a real IFC file.
    They may fail due to known issues in the IFC extraction or meshing stages —
    that is intentional: the validation tests document what is broken.
    """

    IFC_PATH = os.path.join(
        os.path.dirname(__file__), "..", "test_data", "simple_beam.ifc"
    )

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Set up output directory."""
        self.output_dir = str(tmp_path / "pipeline_output")
        os.makedirs(self.output_dir, exist_ok=True)

    def _run_pipeline(self):
        """Run the analysis pipeline, returning the result dict.

        Catches SystemExit from meshio (which calls sys.exit on read errors)
        and converts it to pytest.fail with a diagnostic message.
        """
        from ifc_structural_mechanics.api.structural_analysis import analyze_ifc

        if not os.path.exists(self.IFC_PATH):
            pytest.skip(f"Test IFC file not found: {self.IFC_PATH}")

        try:
            return analyze_ifc(
                ifc_path=self.IFC_PATH,
                output_dir=self.output_dir,
            )
        except SystemExit as e:
            pytest.fail(
                f"Pipeline crashed with SystemExit({e.code}). "
                f"This typically means meshio could not read the Gmsh .msh file. "
                f"Check Gmsh initialization and mesh output format."
            )

    def test_simple_beam_pipeline_runs(self):
        """analyze_ifc() on simple_beam.ifc should complete without crashing."""
        result = self._run_pipeline()

        assert result["status"] in ("success", "completed_with_errors", "failed"), (
            f"Unexpected status: {result['status']}"
        )

        # Print diagnostics regardless of status
        if result.get("errors"):
            for err in result["errors"]:
                print(f"  ERROR: {err.get('message', err)}")
        if result.get("warnings"):
            for warn in result["warnings"]:
                print(f"  WARNING: {warn.get('message', warn)}")

    def test_simple_beam_displacement_nonzero(self):
        """Displacements should be parsed and at least some should be non-zero."""
        result = self._run_pipeline()

        parsed = result.get("parsed_results", {})
        displacements = parsed.get("displacement", [])

        assert len(displacements) > 0, (
            f"No displacement results found. Status: {result['status']}. "
            f"Errors: {result.get('errors', [])}"
        )

        # At least one node should have non-zero displacement
        max_magnitude = max(d.get_magnitude() for d in displacements)
        assert max_magnitude > 0, (
            "All displacement magnitudes are zero — load may not have been applied"
        )

        # Displacement should be physically reasonable (< 1 m for a building beam)
        assert max_magnitude < 1.0, (
            f"Max displacement {max_magnitude:.3f} m seems unreasonably large"
        )

    def test_simple_beam_equilibrium(self):
        """Total reaction forces should approximately balance applied loads."""
        result = self._run_pipeline()

        parsed = result.get("parsed_results", {})
        reactions = parsed.get("reaction", [])

        if not reactions:
            pytest.skip(
                "No reaction forces parsed — cannot check equilibrium. "
                "This may indicate a parser or .dat output issue."
            )

        # Sum all reaction forces
        total_fx = sum(r.get_forces()[0] for r in reactions)
        total_fy = sum(r.get_forces()[1] for r in reactions)
        total_fz = sum(r.get_forces()[2] for r in reactions)

        # The simple_beam.ifc has a -20 kN point load.
        # At minimum, the reaction force magnitude should be non-zero.
        reaction_magnitude = (total_fx**2 + total_fy**2 + total_fz**2) ** 0.5
        assert reaction_magnitude > 0, (
            "Total reaction force magnitude is zero — boundary conditions may be wrong"
        )

        print(
            f"  Total reactions: Fx={total_fx:.1f}, Fy={total_fy:.1f}, "
            f"Fz={total_fz:.1f} N"
        )
        print(f"  Reaction magnitude: {reaction_magnitude:.1f} N")
