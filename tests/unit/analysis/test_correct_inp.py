"""CalculixRunner solves the input file it is given, as written, once.

It used to swap ``analysis.inp`` for a ``model.inp`` lying beside it when that
was five times larger, insert a ``*HEADING`` into large inputs, and edit the
input and run again after some errors.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from ifc_structural_mechanics.analysis.calculix_runner import CalculixRunner
from ifc_structural_mechanics.utils.error_handling import AnalysisError

INPUT = "** analysis\n*NODE\n1, 0, 0, 0\n*STEP\n*STATIC\n*END STEP\n"
RUN = "ifc_structural_mechanics.analysis.calculix_runner.run_subprocess"


def _result(success=True, stdout="Job finished", stderr=""):
    result = MagicMock()
    result.success = success
    result.stdout = stdout
    result.stderr = stderr
    result.return_code = 0 if success else 201
    return result


@pytest.fixture
def system_config():
    config = MagicMock()
    config.get_calculix_path.return_value = "/usr/bin/ccx"
    return config


def _runner(directory, system_config, working_dir=None):
    path = os.path.join(str(directory), "analysis.inp")
    with open(path, "w") as f:
        f.write(INPUT)
    return CalculixRunner(
        input_file_path=path,
        system_config=system_config,
        working_dir=str(working_dir or directory),
    )


class TestInputFile:
    def test_the_given_input_is_run(self, tmp_path, system_config):
        runner = _runner(tmp_path, system_config)
        with patch(RUN, return_value=_result()) as run:
            runner.run_analysis()
        assert run.call_args[0][0] == ["/usr/bin/ccx", "-i", "analysis"]

    def test_a_larger_file_beside_it_is_not_run_instead(self, tmp_path, system_config):
        with open(tmp_path / "model.inp", "w") as f:
            f.write("** another model\n" + "*NODE\n" * 2000)
        runner = _runner(tmp_path, system_config)
        with patch(RUN, return_value=_result()) as run:
            runner.run_analysis()
        assert run.call_args[0][0] == ["/usr/bin/ccx", "-i", "analysis"]

    def test_the_input_is_not_edited(self, tmp_path, system_config):
        runner = _runner(tmp_path, system_config)
        big = INPUT + "*ELEMENT, TYPE=B31\n" * 1500
        with open(runner.input_file_path, "w") as f:
            f.write(big)
        with patch(RUN, return_value=_result()):
            runner.run_analysis()
        with open(runner.input_file_path) as f:
            assert f.read() == big
        assert not os.path.exists(str(runner.input_file_path) + ".original")

    def test_a_failed_run_is_not_repeated(self, tmp_path, system_config):
        runner = _runner(tmp_path, system_config)
        failure = _result(False, stdout="*ERROR reading *ELEMENT: increase ne_")
        with patch(RUN, return_value=failure) as run:
            with pytest.raises(AnalysisError, match="return code 201"):
                runner.run_analysis()
        assert run.call_count == 1
        with open(runner.input_file_path) as f:
            assert f.read() == INPUT

    def test_a_stale_input_in_the_working_directory_is_replaced(
        self, tmp_path, system_config
    ):
        """An earlier run's file of the same name must not be solved instead."""
        source, work = tmp_path / "source", tmp_path / "work"
        source.mkdir()
        work.mkdir()
        with open(work / "analysis.inp", "w") as f:
            f.write("** an earlier analysis\n")
        runner = _runner(source, system_config, working_dir=work)
        with patch(RUN, return_value=_result()):
            runner.run_analysis()
        with open(work / "analysis.inp") as f:
            assert f.read() == INPUT

    def test_missing_input_is_an_error(self, tmp_path, system_config):
        runner = _runner(tmp_path, system_config)
        os.remove(runner.input_file_path)
        with patch(RUN, return_value=_result()) as run:
            with pytest.raises(AnalysisError, match="Input file not found"):
                runner.run_analysis()
        run.assert_not_called()


class TestResultFiles:
    def test_only_this_run_s_files_are_collected(self, tmp_path, system_config):
        """Another analysis may have left its results in the directory."""
        runner = _runner(tmp_path, system_config)
        for name in ("analysis.frd", "analysis.dat", "other.frd", "other.sta"):
            with open(tmp_path / name, "w") as f:
                f.write("x")
        with patch(RUN, return_value=_result()):
            files = runner.run_analysis()
        assert files == {
            "results": str(tmp_path / "analysis.frd"),
            "data": str(tmp_path / "analysis.dat"),
        }
