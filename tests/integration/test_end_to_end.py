"""
Enhanced end-to-end test with improved error handling and debugging.
Updated to use the unified CalculiX writer architecture.
"""

# Verbose logging and debugging
import logging
import os
from unittest.mock import patch

import numpy as np
import pytest

from ifc_structural_mechanics.api.structural_analysis import analyze_ifc
from ifc_structural_mechanics.domain.property import Material, Section
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.ifc.extractor import Extractor

# Updated import for unified writer
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    UnifiedCalculixWriter,
)
from ifc_structural_mechanics.utils.temp_dir import (
    cleanup_temp_dir,
    create_temp_file,
    create_temp_subdir,
    setup_temp_dir,
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class MockExtractor(Extractor):
    def __init__(self, ifc_file):
        self.ifc_file = ifc_file

    def extract_model(self):
        # Create a simple model with a beam
        model = StructuralModel(id="test_model", name="Test Model")

        # Create a material
        material = Material(
            id="steel",
            name="Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
        )

        # Create a section for a beam with reduced dimensions
        section = Section.create_rectangular_section(
            id="beam_section", name="Beam Section", width=0.1, height=0.2
        )

        # Add a simple beam member (just one, to reduce element count)
        beam = CurveMember(
            id="beam_1",
            geometry=[(0, 0, 0), (1, 0, 0)],  # Shorter beam
            material=material,
            section=section,
        )

        # Add a fixed boundary condition to the beam at the first point
        class BoundaryCondition:
            def __init__(self, id, type):
                self.id = id
                self.type = type

        beam.boundary_conditions = [BoundaryCondition(id="fixed_end", type="fixed")]

        model.add_member(beam)

        # We'll skip the surface member to reduce complexity and element count
        # This eliminates the issues with shell sections

        return model


class TestEndToEnd:
    """End-to-end test suite for structural analysis workflow."""

    @classmethod
    def setup_class(cls):
        """
        Set up shared resources for all tests.
        """
        # Use the temp_dir utility to set up a base directory for the class
        cls.temp_base_dir = setup_temp_dir(prefix="end_to_end_test_", keep_files=True)

    @classmethod
    def teardown_class(cls):
        """
        Clean up shared resources after all tests.
        """
        # Only force cleanup if the test failed
        cleanup_temp_dir(force=False)

    def test_end_to_end_successful(self):
        """
        End-to-end test that requires real Gmsh and CalculiX functionality.
        """
        # Initialize Gmsh explicitly to check if it's available
        import gmsh

        # Tracking the Gmsh initialization state
        gmsh_initialized = False

        try:
            if not gmsh.isInitialized():
                gmsh.initialize()
                gmsh_initialized = True

            # Verify Gmsh is working by checking a simple operation
            gmsh.option.getNumber("General.Terminal")
        except Exception as e:
            pytest.skip(f"Gmsh initialization failed. This test requires Gmsh: {e}")

        try:
            # Check if CalculiX is available
            from ifc_structural_mechanics.config.system_config import SystemConfig

            system_config = SystemConfig()
            ccx_path = system_config.get_calculix_path()

            if not ccx_path or not os.path.exists(ccx_path):
                pytest.skip(
                    f"CalculiX executable not found at {ccx_path}. This test requires CalculiX."
                )

            # Use a real IFC file that exists in your test data directory
            ifc_path = os.path.join("tests", "test_data", "simple_beam.ifc")
            if not os.path.exists(ifc_path):
                pytest.skip(
                    f"Test IFC file not found: {ifc_path}. This test requires a valid IFC file."
                )

            # Patch the Extractor to use our mock
            with patch(
                "ifc_structural_mechanics.api.structural_analysis.Extractor",
                MockExtractor,
            ):
                # Set a fixed temporary directory
                fixed_temp_dir = create_temp_subdir(prefix="end_to_end_analysis_")

                # Patch the tempfile.mkdtemp and system config to use our fixed directory
                with patch("tempfile.mkdtemp", return_value=fixed_temp_dir):
                    with patch(
                        "ifc_structural_mechanics.config.system_config.SystemConfig.get_temp_directory",
                        return_value=fixed_temp_dir,
                    ):
                        # Execute the analysis
                        try:
                            result = analyze_ifc(
                                ifc_path=ifc_path,
                                output_dir=fixed_temp_dir,
                                analysis_type="linear_static",
                                mesh_size=0.1,
                                verbose=True,
                            )
                        except Exception:
                            # Debug output - save files for inspection
                            mesh_file = os.path.join(fixed_temp_dir, "mesh.msh")
                            inp_file = os.path.join(fixed_temp_dir, "model.inp")
                            analysis_file = os.path.join(fixed_temp_dir, "analysis.inp")

                            # Log file existence
                            logger.error(
                                f"Mesh file exists: {os.path.exists(mesh_file)}"
                            )
                            logger.error(
                                f"Input file exists: {os.path.exists(inp_file)}"
                            )
                            logger.error(
                                f"Analysis file exists: {os.path.exists(analysis_file)}"
                            )

                            # Detailed file content logging
                            for file_path in [mesh_file, inp_file, analysis_file]:
                                if os.path.exists(file_path):
                                    logger.error(
                                        f"Contents of {os.path.basename(file_path)}:"
                                    )
                                    with open(file_path, "r") as f:
                                        logger.error(f.read())

                            raise

                        # Check the result
                        assert result["status"] == "success"
                        assert "output_files" in result

                        # Log all output files for debugging
                        for file_type, file_path in result["output_files"].items():
                            logger.info(f"Output file: {file_type} - {file_path}")
                            assert os.path.exists(
                                file_path
                            ), f"File not found: {file_path}"

        finally:
            # Finalize Gmsh after test
            if gmsh_initialized and gmsh.isInitialized():
                try:
                    gmsh.finalize()
                except Exception as e:
                    logger.warning(f"Error finalizing Gmsh: {e}")


def test_unified_writer_writes_correct_element_types():
    """
    Test that UnifiedCalculixWriter writes element types correctly.
    Updated to use the new unified architecture.
    """
    from ifc_structural_mechanics.config.analysis_config import AnalysisConfig
    from ifc_structural_mechanics.domain.property import Material, Section
    from ifc_structural_mechanics.domain.structural_member import CurveMember
    from ifc_structural_mechanics.domain.structural_model import StructuralModel

    # Create a simple domain model with a beam
    model = StructuralModel(id="test_model", name="Test Model")

    # Create material and section
    material = Material(
        id="steel",
        name="Steel",
        density=7850.0,
        elastic_modulus=210e9,
        poisson_ratio=0.3,
    )

    section = Section.create_rectangular_section(
        id="beam_section", name="Beam Section", width=0.1, height=0.2
    )

    # Create a beam member
    beam = CurveMember(
        id="beam_1",
        geometry=[(0, 0, 0), (1, 0, 0)],
        material=material,
        section=section,
    )

    model.add_member(beam)

    # Create analysis configuration
    analysis_config = AnalysisConfig()

    # Use temp_dir utility for the output file
    output_file = create_temp_file(prefix="test_unified_writer_", suffix=".inp")

    # Initialize unified writer with correct parameters
    writer = UnifiedCalculixWriter(
        domain_model=model,
        analysis_config=analysis_config,
    )

    # Create a simple mock mesh with line elements
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".msh", delete=False) as f:
        # Write a simple Gmsh mesh file with line elements
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
        mesh_file = f.name

    try:
        # Convert mesh using unified writer
        writer.write_calculix_input_from_mesh(mesh_file, output_file)

        # Read the content
        with open(output_file, "r") as f:
            content = f.read()

        # Verify basic CalculiX structure is present
        assert "*NODE" in content, "Node section is missing"
        assert "*ELEMENT" in content, "Element section is missing"

        # For line elements, we expect B31 (beam) elements in the unified writer
        # The exact element type depends on how the unified writer maps domain members
        assert any(
            elem_type in content for elem_type in ["B31", "B32"]
        ), "Expected beam element type (B31 or B32) not found in content"

    finally:
        # Clean up temporary mesh file
        if os.path.exists(mesh_file):
            os.unlink(mesh_file)


def test_unified_writer_element_preservation():
    """
    Test that the unified writer preserves triangular element topology correctly.
    This is the key validation that replaces the old dual-system coordination tests.
    """
    from ifc_structural_mechanics.config.analysis_config import AnalysisConfig
    from ifc_structural_mechanics.domain.property import Material, Thickness
    from ifc_structural_mechanics.domain.structural_member import SurfaceMember
    from ifc_structural_mechanics.domain.structural_model import StructuralModel

    # Create a surface model that will generate triangular elements
    model = StructuralModel(id="test_model", name="Test Model")

    material = Material(
        id="steel",
        name="Steel",
        density=7850.0,
        elastic_modulus=210e9,
        poisson_ratio=0.3,
    )

    thickness = Thickness(id="thickness_1", name="Plate Thickness", value=0.01)

    # Create a surface member (plate)
    plate = SurfaceMember(
        id="plate_1",
        geometry={
            "type": "plane",
            "boundaries": [[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]],
        },
        material=material,
        thickness=thickness,
    )

    model.add_member(plate)

    # Create analysis configuration
    analysis_config = AnalysisConfig()

    output_file = create_temp_file(prefix="test_element_preservation_", suffix=".inp")

    # Create unified writer with correct parameters
    writer = UnifiedCalculixWriter(
        domain_model=model,
        analysis_config=analysis_config,
    )

    # Create a mock mesh file with triangular elements (S3)
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".msh", delete=False) as f:
        # Write a Gmsh mesh file with triangular elements
        f.write(
            """$MeshFormat
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
        )
        mesh_file = f.name

    try:
        # Process mesh with unified writer
        writer.write_calculix_input_from_mesh(mesh_file, output_file)

        # Read and parse the generated content
        with open(output_file, "r") as f:
            content = f.read()

        # Parse elements from the content
        elements = _parse_elements_from_content(content)

        # Find S3 (triangular shell) elements
        s3_elements = [e for e in elements if e.get("type") == "S3"]

        # Key validation: S3 elements must have exactly 3 nodes (triangular topology preserved)
        for elem in s3_elements:
            assert len(elem["nodes"]) == 3, (
                f"S3 element {elem['id']} has {len(elem['nodes'])} nodes, expected 3. "
                f"Triangular topology not preserved!"
            )

        # Verify we actually found some triangular elements to test
        if s3_elements:
            logger.info(
                f"Successfully validated {len(s3_elements)} S3 triangular elements"
            )
        else:
            # If no S3 elements, check for other shell elements that should preserve topology
            shell_elements = [
                e for e in elements if e.get("type") in ["S3", "S4", "S6", "S8"]
            ]
            assert len(shell_elements) > 0, "No shell elements found in output"
            logger.info(f"Found {len(shell_elements)} shell elements")

    finally:
        # Clean up
        if os.path.exists(mesh_file):
            os.unlink(mesh_file)


def test_unified_writer_direct_mesh_processing():
    """
    Test the unified writer's mesh processing capabilities directly.
    This validates the core functionality that replaces the dual system.
    """
    from unittest.mock import MagicMock

    from ifc_structural_mechanics.config.analysis_config import AnalysisConfig
    from ifc_structural_mechanics.domain.property import Material, Section, Thickness
    from ifc_structural_mechanics.domain.structural_member import (
        CurveMember,
        SurfaceMember,
    )
    from ifc_structural_mechanics.domain.structural_model import StructuralModel

    # Create a model with both curve and surface members
    model = StructuralModel(id="test_model", name="Test Model")

    material = Material(
        id="steel",
        name="Steel",
        density=7850.0,
        elastic_modulus=210e9,
        poisson_ratio=0.3,
    )

    # Add a beam
    section = Section.create_rectangular_section(
        id="beam_section", name="Beam Section", width=0.1, height=0.2
    )

    beam = CurveMember(
        id="beam_1",
        geometry=[(0, 0, 0), (1, 0, 0)],
        material=material,
        section=section,
    )
    model.add_member(beam)

    # Add a surface
    thickness = Thickness(id="thickness_1", name="Plate Thickness", value=0.01)

    plate = SurfaceMember(
        id="plate_1",
        geometry={
            "boundaries": [[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]],
        },
        material=material,
        thickness=thickness,
    )
    model.add_member(plate)

    # Create unified writer
    analysis_config = AnalysisConfig()
    writer = UnifiedCalculixWriter(
        domain_model=model,
        analysis_config=analysis_config,
    )

    # Create a mock mesh with both line and triangle elements
    mock_mesh = MagicMock()
    mock_mesh.points = np.array(
        [
            [0, 0, 0],  # Node 1
            [1, 0, 0],  # Node 2
            [1, 1, 0],  # Node 3
            [0, 1, 0],  # Node 4
        ]
    )

    # Mock the cell structure
    def mock_cell_items():
        return [
            ("line", np.array([[0, 1]])),  # Line element (beam)
            ("triangle", np.array([[1, 2, 3], [0, 2, 3]])),  # Triangle elements (shell)
        ]

    mock_mesh.cells = MagicMock()
    mock_mesh.cells.items = mock_cell_items

    # Process the mesh directly
    writer._process_mesh(mock_mesh)

    # Validate that nodes were processed correctly
    assert len(writer.nodes) == 4, f"Expected 4 nodes, got {len(writer.nodes)}"

    # Validate that elements were processed correctly
    assert len(writer.elements) == 3, f"Expected 3 elements, got {len(writer.elements)}"

    # Verify element types are correctly mapped
    element_types = [elem["type"] for elem in writer.elements.values()]
    assert "B31" in element_types, "Expected B31 beam elements"
    assert "S3" in element_types, "Expected S3 shell elements"

    # Map elements to members
    writer._map_elements_to_members()

    # Verify member-specific element sets were created
    # Use short ID mapping
    beam_short_id = writer._get_short_id(beam.id)
    plate_short_id = writer._get_short_id(plate.id)
    beam_set = f"MEMBER_{beam_short_id}"
    plate_set = f"MEMBER_{plate_short_id}"

    assert beam_set in writer.element_sets, f"Beam element set {beam_set} not created"
    assert (
        plate_set in writer.element_sets
    ), f"Plate element set {plate_set} not created"

    # Verify statistics
    stats = writer.get_statistics()
    assert stats["nodes"] == 4
    assert stats["elements"] == 3
    assert "B31" in stats["element_types"]
    assert "S3" in stats["element_types"]

    logger.info(f"Unified writer statistics: {stats}")


def _parse_elements_from_content(content: str) -> list:
    """
    Parse elements from CalculiX input content.
    This helper function replaces the complex dual-system validation logic.
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
                        {"id": elem_id, "type": current_element_type, "nodes": nodes}
                    )
                except ValueError:
                    # Skip lines that don't parse as integers
                    continue

    return elements
