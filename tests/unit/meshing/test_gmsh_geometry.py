"""
Unit tests for the Gmsh Geometry Converter.

These tests verify the functionality of converting domain model 
geometric representations to Gmsh geometry objects.
"""

import uuid
from unittest.mock import patch

import pytest
import numpy as np
import gmsh

from ifc_structural_mechanics.config.meshing_config import MeshingConfig
from ifc_structural_mechanics.meshing.gmsh_geometry import GmshGeometryConverter
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.property import Material, Section, Thickness


@pytest.fixture(scope="module", autouse=True)
def gmsh_init():
    """Initialize Gmsh for the test module."""
    # Check if Gmsh is already initialized
    try:
        # Initialize Gmsh if it's not already initialized
        if not gmsh.isInitialized():
            gmsh.initialize()
            print("Successfully initialized Gmsh")
        else:
            print("Gmsh was already initialized")

        # Verify initialization worked by performing a simple Gmsh operation
        gmsh.option.getNumber("General.Terminal")
        print("Gmsh verification successful")

    except Exception as e:
        # Instead of skipping, fail the tests explicitly
        pytest.fail(f"Gmsh initialization failed: {e}")

    # Ensure consistent model state
    try:
        # Try to create a new model
        gmsh.model.add("test_model")
    except Exception:
        # If that fails, try to remove existing model first
        try:
            gmsh.model.remove()
            gmsh.model.add("test_model")
        except Exception as nested_e:
            pytest.fail(f"Error setting up Gmsh model: {nested_e}")

    yield

    # Don't finalize Gmsh if it was already initialized when we started
    if not gmsh.isInitialized():
        pytest.fail("Gmsh not initialized after tests")

    # We'll leave the cleanup to the application itself
    # instead of finalizing here, which might disrupt other tests


@pytest.fixture
def meshing_config():
    """Create a default meshing configuration for testing."""
    return MeshingConfig()


@pytest.fixture
def gmsh_converter(meshing_config):
    """Create a Gmsh geometry converter with default configuration."""
    # Create a converter but suppress its own initialization attempts
    with patch.object(GmshGeometryConverter, "__init__", return_value=None):
        converter = GmshGeometryConverter.__new__(GmshGeometryConverter)

    # Set up the converter manually with all required attributes
    converter.meshing_config = meshing_config
    converter._entity_map = {}
    converter._we_initialized_gmsh = False
    converter._gmsh_checked = False  # Add this missing attribute

    return converter


def generate_unique_id():
    """Generate a unique identifier."""
    return str(uuid.uuid4())


def test_point_conversion(gmsh_converter):
    """Test point conversion methods."""
    # Test valid 3D point
    point = [1.0, 2.0, 3.0]
    converted_point = gmsh_converter._convert_point(point)

    assert isinstance(converted_point, np.ndarray)
    assert converted_point.shape == (3,)
    np.testing.assert_array_almost_equal(converted_point, point)

    # Test invalid point raises NotImplementedError
    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_point([1.0, 2.0])  # Incorrect dimensions
    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_point("not a point")


def test_curve_conversion(gmsh_converter):
    """Test curve conversion methods."""
    # Test valid curve (list of 3D points)
    curve_points = [[0.0, 0.0, 0.0], [1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    converted_curve = gmsh_converter._convert_curve(curve_points)

    assert len(converted_curve) == 3
    assert all(isinstance(p, np.ndarray) and p.shape == (3,) for p in converted_curve)

    # Validate conversion
    for orig, conv in zip(curve_points, converted_curve):
        np.testing.assert_array_almost_equal(conv, orig)

    # Add real Gmsh operations to create a curve and verify it works
    # Clear any previous geometry
    gmsh.model.occ.synchronize()

    # Create points in Gmsh using the converted coordinates
    point_tags = []
    for point in converted_curve:
        tag = gmsh.model.occ.addPoint(point[0], point[1], point[2])
        point_tags.append(tag)

    # Create a spline through these points
    curve_tag = gmsh.model.occ.addSpline(point_tags)

    # Synchronize to ensure the model is updated
    gmsh.model.occ.synchronize()

    # Verify the curve exists in the Gmsh model
    curves = gmsh.model.getEntities(1)  # Get all dimension 1 entities (curves)
    assert (1, curve_tag) in curves, "Created curve not found in Gmsh model"

    # Get curve length to verify it's a valid curve
    curve_length = gmsh.model.occ.getMass(1, curve_tag)
    assert curve_length > 0, "Curve has zero length"

    # Cleanup - remove all entities
    gmsh.model.removeEntities([(1, curve_tag)], recursive=True)
    gmsh.model.occ.synchronize()

    # Test invalid curve raises NotImplementedError
    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_curve([1.0, 2.0])  # Invalid point list
    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_curve("not a curve")
    # Test empty curve raises NotImplementedError
    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_curve([])


def test_surface_conversion(gmsh_converter):
    """Test surface conversion methods."""
    # Test valid surface (list of 3D points)
    surface_points = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    converted_surface = gmsh_converter._convert_surface(surface_points)

    assert len(converted_surface) == 4
    assert all(isinstance(p, np.ndarray) and p.shape == (3,) for p in converted_surface)

    # Validate conversion
    for orig, conv in zip(surface_points, converted_surface):
        np.testing.assert_array_almost_equal(conv, orig)

    # Add real Gmsh operations to create a surface and verify it works
    # Clear any previous geometry
    gmsh.model.occ.synchronize()

    # Create points in Gmsh using the converted coordinates
    point_tags = []
    for point in converted_surface:
        tag = gmsh.model.occ.addPoint(point[0], point[1], point[2])
        point_tags.append(tag)

    # Create line loops from the points
    line_tags = []
    for i in range(len(point_tags)):
        line_tags.append(
            gmsh.model.occ.addLine(point_tags[i], point_tags[(i + 1) % len(point_tags)])
        )

    # Create a line loop
    loop_tag = gmsh.model.occ.addCurveLoop(line_tags)

    # Create a surface from the loop
    surface_tag = gmsh.model.occ.addPlaneSurface([loop_tag])

    # Synchronize to ensure the model is updated
    gmsh.model.occ.synchronize()

    # Verify the surface exists in the Gmsh model
    surfaces = gmsh.model.getEntities(2)  # Get all dimension 2 entities (surfaces)
    assert (2, surface_tag) in surfaces, "Created surface not found in Gmsh model"

    # Get surface area to verify it's a valid surface
    surface_area = gmsh.model.occ.getMass(2, surface_tag)
    assert surface_area > 0, "Surface has zero area"

    # Try to mesh the surface to verify it's a valid geometry
    gmsh.model.mesh.setSize(gmsh.model.getEntities(0), 0.1)  # Set mesh size
    try:
        gmsh.model.mesh.generate(2)  # Generate 2D mesh
        mesh_success = True
    except Exception as e:
        mesh_success = False
        print(f"Warning: Meshing failed: {e}")

    # At least verify that the surface is valid even if meshing might fail
    assert mesh_success, "Failed to generate mesh on the surface"

    # Cleanup - remove all entities
    gmsh.model.removeEntities([(2, surface_tag)], recursive=True)
    gmsh.model.occ.synchronize()

    # Test invalid surface raises NotImplementedError
    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_surface([1.0, 2.0])  # Invalid point list
    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_surface("not a surface")
    # Test empty surface raises NotImplementedError
    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_surface([])


def test_curve_member_conversion(gmsh_converter, meshing_config):
    """Test conversion of a curve member to Gmsh geometry."""
    # Create a mock material
    material = Material(
        id=generate_unique_id(),
        name="Steel",
        density=7850,
        elastic_modulus=200e9,
        poisson_ratio=0.3,
    )

    # Create a mock section
    section = Section(
        id=generate_unique_id(),
        name="IPE 300",
        section_type="I-section",
        area=0.00835,  # Example area for an IPE 300 profile
        dimensions={
            "height": 0.3,
            "width": 0.15,
            "web_thickness": 0.01,
            "flange_thickness": 0.02,
        },
    )

    # Create a curve member with a simple linear geometry
    curve_points = [[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]]
    curve_member = CurveMember(
        id="test_beam_01", geometry=curve_points, material=material, section=section
    )

    # Convert the curve member
    converted_entities = gmsh_converter.convert_curve_member(curve_member)

    # Validate conversion
    assert isinstance(converted_entities, list)
    assert len(converted_entities) > 0

    # Check entity map
    assert curve_member.id in gmsh_converter._entity_map
    entity_info = gmsh_converter._entity_map[curve_member.id]
    assert entity_info["type"] == "curve"
    assert "gmsh_tags" in entity_info
    assert "element_type" in entity_info


def test_surface_member_conversion(gmsh_converter, meshing_config):
    """Test conversion of a surface member to Gmsh geometry."""
    # Create a mock material
    material = Material(
        id=generate_unique_id(),
        name="Concrete",
        density=2400,
        elastic_modulus=30e9,
        poisson_ratio=0.2,
    )

    # Create a mock thickness
    thickness = Thickness(
        id=generate_unique_id(),
        name="Slab Thickness",
        value=0.2,  # 20 cm thick
        is_variable=False,
    )

    # Create a surface member with a simple planar geometry
    surface_points = [
        [0.0, 0.0, 0.0],
        [5.0, 0.0, 0.0],
        [5.0, 5.0, 0.0],
        [0.0, 5.0, 0.0],
    ]
    surface_member = SurfaceMember(
        id="test_slab_01",
        geometry=surface_points,
        material=material,
        thickness=thickness,
    )

    # Convert the surface member
    converted_entities = gmsh_converter.convert_surface_member(surface_member)

    # Validate conversion
    assert isinstance(converted_entities, list)
    assert len(converted_entities) > 0

    # Check entity map
    assert surface_member.id in gmsh_converter._entity_map
    entity_info = gmsh_converter._entity_map[surface_member.id]
    assert entity_info["type"] == "surface"
    assert "gmsh_tags" in entity_info
    assert "element_type" in entity_info


def test_mesh_size_application(gmsh_converter, meshing_config):
    """Test applying mesh size to Gmsh entities."""
    # Create a simple line for testing mesh size application
    p1 = gmsh.model.occ.addPoint(0, 0, 0)
    p2 = gmsh.model.occ.addPoint(1, 0, 0)
    line = gmsh.model.occ.addLine(p1, p2)
    gmsh.model.occ.synchronize()

    # Test mesh size application
    test_sizes = [0.1, 0.5, 1.0]
    for size in test_sizes:
        # Apply mesh size
        gmsh_converter.apply_mesh_size(line, size)

        # Since we can't easily verify the mesh size value, we just ensure
        # the call doesn't raise exceptions


def test_model_conversion(gmsh_converter):
    """Test converting an entire structural model to Gmsh geometry."""
    # Create a mock structural model
    model = StructuralModel(id="test_model_01", name="Test Conversion Model")

    # Create materials and properties
    steel_material = Material(
        id=generate_unique_id(),
        name="Steel",
        density=7850,
        elastic_modulus=200e9,
        poisson_ratio=0.3,
    )
    concrete_material = Material(
        id=generate_unique_id(),
        name="Concrete",
        density=2400,
        elastic_modulus=30e9,
        poisson_ratio=0.2,
    )

    # Create a curve member (beam)
    beam_section = Section(
        id=generate_unique_id(),
        name="IPE 300",
        section_type="I-section",
        area=0.00835,  # Example area for an IPE 300 profile
        dimensions={
            "height": 0.3,
            "width": 0.15,
            "web_thickness": 0.01,
            "flange_thickness": 0.02,
        },
    )
    beam = CurveMember(
        id="beam_01",
        geometry=[[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]],
        material=steel_material,
        section=beam_section,
    )
    model.add_member(beam)

    # Create a surface member (slab)
    slab_thickness = Thickness(
        id=generate_unique_id(),
        name="Slab Thickness",
        value=0.2,  # 20 cm thick
        is_variable=False,
    )
    slab = SurfaceMember(
        id="slab_01",
        geometry=[[0.0, 0.0, 0.0], [5.0, 0.0, 0.0], [5.0, 5.0, 0.0], [0.0, 5.0, 0.0]],
        material=concrete_material,
        thickness=slab_thickness,
    )
    model.add_member(slab)

    # Convert the entire model
    entity_map = gmsh_converter.convert_model(model)

    # Validate conversion
    assert isinstance(entity_map, dict)
    assert len(entity_map) == 2  # beam and slab
    assert "beam_01" in entity_map
    assert "slab_01" in entity_map

    # Check each converted entity
    for member_id, entity_info in entity_map.items():
        assert "type" in entity_info
        assert "gmsh_tags" in entity_info
        assert "element_type" in entity_info
        assert len(entity_info["gmsh_tags"]) > 0


def test_invalid_geometry_handling(gmsh_converter):
    """Test handling of invalid geometries."""
    # Test empty geometry
    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_curve([])

    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_surface([])

    # Test invalid input types
    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_curve("string")

    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_surface(123)

    # Test invalid point formats
    with pytest.raises(NotImplementedError):
        gmsh_converter._convert_curve([[1, 2]])  # Missing z coordinate
