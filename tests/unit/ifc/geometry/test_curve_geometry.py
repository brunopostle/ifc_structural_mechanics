"""
Tests for the curve geometry extraction module.

This module contains tests for extracting geometric information from IFC curve
entities (lines, polylines, etc.) and converting them to a consistent internal
representation.
"""

from unittest.mock import Mock, patch
import numpy as np

from ifc_structural_mechanics.ifc.geometry.curve_geometry import (
    extract_curve_geometry,
    get_representation,
    extract_from_edge_representation,
    extract_from_axis_representation,
    extract_from_body_representation,
)

from ifc_structural_mechanics.ifc.entity_identifier import (
    get_coordinate,
    transform_vectors,
)


def test_extract_from_edge_representation():
    """Test extracting geometry from an Edge representation."""
    # Create a mock representation
    mock_rep = Mock()

    # Create a mock IfcEdge
    mock_edge = Mock()
    mock_edge.is_a.return_value = "IfcEdge"

    # Create mock vertices
    mock_start_vertex = Mock()
    mock_start_vertex.VertexGeometry = Mock()
    mock_start_vertex.VertexGeometry.Coordinates = [1.0, 2.0, 3.0]

    mock_end_vertex = Mock()
    mock_end_vertex.VertexGeometry = Mock()
    mock_end_vertex.VertexGeometry.Coordinates = [4.0, 5.0, 6.0]

    # Set edge properties
    mock_edge.EdgeStart = mock_start_vertex
    mock_edge.EdgeEnd = mock_end_vertex

    # Set representation properties
    mock_rep.Items = [mock_edge]

    # Extract geometry
    with patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.get_coordinate",
        side_effect=lambda p: list(p.Coordinates),
    ):
        result = extract_from_edge_representation(mock_rep)

    # Verify the result
    assert result is not None
    assert len(result) == 2
    assert result[0] == [1.0, 2.0, 3.0]
    assert result[1] == [4.0, 5.0, 6.0]


def test_extract_from_axis_representation():
    """Test extracting geometry from an Axis representation."""
    # Create a mock representation
    mock_rep = Mock()

    # Create a mock IfcPolyline
    mock_polyline = Mock()
    mock_polyline.is_a.return_value = "IfcPolyline"

    # Create mock points
    mock_point1 = Mock()
    mock_point1.Coordinates = [0.0, 0.0, 0.0]

    mock_point2 = Mock()
    mock_point2.Coordinates = [10.0, 0.0, 0.0]

    # Set polyline properties
    mock_polyline.Points = [mock_point1, mock_point2]

    # Set representation properties
    mock_rep.Items = [mock_polyline]

    # Extract geometry
    with patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.get_coordinate",
        side_effect=lambda p: list(p.Coordinates),
    ):
        result = extract_from_axis_representation(mock_rep)

    # Verify the result
    assert result is not None
    assert len(result) == 2
    assert result[0] == [0.0, 0.0, 0.0]
    assert result[1] == [10.0, 0.0, 0.0]


def test_extract_from_body_representation():
    """Test extracting geometry from a Body representation."""
    # Create a mock representation
    mock_rep = Mock()

    # Create a mock IfcExtrudedAreaSolid
    mock_solid = Mock()
    mock_solid.is_a.return_value = "IfcExtrudedAreaSolid"

    # Set solid properties
    mock_solid.Position = Mock()
    mock_solid.Position.Location = Mock()
    mock_solid.Position.Location.Coordinates = [1.0, 2.0, 3.0]

    mock_solid.ExtrudedDirection = Mock()
    mock_solid.ExtrudedDirection.DirectionRatios = [0.0, 0.0, 1.0]

    mock_solid.Depth = 5.0

    # Set representation properties
    mock_rep.Items = [mock_solid]

    # Extract geometry
    with patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.get_coordinate",
        side_effect=lambda p: list(p.Coordinates),
    ):
        result = extract_from_body_representation(mock_rep)

    # Verify the result
    assert result is not None
    assert len(result) == 2
    assert result[0] == [1.0, 2.0, 3.0]
    assert result[1] == [1.0, 2.0, 8.0]  # Start point + direction * depth


def test_get_representation():
    """Test getting specific representation from entity."""
    # Create a mock entity with representations
    mock_entity = Mock()
    mock_entity.Representation = Mock()

    # Create mock representations
    mock_rep1 = Mock()
    mock_rep1.RepresentationIdentifier = "Reference"
    mock_rep1.RepresentationType = "Edge"

    mock_rep2 = Mock()
    mock_rep2.RepresentationIdentifier = "Body"
    mock_rep2.RepresentationType = "Brep"

    mock_rep3 = Mock()
    mock_rep3.RepresentationIdentifier = None
    mock_rep3.RepresentationType = "Axis"

    # Set entity representation properties
    mock_entity.Representation.Representations = [mock_rep1, mock_rep2, mock_rep3]

    # Test getting Reference/Edge representation
    result = get_representation(mock_entity, "Edge")
    assert result == mock_rep1

    # Test getting by type only
    result = get_representation(mock_entity, "Axis")
    assert result == mock_rep3

    # Test not found case
    result = get_representation(mock_entity, "NonExistent")
    assert result is None


def test_extract_curve_geometry():
    """Test the main curve geometry extraction function with different strategies."""
    # Create a mock entity
    mock_entity = Mock()
    mock_entity.id.return_value = "test_id"
    mock_entity.ObjectPlacement = Mock()

    # Test with Edge representation
    with patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.get_representation"
    ) as mock_get_rep, patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.extract_from_edge_representation"
    ) as mock_extract_edge, patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.get_transformation"
    ) as mock_get_transform, patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.transform_vectors"
    ) as mock_transform:

        # Setup mocks
        mock_rep = Mock()
        mock_get_rep.return_value = mock_rep
        mock_extract_edge.return_value = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
        mock_get_transform.return_value = {"transform": "data"}
        mock_transform.return_value = ((1.0, 1.0, 1.0), (11.0, 1.0, 1.0))

        # Call function
        result = extract_curve_geometry(mock_entity)

        # Verify result
        assert result == ((1.0, 1.0, 1.0), (11.0, 1.0, 1.0))
        mock_get_rep.assert_called_with(mock_entity, "Edge")
        mock_extract_edge.assert_called_with(mock_rep)
        mock_get_transform.assert_called_with(mock_entity.ObjectPlacement)
        mock_transform.assert_called_with(
            ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)), {"transform": "data"}
        )


def test_extract_curve_geometry_with_fallbacks():
    """Test curve geometry extraction with fallback methods."""
    # Create a mock entity
    mock_entity = Mock()
    mock_entity.id.return_value = "test_id"
    mock_entity.ObjectPlacement = Mock()

    # Test with fallback to Axis representation
    with patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.get_representation"
    ) as mock_get_rep, patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.extract_from_edge_representation"
    ) as mock_extract_edge, patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.extract_from_axis_representation"
    ) as mock_extract_axis, patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.get_transformation"
    ) as mock_get_transform, patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.transform_vectors"
    ) as mock_transform:

        # Setup mocks for first attempt (edge) to fail
        mock_edge_rep = None
        mock_axis_rep = Mock()

        # First call returns None (Edge representation not found)
        # Second call returns mock_axis_rep (Axis representation found)
        mock_get_rep.side_effect = [mock_edge_rep, mock_axis_rep]

        mock_extract_edge.return_value = None
        mock_extract_axis.return_value = ((0.0, 0.0, 0.0), (15.0, 0.0, 0.0))
        mock_get_transform.return_value = {"transform": "data"}
        mock_transform.return_value = ((1.0, 1.0, 1.0), (16.0, 1.0, 1.0))

        # Call function
        result = extract_curve_geometry(mock_entity)

        # Verify result
        assert result == ((1.0, 1.0, 1.0), (16.0, 1.0, 1.0))
        mock_get_rep.assert_any_call(mock_entity, "Edge")
        mock_get_rep.assert_any_call(mock_entity, "Axis")
        mock_extract_axis.assert_called_with(mock_axis_rep)
        mock_get_transform.assert_called_with(mock_entity.ObjectPlacement)
        mock_transform.assert_called_with(
            ((0.0, 0.0, 0.0), (15.0, 0.0, 0.0)), {"transform": "data"}
        )


def test_extract_curve_geometry_error_handling():
    """Test error handling in curve geometry extraction."""
    # Create a mock entity that raises exceptions
    mock_entity = Mock()
    mock_entity.id.return_value = "test_id"

    # Patch get_representation to raise an exception
    with patch(
        "ifc_structural_mechanics.ifc.geometry.curve_geometry.get_representation",
        side_effect=Exception("Test error"),
    ):

        # Call function and verify it handles the error gracefully
        result = extract_curve_geometry(mock_entity)
        assert result is None


def test_get_coordinate():
    """Test coordinate extraction from a point."""
    mock_point = Mock()
    mock_point.is_a.return_value = "IfcCartesianPoint"
    mock_point.Coordinates = [1.0, 2.0, 3.0]

    with patch(
        "ifc_structural_mechanics.ifc.entity_identifier.get_coordinate",
        side_effect=lambda p: list(p.Coordinates),
    ):
        coords = get_coordinate(mock_point)
        assert coords == [1.0, 2.0, 3.0]


def test_transform_vectors():
    """Test transformation of vectors."""
    # Create test data
    points = [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
    transform = {
        "location": np.array([10.0, 20.0, 30.0]),
        "rotationMatrix": np.eye(3),  # Identity matrix
    }

    # Call the actual transform_vectors function
    result = transform_vectors(points, transform)

    # Expected result is points with translation added
    expected = [[11.0, 22.0, 33.0], [14.0, 25.0, 36.0]]

    # Compare results
    assert result == expected, f"Expected {expected}, but got {result}"


def test_transform_vectors_single_point():
    """Test transformation of a single point."""
    point = [1.0, 2.0, 3.0]
    transform = {
        "location": np.array([10.0, 20.0, 30.0]),
        "rotationMatrix": np.eye(3),  # Identity matrix
    }

    # Call the actual transform_vectors function
    result = transform_vectors([point], transform)

    # Expected result is point with translation added
    expected = [[11.0, 22.0, 33.0]]

    # Compare results
    assert result == expected, f"Expected {expected}, but got {result}"


def test_transform_vectors_no_translation():
    """Test transformation of vectors without translation."""
    points = [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]
    transform = {
        "location": np.array([10.0, 20.0, 30.0]),
        "rotationMatrix": np.eye(3),  # Identity matrix
    }

    # Call the actual transform_vectors function with include_translation=False
    result = transform_vectors(points, transform, include_translation=False)

    # Expected result is the original points
    expected = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]

    # Compare results
    assert result == expected, f"Expected {expected}, but got {result}"
