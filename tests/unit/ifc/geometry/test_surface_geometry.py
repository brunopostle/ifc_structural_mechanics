"""
Tests for the surface geometry extraction utilities.
"""

from unittest import mock

import ifcopenshell

from ifc_structural_mechanics.ifc.geometry import surface_geometry


class TestSurfaceGeometry:
    """Test suite for surface geometry extraction utilities."""

    def test_extract_surface_geometry_none_entity(self):
        """Test handling of None entity."""
        result = surface_geometry.extract_surface_geometry(None)
        assert result is None

    def test_extract_surface_geometry_no_representation(self):
        """Test handling of entity with no representation."""
        # Create a mock entity with no representation
        entity = mock.Mock(spec=ifcopenshell.entity_instance)
        entity.id.return_value = 1
        entity.Representation = None

        result = surface_geometry.extract_surface_geometry(entity)
        assert result is None

    def test_extract_face_surface(self):
        """Test extraction of face surface."""
        # Create a mock IfcFaceSurface
        face_surface = mock.Mock(spec=ifcopenshell.entity_instance)
        face_surface.is_a.return_value = True  # Simulate is_a('IfcFaceSurface')

        # Mock the FaceSurface attribute
        surface = mock.Mock(spec=ifcopenshell.entity_instance)
        surface.is_a.side_effect = lambda x: x == "IfcPlane"

        # Mock the Position attribute for the plane
        position = mock.Mock(spec=ifcopenshell.entity_instance)

        # Mock location
        location = mock.Mock(spec=ifcopenshell.entity_instance)
        location.Coordinates = (0, 0, 0)

        # Mock axis
        axis = mock.Mock(spec=ifcopenshell.entity_instance)
        axis.DirectionRatios = (0, 0, 1)

        # Mock ref direction
        ref_direction = mock.Mock(spec=ifcopenshell.entity_instance)
        ref_direction.DirectionRatios = (1, 0, 0)

        # Link all the mocks together
        position.Location = location
        position.Axis = axis
        position.RefDirection = ref_direction
        surface.Position = position
        face_surface.FaceSurface = surface

        # Call the function
        with mock.patch(
            "ifc_structural_mechanics.ifc.geometry.surface_geometry.extract_plane"
        ) as mock_extract_plane:
            mock_extract_plane.return_value = {"type": "plane", "test": True}
            result = surface_geometry.extract_face_surface(face_surface)

            # Check that extract_plane was called
            mock_extract_plane.assert_called_once_with(surface)

            # Check result
            assert result == {"type": "plane", "test": True}

    def test_extract_plane(self):
        """Test extraction of plane."""
        # Create a mock IfcPlane
        plane = mock.Mock(spec=ifcopenshell.entity_instance)

        # Mock the Position attribute
        position = mock.Mock(spec=ifcopenshell.entity_instance)

        # Mock location
        location = mock.Mock(spec=ifcopenshell.entity_instance)
        location.Coordinates = (0, 0, 0)

        # Mock axis
        axis = mock.Mock(spec=ifcopenshell.entity_instance)
        axis.DirectionRatios = (0, 0, 1)

        # Mock ref direction
        ref_direction = mock.Mock(spec=ifcopenshell.entity_instance)
        ref_direction.DirectionRatios = (1, 0, 0)

        # Link all the mocks together
        position.Location = location
        position.Axis = axis
        position.RefDirection = ref_direction
        plane.Position = position

        # Call the function
        result = surface_geometry.extract_plane(plane)

        # Check result
        assert result["type"] == "plane"
        assert result["point"] == (0, 0, 0)
        assert result["normal"] == (0, 0, 1)
        assert result["x_dir"] == (1, 0, 0)
        assert result["y_dir"] == (0, 1, 0)
        assert result["boundaries"] == []
