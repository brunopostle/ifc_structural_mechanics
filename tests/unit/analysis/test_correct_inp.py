import os
import shutil
from unittest.mock import MagicMock, patch

import pytest

from ifc_structural_mechanics.analysis.calculix_runner import CalculixRunner
from ifc_structural_mechanics.utils.temp_dir import create_temp_subdir


class TestCalculixRunner:
    """Test suite for CalculixRunner file handling."""

    def setup_method(self):
        """Set up test environment."""
        # Create a temporary directory for the test
        self.temp_dir = create_temp_subdir(prefix="test_calculix_runner_")

        # Create dummy input files
        self.model_inp = os.path.join(self.temp_dir, "model.inp")
        self.analysis_inp = os.path.join(self.temp_dir, "analysis.inp")

        # Write some content to the files to distinguish them
        with open(self.model_inp, "w") as f:
            f.write("** This is model.inp\n*NODE\n1, 0, 0, 0\n")

        with open(self.analysis_inp, "w") as f:
            f.write(
                "** This is analysis.inp\n*NODE\n1, 0, 0, 0\n*STEP\n*STATIC\n*END STEP\n"
            )

        # Mock system_config
        self.mock_system_config = MagicMock()
        self.mock_system_config.get_calculix_path.return_value = "/usr/bin/ccx"

        # Mock analysis_config
        self.mock_analysis_config = MagicMock()
        self.mock_analysis_config.get_analysis_type.return_value = "linear_static"
        self.mock_analysis_config.get_solver_params.return_value = {}

    def teardown_method(self):
        """Clean up after test."""
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass

    @patch("ifc_structural_mechanics.analysis.calculix_runner.run_subprocess")
    def test_correct_input_file_used(self, mock_run_subprocess):
        """Test that CalculixRunner uses the correct input file."""
        # Configure the mock to return a successful result
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = "STEP TIME COMPLETED"
        mock_result.stderr = ""
        mock_run_subprocess.return_value = mock_result

        # Make model.inp smaller than analysis.inp to simulate our new logic
        # that prefers the larger file
        with open(self.model_inp, "w") as f:
            f.write("** This is a small model.inp\n*NODE\n1, 0, 0, 0\n")

        with open(self.analysis_inp, "w") as f:
            f.write(
                "** This is a larger analysis.inp\n*NODE\n1, 0, 0, 0\n2, 1, 0, 0\n*ELEMENT, TYPE=B31\n1, 1, 2\n*STEP\n*STATIC\n*END STEP\n"
            )

        # Create a CalculixRunner instance with analysis.inp
        runner = CalculixRunner(
            input_file_path=self.analysis_inp,
            system_config=self.mock_system_config,
            analysis_config=self.mock_analysis_config,
            working_dir=self.temp_dir,
        )

        # Add mock _collect_result_files method
        runner._collect_result_files = MagicMock(return_value={"results": "dummy.frd"})
        runner._check_convergence = MagicMock(return_value=True)

        # Run the analysis
        runner.run_analysis()

        # Check that run_subprocess was called with the correct command
        args, kwargs = mock_run_subprocess.call_args
        command = args[0]

        # The command should use "analysis" as the base name since it's now the larger file
        assert (
            "analysis" in command
        ), f"Command does not reference analysis.inp: {command}"

        # Check that the working directory is correct
        assert kwargs.get("cwd") == str(self.temp_dir)

        # NEW TEST: Check that both files still exist (no renaming happens now)
        assert os.path.exists(self.model_inp), "model.inp should still exist"
        assert os.path.exists(self.analysis_inp), "analysis.inp should still exist"

        # Add a second test method

    def test_prefers_larger_input_file(self):
        """Test that CalculixRunner prefers the larger input file."""
        # Mock system and analysis configs
        mock_system_config = MagicMock()
        mock_system_config.get_calculix_path.return_value = "/usr/bin/ccx"

        mock_analysis_config = MagicMock()
        mock_analysis_config.get_analysis_type.return_value = "linear_static"
        mock_analysis_config.get_solver_params.return_value = {}

        # Create files with model.inp much larger than analysis.inp
        with open(os.path.join(self.temp_dir, "model.inp"), "w") as f:
            # Write a large model.inp
            f.write("** This is a large model.inp\n")
            for i in range(1000):
                f.write(f"*NODE\n{i}, {i}.0, 0, 0\n")

        with open(os.path.join(self.temp_dir, "analysis.inp"), "w") as f:
            # Write a small analysis.inp
            f.write(
                "** This is a small analysis.inp\n*NODE\n1, 0, 0, 0\n*STEP\n*STATIC\n*END STEP\n"
            )

        # Patch run_subprocess
        with patch(
            "ifc_structural_mechanics.analysis.calculix_runner.run_subprocess"
        ) as mock_run:
            # Configure the mock to return a successful result
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.stdout = "STEP TIME COMPLETED"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            # Create a CalculixRunner instance with analysis.inp
            runner = CalculixRunner(
                input_file_path=os.path.join(self.temp_dir, "analysis.inp"),
                system_config=mock_system_config,
                analysis_config=mock_analysis_config,
                working_dir=self.temp_dir,
            )

            # Add mock methods
            runner._collect_result_files = MagicMock(
                return_value={"results": "dummy.frd"}
            )
            runner._check_convergence = MagicMock(return_value=True)

            # Run the analysis
            runner.run_analysis()

            # Check that run_subprocess was called with the correct command
            args, kwargs = mock_run.call_args
            command = args[0]

            # The command should use "model" as the base name since it's the larger file
            assert (
                "model" in command
            ), f"Command should reference model.inp (the larger file): {command}"

    @patch("ifc_structural_mechanics.analysis.calculix_runner.run_subprocess")
    def test_missing_input_file_handling(self, mock_run_subprocess):
        """Test that CalculixRunner handles missing input files correctly."""
        # Configure the mock to return a successful result
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stdout = "STEP TIME COMPLETED"
        mock_result.stderr = ""
        mock_run_subprocess.return_value = mock_result

        # Create a non-existent input file path
        # Create a CalculixRunner with a file that exists at initialization but will be deleted before run
        runner = CalculixRunner(
            input_file_path=self.analysis_inp,
            system_config=self.mock_system_config,
            analysis_config=self.mock_analysis_config,
            working_dir=self.temp_dir,
        )

        # Add mock _collect_result_files method
        runner._collect_result_files = MagicMock(return_value={"results": "dummy.frd"})
        runner._check_convergence = MagicMock(return_value=True)

        # Delete the input file to simulate it going missing
        os.remove(self.analysis_inp)

        # Run the analysis - should raise an error because the file is gone
        with pytest.raises(Exception) as exc_info:
            runner.run_analysis()

        # The error should mention the missing file
        assert "not found" in str(exc_info.value) or "copy" in str(exc_info.value)
