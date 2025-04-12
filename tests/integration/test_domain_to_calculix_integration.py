"""
Integration test for the Domain to CalculiX mapper and workflow.

This test demonstrates how the DomainToCalculixMapper fits into the complete workflow
from domain model to CalculiX analysis and error handling.
"""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from src.ifc_structural_mechanics.domain.structural_model import StructuralModel
from src.ifc_structural_mechanics.domain.structural_member import (
    CurveMember,
    SurfaceMember,
)
from src.ifc_structural_mechanics.domain.property import Material, Section, Thickness
from src.ifc_structural_mechanics.mapping.domain_to_calculix import (
    DomainToCalculixMapper,
)
from src.ifc_structural_mechanics.meshing.mesh_converter import MeshConverter
from src.ifc_structural_mechanics.analysis.calculix_runner import CalculixRunner
from src.ifc_structural_mechanics.utils.error_handling import AnalysisError


class TestDomainToCalculixWorkflow(unittest.TestCase):
    """Test the integration of DomainToCalculixMapper in the analysis workflow."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a simple structural model
        self.model = StructuralModel("model_1", "Test Model")

        # Create material
        self.material = Material(
            id="material_1",
            name="Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
        )

        # Create section
        self.section = Section.create_rectangular_section(
            id="section_1", name="Rectangular Section", width=0.1, height=0.2
        )

        # Create thickness
        self.thickness = Thickness(id="thickness_1", name="Plate Thickness", value=0.01)

        # Create beam member
        self.beam = CurveMember(
            id="beam_1",
            geometry=((0, 0, 0), (5, 0, 0)),
            material=self.material,
            section=self.section,
        )

        # Create plate member
        self.plate = SurfaceMember(
            id="plate_1",
            geometry={
                "type": "plane",
                "boundaries": [[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]],
            },
            material=self.material,
            thickness=self.thickness,
        )

        # Add members to model
        self.model.add_member(self.beam)
        self.model.add_member(self.plate)

        # Create temporary files for testing
        self.temp_dir = tempfile.mkdtemp()
        self.inp_file = os.path.join(self.temp_dir, "test.inp")
        self.mapping_file = os.path.join(self.temp_dir, "mapping.json")

    def tearDown(self):
        """Clean up after tests."""
        import shutil

        shutil.rmtree(self.temp_dir)

    @patch("meshio.read")
    @patch("meshio.Mesh")
    def test_mesh_converter_with_mapper(self, mock_mesh, mock_read):
        """Test that the mesh converter uses the mapper correctly."""
        # Mock meshio.read and return a mesh with some elements
        mock_read.return_value = mock_mesh
        mock_mesh.points = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]

        # Set up cells with one of each element type
        # Use lists instead of numpy arrays for simpler mocking
        line_cells = [[0, 1]]
        quad_cells = [[0, 1, 2, 3]]

        # In newer meshio versions, cells is a list of tuples
        mock_mesh.cells = [("line", line_cells), ("quad", quad_cells)]

        # Create mapper and mesh converter
        mapper = DomainToCalculixMapper()

        # Add beam_1 and plate_1 to model in a way that _map_element_to_member will find them
        self.model.members[0].id = "beam_1"  # First member (beam) in the model
        self.model.members[1].id = "plate_1"  # Second member (plate) in the model

        converter = MeshConverter(domain_model=self.model, mapper=mapper)

        # Patch the _map_element_to_member method to return specific domain entity IDs for testing
        def mock_map_element(element_id, element_type, nodes):
            if element_type == "line":
                return "beam_1"
            elif element_type == "quad":
                return "plate_1"
            return None

        converter._map_element_to_member = mock_map_element

        # Convert mesh to CalculiX format
        with open(self.inp_file, "w") as f:
            f.write("Test")  # Create an empty file to satisfy file existence checks

        # Mock the _write_inp_file method to avoid actual file operations but still call _write_elements
        def mock_write_inp(mesh, output_file):
            with open(output_file, "w") as f:
                f.write("Mock INP file\n")
                converter._write_elements(mesh, f)
            return output_file

        with patch.object(converter, "_write_inp_file", side_effect=mock_write_inp):
            result = converter.convert_mesh(
                mesh_file="dummy.msh",
                output_file=self.inp_file,
                mapping_file=self.mapping_file,
            )

        # Check that the mapper now contains mappings
        self.assertGreater(len(mapper.domain_to_ccx["element"]), 0)
        self.assertTrue("beam_1" in mapper.domain_to_ccx["element"])
        self.assertTrue("plate_1" in mapper.domain_to_ccx["element"])

        # Check that the mapping file was created
        self.assertTrue(os.path.exists(self.mapping_file))

    @patch("src.ifc_structural_mechanics.utils.subprocess_utils.run_subprocess")
    def test_calculix_runner_with_mapper(self, mock_run_subprocess):
        """Test that the CalculiX runner uses the mapper for error handling."""
        # Create a test input file
        with open(self.inp_file, "w") as f:
            f.write("*NODE\n1, 0.0, 0.0, 0.0\n*ELEMENT\n1, 1\n")

        # Create a mapper and explicitly register element 1 to beam_1
        mapper = DomainToCalculixMapper()
        mapper.register_element("beam_1", 1)

        # Create mock subprocess result with the actual error message seen in the output
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.return_code = -11
        mock_result.stdout = "ERROR reading *ELEMENT: element type is lacking\nERROR reading *ELEMENT. Card image:"
        mock_result.stderr = ""
        mock_run_subprocess.return_value = mock_result

        # Create CalculiX runner with mapper
        runner = CalculixRunner(input_file_path=self.inp_file, mapper=mapper)

        # Make sure our mapper is properly set
        self.assertEqual(runner.mapper, mapper)

        # Run analysis and expect error
        try:
            runner.run_analysis()
            self.fail("Expected AnalysisError was not raised")
        except AnalysisError as e:
            # Check that the error context contains error_details
            self.assertIn(
                "error_details",
                e.context,
                f"Error context should contain 'error_details', but contains: {e.context}",
            )

            # Get the error details
            error_details = e.context["error_details"]

            # Verify there's at least one error detail
            self.assertTrue(len(error_details) > 0, "No error details found")

            # Print error details for easier debugging
            print(f"Error details: {error_details}")

            # Find an error detail with domain_id == "beam_1"
            beam_error = None
            for detail in error_details:
                if detail.get("domain_id") == "beam_1":
                    beam_error = detail
                    break

            # Verify we found an error mapped to beam_1
            self.assertIsNotNone(
                beam_error,
                f"No error detail mapped to beam_1 found in: {error_details}",
            )

            # For this test, we don't care about the specific values
            # as long as it's mapped to the correct domain entity

    def test_complete_workflow_simulation(self):
        """
        Test a simulated complete workflow from domain model to analysis.
        This test mocks the actual meshing and analysis, but shows how the mapper
        is used throughout the process.
        """
        # Create mapper
        mapper = DomainToCalculixMapper()

        # Step 1: Mock mesh conversion
        converter = MeshConverter(domain_model=self.model, mapper=mapper)

        # Register some mappings as if they came from mesh conversion
        mapper.register_element("beam_1", 1, "beam")
        mapper.register_element("beam_1", 2, "beam")
        mapper.register_element("plate_1", 3, "shell")
        mapper.register_element("plate_1", 4, "shell")
        mapper.register_node("node_1", 1)
        mapper.register_node("node_2", 2)
        mapper.register_material("material_1", "MAT_material_1")
        mapper.register_section("section_1", "SECT_section_1")

        # Save mapping to file
        mapper.create_mapping_file(self.mapping_file)

        # Step 2: Mock analysis with error
        # Create a test input file
        with open(self.inp_file, "w") as f:
            f.write("*NODE\n1, 0.0, 0.0, 0.0\n*ELEMENT\n1, 1\n")

        # Create mock subprocess result with actual error format seen in test output
        with patch(
            "src.ifc_structural_mechanics.utils.subprocess_utils.run_subprocess"
        ) as mock_run:
            mock_result = MagicMock()
            mock_result.success = False
            mock_result.return_code = -11
            mock_result.stdout = "ERROR reading *ELEMENT: element type is lacking\nERROR reading *ELEMENT. Card image:"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            # Run analysis with mapper
            runner = CalculixRunner(input_file_path=self.inp_file, mapper=mapper)

            # Run analysis and catch the error
            try:
                runner.run_analysis()
                self.fail("Expected an AnalysisError to be raised")
            except AnalysisError as e:
                # Print the full error context for debugging
                print(f"Error context: {e.context}")

                # Check that the error was mapped to the correct domain entity
                error_details = e.context.get("error_details", [])
                self.assertTrue(len(error_details) > 0, "No error details were found")

                # Find an error detail with domain_id == "beam_1"
                beam_error = None
                for detail in error_details:
                    if detail.get("domain_id") == "beam_1":
                        beam_error = detail
                        break

                # Verify we found an error mapped to beam_1
                self.assertIsNotNone(
                    beam_error,
                    f"No error detail mapped to beam_1 found in: {error_details}",
                )

        # Step 3: Load mapping from file in a new mapper
        new_mapper = DomainToCalculixMapper()
        new_mapper.load_mapping_file(self.mapping_file)

        # Verify mappings were preserved
        self.assertEqual(new_mapper.get_domain_entity_id(1, "element"), "beam_1")
        self.assertEqual(new_mapper.get_domain_entity_id(3, "element"), "plate_1")
        self.assertEqual(
            new_mapper.get_ccx_id("material_1", "material"), "MAT_material_1"
        )


if __name__ == "__main__":
    unittest.main()
