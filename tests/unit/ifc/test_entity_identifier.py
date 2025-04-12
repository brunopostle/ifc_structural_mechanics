"""
Unit tests for IFC entity identification and relationship navigation utilities.
"""

import ifcopenshell
from unittest.mock import Mock

from ifc_structural_mechanics.ifc.entity_identifier import (
    is_structural_member,
    is_structural_curve_member,
    is_structural_surface_member,
    is_structural_connection,
    is_structural_load,
    is_structural_boundary_condition,
    find_related_properties,
    find_related_material,
    find_related_profile,
    find_structural_connections,
    find_connected_elements,
    find_applied_loads,
    get_coordinate,
    analyze_connection_type,
)


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


def test_is_structural_load():
    """Test identification of structural loads."""
    # Test positive cases
    assert is_structural_load(create_mock_entity("IfcStructuralPointAction"))
    assert is_structural_load(create_mock_entity("IfcStructuralLinearAction"))
    assert is_structural_load(create_mock_entity("IfcStructuralPlanarAction"))
    assert is_structural_load(create_mock_entity("IfcStructuralLoadCase"))

    # Test negative cases
    assert not is_structural_load(create_mock_entity("IfcBeam"))
    assert not is_structural_load(create_mock_entity("IfcWall"))
    assert not is_structural_load(None)


def test_is_structural_boundary_condition():
    """Test identification of structural boundary conditions."""
    # Test positive cases
    assert is_structural_boundary_condition(
        create_mock_entity("IfcBoundaryNodeCondition")
    )
    assert is_structural_boundary_condition(
        create_mock_entity("IfcBoundaryEdgeCondition")
    )
    assert is_structural_boundary_condition(
        create_mock_entity("IfcBoundaryFaceCondition")
    )
    assert is_structural_boundary_condition(
        create_mock_entity("IfcStructuralBoundaryCondition")
    )

    # Test negative cases
    assert not is_structural_boundary_condition(create_mock_entity("IfcBeam"))
    assert not is_structural_boundary_condition(create_mock_entity("IfcWall"))
    assert not is_structural_boundary_condition(None)


def test_find_related_properties():
    """Test finding related property sets."""
    # Create a mock entity with property sets
    mock_entity = Mock(spec=ifcopenshell.entity_instance)

    # Mock IsDefinedBy relationship with property sets
    mock_prop_set1 = Mock()
    mock_prop_set1.is_a.return_value = "IfcPropertySet"
    mock_prop_set2 = Mock()
    mock_prop_set2.is_a.return_value = "IfcPropertySet"

    mock_rel1 = Mock()
    mock_rel1.RelatingPropertyDefinition = mock_prop_set1
    mock_rel2 = Mock()
    mock_rel2.RelatingPropertyDefinition = mock_prop_set2

    mock_entity.IsDefinedBy = [mock_rel1, mock_rel2]

    # Test property set retrieval
    related_props = find_related_properties(mock_entity)
    assert len(related_props) == 2
    assert related_props[0] == mock_prop_set1
    assert related_props[1] == mock_prop_set2

    # Test empty case
    mock_entity_no_props = Mock(spec=ifcopenshell.entity_instance)
    assert find_related_properties(mock_entity_no_props) == []


def test_find_related_material():
    """Test finding related material."""
    # Create mock entity with material associations
    mock_entity = Mock(spec=ifcopenshell.entity_instance)

    # First mock: IfcMaterial case
    mock_material = Mock()
    mock_material.is_a.side_effect = lambda x=None: (
        x == "IfcMaterial" if x is not None else False
    )

    # Setup the association
    mock_assoc = Mock()
    mock_assoc.is_a.return_value = "IfcRelAssociatesMaterial"
    mock_assoc.RelatingMaterial = mock_material

    mock_entity.HasAssociations = [mock_assoc]

    # Test material retrieval through associations
    related_material = find_related_material(mock_entity)
    assert related_material == mock_material


def test_find_related_profile():
    """Test finding related profile definitions."""
    # Create mock entity with different profile retrieval methods

    # Test SweptArea method
    mock_entity_swept = Mock(spec=ifcopenshell.entity_instance)
    mock_profile_swept = Mock()
    mock_entity_swept.SweptArea = mock_profile_swept

    # The issue is in the implementation - we need to properly mock the Representation
    # and Items structure for the find_related_profile function

    # First, create empty HasAssociations to skip the material profile check
    mock_entity_swept.HasAssociations = []

    # Now, we need to mock the Representation structure
    mock_representation = Mock()
    mock_representations = [mock_representation]
    mock_representation.Items = []

    # Create a mock Item that will match the extruded area solid check
    mock_item = Mock()
    mock_item.is_a.return_value = "IfcExtrudedAreaSolid"  # This should match the check
    mock_item.SweptArea = mock_profile_swept

    # Add the item to the representation's Items
    mock_representation.Items = [mock_item]

    # Create the Representation structure
    mock_repr_container = Mock()
    mock_repr_container.Representations = mock_representations
    mock_entity_swept.Representation = mock_repr_container

    # Now the test should pass
    assert find_related_profile(mock_entity_swept) == mock_profile_swept


def test_find_structural_connections():
    """Test finding structural connections."""
    # Create mock entity with connection relationships
    mock_entity = Mock(spec=ifcopenshell.entity_instance)

    # Create mock connections
    mock_connection1 = Mock()
    mock_connection1.RelatedElement = create_mock_entity("IfcStructuralPointConnection")
    mock_connection2 = Mock()
    mock_connection2.RelatedElement = create_mock_entity("IfcStructuralCurveConnection")

    # Mock connection relationships
    mock_entity.ConnectedTo = [mock_connection1]
    mock_entity.ConnectedFrom = [mock_connection2]

    # Test connection retrieval
    connections = find_structural_connections(mock_entity)
    assert len(connections) == 2

    # Test entity with no connections
    mock_entity_no_connections = Mock(spec=ifcopenshell.entity_instance)
    assert find_structural_connections(mock_entity_no_connections) == []


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


def test_find_applied_loads():
    """Test finding applied loads."""
    # Create mock entity with load assignments
    mock_entity = Mock(spec=ifcopenshell.entity_instance)

    # Create mock loads
    mock_load1 = create_mock_entity("IfcStructuralPointAction")
    mock_load2 = create_mock_entity("IfcStructuralLoadCase")

    # Mock assignment relationships
    mock_assn1 = Mock()
    mock_assn1.RelatedObjects = mock_load1
    mock_assn2 = Mock()
    mock_assn2.RelatedObjects = mock_load2

    mock_entity.HasAssignments = [mock_assn1, mock_assn2]

    # Test load retrieval
    loads = find_applied_loads(mock_entity)
    assert len(loads) == 2
    assert loads[0] == mock_load1
    assert loads[1] == mock_load2

    # Test entity with no loads
    mock_entity_no_loads = Mock(spec=ifcopenshell.entity_instance)
    assert find_applied_loads(mock_entity_no_loads) == []


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
    """Test error handling in relationship navigation functions."""

    # Create a mock entity that raises exceptions when accessing attributes
    class ErrorRaisingMock:
        def is_a(self, *args, **kwargs):
            raise Exception("Simulated error")

    error_entity = ErrorRaisingMock()

    # Test that functions handle exceptions gracefully
    assert not is_structural_member(error_entity)
    assert find_related_properties(error_entity) == []
    assert find_related_material(error_entity) is None
    assert find_related_profile(error_entity) is None
    assert find_structural_connections(error_entity) == []
    assert find_applied_loads(error_entity) == []
    assert find_connected_elements(error_entity) == []
