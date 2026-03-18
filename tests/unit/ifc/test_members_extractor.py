"""
Tests for extracting structural members from IFC4 files.

This module tests the extraction of structural members from IFC4 files, including
curve members (beams, columns) and surface members (walls, slabs).
"""

import os

import ifcopenshell
import pytest

from ifc_structural_mechanics.domain.property import Material, Section, Thickness
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.ifc.members_extractor import MembersExtractor


class TestMemberExtraction:
    """Test the extraction of structural members from an IFC4 file."""

    @pytest.fixture
    def test_file_path(self):
        """Get the path to the test IFC file."""
        # Get the directory of this test file
        test_dir = os.path.dirname(os.path.abspath(__file__))

        # Navigate to the test_data directory
        test_data_dir = os.path.join(test_dir, "..", "..", "test_data")

        # Return the path to the test file
        return os.path.join(test_data_dir, "simple_beam.ifc")

    def test_extract_all_members(self, test_file_path):
        """Test extracting all structural members from an IFC4 file."""
        # Skip test if file doesn't exist
        if not os.path.exists(test_file_path):
            pytest.skip(f"Test file not found: {test_file_path}")

        # Open the IFC file
        ifc_file = ifcopenshell.open(test_file_path)

        # Skip test if not IFC4
        if ifc_file.schema != "IFC4":
            pytest.skip(
                f"Test file has schema {ifc_file.schema}, but this test is for IFC4 only"
            )

        # Log the IFC schema and contents for debugging
        print(f"IFC schema: {ifc_file.schema}")
        print("IFC entities by type:")
        for entity_type in [
            "IfcProject",
            "IfcStructuralAnalysisModel",
            "IfcStructuralCurveMember",
            "IfcStructuralSurfaceMember",
            "IfcBeam",
            "IfcColumn",
            "IfcWall",
            "IfcSlab",
        ]:
            try:
                entities = list(ifc_file.by_type(entity_type))
                print(f"  - {entity_type}: {len(entities)}")
            except Exception as e:
                print(f"  - {entity_type}: Error: {e}")

        # Print IFC4-specific entity types
        print("IFC4-specific entity types:")
        for entity_type in [
            "IfcStructuralMember",
            "IfcStructuralConnection",
            "IfcStructuralLoadCase",
            "IfcStructuralResultGroup",
        ]:
            try:
                entities = list(ifc_file.by_type(entity_type))
                print(f"  - {entity_type}: {len(entities)}")
            except Exception as e:
                print(f"  - {entity_type}: Error: {e}")

        # Create the extractor with the IFC file
        extractor = MembersExtractor(ifc_file)

        # Extract all members
        members = extractor.extract_all_members()

        # Verify members were extracted
        print(f"Extracted {len(members)} total structural members")
        assert len(members) > 0, "No structural members were extracted"

        # Verify types of members
        curve_members = [m for m in members if isinstance(m, CurveMember)]
        surface_members = [m for m in members if isinstance(m, SurfaceMember)]

        print(f"  - Curve members: {len(curve_members)}")
        print(f"  - Surface members: {len(surface_members)}")

        # Check all members have required properties
        for i, member in enumerate(members):
            print(f"\nMember {i+1}: {member.id}")
            print(
                f"  - Type: {'curve' if isinstance(member, CurveMember) else 'surface'}"
            )

            # Check geometry
            assert member.geometry is not None, f"Member {member.id} has no geometry"
            if isinstance(member.geometry, tuple) and len(member.geometry) == 2:
                print(
                    f"  - Geometry: Line from {member.geometry[0]} to {member.geometry[1]}"
                )
            else:
                print(f"  - Geometry: {type(member.geometry)}")

            # Check material
            if member.material is not None:
                if isinstance(member.material, Material):
                    print(f"  - Material: {member.material.name}")
                    print(f"    - Density: {member.material.density}")
                    print(f"    - Elastic modulus: {member.material.elastic_modulus}")
                    print(f"    - Poisson ratio: {member.material.poisson_ratio}")
                else:
                    print(f"  - Material: {member.material}")
            else:
                print("  - Material: None")

            # Check section or thickness
            if isinstance(member, CurveMember):
                if member.section is not None:
                    if isinstance(member.section, Section):
                        print(f"  - Section: {member.section.name}")
                        print(f"    - Type: {member.section.section_type}")
                        print(f"    - Area: {member.section.area}")
                        print(f"    - Dimensions: {member.section.dimensions}")

                        # Verify section properties for IFC4
                        assert (
                            member.section.area > 0
                        ), "Section area should be positive"
                        assert member.section.section_type in [
                            "rectangular",
                            "circular",
                            "i",
                            "hollow_rectangular",
                            "hollow_circular",
                            "t",
                            "l",
                            "c",
                        ], f"Invalid section type: {member.section.section_type}"
                    else:
                        print(f"  - Section: {member.section}")
                else:
                    print("  - Section: None")

            elif isinstance(member, SurfaceMember):
                if member.thickness is not None:
                    if isinstance(member.thickness, Thickness):
                        print(f"  - Thickness: {member.thickness.name}")
                        print(f"    - Value: {member.thickness.value}")

                        # Verify thickness properties for IFC4
                        assert (
                            member.thickness.value > 0
                        ), "Thickness value should be positive"
                    else:
                        print(f"  - Thickness: {member.thickness}")
                else:
                    print("  - Thickness: None")

    def test_extract_curve_members(self, test_file_path):
        """Test extracting curve members specifically."""
        # Skip test if file doesn't exist
        if not os.path.exists(test_file_path):
            pytest.skip(f"Test file not found: {test_file_path}")

        # Open the IFC file
        ifc_file = ifcopenshell.open(test_file_path)

        # Skip test if not IFC4
        if ifc_file.schema != "IFC4":
            pytest.skip(
                f"Test file has schema {ifc_file.schema}, but this test is for IFC4 only"
            )

        # Create the extractor with the IFC file
        extractor = MembersExtractor(ifc_file)

        # Extract curve members
        curve_members = extractor.extract_curve_members()

        print(f"Extracted {len(curve_members)} curve members")

        # If no curve members were found, this might be normal for this file
        if not curve_members:
            print("No curve members found in the test file.")
            return

        # Check the first curve member in detail
        member = curve_members[0]
        print(f"Example curve member: {member.id}")

        # Check geometry
        assert member.geometry is not None, "Member has no geometry"
        if isinstance(member.geometry, tuple) and len(member.geometry) == 2:
            start_point, end_point = member.geometry
            print(f"Geometry: Line from {start_point} to {end_point}")

            # Verify the points are 3D coordinates
            assert len(start_point) == 3, "Start point should be 3D"
            assert len(end_point) == 3, "End point should be 3D"

            # Check that start and end points are different (valid line)
            assert start_point != end_point, "Start and end points should be different"
        else:
            print(f"Geometry type: {type(member.geometry)}")

        # Check material if present
        if member.material is not None:
            print(
                f"Material: {member.material.name if isinstance(member.material, Material) else type(member.material)}"
            )
            if isinstance(member.material, Material):
                assert (
                    member.material.elastic_modulus > 0
                ), "Elastic modulus should be positive"
                assert (
                    0 <= member.material.poisson_ratio < 0.5
                ), "Poisson ratio should be between 0 and 0.5"
                assert (
                    member.material.density > 0
                ), "Material density should be positive"
