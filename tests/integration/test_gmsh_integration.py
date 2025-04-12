"""
Integration tests for the Gmsh runner with real Gmsh executable.

These tests will only run if Gmsh is available on the system.
"""

import os
import subprocess
import pytest
import gmsh

from src.ifc_structural_mechanics.config.meshing_config import MeshingConfig
from src.ifc_structural_mechanics.config.system_config import SystemConfig
from src.ifc_structural_mechanics.meshing.gmsh_runner import GmshRunner
from src.ifc_structural_mechanics.utils.temp_dir import (
    setup_temp_dir,
    cleanup_temp_dir,
    create_temp_subdir,
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
    except:
        # Try to find the executable
        try:
            result = subprocess.run(
                ["gmsh", "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )
            return result.returncode == 0
        except:
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
        # Configure to use Python API
        self.meshing_config.use_python_api = True

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

    def test_executable_meshing(self):
        """
        Test meshing with the Gmsh executable.
        """
        # Skip if gmsh executable not found
        gmsh_path = subprocess.getoutput("which gmsh").strip()
        if not gmsh_path:
            pytest.skip("Gmsh executable not found in PATH")

        # Log the found gmsh path
        print(f"Found Gmsh executable at: {gmsh_path}")

        # Try running gmsh directly to get version information
        try:
            result = subprocess.run(
                [gmsh_path, "--info"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            print(f"Gmsh version information:\n{result.stdout}")
        except Exception as e:
            print(f"Error getting Gmsh version: {e}")

        # Configure to use executable
        self.meshing_config.use_python_api = False

        # Create the runner
        runner = GmshRunner(
            meshing_config=self.meshing_config, system_config=self.system_config
        )

        # Make sure the runner has the correct gmsh path
        print(f"Runner gmsh path: {runner.gmsh_path}")

        # Create a simple .geo file for testing
        test_geo = os.path.join(self.temp_dir, "test.geo")
        test_msh = os.path.join(self.temp_dir, "test.msh")

        # Write a simple geometry file
        with open(test_geo, "w") as f:
            f.write(
                """
            // Simple cube
            Point(1) = {0, 0, 0, 1.0};
            Point(2) = {1, 0, 0, 1.0};
            Point(3) = {1, 1, 0, 1.0};
            Point(4) = {0, 1, 0, 1.0};
            Point(5) = {0, 0, 1, 1.0};
            Point(6) = {1, 0, 1, 1.0};
            Point(7) = {1, 1, 1, 1.0};
            Point(8) = {0, 1, 1, 1.0};
            
            Line(1) = {1, 2};
            Line(2) = {2, 3};
            Line(3) = {3, 4};
            Line(4) = {4, 1};
            Line(5) = {5, 6};
            Line(6) = {6, 7};
            Line(7) = {7, 8};
            Line(8) = {8, 5};
            Line(9) = {1, 5};
            Line(10) = {2, 6};
            Line(11) = {3, 7};
            Line(12) = {4, 8};
            
            Curve Loop(1) = {1, 2, 3, 4};
            Plane Surface(1) = {1};
            Curve Loop(2) = {5, 6, 7, 8};
            Plane Surface(2) = {2};
            Curve Loop(3) = {1, 10, -5, -9};
            Plane Surface(3) = {3};
            Curve Loop(4) = {2, 11, -6, -10};
            Plane Surface(4) = {4};
            Curve Loop(5) = {3, 12, -7, -11};
            Plane Surface(5) = {5};
            Curve Loop(6) = {4, 9, -8, -12};
            Plane Surface(6) = {6};
            
            Surface Loop(1) = {1, 2, 3, 4, 5, 6};
            Volume(1) = {1};
            """
            )

        # Try running gmsh directly with subprocess
        try:
            cmd = [gmsh_path, test_geo, "-3", "-o", test_msh]
            print(f"Running gmsh with command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            print(f"Gmsh output: {result.stdout}")
            print(f"Gmsh errors: {result.stderr}")

            # Check if the file was created
            if os.path.exists(test_msh):
                print(
                    f"Mesh file created: {test_msh}, size: {os.path.getsize(test_msh)}"
                )
            else:
                print(f"Mesh file not created: {test_msh}")
        except Exception as e:
            print(f"Error running Gmsh subprocess: {e}")

        # Now try using the runner
        result = runner.run_meshing()
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
        # Configure to use Python API for simplicity
        self.meshing_config.use_python_api = True

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
            mesh_file = runner.generate_mesh_file(output_file, format=fmt)

            assert os.path.exists(mesh_file)
            assert os.path.getsize(mesh_file) > 0

            # Check if mapping file was created
            mapping_file = os.path.splitext(output_file)[0] + ".map.json"
            # Note: in this test, the mapping might be empty since we didn't use GmshGeometryConverter

    def test_full_workflow_with_domain_model(self):
        """
        Test the full workflow with a domain model, geometry converter, and meshing.
        """
        from src.ifc_structural_mechanics.domain.structural_model import StructuralModel
        from src.ifc_structural_mechanics.domain.structural_member import CurveMember
        from src.ifc_structural_mechanics.meshing.gmsh_geometry import (
            GmshGeometryConverter,
        )
        from src.ifc_structural_mechanics.mapping.domain_to_gmsh import (
            DomainToGmshMapper,
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

        # Create a mapper
        mapper = DomainToGmshMapper()

        # Convert domain model to Gmsh geometry
        geometry_converter = GmshGeometryConverter(
            meshing_config=self.meshing_config, mapper=mapper
        )

        entity_map = geometry_converter.convert_model(model)

        # Verify the entity map contains our beam
        assert "beam_1" in entity_map

        # Create the runner with the same mapper
        runner = GmshRunner(
            meshing_config=self.meshing_config,
            system_config=self.system_config,
            mapper=mapper,
        )

        # Run meshing
        result = runner.run_meshing()
        assert result is True

        # Generate mesh file
        output_file = os.path.join(self.temp_dir, "beam.msh")
        mesh_file = runner.generate_mesh_file(output_file)

        assert os.path.exists(mesh_file)
        assert os.path.getsize(mesh_file) > 0

        # Check if mapping file was created
        mapping_file = os.path.splitext(output_file)[0] + ".map.json"
        assert os.path.exists(mapping_file)

        # Verify we can load the mapping
        new_mapper = DomainToGmshMapper()
        new_mapper.load_mapping_file(mapping_file)

        # Check if our beam is in the loaded mapping - updated for BaseMapper structure
        # A beam is a curve, so it should be in the 'curve' category
        assert "beam_1" in new_mapper.domain_to_tool["curve"]
