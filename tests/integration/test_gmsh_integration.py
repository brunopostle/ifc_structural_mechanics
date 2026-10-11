"""
Integration tests for the Gmsh runner with real Gmsh executable.

These tests will only run if Gmsh is available on the system.
"""

import os
import subprocess

import gmsh
import pytest

from src.ifc_structural_mechanics.config.meshing_config import MeshingConfig
from src.ifc_structural_mechanics.config.system_config import SystemConfig
from src.ifc_structural_mechanics.meshing.gmsh_runner import GmshRunner
from src.ifc_structural_mechanics.utils.temp_dir import (
    cleanup_temp_dir,
    create_temp_subdir,
    setup_temp_dir,
)


def is_gmsh_available():
    """
    Check if Gmsh is available on the system.

    Returns:
        bool: True if Gmsh is available, False otherwise.
    """
    try:
        # Try to initialize Gmsh - if it works, the library is available
        if not gmsh.isInitialized():
            gmsh.initialize()
            gmsh.finalize()
        return True
    except Exception:
        # Try to find the executable
        try:
            result = subprocess.run(
                ["gmsh", "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False


# Skip all tests in this module if Gmsh is not available
pytestmark = pytest.mark.skipif(
    not is_gmsh_available(), reason="Gmsh is not available on the system"
)


class TestGmshIntegration:
    """
    Integration tests for Gmsh that run the actual executable.
    """

    @classmethod
    def setup_class(cls):
        """
        Set up shared resources for all tests.
        """
        # Use the temp_dir utility to set up a base directory for the class
        cls.temp_base_dir = setup_temp_dir(prefix="gmsh_integration_test_")

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
        # Create a dedicated temporary directory for this test method
        self.temp_dir = create_temp_subdir(prefix="gmsh_test_")

        # Create configurations
        self.meshing_config = MeshingConfig()
        self.system_config = SystemConfig()

        # Initialize gmsh for creating test geometries
        if not gmsh.isInitialized():
            gmsh.initialize()

        # Create a simple test model - a cube
        gmsh.model.add("test_cube")
        gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
        gmsh.model.occ.synchronize()

    def teardown_method(self):
        """
        Clean up after each test.
        """
        # Finalize gmsh
        if gmsh.isInitialized():
            gmsh.finalize()

    def test_python_api_meshing(self):
        """
        Test meshing with the Python API.
        """

        # Create the runner
        runner = GmshRunner(
            meshing_config=self.meshing_config, system_config=self.system_config
        )

        # Run meshing
        result = runner.run_meshing()

        # Verify meshing succeeded
        assert result is True

        # Generate mesh file and check it exists
        output_file = os.path.join(self.temp_dir, "cube.msh")
        mesh_file = runner.generate_mesh_file(output_file)

        assert os.path.exists(mesh_file)
        assert os.path.getsize(mesh_file) > 0

    def test_format_conversion(self):
        """
        Test converting the mesh to different formats.
        """

        # Create the runner
        runner = GmshRunner(
            meshing_config=self.meshing_config, system_config=self.system_config
        )

        # Run meshing
        result = runner.run_meshing()
        assert result is True

        # Generate mesh files in different formats
        formats = ["msh", "vtk", "inp"]

        for fmt in formats:
            output_file = os.path.join(self.temp_dir, f"cube.{fmt}")
            mesh_file = runner.generate_mesh_file(output_file)

            assert os.path.exists(mesh_file)
            assert os.path.getsize(mesh_file) > 0

            # Check if mapping file was created
            # Note: in this test, the mapping might be empty since we didn't use GmshGeometryConverter

    def test_full_workflow_with_domain_model(self):
        """
        Test the full workflow with a domain model, geometry converter, and meshing.
        """
        from src.ifc_structural_mechanics.domain.structural_member import CurveMember
        from src.ifc_structural_mechanics.domain.structural_model import StructuralModel
        from src.ifc_structural_mechanics.meshing.gmsh_geometry import (
            GmshGeometryConverter,
        )

        # Create a simple domain model with a beam
        model = StructuralModel(id="test_model", name="Test Model")

        # Create a simple beam member
        beam = CurveMember(
            id="beam_1",
            geometry=((0, 0, 0), (10, 0, 0)),  # 10m long beam along X axis
            material={"id": "steel", "name": "Steel", "elastic_modulus": 2.1e11},
            section={
                "id": "rect_100x200",
                "area": 0.02,
                "shape": "rectangle",
                "width": 0.1,
                "height": 0.2,
            },
        )

        # Add the beam to the model
        model.add_member(beam)

        # Convert domain model to Gmsh geometry
        geometry_converter = GmshGeometryConverter(meshing_config=self.meshing_config)

        entity_map = geometry_converter.convert_model(model)

        # Verify the entity map contains our beam
        assert "beam_1" in entity_map

        # Create the runner
        runner = GmshRunner(
            meshing_config=self.meshing_config,
            system_config=self.system_config,
        )

        # Run meshing
        result = runner.run_meshing()
        assert result is True

        # Generate mesh file
        output_file = os.path.join(self.temp_dir, "beam.msh")
        mesh_file = runner.generate_mesh_file(output_file)

        assert os.path.exists(mesh_file)
        assert os.path.getsize(mesh_file) > 0

        # Check if mapping file was created (mapper functionality removed, test skipped)
        # mapping_file = os.path.splitext(output_file)[0] + ".map.json"
        # assert os.path.exists(mapping_file)
