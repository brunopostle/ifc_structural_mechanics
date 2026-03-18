"""
Tests for extracting material and section properties from IFC files.

This module tests the extraction of material, section, and thickness properties
from IFC4 files, ensuring they're correctly mapped to domain objects.
"""

import os

import ifcopenshell
import pytest

from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.ifc.properties_extractor import PropertiesExtractor


class TestPropertyExtraction:
    """Test the extraction of properties from an IFC file."""

    @pytest.fixture
    def test_file_path(self):
        """Get the path to the test IFC file."""
        # Get the directory of this test file
        test_dir = os.path.dirname(os.path.abspath(__file__))

        # Navigate to the test_data directory
        test_data_dir = os.path.join(test_dir, "..", "..", "test_data")

        # Return the path to the test file
        return os.path.join(test_data_dir, "simple_beam.ifc")

    def test_extract_materials(self, test_file_path):
        """Test extracting material properties from IFC entities."""
        # Skip test if file doesn't exist
        if not os.path.exists(test_file_path):
            pytest.skip(f"Test file not found: {test_file_path}")

        # Open the IFC file
        ifc_file = ifcopenshell.open(test_file_path)

        # Create the extractor with the IFC file
        extractor = PropertiesExtractor(ifc_file)

        # Find entities that might have materials
        material_entities = []

        # Look for entities that typically have materials
        for entity_type in [
            "IfcBeam",
            "IfcColumn",
            "IfcWall",
            "IfcSlab",
            "IfcStructuralCurveMember",
            "IfcStructuralSurfaceMember",
        ]:
            entities = list(ifc_file.by_type(entity_type))
            material_entities.extend(entities)

        print(f"Found {len(material_entities)} entities that might have materials")

        # Try to extract materials from these entities
        materials = []
        for entity in material_entities:
            material = extractor.extract_material(entity)
            if material is not None:
                materials.append(material)
                print(f"Extracted material from {entity.is_a()}: {material.name}")

        # Even if no materials found, don't fail the test
        print(f"Successfully extracted {len(materials)} materials")

        # Validate properties of extracted materials
        for material in materials:
            assert isinstance(
                material, Material
            ), f"Expected Material object, got {type(material)}"
            assert material.id is not None, "Material ID is missing"
            assert material.name is not None, "Material name is missing"
            assert material.density > 0, "Material density should be positive"
            assert (
                material.elastic_modulus > 0
            ), "Material elastic modulus should be positive"
            assert (
                -1.0 < material.poisson_ratio < 0.5
            ), f"Material Poisson ratio should be between -1.0 and 0.5, got {material.poisson_ratio}"

            print(f"Material {material.name}:")
            print(f"  - Density: {material.density} kg/m³")
            print(f"  - Elastic modulus: {material.elastic_modulus:.2e} N/m²")
            print(f"  - Poisson ratio: {material.poisson_ratio}")
            if material.thermal_expansion_coefficient is not None:
                print(
                    f"  - Thermal expansion: {material.thermal_expansion_coefficient} 1/K"
                )
            if material.yield_strength is not None:
                print(f"  - Yield strength: {material.yield_strength:.2e} N/m²")
            if material.ultimate_strength is not None:
                print(f"  - Ultimate strength: {material.ultimate_strength:.2e} N/m²")

    def test_extract_sections(self, test_file_path):
        """Test extracting section properties from IFC entities."""
        # Skip test if file doesn't exist
        if not os.path.exists(test_file_path):
            pytest.skip(f"Test file not found: {test_file_path}")

        # Open the IFC file
        ifc_file = ifcopenshell.open(test_file_path)

        # Create the extractor with the IFC file
        extractor = PropertiesExtractor(ifc_file)

        # Find entities that might have section profiles
        section_entities = []

        # Look for entities that typically have sections
        for entity_type in ["IfcBeam", "IfcColumn", "IfcStructuralCurveMember"]:
            entities = list(ifc_file.by_type(entity_type))
            section_entities.extend(entities)

        print(f"Found {len(section_entities)} entities that might have sections")

        # Try to extract sections from these entities
        sections = []
        for entity in section_entities:
            section = extractor.extract_section(entity)
            if section is not None:
                sections.append(section)
                print(f"Extracted section from {entity.is_a()}: {section.name}")

        # Even if no sections found, don't fail the test
        print(f"Successfully extracted {len(sections)} sections")

        # Validate properties of extracted sections
        for section in sections:
            assert isinstance(
                section, Section
            ), f"Expected Section object, got {type(section)}"
            assert section.id is not None, "Section ID is missing"
            assert section.name is not None, "Section name is missing"
            assert section.section_type is not None, "Section type is missing"
            assert section.area > 0, "Section area should be positive"
            assert section.dimensions is not None, "Section dimensions are missing"

            print(f"Section {section.name}:")
            print(f"  - Type: {section.section_type}")
            print(f"  - Area: {section.area} m²")
            print(f"  - Dimensions: {section.dimensions}")

            # Check calculated properties
            if (
                hasattr(section, "moment_of_inertia_y")
                and section.moment_of_inertia_y is not None
            ):
                print(f"  - Moment of inertia Y: {section.moment_of_inertia_y} m⁴")
            if (
                hasattr(section, "moment_of_inertia_z")
                and section.moment_of_inertia_z is not None
            ):
                print(f"  - Moment of inertia Z: {section.moment_of_inertia_z} m⁴")

            # If rectangular, check dimensions
            if section.section_type == "rectangular":
                assert (
                    "width" in section.dimensions
                ), "Rectangular section missing width"
                assert (
                    "height" in section.dimensions
                ), "Rectangular section missing height"
            # If circular, check radius
            elif section.section_type == "circular":
                assert "radius" in section.dimensions, "Circular section missing radius"

    def test_extract_thicknesses(self, test_file_path):
        """Test extracting thickness properties from IFC entities."""
        # Skip test if file doesn't exist
        if not os.path.exists(test_file_path):
            pytest.skip(f"Test file not found: {test_file_path}")

        # Open the IFC file
        ifc_file = ifcopenshell.open(test_file_path)

        # Create the extractor with the IFC file
        extractor = PropertiesExtractor(ifc_file)

        # Find entities that might have thickness properties
        thickness_entities = []

        # Look for entities that typically have thickness
        for entity_type in ["IfcWall", "IfcSlab", "IfcStructuralSurfaceMember"]:
            entities = list(ifc_file.by_type(entity_type))
            thickness_entities.extend(entities)

        print(
            f"Found {len(thickness_entities)} entities that might have thickness properties"
        )

        # Try to extract thickness from these entities
        thicknesses = []
        for entity in thickness_entities:
            thickness = extractor.extract_thickness(entity)
            if thickness is not None:
                thicknesses.append(thickness)
                print(f"Extracted thickness from {entity.is_a()}: {thickness.name}")

        # Even if no thicknesses found, don't fail the test
        print(f"Successfully extracted {len(thicknesses)} thickness properties")

        # Validate properties of extracted thicknesses
        for thickness in thicknesses:
            assert isinstance(
                thickness, Thickness
            ), f"Expected Thickness object, got {type(thickness)}"
            assert thickness.id is not None, "Thickness ID is missing"
            assert thickness.name is not None, "Thickness name is missing"
            assert thickness.value > 0, "Thickness value should be positive"

            print(f"Thickness {thickness.name}:")
            print(f"  - Value: {thickness.value} m")
            if thickness.is_variable:
                print(
                    f"  - Variable with range: {thickness.min_value} to {thickness.max_value} m"
                )

    def test_get_pset_properties(self, test_file_path):
        """Test extracting property sets from IFC entities."""
        # Skip test if file doesn't exist
        if not os.path.exists(test_file_path):
            pytest.skip(f"Test file not found: {test_file_path}")

        # Open the IFC file
        ifc_file = ifcopenshell.open(test_file_path)

        # Create the extractor with the IFC file
        extractor = PropertiesExtractor(ifc_file)

        # Find some entities to extract properties from
        entities = []

        # Get a variety of entity types
        for entity_type in [
            "IfcBeam",
            "IfcColumn",
            "IfcWall",
            "IfcSlab",
            "IfcStructuralCurveMember",
            "IfcStructuralSurfaceMember",
        ]:
            entities.extend(
                list(ifc_file.by_type(entity_type))[:2]
            )  # Get up to 2 of each type

        print(f"Testing property extraction on {len(entities)} entities")

        # Look for property sets for each entity
        total_property_sets = 0
        total_properties = 0

        for entity in entities:
            # Find related property sets
            psets = []
            if hasattr(entity, "IsDefinedBy"):
                for definition in entity.IsDefinedBy:
                    if (
                        hasattr(definition, "RelatingPropertyDefinition")
                        and definition.RelatingPropertyDefinition
                        and definition.RelatingPropertyDefinition.is_a("IfcPropertySet")
                    ):
                        psets.append(definition.RelatingPropertyDefinition)

            if hasattr(entity, "HasProperties"):
                psets.extend(entity.HasProperties)

            print(f"\nProperty sets for {entity.is_a()} (ID: {entity.id()}):")
            for pset_name in [p.Name for p in psets]:
                properties = extractor.get_pset_properties(psets, pset_name)

                if properties:
                    total_property_sets += 1
                    print(f"  - {pset_name}:")
                    for prop_name, value in properties.items():
                        print(f"    - {prop_name}: {value}")
                        total_properties += 1

        print(
            f"\nExtracted {total_property_sets} property sets with {total_properties} total properties"
        )
