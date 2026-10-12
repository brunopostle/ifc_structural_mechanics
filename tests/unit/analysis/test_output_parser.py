"""What is read from CalculiX's own output (`aiz.66`)."""

import shutil
import textwrap

import pytest

from ifc_structural_mechanics.analysis.calculix_runner import CalculixRunner
from ifc_structural_mechanics.analysis.output_parser import (
    OutputParser,
    solver_warnings,
)

# As CalculiX 2.23 prints it, once in every step
NO_DENSITY = """
 STEP            {step}

 *WARNING in calinput: no density was assigned
          to material STEEL in a dynamic
          calculation or a calculation with
          centrifugal or gravitational loads
          or an incompressible CFD calculation

 Static analysis was selected
"""


class TestSolverWarnings:
    def test_output_without_warnings(self):
        assert solver_warnings("") == []
        assert solver_warnings(" Static analysis was selected\n\n Job finished\n") == []

    def test_a_warning_runs_to_the_next_blank_line(self):
        (warning,) = solver_warnings(NO_DENSITY.format(step=1))
        assert warning["severity"] == "warning"
        assert warning["message"] == (
            "CalculiX: *WARNING in calinput: no density was assigned to material "
            "STEEL in a dynamic calculation or a calculation with centrifugal or "
            "gravitational loads or an incompressible CFD calculation"
        )

    def test_a_warning_repeated_in_every_step_is_given_once(self):
        output = "".join(NO_DENSITY.format(step=step) for step in (1, 2, 3))
        (warning,) = solver_warnings(output)
        assert warning["message"].startswith("CalculiX (3 times): *WARNING in calinput")

    def test_warnings_that_differ_in_their_numbers_are_one_kind(self):
        output = "".join(
            f" *WARNING in gen3dnor: node {node} is strange\n\n" for node in (7, 12)
        )
        (warning,) = solver_warnings(output)
        assert "(2 times)" in warning["message"]
        assert "node 7 is strange" in warning["message"]

    def test_different_warnings_are_kept_apart(self):
        output = " *WARNING in a: one thing\n\n *WARNING in b: another\n"
        assert len(solver_warnings(output)) == 2

    def test_many_kinds_are_counted_not_listed(self):
        output = "".join(f" *WARNING in r{chr(97 + i)}: x\n\n" for i in range(14))
        warnings = solver_warnings(output)
        assert len(warnings) == 11
        assert "4 more kinds of warning" in warnings[-1]["message"]


class TestCheckConvergence:
    def test_finished(self):
        converged, _ = OutputParser().check_convergence(" Job finished\n")
        assert converged

    def test_failed(self):
        converged, reason = OutputParser().check_convergence(
            "*ERROR: NO CONVERGENCE IN ITERATION 10"
        )
        assert not converged
        assert "NO CONVERGENCE" in reason

    def test_nothing_to_go_by(self):
        converged, _ = OutputParser().check_convergence("Factoring the system")
        assert not converged


@pytest.mark.skipif(shutil.which("ccx") is None, reason="CalculiX not installed")
def test_a_real_warning_is_read_from_a_real_run(tmp_path):
    """Gravity on one bar makes CalculiX warn that the other has no density."""
    input_file = tmp_path / "bar.inp"
    input_file.write_text(
        textwrap.dedent(
            """\
            *NODE
            1, 0., 0., 0.
            2, 1., 0., 0.
            3, 2., 0., 0.
            4, 3., 0., 0.
            5, 4., 0., 0.
            *ELEMENT, TYPE=B32R, ELSET=HEAVY
            1, 1, 2, 3
            *ELEMENT, TYPE=B32R, ELSET=LIGHT
            2, 3, 4, 5
            *MATERIAL, NAME=STEEL
            *ELASTIC
            2.1e11, 0.3
            *DENSITY
            7850.
            *MATERIAL, NAME=NOTHING
            *ELASTIC
            2.1e11, 0.3
            *BEAM SECTION, ELSET=HEAVY, MATERIAL=STEEL, SECTION=RECT
            0.1, 0.1
            0., 0., 1.
            *BEAM SECTION, ELSET=LIGHT, MATERIAL=NOTHING, SECTION=RECT
            0.1, 0.1
            0., 0., 1.
            *BOUNDARY
            1, 1, 6
            *STEP
            *STATIC
            *DLOAD
            HEAVY, GRAV, 9.81, 0., 0., -1.
            *NODE FILE
            U
            *END STEP
            """
        )
    )
    runner = CalculixRunner(input_file_path=str(input_file), working_dir=str(tmp_path))
    assert runner.solver_output == ""
    runner.run_analysis()
    (warning,) = solver_warnings(runner.solver_output)
    assert "no density was assigned to material NOTHING" in warning["message"]
