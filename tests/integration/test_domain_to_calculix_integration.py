"""
Integration test for the Domain to CalculiX unified workflow.

This test demonstrates the new unified approach that eliminates dual element writing
and validates the complete workflow from domain model to CalculiX analysis.
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

# Updated import to use unified writer instead of removed MeshConverter
from src.ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
    run_complete_analysis_workflow,
)
from src.ifc_structural_mechanics.analysis.calculix_runner import CalculixRunner
from src.ifc_structural_mechanics.config.analysis_config import AnalysisConfig
from src.ifc_structural_mechanics.config.meshing_config import MeshingConfig
from src.ifc_structural_mechanics.config.system_config import SystemConfig


class TestDomainToCalculixUnifiedWorkflow(unittest.TestCase):
    """Test the unified Domain to CalculiX workflow that eliminates dual element writing."""

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

        # Create configurations for unified workflow
        self.analysis_config = AnalysisConfig()
        self.meshing_config = MeshingConfig()
        self.system_config = SystemConfig()

    def tearDown(self):
        """Clean up after tests."""
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_unified_writer_with_mapper(self):
        """Test that the unified writer integrates correctly with the mapper."""

        # Create unified writer with correct parameters
        writer = UnifiedCalculixWriter(
            domain_model=self.model,
            analysis_config=self.analysis_config,
        )

        # Create a mock mesh file with mixed element types
        mesh_content = """$MeshFormat
2.2 0 8
$EndMeshFormat
$Nodes
4
1 0 0 0
2 5 0 0
3 1 0 0
4 1 1 0
$EndNodes
$Elements
2
1 1 2 0 1 1 2
2 2 2 0 1 3 4 1
$EndElements
"""

        mesh_file = os.path.join(self.temp_dir, "test.msh")
        with open(mesh_file, "w") as f:
            f.write(mesh_content)

        # Process mesh with unified writer
        writer.write_calculix_input_from_mesh(mesh_file, self.inp_file)

        # Verify file was created
        self.assertTrue(os.path.exists(self.inp_file))

        # Read and validate content
        with open(self.inp_file, "r") as f:
            content = f.read()

        # Verify basic CalculiX structure
        self.assertIn("*NODE", content)
        self.assertIn("*ELEMENT", content)

        # Verify elements are present and correctly typed
        elements = self._parse_elements_from_content(content)
        self.assertGreater(len(elements), 0, "No elements found in output")

        # Key validation: Check that elements maintain correct node counts
        for elem in elements:
            if elem.get("type") == "B31":  # Beam elements should have 2 nodes
                self.assertEqual(
                    len(elem["nodes"]),
                    2,
                    f"B31 element {elem['id']} should have 2 nodes",
                )
            elif (
                elem.get("type") == "S3"
            ):  # Triangular shell elements should have 3 nodes
                self.assertEqual(
                    len(elem["nodes"]),
                    3,
                    f"S3 element {elem['id']} should have 3 nodes",
                )

    def test_run_complete_analysis_workflow(self):
        """Test the complete unified workflow function."""

        intermediate_dir = os.path.join(self.temp_dir, "intermediate")

        # Mock the Gmsh operations at their correct locations
        with patch(
            "src.ifc_structural_mechanics.meshing.gmsh_geometry.GmshGeometryConverter"
        ) as mock_converter:
            with patch(
                "src.ifc_structural_mechanics.meshing.gmsh_runner.GmshRunner"
            ) as mock_runner:

                # Mock the geometry converter
                mock_converter_instance = MagicMock()
                mock_converter.return_value = mock_converter_instance
                mock_converter_instance.convert_model.return_value = {
                    "beam_1": {"type": "curve"},
                    "plate_1": {"type": "surface"},
                }

                # Mock the Gmsh runner
                mock_runner_instance = MagicMock()
                mock_runner.return_value = mock_runner_instance
                mock_runner_instance.run_meshing.return_value = True

                # Create a mock mesh file that the runner would generate
                os.makedirs(intermediate_dir, exist_ok=True)
                mock_mesh_file = os.path.join(intermediate_dir, "mesh.msh")
                with open(mock_mesh_file, "w") as f:
                    f.write(
                        """$MeshFormat
2.2 0 8
$EndMeshFormat
$Nodes
2
1 0 0 0
2 1 0 0
$EndNodes
$Elements
1
1 1 2 0 1 1 2
$EndElements
"""
                    )

                mock_runner_instance.generate_mesh_file.return_value = mock_mesh_file

                # Run the complete workflow
                result_file = run_complete_analysis_workflow(
                    domain_model=self.model,
                    output_inp_file=self.inp_file,
                    analysis_config=self.analysis_config,
                    meshing_config=self.meshing_config,
                    system_config=self.system_config,
                    intermediate_files_dir=intermediate_dir,
                )

                # Validate results
                self.assertEqual(result_file, self.inp_file)
                self.assertTrue(os.path.exists(result_file))

                # Verify the unified workflow was called correctly
                mock_converter_instance.convert_model.assert_called_once()
                mock_runner_instance.run_meshing.assert_called_once()

    def test_unified_workflow_element_preservation(self):
        """Test that the unified workflow preserves element topology correctly."""

        # Create a model with only a surface member to focus on triangular elements
        surface_model = StructuralModel("surface_model", "Surface Model")
        surface_model.add_member(self.plate)

        # Create unified writer with correct parameters
        writer = UnifiedCalculixWriter(
            domain_model=surface_model,
            analysis_config=self.analysis_config,
        )

        # Create mock mesh with triangular elements
        mesh_content = """$MeshFormat
2.2 0 8
$EndMeshFormat
$Nodes
3
1 0 0 0
2 1 0 0
3 0 1 0
$EndNodes
$Elements
1
1 2 2 0 1 1 2 3
$EndElements
"""

        mesh_file = os.path.join(self.temp_dir, "triangular.msh")
        with open(mesh_file, "w") as f:
            f.write(mesh_content)

        # Process with unified writer
        writer.write_calculix_input_from_mesh(mesh_file, self.inp_file)

        # Parse generated elements
        with open(self.inp_file, "r") as f:
            content = f.read()

        elements = self._parse_elements_from_content(content)

        # Find triangular shell elements
        triangular_elements = [e for e in elements if e.get("type") in ["S3", "S6"]]

        # Critical validation: Triangular elements must preserve 3-node topology
        for elem in triangular_elements:
            self.assertEqual(
                len(elem["nodes"]),
                3,
                f"Triangular element {elem['id']} has {len(elem['nodes'])} nodes, "
                f"expected 3. Topology not preserved!",
            )

    def test_calculix_runner_with_unified_output(self):
        """Test that CalculiX runner works with unified writer output."""

        # Create a minimal but valid CalculiX input file using unified writer
        minimal_model = StructuralModel("minimal", "Minimal Model")
        minimal_model.add_member(self.beam)

        # Create unified writer with correct parameters
        writer = UnifiedCalculixWriter(
            domain_model=minimal_model,
            analysis_config=self.analysis_config,
        )

        # Create simple mesh for the beam
        beam_mesh = """$MeshFormat
2.2 0 8
$EndMeshFormat
$Nodes
2
1 0 0 0
2 5 0 0
$EndNodes
$Elements
1
1 1 2 0 1 1 2
$EndElements
"""

        mesh_file = os.path.join(self.temp_dir, "beam.msh")
        with open(mesh_file, "w") as f:
            f.write(beam_mesh)

        # Generate CalculiX input with unified writer
        writer.write_calculix_input_from_mesh(mesh_file, self.inp_file)

        # Mock CalculiX execution
        with patch(
            "src.ifc_structural_mechanics.utils.subprocess_utils.run_subprocess"
        ) as mock_run:
            # Mock successful run
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.return_code = 0
            mock_result.stdout = "Job completed successfully"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            # Run CalculiX with unified input
            runner = CalculixRunner(input_file_path=self.inp_file)

            # This should not raise an exception
            try:
                result = runner.run_analysis()
                # Verify some output files would be generated
                self.assertIsInstance(result, dict)
            except Exception as e:
                self.fail(f"CalculiX runner failed with unified input: {e}")

    def test_unified_workflow_no_dual_writing(self):
        """
        Test that ensures no dual element writing occurs in the unified workflow.
        This is the key test that validates the architectural fix.
        """

        # Create unified writer with correct parameters
        writer = UnifiedCalculixWriter(
            domain_model=self.model,
            analysis_config=self.analysis_config,
        )

        # Create mock mesh
        mesh_content = """$MeshFormat
2.2 0 8
$EndMeshFormat
$Nodes
4  
1 0 0 0
2 5 0 0
3 1 0 0
4 1 1 0
$EndNodes
$Elements
2
1 1 2 0 1 1 2
2 2 2 0 1 3 4 1
$EndElements
"""

        mesh_file = os.path.join(self.temp_dir, "mixed.msh")
        with open(mesh_file, "w") as f:
            f.write(mesh_content)

        # Track the elements before and after mesh mapping
        writer.write_calculix_input_from_mesh(mesh_file, self.inp_file)

        # Read the generated content
        with open(self.inp_file, "r") as f:
            content = f.read()

        # Parse all elements from the output
        elements = self._parse_elements_from_content(content)

        # Critical validation: Each element should appear exactly once
        # (No dual writing means no duplicate elements)
        element_ids = [elem["id"] for elem in elements]
        unique_element_ids = set(element_ids)

        self.assertEqual(
            len(element_ids),
            len(unique_element_ids),
            f"Duplicate element IDs found: {element_ids}. "
            f"This indicates dual writing occurred!",
        )

        # Verify we have the expected number of elements (2 from mock mesh)
        self.assertEqual(
            len(elements),
            2,
            f"Expected 2 elements, found {len(elements)}. "
            f"Element count mismatch suggests writing issues.",
        )

        # Additional validation: verify each element type appears in appropriate counts
        element_types = [elem["type"] for elem in elements]
        type_counts = {}
        for elem_type in element_types:
            type_counts[elem_type] = type_counts.get(elem_type, 0) + 1

        # Should have reasonable element type distribution (no excessive duplicates)
        for elem_type, count in type_counts.items():
            self.assertLessEqual(
                count,
                2,
                f"Element type {elem_type} appears {count} times, suggesting dual writing",
            )

    def test_complete_workflow_simulation_unified(self):
        """
        Test a simulated complete workflow using the unified approach.
        This replaces the old dual-system coordination test.
        """

        # Mock the complete analysis workflow with correct paths
        with patch(
            "src.ifc_structural_mechanics.meshing.gmsh_geometry.GmshGeometryConverter"
        ) as mock_geo:
            with patch(
                "src.ifc_structural_mechanics.meshing.gmsh_runner.GmshRunner"
            ) as mock_gmsh:

                # Set up mocks
                mock_geo_instance = MagicMock()
                mock_geo.return_value = mock_geo_instance
                mock_geo_instance.convert_model.return_value = {
                    "beam_1": {"type": "curve"},
                    "plate_1": {"type": "surface"},
                }

                mock_gmsh_instance = MagicMock()
                mock_gmsh.return_value = mock_gmsh_instance
                mock_gmsh_instance.run_meshing.return_value = True

                # Create intermediate directory and mock mesh file
                intermediate_dir = os.path.join(self.temp_dir, "intermediate")
                os.makedirs(intermediate_dir, exist_ok=True)

                mock_mesh_file = os.path.join(intermediate_dir, "mesh.msh")
                with open(mock_mesh_file, "w") as f:
                    f.write(
                        """$MeshFormat
2.2 0 8
$EndMeshFormat
$Nodes
4
1 0 0 0
2 5 0 0
3 1 0 0
4 1 1 0
$EndNodes
$Elements
2
1 1 2 0 1 1 2
2 2 2 0 1 3 4 1
$EndElements
"""
                    )

                mock_gmsh_instance.generate_mesh_file.return_value = mock_mesh_file

                # Run the unified workflow
                result_file = run_complete_analysis_workflow(
                    domain_model=self.model,
                    output_inp_file=self.inp_file,
                    analysis_config=self.analysis_config,
                    meshing_config=self.meshing_config,
                    system_config=self.system_config,
                    intermediate_files_dir=intermediate_dir,
                )

                # Validate the unified workflow succeeded
                self.assertEqual(result_file, self.inp_file)
                self.assertTrue(os.path.exists(result_file))

                # Validate content structure
                with open(result_file, "r") as f:
                    content = f.read()

                # Basic CalculiX format validation
                self.assertIn("*NODE", content)
                self.assertIn("*ELEMENT", content)
                self.assertIn("*MATERIAL", content)

                # Parse and validate elements
                elements = self._parse_elements_from_content(content)
                self.assertGreater(
                    len(elements), 0, "No elements found in unified output"
                )

                # Verify no duplicate elements (key anti-dual-writing check)
                element_ids = [elem["id"] for elem in elements]
                self.assertEqual(
                    len(element_ids),
                    len(set(element_ids)),
                    "Duplicate elements found - dual writing detected!",
                )

                # Verify element types are appropriate for domain members
                element_types = {elem["type"] for elem in elements if elem["type"]}
                expected_types = {
                    "B31",
                    "B32",
                    "S3",
                    "S4",
                    "S6",
                    "S8",
                }  # Common beam and shell types
                self.assertTrue(
                    element_types.issubset(expected_types),
                    f"Unexpected element types found: {element_types - expected_types}",
                )

    def test_unified_vs_old_workflow_compatibility(self):
        """
        Test that demonstrates the unified workflow produces equivalent results
        to what the old dual system should have produced (without conflicts).
        """

        # Create a simple model that would have been problematic with dual writing
        simple_model = StructuralModel("simple", "Simple Model")
        simple_model.add_member(self.beam)

        # Generate output with unified writer using correct parameters
        writer = UnifiedCalculixWriter(
            domain_model=simple_model,
            analysis_config=self.analysis_config,
        )

        # Simple beam mesh
        mesh_content = """$MeshFormat
2.2 0 8
$EndMeshFormat
$Nodes
2
1 0 0 0
2 5 0 0
$EndNodes
$Elements
1
1 1 2 0 1 1 2
$EndElements
"""

        mesh_file = os.path.join(self.temp_dir, "simple.msh")
        with open(mesh_file, "w") as f:
            f.write(mesh_content)

        writer.write_calculix_input_from_mesh(mesh_file, self.inp_file)

        # Read and validate
        with open(self.inp_file, "r") as f:
            content = f.read()

        # Key compatibility checks
        self.assertIn("*NODE", content, "Missing node section")
        self.assertIn("*ELEMENT", content, "Missing element section")

        # Parse elements and verify integrity
        elements = self._parse_elements_from_content(content)

        # Debug output if test fails
        if len(elements) != 1:
            print(f"\nDEBUG: Expected 1 element, got {len(elements)}")
            print(f"Elements found: {elements}")
            self._debug_calculix_content(content)

        # Should have exactly one element (from our mesh)
        self.assertEqual(len(elements), 1, f"Expected 1 element, got {len(elements)}")

        # Element should be a beam type with 2 nodes
        elem = elements[0]
        self.assertIn(
            elem["type"],
            ["B31", "B32"],
            f"Expected beam element type, got {elem['type']}",
        )
        self.assertEqual(
            len(elem["nodes"]),
            2,
            f"Beam element should have 2 nodes, got {len(elem['nodes'])}",
        )

        # Verify no artifacts of dual writing by checking element uniqueness
        # This is a more reliable test than counting lines with commas
        element_ids = [elem["id"] for elem in elements]
        unique_element_ids = set(element_ids)

        self.assertEqual(
            len(element_ids),
            len(unique_element_ids),
            f"Duplicate element IDs found: {element_ids}. This indicates dual writing!",
        )

        # Additional verification: check that we have exactly the expected elements
        # from our simple mesh (1 line element should become 1 beam element)
        beam_elements = [e for e in elements if e.get("type") in ["B31", "B32"]]
        self.assertEqual(
            len(beam_elements),
            1,
            f"Expected exactly 1 beam element, got {len(beam_elements)}",
        )

    def test_unified_writer_direct_processing(self):
        """
        Test the unified writer's direct mesh processing without file I/O.
        This validates the core element processing logic.
        """
        from unittest.mock import MagicMock
        import numpy as np

        # Create unified writer
        writer = UnifiedCalculixWriter(
            domain_model=self.model,
            analysis_config=self.analysis_config,
        )

        # Create a mock mesh with both line and triangle elements
        mock_mesh = MagicMock()
        mock_mesh.points = np.array(
            [
                [0, 0, 0],  # Node 1
                [5, 0, 0],  # Node 2
                [1, 0, 0],  # Node 3
                [1, 1, 0],  # Node 4
            ]
        )

        # Mock the cell structure with both element types
        def mock_cell_items():
            return [
                ("line", np.array([[0, 1]])),  # Line element (beam)
                ("triangle", np.array([[2, 3, 0]])),  # Triangle element (shell)
            ]

        mock_mesh.cells = MagicMock()
        mock_mesh.cells.items = mock_cell_items

        # Process the mesh directly
        writer._process_mesh(mock_mesh)

        # Validate that nodes were processed correctly
        self.assertEqual(
            len(writer.nodes), 4, f"Expected 4 nodes, got {len(writer.nodes)}"
        )

        # Validate that elements were processed correctly
        self.assertEqual(
            len(writer.elements), 2, f"Expected 2 elements, got {len(writer.elements)}"
        )

        # Verify element types are correctly mapped
        element_types = [elem["type"] for elem in writer.elements.values()]
        self.assertIn("B31", element_types, "Expected B31 beam elements")
        self.assertIn("S3", element_types, "Expected S3 shell elements")

        # Map elements to members
        writer._map_elements_to_members()

        # Verify member-specific element sets were created
        # Use short ID mapping
        beam_short_id = writer._get_short_id(self.beam.id)
        plate_short_id = writer._get_short_id(self.plate.id)
        beam_set = f"MEMBER_{beam_short_id}"
        plate_set = f"MEMBER_{plate_short_id}"

        self.assertIn(
            beam_set, writer.element_sets, f"Beam element set {beam_set} not created"
        )
        self.assertIn(
            plate_set, writer.element_sets, f"Plate element set {plate_set} not created"
        )

        # Verify statistics
        stats = writer.get_statistics()
        self.assertEqual(stats["nodes"], 4)
        self.assertEqual(stats["elements"], 2)
        self.assertIn("B31", stats["element_types"])
        self.assertIn("S3", stats["element_types"])

    def _parse_elements_from_content(self, content: str) -> list:
        """
        Parse elements from CalculiX input content.
        Helper method for validation.
        """
        elements = []
        in_element_section = False
        current_element_type = None

        for line in content.split("\n"):
            line = line.strip()

            if line.startswith("*ELEMENT"):
                in_element_section = True
                # Extract element type from header
                current_element_type = None
                if "TYPE=" in line:
                    type_part = line.split("TYPE=")[1].split(",")[0].strip()
                    current_element_type = type_part
                continue
            elif line.startswith("*") and in_element_section:
                in_element_section = False
                current_element_type = None
                continue

            if in_element_section and line and not line.startswith("*"):
                # Parse element definition: element_id, node1, node2, ...
                parts = [p.strip() for p in line.split(",") if p.strip()]
                if len(parts) >= 2:
                    try:
                        elem_id = int(parts[0])
                        nodes = [
                            int(parts[i])
                            for i in range(1, len(parts))
                            if parts[i].isdigit()
                        ]
                        elements.append(
                            {
                                "id": elem_id,
                                "type": current_element_type,
                                "nodes": nodes,
                            }
                        )
                    except ValueError:
                        # Skip lines that don't parse as integers
                        continue

        return elements

    def _debug_calculix_content(self, content: str) -> None:
        """
        Debug helper to understand what's in the CalculiX content.
        """
        lines = content.split("\n")
        print(f"\n=== CalculiX Content Debug ({len(lines)} lines) ===")

        section = "Unknown"
        for i, line in enumerate(lines[:50]):  # Only show first 50 lines
            line_clean = line.strip()

            if line_clean.startswith("*"):
                section = line_clean
                print(f"{i:3d}: [{section}] {line_clean}")
            elif line_clean and not line_clean.startswith("**"):
                print(f"{i:3d}: [{section}] {line_clean}")

        if len(lines) > 50:
            print(f"... and {len(lines) - 50} more lines")
        print("=== End Debug ===\n")


if __name__ == "__main__":
    unittest.main()
