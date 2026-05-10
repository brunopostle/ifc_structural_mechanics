"""
Validation tests: Euler column buckling benchmark against analytical solution.

Tier 1 (TestDirectCalculixBucklingValidation):
    Hand-crafted .inp file → CalculiX → parse eigenvalue → compare to π²EI/L².
    Isolates the solver + parser from the IFC extraction pipeline.

Benchmark problem:
    - Pinned-pinned column, L = 1.0 m, 10 B31 beam elements along x-axis
    - Square cross-section 0.1 × 0.1 m
    - E = 210 GPa, ν = 0.3
    - Unit axial compressive load P_ref = 1 N applied at free end (node 11, x=1)
    - Pinned BCs: node 1 fixed in DOF 1-3, node 11 fixed in DOF 2-3

Analytical solution (Euler, pinned-pinned, K=1):
    - I = bh³/12 = 8.333×10⁻⁶ m⁴
    - P_cr = π²EI / L² = π² × 210e9 × 8.333e-6 ≈ 1.728×10⁷ N
    - CalculiX first eigenvalue λ₁ should satisfy: P_cr = λ₁ × P_ref
      → λ₁ ≈ 1.728×10⁷ (when P_ref = 1 N)
"""

import math
import os
import shutil
import textwrap

import pytest

# Check if CalculiX is available
CCX_AVAILABLE = shutil.which("ccx") is not None

# Benchmark parameters
BEAM_LENGTH = 1.0          # m
YOUNG_MODULUS = 210e9      # Pa
POISSON_RATIO = 0.3
SECTION_WIDTH = 0.1        # m
SECTION_HEIGHT = 0.1       # m
PRELOAD = 1.0              # N (unit load so eigenvalue = critical load in N)

MOMENT_OF_INERTIA = SECTION_WIDTH * SECTION_HEIGHT**3 / 12  # 8.333e-6 m⁴
ANALYTICAL_PCR = math.pi**2 * YOUNG_MODULUS * MOMENT_OF_INERTIA / BEAM_LENGTH**2

TOLERANCE = 0.05  # 5% discretization error allowed


def _write_euler_column_inp(inp_path: str) -> None:
    """Write a CalculiX input file for the Euler column buckling benchmark.

    11 nodes along x-axis (0.0 to 1.0, spacing 0.1 m), 10 B31 elements.
    Pinned BCs at both ends; unit compressive load at free end.
    Two steps: static preload, then buckling extraction of 1 mode.
    """
    inp_content = textwrap.dedent(
        """\
        *HEADING
        Euler column buckling benchmark: pinned-pinned, 10 B31 elements
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
        *ELEMENT, TYPE=B31, ELSET=COLUMN
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
        *BEAM SECTION, ELSET=COLUMN, MATERIAL=STEEL, SECTION=RECT
        0.1, 0.1
        0.0, 0.0, 1.0
        *MATERIAL, NAME=STEEL
        *ELASTIC
        210.0E9, 0.3
        ** Pinned support at x=0: fix all translations, allow rotations
        *NSET, NSET=PIN_BASE
        1
        ** Pinned support at x=1: fix lateral translations only (allow x-movement for compression)
        *NSET, NSET=PIN_TOP
        11
        *NSET, NSET=LOADED
        11
        *BOUNDARY
        PIN_BASE, 1, 3, 0.0
        PIN_TOP, 2, 3, 0.0
        ** Step 1: apply unit compressive preload
        *STEP
        *STATIC
        *CLOAD
        LOADED, 1, -1.0
        *END STEP
        ** Step 2: extract first buckling mode
        *STEP
        *BUCKLE
        1
        *NODE FILE
        U
        *END STEP
    """
    )
    with open(inp_path, "w") as f:
        f.write(inp_content)


@pytest.mark.skipif(not CCX_AVAILABLE, reason="CalculiX (ccx) not installed")
class TestDirectCalculixBucklingValidation:
    """Tier 1: Direct CalculiX buckling solver validation bypassing IFC/Gmsh."""

    @pytest.fixture(autouse=True)
    def setup_and_run(self, tmp_path):
        """Write .inp, run CalculiX, parse results — shared across all tests."""
        from ifc_structural_mechanics.analysis.calculix_runner import CalculixRunner
        from ifc_structural_mechanics.analysis.results_parser import ResultsParser

        self.work_dir = tmp_path / "euler_column"
        self.work_dir.mkdir()
        inp_path = self.work_dir / "euler_column.inp"
        _write_euler_column_inp(str(inp_path))

        runner = CalculixRunner(
            input_file_path=str(inp_path),
            working_dir=str(self.work_dir),
        )
        self.result_files = runner.run_analysis()

        parser = ResultsParser()
        self.parsed = parser.parse_results(self.result_files)
        self.eigenvalues = self.parsed.get("buckling", [])

    def test_buckling_eigenvalue_parsed(self):
        """At least one eigenvalue should be extracted from the .dat file."""
        dat_path = self.result_files.get("dat") or self.result_files.get("data")
        assert self.eigenvalues, (
            f"No buckling eigenvalues found in result files: {self.result_files}. "
            f"Check that CalculiX wrote a .dat file and that *BUCKLE step completed."
        )

    def test_first_eigenvalue_matches_euler(self):
        """First buckling eigenvalue should match π²EI/L² within 5%.

        With a unit preload of 1 N, the eigenvalue λ₁ equals the critical
        load in Newtons. For a pinned-pinned Euler column: P_cr = π²EI/L².
        """
        assert self.eigenvalues, "No eigenvalues to check — see test_buckling_eigenvalue_parsed"

        # eigenvalues list contains (mode_number, value) tuples
        first_mode, first_eigenvalue = min(self.eigenvalues, key=lambda t: t[0])

        assert first_eigenvalue > 0, (
            f"First eigenvalue {first_eigenvalue} is non-positive — "
            f"the column may be in tension or the preload direction is wrong"
        )

        # With P_ref = 1 N, eigenvalue = P_cr in Newtons
        critical_load = first_eigenvalue * PRELOAD

        rel_error = abs(critical_load - ANALYTICAL_PCR) / ANALYTICAL_PCR
        assert rel_error < TOLERANCE, (
            f"First buckling load {critical_load:.4e} N deviates from Euler "
            f"analytical P_cr = {ANALYTICAL_PCR:.4e} N by {rel_error*100:.1f}% "
            f"(tolerance: {TOLERANCE*100:.0f}%)"
        )
