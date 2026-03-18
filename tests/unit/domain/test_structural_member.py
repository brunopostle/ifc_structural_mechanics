"""
Unit tests for the structural member domain models.
"""

import pytest

from ifc_structural_mechanics.domain.structural_member import (
    CurveMember,
    StructuralMember,
    SurfaceMember,
)


class TestStructuralMember:
    """Tests for the base StructuralMember class."""

    def test_init_valid_parameters(self):
        """Test initialization with valid parameters."""
        # Arrange
        id = "member-001"
        type = "curve"
        geometry = {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]}
        material = {"name": "Steel", "elastic_modulus": 210000}

        # Act
        member = StructuralMember(id, type, geometry, material)

        # Assert
        assert member.id == id
        assert member.entity_type == type  # Changed from type to entity_type
        assert member.geometry == geometry
        assert member.material == material
        assert member.boundary_conditions == []
        assert member.loads == []

    def test_init_invalid_id(self):
        """Test initialization with invalid ID."""
        # Arrange
        id = ""  # Empty string, should be invalid
        type = "curve"
        geometry = {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]}
        material = {"name": "Steel", "elastic_modulus": 210000}

        # Act/Assert
        with pytest.raises(ValueError, match="ID cannot be empty"):
            StructuralMember(id, type, geometry, material)

    def test_init_invalid_type(self):
        """Test initialization with invalid type."""
        # Arrange
        id = "member-001"
        type = "invalid"  # Invalid type
        geometry = {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]}
        material = {"name": "Steel", "elastic_modulus": 210000}

        # Act/Assert
        with pytest.raises(ValueError, match="Member type 'invalid' is not supported"):
            StructuralMember(id, type, geometry, material)

    def test_init_none_geometry(self):
        """Test initialization with None geometry."""
        # Arrange
        id = "member-001"
        type = "curve"
        geometry = None  # Invalid geometry
        material = {"name": "Steel", "elastic_modulus": 210000}

        # Act/Assert
        with pytest.raises(ValueError, match="Geometry cannot be None"):
            StructuralMember(id, type, geometry, material)

    def test_init_none_material(self):
        """Test initialization with None material."""
        # Arrange
        id = "member-001"
        type = "curve"
        geometry = {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]}
        material = None  # Invalid material

        # Act/Assert
        with pytest.raises(ValueError, match="Material cannot be None"):
            StructuralMember(id, type, geometry, material)

    def test_add_boundary_condition(self):
        """Test adding a boundary condition."""
        # Arrange
        member = StructuralMember(
            "member-001",
            "curve",
            {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]},
            {"name": "Steel", "elastic_modulus": 210000},
        )
        boundary_condition = {"type": "fixed", "location": [0, 0, 0]}

        # Act
        member.add_boundary_condition(boundary_condition)

        # Assert
        assert len(member.boundary_conditions) == 1
        assert member.boundary_conditions[0] == boundary_condition

    def test_add_boundary_condition_none(self):
        """Test adding a None boundary condition."""
        # Arrange
        member = StructuralMember(
            "member-001",
            "curve",
            {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]},
            {"name": "Steel", "elastic_modulus": 210000},
        )

        # Act/Assert
        with pytest.raises(ValueError, match="Boundary condition cannot be None"):
            member.add_boundary_condition(None)

    def test_remove_boundary_condition(self):
        """Test removing a boundary condition."""
        # Arrange
        member = StructuralMember(
            "member-001",
            "curve",
            {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]},
            {"name": "Steel", "elastic_modulus": 210000},
        )
        boundary_condition = {"type": "fixed", "location": [0, 0, 0]}
        member.add_boundary_condition(boundary_condition)

        # Act
        member.remove_boundary_condition(boundary_condition)

        # Assert
        assert len(member.boundary_conditions) == 0

    def test_remove_boundary_condition_not_found(self):
        """Test removing a boundary condition that doesn't exist."""
        # Arrange
        member = StructuralMember(
            "member-001",
            "curve",
            {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]},
            {"name": "Steel", "elastic_modulus": 210000},
        )
        boundary_condition = {"type": "fixed", "location": [0, 0, 0]}

        # Act/Assert
        with pytest.raises(ValueError, match="Boundary condition not found"):
            member.remove_boundary_condition(boundary_condition)

    def test_add_load(self):
        """Test adding a load."""
        # Arrange
        member = StructuralMember(
            "member-001",
            "curve",
            {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]},
            {"name": "Steel", "elastic_modulus": 210000},
        )
        load = {
            "type": "point",
            "magnitude": 1000,
            "direction": [0, 0, -1],
            "position": [0.5, 0, 0],
        }

        # Act
        member.add_load(load)

        # Assert
        assert len(member.loads) == 1
        assert member.loads[0] == load

    def test_add_load_none(self):
        """Test adding a None load."""
        # Arrange
        member = StructuralMember(
            "member-001",
            "curve",
            {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]},
            {"name": "Steel", "elastic_modulus": 210000},
        )

        # Act/Assert
        with pytest.raises(ValueError, match="Load cannot be None"):
            member.add_load(None)

    def test_remove_load(self):
        """Test removing a load."""
        # Arrange
        member = StructuralMember(
            "member-001",
            "curve",
            {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]},
            {"name": "Steel", "elastic_modulus": 210000},
        )
        load = {
            "type": "point",
            "magnitude": 1000,
            "direction": [0, 0, -1],
            "position": [0.5, 0, 0],
        }
        member.add_load(load)

        # Act
        member.remove_load(load)

        # Assert
        assert len(member.loads) == 0

    def test_remove_load_not_found(self):
        """Test removing a load that doesn't exist."""
        # Arrange
        member = StructuralMember(
            "member-001",
            "curve",
            {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]},
            {"name": "Steel", "elastic_modulus": 210000},
        )
        load = {
            "type": "point",
            "magnitude": 1000,
            "direction": [0, 0, -1],
            "position": [0.5, 0, 0],
        }

        # Act/Assert
        with pytest.raises(ValueError, match="Load not found"):
            member.remove_load(load)


class TestCurveMember:
    """Tests for the CurveMember class."""

    def test_init_valid_parameters(self):
        """Test initialization with valid parameters."""
        # Arrange
        id = "beam-001"
        geometry = {"type": "line", "start": [0, 0, 0], "end": [3, 0, 0]}
        material = {"name": "Steel", "elastic_modulus": 210000}
        section = {"type": "I-section", "height": 0.2, "width": 0.1}

        # Act
        curve_member = CurveMember(id, geometry, material, section)

        # Assert
        assert curve_member.id == id
        assert curve_member.entity_type == "curve"  # Changed from type to entity_type
        assert curve_member.geometry == geometry
        assert curve_member.material == material
        assert curve_member.section == section
        assert curve_member.boundary_conditions == []
        assert curve_member.loads == []

    def test_init_none_section(self):
        """Test initialization with None section."""
        # Arrange
        id = "beam-001"
        geometry = {"type": "line", "start": [0, 0, 0], "end": [3, 0, 0]}
        material = {"name": "Steel", "elastic_modulus": 210000}
        section = None  # Invalid section

        # Act/Assert
        with pytest.raises(
            ValueError, match="Section cannot be None for a curve member"
        ):
            CurveMember(id, geometry, material, section)


class TestSurfaceMember:
    """Tests for the SurfaceMember class."""

    def test_init_valid_parameters(self):
        """Test initialization with valid parameters."""
        # Arrange
        id = "slab-001"
        geometry = {"type": "rectangle", "origin": [0, 0, 0], "length": 5, "width": 4}
        material = {"name": "Concrete", "elastic_modulus": 30000}
        thickness = {"value": 0.2, "unit": "m"}

        # Act
        surface_member = SurfaceMember(id, geometry, material, thickness)

        # Assert
        assert surface_member.id == id
        assert (
            surface_member.entity_type == "surface"
        )  # Changed from type to entity_type
        assert surface_member.geometry == geometry
        assert surface_member.material == material
        assert surface_member.thickness == thickness
        assert surface_member.boundary_conditions == []
        assert surface_member.loads == []

    def test_init_none_thickness(self):
        """Test initialization with None thickness."""
        # Arrange
        id = "slab-001"
        geometry = {"type": "rectangle", "origin": [0, 0, 0], "length": 5, "width": 4}
        material = {"name": "Concrete", "elastic_modulus": 30000}
        thickness = None  # Invalid thickness

        # Act/Assert
        with pytest.raises(
            ValueError, match="Thickness cannot be None for a surface member"
        ):
            SurfaceMember(id, geometry, material, thickness)
