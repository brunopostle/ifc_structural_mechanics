"""
Comprehensive test suite for the UnifiedCalculixWriter.

This test suite verifies that the unified approach correctly:
1. Processes Gmsh mesh data 
2. Writes CalculiX input files
3. Preserves triangular element topology
4. Maps elements to domain model members
5. Eliminates dual element writing conflicts
"""

import pytest
from unittest.mock import MagicMock, patch, mock_open

import numpy as np
import meshio

from src.ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
    generate_calculix_input,
    run_complete_analysis_workflow,
)
from src.ifc_structural_mechanics.domain.structural_model import StructuralModel
from src.ifc_structural_mechanics.domain.structural_member import (
    CurveMember,
    SurfaceMember,
)
from src.ifc_structural_mechanics.domain.property import Material, Section, Thickness
from src.ifc_structural_mechanics.domain.load import PointLoad, AreaLoad, LoadGroup
from src.ifc_structural_mechanics.config.analysis_config import AnalysisConfig
from src.ifc_structural_mechanics.config.meshing_config import MeshingConfig
from src.ifc_structural_mechanics.config.system_config import SystemConfig
from src.ifc_structural_mechanics.utils.error_handling import (
    AnalysisError,
)
from src.ifc_structural_mechanics.utils.temp_dir import (
    setup_temp_dir,
    cleanup_temp_dir,
    create_temp_file,
    set_keep_temp_files,
)

# Configure for debugging
set_keep_temp_files(keep_files=True)


class TestUnifiedCalculixWriter:
    """Test suite for the UnifiedCalculixWriter class."""

    @classmethod
    def setup_class(cls):
        """Set up shared resources for all tests."""
        cls.temp_base_dir = setup_temp_dir(prefix="unified_calculix_test_")

    @classmethod
    def teardown_class(cls):
        """Clean up shared resources after all tests."""
        cleanup_temp_dir(force=False)

    def setup_method(self):
        """Set up test fixtures before each test method."""
        # Create a comprehensive structural model for testing
        self.model = self._create_test_structural_model()

        # Create configurations
        self.analysis_config = AnalysisConfig()
        self.meshing_config = MeshingConfig()
        self.system_config = SystemConfig()

        # Create the unified writer
        self.writer = UnifiedCalculixWriter(
            domain_model=self.model,
            analysis_config=self.analysis_config,
        )

    def _create_test_structural_model(self):
        """Create a comprehensive test structural model."""
        model = StructuralModel(id="test_unified_model", name="Unified Test Model")

        # Create materials
        steel = Material(
            id="steel_1",
            name="Structural Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
            yield_strength=355e6,
        )

        concrete = Material(
            id="concrete_1",
            name="Concrete C30/37",
            density=2500.0,
            elastic_modulus=33e9,
            poisson_ratio=0.2,
        )

        # Create sections
        beam_section = Section.create_rectangular_section(
            id="beam_rect_1", name="300x600 Beam", width=0.3, height=0.6
        )

        column_section = Section.create_circular_section(
            id="column_circ_1", name="400mm Column", radius=0.2
        )

        # Create thickness
        slab_thickness = Thickness(id="slab_thick_1", name="200mm Slab", value=0.2)

        # Create beam member
        beam = CurveMember(
            id="beam_1",
            geometry=((0, 0, 3), (6, 0, 3)),  # 6m beam at 3m height
            material=steel,
            section=beam_section,
        )

        # Create column member
        column = CurveMember(
            id="column_1",
            geometry=((0, 0, 0), (0, 0, 3)),  # 3m column
            material=concrete,
            section=column_section,
        )

        # Create slab member
        slab = SurfaceMember(
            id="slab_1",
            geometry={
                "boundaries": [
                    [(0, 0, 3), (6, 0, 3), (6, 4, 3), (0, 4, 3)]  # 6x4m slab
                ]
            },
            material=concrete,
            thickness=slab_thickness,
        )

        # Add members to model
        model.add_member(beam)
        model.add_member(column)
        model.add_member(slab)

        # Create loads
        point_load = PointLoad(
            id="load_1", magnitude=10000.0, direction=[0, 0, -1], position=[3, 2, 3]
        )

        area_load = AreaLoad(
            id="load_2",
            magnitude=5000.0,
            direction=[0, 0, -1],
            surface_reference="slab_1",
        )

        # Create load group
        load_group = LoadGroup(id="load_group_1", name="Design Loads")
        load_group.add_load(point_load)
        load_group.add_load(area_load)
        model.add_load_group(load_group)

        return model

    def _create_test_mesh(self):
        """Create a test mesh with triangular and beam elements."""
        # Create nodes
        points = np.array(
            [
                [0.0, 0.0, 0.0],  # 0 - column base
                [0.0, 0.0, 3.0],  # 1 - beam/column junction
                [6.0, 0.0, 3.0],  # 2 - beam end
                [0.0, 4.0, 3.0],  # 3 - slab corner
                [6.0, 4.0, 3.0],  # 4 - slab corner
                [3.0, 2.0, 3.0],  # 5 - slab center
            ]
        )

        # Create elements
        cells = [
            ("line", np.array([[0, 1], [1, 2]])),  # Column and beam elements
            (
                "triangle",
                np.array([[1, 3, 5], [1, 5, 2], [2, 5, 4], [3, 4, 5]]),
            ),  # Slab triangles
        ]

        return meshio.Mesh(points=points, cells=cells)

    def test_initialization(self):
        """Test that UnifiedCalculixWriter initializes correctly."""
        # Test basic initialization
        assert self.writer.domain_model == self.model
        assert self.writer.analysis_config == self.analysis_config
        assert isinstance(self.writer.nodes, dict)
        assert isinstance(self.writer.elements, dict)
        assert isinstance(self.writer.element_sets, dict)
        assert isinstance(self.writer.node_sets, dict)

        # Test that validation passed
        assert len(self.model.members) == 3

    def test_process_mesh(self):
        """Test processing of mesh data into internal structures."""
        test_mesh = self._create_test_mesh()

        # Process the mesh
        self.writer._process_mesh(test_mesh)

        # Verify nodes were processed
        assert len(self.writer.nodes) == 6
        assert self.writer.nodes[1] == (0.0, 0.0, 0.0)  # 1-based indexing
        assert self.writer.nodes[6] == (3.0, 2.0, 3.0)

        # Verify elements were processed
        assert len(self.writer.elements) > 0

        # Check element types
        element_types = set(elem["type"] for elem in self.writer.elements.values())
        assert "B31" in element_types  # Beam elements from lines
        assert "S3" in element_types  # Triangular shell elements

        # Verify element sets were created
        assert "ELSET_LINE" in self.writer.element_sets
        assert "ELSET_TRIANGLE" in self.writer.element_sets
        assert len(self.writer.element_sets["ELSET_LINE"]) == 2  # 2 line elements
        assert (
            len(self.writer.element_sets["ELSET_TRIANGLE"]) == 4
        )  # 4 triangle elements

        # Check element connectivity preservation
        triangle_elements = [
            elem for elem in self.writer.elements.values() if elem["type"] == "S3"
        ]

        for elem in triangle_elements:
            # Each triangle should have exactly 3 nodes
            assert (
                len(elem["nodes"]) == 3
            ), f"S3 element has {len(elem['nodes'])} nodes, should be 3"

            # Node indices should be valid (1-based)
            for node_id in elem["nodes"]:
                assert 1 <= node_id <= 6, f"Invalid node ID: {node_id}"

    def test_map_elements_to_members(self):
        """Test mapping of mesh elements to domain model members."""
        test_mesh = self._create_test_mesh()

        # Process mesh and map elements
        self.writer._process_mesh(test_mesh)
        self.writer._map_elements_to_members()

        # Verify member-specific element sets were created
        curve_members = [m for m in self.model.members if m.entity_type == "curve"]
        surface_members = [m for m in self.model.members if m.entity_type == "surface"]

        for member in curve_members:
            # Use short ID mapping
            short_id = self.writer._get_short_id(member.id)
            member_set = f"MEMBER_{short_id}"
            assert member_set in self.writer.element_sets
            assert member_set in self.writer.defined_element_sets
            assert len(self.writer.element_sets[member_set]) > 0

        for member in surface_members:
            # Use short ID mapping
            short_id = self.writer._get_short_id(member.id)
            member_set = f"MEMBER_{short_id}"
            assert member_set in self.writer.element_sets
            assert member_set in self.writer.defined_element_sets
            assert len(self.writer.element_sets[member_set]) > 0

    @patch("meshio.read")
    def test_write_calculix_input_from_mesh(self, mock_meshio_read):
        """Test the main method that writes CalculiX input from mesh."""
        # Create temporary files
        mesh_file = create_temp_file(prefix="test_mesh", suffix=".msh")
        output_file = create_temp_file(prefix="unified_output", suffix=".inp")

        # Create mock mesh object to return from meshio.read
        mock_mesh = self._create_test_mesh()
        mock_meshio_read.return_value = mock_mesh

        # Mock file operations to capture content
        written_content = []

        def mock_write_method(content):
            written_content.append(content)
            return len(content)

        mock_file_handle = MagicMock()
        mock_file_handle.write = mock_write_method

        with patch("builtins.open", mock_open()) as mock_file:
            mock_file.return_value.__enter__.return_value = mock_file_handle

            # Write CalculiX input
            result = self.writer.write_calculix_input_from_mesh(
                mesh_file=mesh_file, output_file=output_file
            )

        # Verify result
        assert result == output_file

        # Verify meshio.read was called with the correct file
        mock_meshio_read.assert_called_once_with(mesh_file)

        # Verify content was written
        full_content = "".join(written_content)

        # Check for required sections
        assert "** CalculiX Input File - Unified Writer" in full_content
        assert "*NODE" in full_content
        assert "*ELEMENT" in full_content
        assert "TYPE=B31" in full_content  # Beam elements
        assert "TYPE=S3" in full_content  # Triangular shell elements
        assert "*ELSET" in full_content
        assert "*MATERIAL" in full_content
        assert "*BEAM SECTION" in full_content
        assert "*SHELL SECTION" in full_content
        assert "*STEP" in full_content
        assert "*END STEP" in full_content

    def test_element_type_mapping(self):
        """Test that Gmsh element types are correctly mapped to CalculiX types."""
        # Test the mapping dictionary
        mapping = UnifiedCalculixWriter.ELEMENT_TYPE_MAPPING

        assert mapping["line"] == "B31"
        assert mapping["triangle"] == "S3"
        assert mapping["quad"] == "S4"
        assert mapping["tetra"] == "C3D4"

        # Test with actual mesh processing
        test_mesh = self._create_test_mesh()
        self.writer._process_mesh(test_mesh)

        # Verify correct element types were assigned
        line_elements = [e for e in self.writer.elements.values() if e["type"] == "B31"]
        triangle_elements = [
            e for e in self.writer.elements.values() if e["type"] == "S3"
        ]

        assert len(line_elements) == 2  # 2 line elements
        assert len(triangle_elements) == 4  # 4 triangle elements

    def test_no_dual_element_writing(self):
        """Test that only one system writes elements (no conflicts)."""
        test_mesh = self._create_test_mesh()

        # Process mesh
        self.writer._process_mesh(test_mesh)

        # Get initial element count
        initial_element_count = len(self.writer.elements)
        initial_elements = set(self.writer.elements.keys())

        # Map elements to members
        self.writer._map_elements_to_members()

        # Verify element count didn't change (no regeneration)
        assert len(self.writer.elements) == initial_element_count
        assert set(self.writer.elements.keys()) == initial_elements

        # Verify elements maintain their original types and connectivity
        for elem_id, elem_data in self.writer.elements.items():
            if elem_data["type"] == "S3":
                assert len(elem_data["nodes"]) == 3, "S3 elements must have 3 nodes"
            elif elem_data["type"] == "B31":
                assert len(elem_data["nodes"]) == 2, "B31 elements must have 2 nodes"

    def test_triangular_element_preservation(self):
        """Test that triangular elements from Gmsh are preserved correctly."""
        test_mesh = self._create_test_mesh()
        self.writer._process_mesh(test_mesh)

        # Find all S3 elements
        s3_elements = [
            (elem_id, elem_data)
            for elem_id, elem_data in self.writer.elements.items()
            if elem_data["type"] == "S3"
        ]

        # Verify we have S3 elements
        assert len(s3_elements) > 0, "Should have S3 triangular elements"

        # Verify each S3 element has exactly 3 nodes
        for elem_id, elem_data in s3_elements:
            nodes = elem_data["nodes"]
            assert (
                len(nodes) == 3
            ), f"S3 element {elem_id} has {len(nodes)} nodes, should be 3"

            # Verify nodes are valid
            for node_id in nodes:
                assert (
                    node_id in self.writer.nodes
                ), f"Node {node_id} not found in node list"

    def test_material_and_section_writing(self):
        """Test writing of materials and sections."""
        test_mesh = self._create_test_mesh()

        # Process mesh and map elements
        self.writer._process_mesh(test_mesh)
        self.writer._map_elements_to_members()

        # Mock file handle
        written_content = []

        def mock_write(content):
            written_content.append(content)

        mock_file = MagicMock()
        mock_file.write = mock_write

        # Write materials
        self.writer._write_materials(mock_file)

        materials_content = "".join(written_content)
        assert "*MATERIAL, NAME=MAT_steel_1" in materials_content
        assert "*MATERIAL, NAME=MAT_concrete_1" in materials_content
        assert "*ELASTIC" in materials_content

        # Reset and write sections
        written_content.clear()
        self.writer._write_sections(mock_file)

        sections_content = "".join(written_content)
        assert "*BEAM SECTION" in sections_content
        assert "*SHELL SECTION" in sections_content

    def test_element_set_validation(self):
        """Test element set validation and tracking."""
        test_mesh = self._create_test_mesh()
        self.writer._process_mesh(test_mesh)
        self.writer._map_elements_to_members()

        # Check that element sets are properly tracked
        assert len(self.writer.defined_element_sets) > 0

        # Verify element sets contain actual elements
        for set_name in self.writer.defined_element_sets:
            assert set_name in self.writer.element_sets
            assert len(self.writer.element_sets[set_name]) > 0

        # Test element set validation
        for set_name in self.writer.element_sets:
            if self.writer.element_sets[set_name]:  # Non-empty sets
                # All elements in set should exist
                for elem_id in self.writer.element_sets[set_name]:
                    assert elem_id in self.writer.elements

    def test_statistics_generation(self):
        """Test generation of processing statistics."""
        test_mesh = self._create_test_mesh()
        self.writer._process_mesh(test_mesh)

        stats = self.writer.get_statistics()

        assert "nodes" in stats
        assert "elements" in stats
        assert "element_sets" in stats
        assert "element_types" in stats

        assert stats["nodes"] == 6
        assert stats["elements"] > 0
        assert "B31" in stats["element_types"]
        assert "S3" in stats["element_types"]


class TestUnifiedWorkflowFunctions:
    """Test the convenience functions and complete workflow."""

    @classmethod
    def setup_class(cls):
        """Set up shared resources for all tests."""
        cls.temp_base_dir = setup_temp_dir(prefix="unified_workflow_test_")

    def setup_method(self):
        """Set up test fixtures."""
        self.model = self._create_simple_model()

    def _create_simple_model(self):
        """Create a simple model for workflow testing."""
        model = StructuralModel(id="simple_workflow", name="Simple Workflow Model")

        steel = Material(
            id="steel",
            name="Steel",
            elastic_modulus=210e9,
            poisson_ratio=0.3,
            density=7850,
        )

        section = Section.create_rectangular_section(
            id="beam_section", name="Standard Beam", width=0.2, height=0.3
        )

        beam = CurveMember(
            id="beam_simple",
            geometry=((0, 0, 0), (5, 0, 0)),
            material=steel,
            section=section,
        )

        model.add_member(beam)
        return model

    @patch("meshio.read")
    def test_generate_calculix_input_function(self, mock_read):
        """Test the generate_calculix_input convenience function."""
        # Create temporary files
        mesh_file = create_temp_file(prefix="workflow_mesh", suffix=".msh")
        output_file = create_temp_file(prefix="workflow_output", suffix=".inp")

        # Mock mesh reading
        mock_mesh = self._create_mock_mesh()
        mock_read.return_value = mock_mesh

        # Mock file writing
        with patch("builtins.open", mock_open()) as mock_file:
            result = generate_calculix_input(
                domain_model=self.model, mesh_file=mesh_file, output_file=output_file
            )

        assert result == output_file
        mock_read.assert_called_once_with(mesh_file)
        mock_file.assert_called()

    def _create_mock_mesh(self):
        """Create a mock mesh for testing."""
        mock_mesh = MagicMock()
        mock_mesh.points = np.array([[0, 0, 0], [5, 0, 0]])

        # Mock cells in a way that works with our processing
        def mock_items():
            return [("line", np.array([[0, 1]]))]

        mock_mesh.cells = MagicMock()
        mock_mesh.cells.items = mock_items

        return mock_mesh

    def test_run_complete_analysis_workflow_interface(self):
        """Test that the workflow function exists and has correct interface."""
        # Test 1: Function exists and is callable
        assert callable(run_complete_analysis_workflow)

        # Test 2: Function signature is correct
        import inspect

        sig = inspect.signature(run_complete_analysis_workflow)
        expected_params = ["domain_model", "output_inp_file"]
        actual_params = list(sig.parameters.keys())

        for param in expected_params:
            assert param in actual_params, f"Missing parameter: {param}"

    def test_unified_writer_core_functionality(self):
        """Test core unified writer functionality without external dependencies."""

        # Test that we can create a writer
        writer = UnifiedCalculixWriter(domain_model=self.model)

        # Test internal mesh processing using the mock mesh method
        test_mesh = self._create_mock_mesh()
        writer._process_mesh(test_mesh)

        # Verify core functionality: no dual element writing
        initial_element_count = len(writer.elements)
        initial_elements = set(writer.elements.keys())

        # Map elements to members
        writer._map_elements_to_members()

        # Verify no dual writing occurred
        assert len(writer.elements) == initial_element_count
        assert set(writer.elements.keys()) == initial_elements

        # Verify elements exist
        assert len(writer.elements) > 0, "Should have processed some elements"

    @patch("meshio.read")
    @patch("builtins.open", mock_open())
    def test_write_calculix_input_from_mesh_mocked(self, mock_meshio_read):
        """Test the main unified writer method with proper mocking."""

        # Mock meshio.read to return test mesh
        mock_mesh = self._create_mock_mesh()
        mock_meshio_read.return_value = mock_mesh

        # Create a writer for this test
        writer = UnifiedCalculixWriter(domain_model=self.model)

        # Test the unified writer
        mesh_file = "dummy.msh"
        output_file = "dummy.inp"

        try:
            result = writer.write_calculix_input_from_mesh(
                mesh_file=mesh_file, output_file=output_file
            )
            assert result == output_file
            mock_meshio_read.assert_called_once_with(mesh_file)
        except ImportError:
            pytest.skip("External dependencies not available")

    def test_workflow_error_handling(self):
        """Test error handling in the workflow functions - simplified version."""
        # Test with invalid domain model
        with pytest.raises(AnalysisError):
            writer = UnifiedCalculixWriter(domain_model=None)

        # Test with empty domain model
        empty_model = StructuralModel(id="empty", name="Empty")
        with pytest.raises(AnalysisError):
            writer = UnifiedCalculixWriter(domain_model=empty_model)

    def test_workflow_function_exists(self):
        """Test that workflow functions exist and are callable."""
        # These are interface tests - just verify the functions exist
        assert callable(run_complete_analysis_workflow)
        assert callable(generate_calculix_input)

        # Test function signatures
        import inspect

        workflow_sig = inspect.signature(run_complete_analysis_workflow)
        assert "domain_model" in workflow_sig.parameters
        assert "output_inp_file" in workflow_sig.parameters

        generate_sig = inspect.signature(generate_calculix_input)
        assert "domain_model" in generate_sig.parameters


class TestMigrationAndCompatibility:
    """Test migration from old dual system to unified approach."""

    def test_backward_compatibility(self):
        """Test that the unified writer can handle old-style inputs."""
        # This would test compatibility with existing code patterns
        # For now, just verify the basic interface exists

        assert hasattr(UnifiedCalculixWriter, "write_calculix_input_from_mesh")
        assert callable(generate_calculix_input)
        assert callable(run_complete_analysis_workflow)

    def test_element_format_compatibility(self):
        """Test that element formats are compatible with CalculiX."""
        # Create model with at least one member
        model = StructuralModel(id="test", name="Test")

        material = Material(
            id="steel",
            name="Steel",
            elastic_modulus=210e9,
            poisson_ratio=0.3,
            density=7850.0,  # ✅ Include required density
        )

        section = Section.create_rectangular_section(
            id="section", name="Test Section", width=0.1, height=0.2
        )

        member = CurveMember(
            id="test_member",
            geometry=[(0, 0, 0), (1, 0, 0)],
            material=material,
            section=section,
        )

        model.add_member(member)  # ✅ Add member to avoid validation error

        writer = UnifiedCalculixWriter(domain_model=model)

        # Test element type mappings are valid CalculiX types
        valid_calculix_types = {
            "B31",
            "B32",
            "S3",
            "S4",
            "S6",
            "S8",
            "S9",
            "C3D4",
            "C3D8",
            "C3D10",
            "C3D20",
            "C3D27",
        }

        for gmsh_type, calculix_type in writer.ELEMENT_TYPE_MAPPING.items():
            assert (
                calculix_type in valid_calculix_types
            ), f"Invalid CalculiX type: {calculix_type}"


class TestPerformanceAndScaling:
    """Test performance characteristics of the unified approach."""

    def test_large_mesh_handling(self):
        """Test handling of larger meshes."""
        # Create a larger test mesh
        n_nodes = 1000
        points = np.random.rand(n_nodes, 3) * 10

        # Create triangular elements
        n_triangles = 500
        triangles = np.random.randint(0, n_nodes, size=(n_triangles, 3))

        large_mesh = meshio.Mesh(points=points, cells=[("triangle", triangles)])

        # Create a simple model
        model = StructuralModel(id="large_test", name="Large Test")
        steel = Material(
            id="steel",
            name="Steel",
            elastic_modulus=210e9,
            poisson_ratio=0.3,
            density=7850.0,  # ✅ Add required density
        )
        thickness = Thickness(id="thick", name="Thick", value=0.1)

        surface = SurfaceMember(
            id="large_surface",
            geometry={"boundaries": [[(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]]},
            material=steel,
            thickness=thickness,
        )
        model.add_member(surface)

        # Test processing
        writer = UnifiedCalculixWriter(domain_model=model)
        writer._process_mesh(large_mesh)

        # Verify processing completed
        assert len(writer.nodes) == n_nodes
        assert len(writer.elements) == n_triangles

        # Verify all elements are S3 type with 3 nodes
        for elem_data in writer.elements.values():
            assert elem_data["type"] == "S3"
            assert len(elem_data["nodes"]) == 3

    def test_memory_efficiency(self):
        """Test that the unified approach doesn't duplicate element data."""
        model = StructuralModel(id="memory_test", name="Memory Test")

        # Add a member to avoid validation error
        material = Material(
            id="mat",
            name="Material",
            elastic_modulus=210e9,
            poisson_ratio=0.3,
            density=7850.0,  # ✅ Add required density
        )
        section = Section.create_rectangular_section(
            id="sec", name="Section", width=0.1, height=0.2
        )
        member = CurveMember(
            id="mem",
            geometry=[(0, 0, 0), (1, 0, 0)],
            material=material,
            section=section,
        )
        model.add_member(member)

        writer = UnifiedCalculixWriter(domain_model=model)

        # Process a mesh
        test_mesh = meshio.Mesh(
            points=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]]),
            cells=[("triangle", np.array([[0, 1, 2]]))],
        )

        writer._process_mesh(test_mesh)

        # Verify elements are stored only once
        assert len(writer.elements) == 1

        # Map to members
        writer._map_elements_to_members()

        # Verify elements are still stored only once (no duplication)
        assert len(writer.elements) == 1


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main(["-v", __file__])
