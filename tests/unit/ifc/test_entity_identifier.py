"""
Unit tests for IFC entity identification and relationship navigation utilities.
"""

from unittest.mock import Mock

import ifcopenshell
import pytest

from ifc_structural_mechanics.ifc.entity_identifier import (
    analyze_connection_type,
    find_connected_elements,
    get_coordinate,
    is_structural_connection,
    is_structural_curve_member,
    is_structural_member,
    is_structural_surface_member,
)
from ifc_structural_mechanics.utils.error_handling import ModelExtractionError


# Mock IFC entity creation utility
def create_mock_entity(entity_type):
    """Create a mock IFC entity with a specific type."""
    mock_entity = Mock(spec=ifcopenshell.entity_instance)
    mock_entity.is_a.return_value = entity_type
    return mock_entity


def test_is_structural_member():
    """Test identification of structural members."""
    # Test positive cases
    assert is_structural_member(create_mock_entity("IfcStructuralCurveMember"))
    assert is_structural_member(create_mock_entity("IfcStructuralSurfaceMember"))
    assert is_structural_member(create_mock_entity("IfcBeam"))
    assert is_structural_member(create_mock_entity("IfcColumn"))
    assert is_structural_member(create_mock_entity("IfcWall"))
    assert is_structural_member(create_mock_entity("IfcSlab"))

    # Test negative cases
    assert not is_structural_member(create_mock_entity("IfcDoor"))
    assert not is_structural_member(None)


def test_is_structural_curve_member():
    """Test identification of structural curve members."""
    # Test positive cases
    assert is_structural_curve_member(create_mock_entity("IfcStructuralCurveMember"))
    assert is_structural_curve_member(create_mock_entity("IfcBeam"))
    assert is_structural_curve_member(create_mock_entity("IfcColumn"))

    # Test negative cases
    assert not is_structural_curve_member(create_mock_entity("IfcWall"))
    assert not is_structural_curve_member(create_mock_entity("IfcSlab"))
    assert not is_structural_curve_member(None)


def test_is_structural_surface_member():
    """Test identification of structural surface members."""
    # Test positive cases
    assert is_structural_surface_member(
        create_mock_entity("IfcStructuralSurfaceMember")
    )
    assert is_structural_surface_member(create_mock_entity("IfcWall"))
    assert is_structural_surface_member(create_mock_entity("IfcSlab"))

    # Test negative cases
    assert not is_structural_surface_member(create_mock_entity("IfcBeam"))
    assert not is_structural_surface_member(create_mock_entity("IfcColumn"))
    assert not is_structural_surface_member(None)


def test_is_structural_connection():
    """Test identification of structural connections."""
    # Test positive cases
    assert is_structural_connection(create_mock_entity("IfcStructuralPointConnection"))
    assert is_structural_connection(create_mock_entity("IfcStructuralCurveConnection"))
    assert is_structural_connection(
        create_mock_entity("IfcStructuralSurfaceConnection")
    )

    # Test negative cases
    assert not is_structural_connection(create_mock_entity("IfcBeam"))
    assert not is_structural_connection(create_mock_entity("IfcWall"))
    assert not is_structural_connection(None)


def test_find_connected_elements():
    """Test finding connected elements."""
    # Create mock entity with connections to other elements
    mock_connection = Mock(spec=ifcopenshell.entity_instance)
    mock_connection.is_a.return_value = "IfcStructuralPointConnection"

    # Create mock relationship to structural members
    mock_member1 = Mock()
    mock_member1.GlobalId = "Member1_ID"
    mock_member2 = Mock()
    mock_member2.GlobalId = "Member2_ID"

    mock_rel1 = Mock()
    mock_rel1.RelatingStructuralMember = mock_member1
    mock_rel2 = Mock()
    mock_rel2.RelatingStructuralMember = mock_member2

    mock_connection.ConnectsStructuralMembers = [mock_rel1, mock_rel2]

    # Test connected elements retrieval
    elements = find_connected_elements(mock_connection)
    assert len(elements) == 2
    assert "Member1_ID" in elements
    assert "Member2_ID" in elements

    # Test entity with no connected elements
    mock_entity_no_connections = Mock(spec=ifcopenshell.entity_instance)
    assert find_connected_elements(mock_entity_no_connections) == []


def test_get_coordinate():
    """Test coordinate extraction from IfcCartesianPoint."""
    # Create mock IfcCartesianPoint
    mock_point = Mock()
    mock_point.is_a.return_value = "IfcCartesianPoint"
    mock_point.Coordinates = [1.0, 2.0, 3.0]

    # Test coordinate extraction
    coords = get_coordinate(mock_point)
    assert coords == [1.0, 2.0, 3.0]


def test_analyze_connection_type():
    """Test determining the type of structural connection."""
    # Create mock connection with applied condition
    mock_connection = Mock(spec=ifcopenshell.entity_instance)
    mock_connection.is_a.return_value = "IfcStructuralPointConnection"

    # Create mock applied condition for rigid connection
    mock_rigid_condition = Mock()
    mock_rigid_condition.RotationalStiffnessX = Mock(wrappedValue=1.0e6)
    mock_rigid_condition.RotationalStiffnessY = Mock(wrappedValue=1.0e6)
    mock_rigid_condition.RotationalStiffnessZ = Mock(wrappedValue=1.0e6)

    mock_connection.AppliedCondition = mock_rigid_condition

    # Test rigid connection identification
    assert analyze_connection_type(mock_connection) == "rigid"

    # Create mock applied condition for hinge connection
    mock_hinge_condition = Mock()
    mock_hinge_condition.RotationalStiffnessX = Mock(wrappedValue=0.0)
    mock_hinge_condition.RotationalStiffnessY = Mock(wrappedValue=1.0e6)
    mock_hinge_condition.RotationalStiffnessZ = Mock(wrappedValue=1.0e6)

    mock_connection.AppliedCondition = mock_hinge_condition

    # Test hinge connection identification
    assert analyze_connection_type(mock_connection) == "hinge"

    # Test default case without applied condition
    mock_connection.AppliedCondition = None
    assert analyze_connection_type(mock_connection) == "point"


def test_error_handling():
    """An entity that cannot be read is an error, not a quiet "no"."""

    class ErrorRaisingMock:
        def is_a(self, *args, **kwargs):
            raise Exception("Simulated error")

    error_entity = ErrorRaisingMock()

    with pytest.raises(ModelExtractionError):
        is_structural_member(error_entity)
    with pytest.raises(ModelExtractionError):
        find_connected_elements(error_entity)
