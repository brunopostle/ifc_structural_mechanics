"""
Unit tests for the Gmsh runner module.
"""

import subprocess
from unittest import mock
import pytest

import gmsh
from src.ifc_structural_mechanics.config.meshing_config import MeshingConfig
from src.ifc_structural_mechanics.config.system_config import SystemConfig
from src.ifc_structural_mechanics.meshing.gmsh_runner import GmshRunner
from src.ifc_structural_mechanics.utils.error_handling import MeshingError
from src.ifc_structural_mechanics.utils.temp_dir import (
    setup_temp_dir,
    get_temp_dir,
    cleanup_temp_dir,
    create_temp_file,
)


class TestGmshRunner:
    """
    Test suite for the GmshRunner class.
    """

    @classmethod
    def setup_class(cls):
        """
        Set up shared resources for all tests.
        """
        # Use the temp_dir utility to set up a base directory for the class
        cls.temp_base_dir = setup_temp_dir(prefix="gmsh_test_")

    @classmethod
    def teardown_class(cls):
        """
        Clean up shared resources after all tests.
        """
        # Only force cleanup if the test failed
        cleanup_temp_dir(force=False)

    def setup_method(self):
        """
        Set up test environment before each test.
        """
        # Initialize gmsh before tests since some tests will need the API
        if not gmsh.isInitialized():
            gmsh.initialize()

        # Mock configurations
        self.mock_meshing_config = MeshingConfig()
        self.mock_system_config = SystemConfig()

        # Configure system config to use temporary directory
        with mock.patch.object(
            self.mock_system_config, "get_temp_directory", return_value=get_temp_dir()
        ):
            # Create the runner with mocked configs
            self.runner = GmshRunner(
                meshing_config=self.mock_meshing_config,
                system_config=self.mock_system_config,
            )

    def teardown_method(self):
        """
        Clean up after each test.
        """
        # Finalize gmsh to clean up its resources
        if gmsh.isInitialized():
            gmsh.finalize()

    @mock.patch(
        "src.ifc_structural_mechanics.meshing.gmsh_runner.GmshRunner._verify_gmsh_executable"
    )
    def test_initialization(self, mock_verify):
        """
        Test that the GmshRunner initializes correctly.
        """
        # Verify that initialization works
        runner = GmshRunner(
            meshing_config=self.mock_meshing_config,
            system_config=self.mock_system_config,
        )

        assert runner is not None
        assert runner.meshing_config is self.mock_meshing_config
        assert runner.system_config is self.mock_system_config
        mock_verify.assert_called_once()

    @mock.patch("subprocess.run")
    @mock.patch("src.ifc_structural_mechanics.utils.subprocess_utils.run_subprocess")
    def test_run_meshing_python_api(self, mock_run_subprocess, mock_subproc_run):
        """
        Test running meshing process using the Python API.
        """
        # Configure to use Python API
        self.runner.use_python_api = True

        # Mock gmsh.model.mesh.generate to avoid actual meshing
        with mock.patch("gmsh.model.mesh.generate") as mock_generate:
            # Run meshing
            result = self.runner.run_meshing()

            # Check that meshing was called and succeeded
            assert result is True
            mock_generate.assert_called_once_with(3)  # Default to 3D mesh

            # The subprocess should not have been called when using Python API
            mock_run_subprocess.assert_not_called()

    def test_run_meshing_exe(self):
        """
        Test running meshing process using the executable.
        """
        # Configure to use executable instead of Python API
        self.runner.use_python_api = False

        # Create necessary mocks with direct patching
        with mock.patch(
            "src.ifc_structural_mechanics.meshing.gmsh_runner.run_subprocess"
        ) as mock_run_subprocess, mock.patch.object(
            self.runner, "_create_temp_geo_file"
        ) as mock_create_geo, mock.patch.object(
            self.runner, "_prepare_command"
        ) as mock_prepare_cmd, mock.patch.object(
            self.runner, "_handle_output"
        ) as mock_handle_output, mock.patch.object(
            self.runner, "_validate_mesh_quality"
        ) as mock_validate_quality:

            # Setup mock return values
            geo_file = create_temp_file(prefix="test", suffix=".geo")
            mock_create_geo.return_value = geo_file
            mock_prepare_cmd.return_value = ["gmsh", geo_file]

            # Mock successful subprocess result
            mock_process_result = mock.MagicMock()
            mock_process_result.stdout = "Mesh generation complete"
            mock_process_result.stderr = ""
            mock_run_subprocess.return_value = mock_process_result

            # Mock handle_output to return True for success
            mock_handle_output.return_value = True

            # Run meshing
            result = self.runner.run_meshing()

            # Check that the subprocess was called and meshing succeeded
            assert result is True
            mock_run_subprocess.assert_called_once()
            mock_create_geo.assert_called_once()
            mock_prepare_cmd.assert_called_once()
            mock_handle_output.assert_called_once()
            mock_validate_quality.assert_called_once()

    def test_run_meshing_exe_error(self):
        """
        Test handling of errors during meshing with executable.
        """
        # Configure to use executable
        self.runner.use_python_api = False

        # Create necessary mocks with direct patching
        with mock.patch(
            "src.ifc_structural_mechanics.meshing.gmsh_runner.run_subprocess"
        ) as mock_run_subprocess, mock.patch.object(
            self.runner, "_create_temp_geo_file"
        ) as mock_create_geo, mock.patch.object(
            self.runner, "_prepare_command"
        ) as mock_prepare_cmd, mock.patch.object(
            self.runner, "_handle_output"
        ) as mock_handle_output:

            # Setup mock return values
            geo_file = create_temp_file(prefix="test", suffix=".geo")
            mock_create_geo.return_value = geo_file
            mock_prepare_cmd.return_value = ["gmsh", geo_file]

            # Mock error in subprocess
            mock_process_result = mock.MagicMock()
            mock_process_result.stdout = ""
            mock_process_result.stderr = "Error: meshing failed"
            mock_run_subprocess.return_value = mock_process_result

            # Mock handle_output to return False to trigger error path
            mock_handle_output.return_value = False

            # Run meshing should raise an error
            with pytest.raises(MeshingError):
                self.runner.run_meshing()

            # Check that the subprocess was called
            mock_run_subprocess.assert_called_once()
            mock_create_geo.assert_called_once()
            mock_prepare_cmd.assert_called_once()
            mock_handle_output.assert_called_once()

    def test_run_meshing_timeout(self):
        """
        Test handling of timeout during meshing.
        """
        # Configure to use executable
        self.runner.use_python_api = False

        # Create necessary mocks with direct patching
        with mock.patch(
            "src.ifc_structural_mechanics.meshing.gmsh_runner.run_subprocess"
        ) as mock_run_subprocess, mock.patch.object(
            self.runner, "_create_temp_geo_file"
        ) as mock_create_geo, mock.patch.object(
            self.runner, "_prepare_command"
        ) as mock_prepare_cmd:

            # Setup mock return values
            geo_file = create_temp_file(prefix="test", suffix=".geo")
            mock_create_geo.return_value = geo_file
            mock_prepare_cmd.return_value = ["gmsh", geo_file]

            # Mock timeout in subprocess - critical to use the correct exception
            mock_run_subprocess.side_effect = subprocess.TimeoutExpired(
                cmd="gmsh", timeout=5
            )

            # Run meshing with timeout should raise an error
            with pytest.raises(MeshingError):
                self.runner.run_meshing(timeout=5)

            # Check that the subprocess was called
            mock_run_subprocess.assert_called_once()
            mock_create_geo.assert_called_once()
            mock_prepare_cmd.assert_called_once()

    @mock.patch(
        "src.ifc_structural_mechanics.meshing.gmsh_runner.GmshRunner._prepare_command"
    )
    @mock.patch("src.ifc_structural_mechanics.utils.subprocess_utils.run_subprocess")
    def test_generate_mesh_file_api(self, mock_run_subprocess, mock_prepare_command):
        """
        Test generating a mesh file using the Python API.
        """
        # Configure to use Python API
        self.runner.use_python_api = True

        # Create a simple model
        gmsh.model.add("test_model")
        gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
        gmsh.model.occ.synchronize()

        # Use temp_dir utility for output path
        output_path = create_temp_file(prefix="gmsh_output", suffix=".msh")

        # Mock gmsh.write to avoid actual file writing
        with mock.patch("gmsh.write") as mock_write:
            # Mock gmsh.model.mesh.getNodes to simulate mesh existence
            with mock.patch("gmsh.model.mesh.getNodes", return_value=([1], None, None)):
                # Mock run_meshing to avoid actual meshing
                with mock.patch.object(self.runner, "run_meshing") as mock_run_meshing:
                    result = self.runner.generate_mesh_file(output_path)

                    # run_meshing should not be called if mesh already exists
                    mock_run_meshing.assert_not_called()

            # Check that the file was "generated" (mocked)
            assert result == output_path
            mock_write.assert_called_once_with(output_path)

            # Subprocess should not have been called for API usage
            mock_run_subprocess.assert_not_called()

    def test_generate_mesh_file_exe(self):
        """
        Test generating a mesh file using the executable.
        """
        # Configure to use executable
        self.runner.use_python_api = False

        # Create a temp file for the latest mesh
        latest_mesh_file = create_temp_file(prefix="temp", suffix=".msh")
        with open(latest_mesh_file, "w") as f:
            f.write("Mock mesh file content")
        self.runner.latest_mesh_file = latest_mesh_file

        # Output file path using temp_dir utility
        output_path = create_temp_file(prefix="output", suffix=".vtk")

        # Create necessary mocks with direct patching
        with mock.patch(
            "src.ifc_structural_mechanics.meshing.gmsh_runner.run_subprocess"
        ) as mock_run_subprocess, mock.patch.object(
            self.runner, "_prepare_command"
        ) as mock_prepare_command, mock.patch.object(
            self.runner, "_handle_output"
        ) as mock_handle_output:

            # Configure prepare_command
            mock_prepare_command.return_value = [
                "gmsh",
                "-o",
                output_path,
                latest_mesh_file,
            ]

            # Configure run_subprocess
            mock_process_result = mock.MagicMock()
            mock_process_result.stdout = "Mesh written to file"
            mock_process_result.stderr = ""
            mock_run_subprocess.return_value = mock_process_result

            # Configure handle_output
            mock_handle_output.return_value = True

            # Generate mesh file in a different format
            result = self.runner.generate_mesh_file(output_path, format="vtk")

            # Check that the subprocess was called
            mock_run_subprocess.assert_called_once()
            mock_prepare_command.assert_called_once()

            # Verify the output path
            assert result == output_path

    def test_prepare_command(self):
        """
        Test the command preparation logic.
        """
        # Use a known gmsh path for consistent testing
        test_gmsh_path = "/usr/bin/gmsh"

        # Create a fresh runner with the gmsh path mocked during initialization
        with mock.patch.object(
            SystemConfig, "get_gmsh_path", return_value=test_gmsh_path
        ):
            # Create fresh config instances
            test_meshing_config = MeshingConfig()
            test_system_config = SystemConfig()

            # Mock the temp directory method
            with mock.patch.object(
                test_system_config, "get_temp_directory", return_value=get_temp_dir()
            ):
                # Create a new runner with the mocked gmsh path
                test_runner = GmshRunner(
                    meshing_config=test_meshing_config,
                    system_config=test_system_config,
                )

        # Now mock the meshing config methods for this test
        with mock.patch.object(
            test_runner.meshing_config, "get_mesh_dimension", return_value=3
        ), mock.patch.object(
            test_runner.meshing_config, "get_min_element_size", return_value=0.01
        ), mock.patch.object(
            test_runner.meshing_config, "get_max_element_size", return_value=1.0
        ), mock.patch.object(
            test_runner.meshing_config, "get_additional_options", return_value={}
        ):
            # Test meshing command
            input_file = create_temp_file(prefix="input", suffix=".geo")
            output_file = create_temp_file(prefix="output", suffix=".msh")
            command = test_runner._prepare_command(input_file, output_file)

            # Verify command structure - use the mocked path
            assert command[0] == test_gmsh_path
            assert input_file in command
            assert "-o" in command
            assert output_file in command

            # Test format conversion command
            command = test_runner._prepare_command(
                input_file, output_file, convert_format=True
            )

            # Verify command structure for conversion
            assert command[0] == test_gmsh_path
            assert "-o" in command
            assert output_file in command
            assert input_file in command

    def test_handle_output(self):
        """
        Test output handling logic.
        """
        # Test successful output
        success = self.runner._handle_output(
            "Mesh generation complete\nMesh written to file", ""
        )
        assert success is True

        # Test error in stderr
        success = self.runner._handle_output(
            "Starting meshing...", "Error: could not create mesh"
        )
        assert success is False

        # Test error in stdout
        success = self.runner._handle_output(
            "Starting meshing...\nError: invalid geometry", ""
        )
        assert success is False
