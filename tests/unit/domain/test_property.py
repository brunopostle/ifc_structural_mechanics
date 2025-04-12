"""
Tests for property classes in the structural domain model.

This module contains unit tests for Material, Section, and Thickness classes.
"""

import math
import pytest

from ifc_structural_mechanics.domain.property import Material, Section, Thickness


class TestMaterial:
    """Tests for the Material class."""

    def test_initialization_with_valid_parameters(self):
        """Test material initialization with valid parameters."""
        material = Material(
            id="steel_1",
            name="Structural Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
            thermal_expansion_coefficient=1.2e-5,
            yield_strength=350e6,
            ultimate_strength=450e6,
        )

        assert material.id == "steel_1"
        assert material.name == "Structural Steel"
        assert material.density == 7850.0
        assert material.elastic_modulus == 210e9
        assert material.poisson_ratio == 0.3
        assert material.thermal_expansion_coefficient == 1.2e-5
        assert material.yield_strength == 350e6
        assert material.ultimate_strength == 450e6

    def test_initialization_with_minimal_parameters(self):
        """Test material initialization with only required parameters."""
        material = Material(
            id="concrete_1",
            name="Concrete C25/30",
            density=2500.0,
            elastic_modulus=30e9,
            poisson_ratio=0.2,
        )

        assert material.id == "concrete_1"
        assert material.name == "Concrete C25/30"
        assert material.density == 2500.0
        assert material.elastic_modulus == 30e9
        assert material.poisson_ratio == 0.2
        assert material.thermal_expansion_coefficient is None
        assert material.yield_strength is None
        assert material.ultimate_strength is None

    def test_validation_of_required_properties(self):
        """Test validation of required material properties."""
        # Test empty ID
        with pytest.raises(ValueError, match="Material ID cannot be empty"):
            Material(
                id="",
                name="Test Material",
                density=1000.0,
                elastic_modulus=10e9,
                poisson_ratio=0.3,
            )

        # Test empty name
        with pytest.raises(ValueError, match="Material name cannot be empty"):
            Material(
                id="test_1",
                name="",
                density=1000.0,
                elastic_modulus=10e9,
                poisson_ratio=0.3,
            )

        # Test negative density
        with pytest.raises(ValueError, match="Density must be positive"):
            Material(
                id="test_1",
                name="Test Material",
                density=-1000.0,
                elastic_modulus=10e9,
                poisson_ratio=0.3,
            )

        # Test zero elastic modulus
        with pytest.raises(ValueError, match="Elastic modulus must be positive"):
            Material(
                id="test_1",
                name="Test Material",
                density=1000.0,
                elastic_modulus=0.0,
                poisson_ratio=0.3,
            )

        # Test invalid Poisson's ratio
        with pytest.raises(
            ValueError, match="Poisson's ratio must be between -1.0 and 0.5"
        ):
            Material(
                id="test_1",
                name="Test Material",
                density=1000.0,
                elastic_modulus=10e9,
                poisson_ratio=0.6,
            )

    def test_validation_of_optional_properties(self):
        """Test validation of optional material properties."""
        # Test negative thermal expansion coefficient
        with pytest.raises(
            ValueError, match="Thermal expansion coefficient cannot be negative"
        ):
            Material(
                id="test_1",
                name="Test Material",
                density=1000.0,
                elastic_modulus=10e9,
                poisson_ratio=0.3,
                thermal_expansion_coefficient=-1.0e-5,
            )

        # Test negative yield strength
        with pytest.raises(ValueError, match="Yield strength must be positive"):
            Material(
                id="test_1",
                name="Test Material",
                density=1000.0,
                elastic_modulus=10e9,
                poisson_ratio=0.3,
                yield_strength=-350e6,
            )

        # Test negative ultimate strength
        with pytest.raises(ValueError, match="Ultimate strength must be positive"):
            Material(
                id="test_1",
                name="Test Material",
                density=1000.0,
                elastic_modulus=10e9,
                poisson_ratio=0.3,
                ultimate_strength=-450e6,
            )

    def test_derived_properties_calculation(self):
        """Test calculation of derived material properties."""
        material = Material(
            id="steel_1",
            name="Structural Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
        )

        # Test shear modulus calculation
        expected_shear_modulus = 210e9 / (2 * (1 + 0.3))
        assert math.isclose(
            material.get_shear_modulus(), expected_shear_modulus, rel_tol=1e-10
        )

        # Test bulk modulus calculation
        expected_bulk_modulus = 210e9 / (3 * (1 - 2 * 0.3))
        assert math.isclose(
            material.get_bulk_modulus(), expected_bulk_modulus, rel_tol=1e-10
        )

        # Test Lamé parameters calculation
        expected_lambda, expected_mu = material.get_lame_parameters()
        assert math.isclose(expected_mu, material.get_shear_modulus(), rel_tol=1e-10)
        expected_lambda_param = (210e9 * 0.3) / ((1 + 0.3) * (1 - 2 * 0.3))
        assert math.isclose(expected_lambda, expected_lambda_param, rel_tol=1e-10)

    def test_as_dict_method(self):
        """Test the as_dict method returns the correct dictionary."""
        material = Material(
            id="steel_1",
            name="Structural Steel",
            density=7850.0,
            elastic_modulus=210e9,
            poisson_ratio=0.3,
            thermal_expansion_coefficient=1.2e-5,
            yield_strength=350e6,
            ultimate_strength=450e6,
        )

        material_dict = material.as_dict()
        assert material_dict["id"] == "steel_1"
        assert material_dict["name"] == "Structural Steel"
        assert material_dict["density"] == 7850.0
        assert material_dict["elastic_modulus"] == 210e9
        assert material_dict["poisson_ratio"] == 0.3
        assert material_dict["thermal_expansion_coefficient"] == 1.2e-5
        assert material_dict["yield_strength"] == 350e6
        assert material_dict["ultimate_strength"] == 450e6


class TestSection:
    """Tests for the Section class."""

    def test_initialization_with_valid_parameters(self):
        """Test section initialization with valid parameters."""
        section = Section(
            id="beam_1",
            name="Rectangular Beam",
            section_type="rectangular",
            area=0.04,
            dimensions={"width": 0.2, "height": 0.2},
        )

        assert section.id == "beam_1"
        assert section.name == "Rectangular Beam"
        assert section.section_type == "rectangular"
        assert section.area == 0.04
        assert section.dimensions["width"] == 0.2
        assert section.dimensions["height"] == 0.2

    def test_validation_of_required_properties(self):
        """Test validation of required section properties."""
        # Test empty ID
        with pytest.raises(ValueError, match="Section ID cannot be empty"):
            Section(
                id="",
                name="Test Section",
                section_type="rectangular",
                area=0.04,
                dimensions={"width": 0.2, "height": 0.2},
            )

        # Test empty name
        with pytest.raises(ValueError, match="Section name cannot be empty"):
            Section(
                id="section_1",
                name="",
                section_type="rectangular",
                area=0.04,
                dimensions={"width": 0.2, "height": 0.2},
            )

        # Test empty section type
        with pytest.raises(ValueError, match="Section type cannot be empty"):
            Section(
                id="section_1",
                name="Test Section",
                section_type="",
                area=0.04,
                dimensions={"width": 0.2, "height": 0.2},
            )

        # Test negative area
        with pytest.raises(ValueError, match="Area must be positive"):
            Section(
                id="section_1",
                name="Test Section",
                section_type="rectangular",
                area=-0.04,
                dimensions={"width": 0.2, "height": 0.2},
            )

        # Test empty dimensions
        with pytest.raises(ValueError, match="Dimensions dictionary cannot be empty"):
            Section(
                id="section_1",
                name="Test Section",
                section_type="rectangular",
                area=0.04,
                dimensions={},
            )

    def test_validation_of_section_type_dimensions(self):
        """Test validation of dimensions based on section type."""
        # Test missing required dimension for rectangular section
        with pytest.raises(ValueError, match="Required dimension 'height' missing"):
            Section(
                id="section_1",
                name="Test Section",
                section_type="rectangular",
                area=0.04,
                dimensions={"width": 0.2},
            )

        # Test negative dimension value
        with pytest.raises(ValueError, match="Dimension 'width' must be positive"):
            Section(
                id="section_1",
                name="Test Section",
                section_type="rectangular",
                area=0.04,
                dimensions={"width": -0.2, "height": 0.2},
            )

    def test_rectangular_section_creation(self):
        """Test creation of rectangular section using factory method."""
        section = Section.create_rectangular_section(
            id="rect_1", name="Rectangle 200x300", width=0.2, height=0.3
        )

        assert section.id == "rect_1"
        assert section.name == "Rectangle 200x300"
        assert section.section_type == "rectangular"
        assert math.isclose(section.area, 0.2 * 0.3, rel_tol=1e-10)
        assert section.dimensions["width"] == 0.2
        assert section.dimensions["height"] == 0.3

        # Check calculated properties
        assert hasattr(section, "moment_of_inertia_y")
        assert hasattr(section, "moment_of_inertia_z")
        assert hasattr(section, "torsional_constant")

        # Test moment of inertia calculation for rectangular section
        expected_Iy = (0.2 * 0.3**3) / 12
        expected_Iz = (0.3 * 0.2**3) / 12
        assert math.isclose(section.moment_of_inertia_y, expected_Iy, rel_tol=1e-10)
        assert math.isclose(section.moment_of_inertia_z, expected_Iz, rel_tol=1e-10)

    def test_circular_section_creation(self):
        """Test creation of circular section using factory method."""
        section = Section.create_circular_section(
            id="circ_1", name="Circle D100", radius=0.05
        )

        assert section.id == "circ_1"
        assert section.name == "Circle D100"
        assert section.section_type == "circular"
        assert math.isclose(section.area, math.pi * 0.05**2, rel_tol=1e-10)
        assert section.dimensions["radius"] == 0.05

        # Check calculated properties
        assert hasattr(section, "moment_of_inertia_y")
        assert hasattr(section, "moment_of_inertia_z")
        assert hasattr(section, "torsional_constant")

        # Test moment of inertia calculation for circular section
        expected_I = (math.pi * 0.05**4) / 4
        assert math.isclose(section.moment_of_inertia_y, expected_I, rel_tol=1e-10)
        assert math.isclose(section.moment_of_inertia_z, expected_I, rel_tol=1e-10)

    def test_i_section_creation(self):
        """Test creation of I-section using factory method."""
        section = Section.create_i_section(
            id="i_1",
            name="I-Beam 200x300",
            width=0.2,
            height=0.3,
            web_thickness=0.01,
            flange_thickness=0.015,
        )

        assert section.id == "i_1"
        assert section.name == "I-Beam 200x300"
        assert section.section_type == "i"

        # Calculate expected area: 2 flanges + 1 web
        expected_area = 2 * 0.2 * 0.015 + 0.01 * (0.3 - 2 * 0.015)
        assert math.isclose(section.area, expected_area, rel_tol=1e-10)

        assert section.dimensions["width"] == 0.2
        assert section.dimensions["height"] == 0.3
        assert section.dimensions["web_thickness"] == 0.01
        assert section.dimensions["flange_thickness"] == 0.015

    def test_hollow_rectangular_section_creation(self):
        """Test creation of hollow rectangular section using factory method."""
        section = Section.create_hollow_rectangular_section(
            id="hRect_1",
            name="Hollow Rect 200x300x10",
            outer_width=0.2,
            outer_height=0.3,
            thickness=0.01,
        )

        assert section.id == "hRect_1"
        assert section.name == "Hollow Rect 200x300x10"
        assert section.section_type == "hollow_rectangular"

        # Calculate expected area: outer area - inner area
        inner_width = 0.2 - 2 * 0.01
        inner_height = 0.3 - 2 * 0.01
        expected_area = 0.2 * 0.3 - inner_width * inner_height
        assert math.isclose(section.area, expected_area, rel_tol=1e-10)

    def test_hollow_circular_section_creation(self):
        """Test creation of hollow circular section using factory method."""
        section = Section.create_hollow_circular_section(
            id="hCirc_1",
            name="Hollow Circle D100x10",
            outer_radius=0.05,
            thickness=0.01,
        )

        assert section.id == "hCirc_1"
        assert section.name == "Hollow Circle D100x10"
        assert section.section_type == "hollow_circular"

        # Calculate expected area: outer area - inner area
        inner_radius = 0.05 - 0.01
        expected_area = math.pi * (0.05**2 - inner_radius**2)
        assert math.isclose(section.area, expected_area, rel_tol=1e-10)

    def test_invalid_hollow_section_parameters(self):
        """Test validation of hollow section parameters."""
        # Test thickness too large for hollow rectangular
        with pytest.raises(
            ValueError, match="Thickness too large for given dimensions"
        ):
            Section.create_hollow_rectangular_section(
                id="hRect_1",
                name="Invalid Hollow Rect",
                outer_width=0.2,
                outer_height=0.3,
                thickness=0.15,  # Too large
            )

        # Test thickness too large for hollow circular
        with pytest.raises(ValueError, match="Thickness too large for given radius"):
            Section.create_hollow_circular_section(
                id="hCirc_1",
                name="Invalid Hollow Circle",
                outer_radius=0.05,
                thickness=0.06,  # Too large
            )

    def test_radius_of_gyration_calculation(self):
        """Test calculation of radius of gyration."""
        section = Section.create_rectangular_section(
            id="rect_1", name="Rectangle 100x200", width=0.1, height=0.2
        )

        ry, rz = section.get_radius_of_gyration()

        # Expected values
        expected_ry = math.sqrt(section.moment_of_inertia_y / section.area)
        expected_rz = math.sqrt(section.moment_of_inertia_z / section.area)

        assert math.isclose(ry, expected_ry, rel_tol=1e-10)
        assert math.isclose(rz, expected_rz, rel_tol=1e-10)

    def test_section_modulus_calculation(self):
        """Test calculation of section modulus."""
        section = Section.create_rectangular_section(
            id="rect_1", name="Rectangle 100x200", width=0.1, height=0.2
        )

        wy, wz = section.get_section_modulus()

        # Expected values for rectangular section
        expected_wy = section.moment_of_inertia_y / (0.2 / 2)
        expected_wz = section.moment_of_inertia_z / (0.1 / 2)

        assert math.isclose(wy, expected_wy, rel_tol=1e-10)
        assert math.isclose(wz, expected_wz, rel_tol=1e-10)

    def test_as_dict_method(self):
        """Test the as_dict method returns the correct dictionary with calculated properties."""
        section = Section.create_rectangular_section(
            id="rect_1", name="Rectangle 100x200", width=0.1, height=0.2
        )

        section_dict = section.as_dict()

        assert section_dict["id"] == "rect_1"
        assert section_dict["name"] == "Rectangle 100x200"
        assert section_dict["section_type"] == "rectangular"
        assert math.isclose(section_dict["area"], 0.1 * 0.2, rel_tol=1e-10)
        assert section_dict["dimensions"]["width"] == 0.1
        assert section_dict["dimensions"]["height"] == 0.2

        # Check calculated properties are included
        assert "moment_of_inertia_y" in section_dict
        assert "moment_of_inertia_z" in section_dict
        assert "torsional_constant" in section_dict
        assert "shear_area_y" in section_dict
        assert "shear_area_z" in section_dict


class TestThickness:
    """Tests for the Thickness class."""

    def test_initialization_with_valid_parameters(self):
        """Test thickness initialization with valid parameters."""
        thickness = Thickness(
            id="slab_1",
            name="Concrete Slab",
            value=0.2,
        )

        assert thickness.id == "slab_1"
        assert thickness.name == "Concrete Slab"
        assert thickness.value == 0.2
        assert thickness.is_variable is False
        assert thickness.min_value is None
        assert thickness.max_value is None

    def test_initialization_with_variable_thickness(self):
        """Test thickness initialization with variable parameters."""
        thickness = Thickness(
            id="slab_2",
            name="Variable Thickness Slab",
            value=0.25,
            is_variable=True,
            min_value=0.2,
            max_value=0.3,
        )

        assert thickness.id == "slab_2"
        assert thickness.name == "Variable Thickness Slab"
        assert thickness.value == 0.25
        assert thickness.is_variable is True
        assert thickness.min_value == 0.2
        assert thickness.max_value == 0.3

    def test_validation_of_required_properties(self):
        """Test validation of required thickness properties."""
        # Test empty ID
        with pytest.raises(ValueError, match="Thickness ID cannot be empty"):
            Thickness(
                id="",
                name="Test Thickness",
                value=0.2,
            )

        # Test empty name
        with pytest.raises(ValueError, match="Thickness name cannot be empty"):
            Thickness(
                id="thick_1",
                name="",
                value=0.2,
            )

        # Test negative thickness value
        with pytest.raises(ValueError, match="Thickness value must be positive"):
            Thickness(
                id="thick_1",
                name="Test Thickness",
                value=-0.2,
            )

    def test_validation_of_variable_thickness(self):
        """Test validation of variable thickness properties."""
        # Test variable thickness without min/max values
        with pytest.raises(ValueError, match="Min and max values must be provided"):
            Thickness(
                id="thick_1",
                name="Test Thickness",
                value=0.2,
                is_variable=True,
            )

        # Test negative min value
        with pytest.raises(
            ValueError, match="Minimum thickness value must be positive"
        ):
            Thickness(
                id="thick_1",
                name="Test Thickness",
                value=0.2,
                is_variable=True,
                min_value=-0.1,
                max_value=0.3,
            )

        # Test negative max value
        with pytest.raises(
            ValueError, match="Maximum thickness value must be positive"
        ):
            Thickness(
                id="thick_1",
                name="Test Thickness",
                value=0.2,
                is_variable=True,
                min_value=0.1,
                max_value=-0.3,
            )

        # Test min > max
        with pytest.raises(
            ValueError, match="Minimum thickness .* cannot be greater than"
        ):
            Thickness(
                id="thick_1",
                name="Test Thickness",
                value=0.2,
                is_variable=True,
                min_value=0.3,
                max_value=0.2,
            )

        # Test nominal value outside min-max range
        with pytest.raises(ValueError, match="Nominal thickness .* must be between"):
            Thickness(
                id="thick_1",
                name="Test Thickness",
                value=0.4,
                is_variable=True,
                min_value=0.1,
                max_value=0.3,
            )

    def test_get_average_value(self):
        """Test calculation of average thickness value."""
        # For constant thickness
        thickness1 = Thickness(
            id="slab_1",
            name="Constant Thickness",
            value=0.2,
        )
        assert thickness1.get_average_value() == 0.2

        # For variable thickness
        thickness2 = Thickness(
            id="slab_2",
            name="Variable Thickness",
            value=0.25,
            is_variable=True,
            min_value=0.2,
            max_value=0.3,
        )
        assert thickness2.get_average_value() == 0.25

    def test_as_dict_method(self):
        """Test the as_dict method returns the correct dictionary."""
        thickness = Thickness(
            id="slab_1",
            name="Concrete Slab",
            value=0.2,
            is_variable=True,
            min_value=0.15,
            max_value=0.25,
        )

        thickness_dict = thickness.as_dict()
        assert thickness_dict["id"] == "slab_1"
        assert thickness_dict["name"] == "Concrete Slab"
        assert thickness_dict["value"] == 0.2
        assert thickness_dict["is_variable"] is True
        assert thickness_dict["min_value"] == 0.15
        assert thickness_dict["max_value"] == 0.25
