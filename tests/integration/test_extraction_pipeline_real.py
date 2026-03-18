"""
Integration tests for the IFC structural model extraction process.

This module tests the full extraction process from an IFC file to domain model objects,
using actual IFC test files instead of mocks.
"""

import os

import ifcopenshell
import pytest

from ifc_structural_mechanics.domain.load import AreaLoad, LineLoad, PointLoad
from ifc_structural_mechanics.domain.structural_member import CurveMember, SurfaceMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.ifc.extractor import Extractor


class TestIFCExtraction:
    """Test the extraction of structural model from an actual IFC file."""

    @pytest.fixture
    def test_file_path(self):
        """Get the path to the test IFC file."""
        # Get the directory of this test file
        test_dir = os.path.dirname(os.path.abspath(__file__))

        # Navigate to the test_data directory
        test_data_dir = os.path.join(test_dir, "..", "test_data")

        # Return the path to the test file
        return os.path.join(test_data_dir, "simple_beam.ifc")

    def test_extract_model(self, test_file_path):
        """Test extracting a complete structural model from an IFC file."""
        # Skip test if file doesn't exist
        if not os.path.exists(test_file_path):
            pytest.skip(f"Test file not found: {test_file_path}")

        # Open the IFC file
        ifc_file = ifcopenshell.open(test_file_path)

        # Create the extractor with the IFC file
        extractor = Extractor(ifc_file)

        # Extract the model
        model = extractor.extract_model()

        # Basic verification
        assert model is not None
        assert isinstance(model, StructuralModel)

        # Verify model metadata
        assert model.id is not None
        assert model.name is not None

        # Print some debug info about the extracted model
        print(f"Extracted model: {model.name} (ID: {model.id})")
        print(f"Members: {len(model.members)}")
        print(f"Connections: {len(model.connections)}")
        print(f"Load groups: {len(model.load_groups)}")
        print(f"Load combinations: {len(model.load_combinations)}")

        # If members exist, check at least one has proper properties
        if model.members:
            # Verify at least one member has material and section/thickness properties
            has_material = False
            has_section_or_thickness = False

            for member in model.members:
                if member.material is not None:
                    has_material = True

                if isinstance(member, CurveMember) and member.section is not None:
                    has_section_or_thickness = True
                elif isinstance(member, SurfaceMember) and member.thickness is not None:
                    has_section_or_thickness = True

            # Only assert if we have members
            if len(model.members) > 0:
                assert has_material, "No members have material properties"
                assert (
                    has_section_or_thickness
                ), "No members have section or thickness properties"

        # If connections exist, check their properties
        if model.connections:
            for conn in model.connections:
                print(f"Connection {conn.id}")
                print(f"  - Type: {conn.entity_type}")
                print(f"  - Position: {conn.position}")
                print(f"  - Connected members: {conn.connected_members}")

        # If load groups exist, check their properties
        if model.load_groups:
            for group in model.load_groups:
                print(f"Load group {group.id}: {group.name}")
                print(f"  - Loads: {len(group.loads)}")

                for load in group.loads:
                    if isinstance(load, PointLoad):
                        print(f"    - Point load at {load.position}")
                    elif isinstance(load, LineLoad):
                        print(
                            f"    - Line load from {load.start_position} to {load.end_position}"
                        )
                    elif isinstance(load, AreaLoad):
                        print(f"    - Area load on surface {load.surface_reference}")
                    else:
                        print(f"    - Generic load of type {load.load_type}")
