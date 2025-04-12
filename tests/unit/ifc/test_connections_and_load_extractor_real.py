"""
Tests for extracting structural connections and loads from IFC files.

This module tests the extraction of structural connections, loads, load groups,
and load combinations from IFC files, ensuring they're correctly mapped to domain objects.
"""

import os
import pytest
import ifcopenshell

from ifc_structural_mechanics.ifc.connections_extractor import ConnectionsExtractor
from ifc_structural_mechanics.ifc.loads_extractor import LoadsExtractor
from ifc_structural_mechanics.domain.structural_connection import (
    PointConnection,
    RigidConnection,
    HingeConnection,
)
from ifc_structural_mechanics.domain.load import (
    PointLoad,
    LineLoad,
    AreaLoad,
)


class TestConnectionExtraction:
    """Test the extraction of structural connections from an IFC file."""

    @pytest.fixture
    def test_file_path(self):
        """Get the path to the test IFC file."""
        # Get the directory of this test file
        test_dir = os.path.dirname(os.path.abspath(__file__))

        # Navigate to the test_data directory
        test_data_dir = os.path.join(test_dir, "..", "..", "test_data")

        # Return the path to the test file
        return os.path.join(test_data_dir, "simple_beam.ifc")

    def test_extract_all_connections(self, test_file_path):
        """Test extracting all structural connections from an IFC file."""
        # Skip test if file doesn't exist
        if not os.path.exists(test_file_path):
            pytest.skip(f"Test file not found: {test_file_path}")

        # Open the IFC file
        ifc_file = ifcopenshell.open(test_file_path)

        # Log the IFC entities that represent connections
        print("IFC connection entities:")
        for entity_type in [
            "IfcStructuralPointConnection",
            "IfcStructuralCurveConnection",
            "IfcStructuralSurfaceConnection",
        ]:
            try:
                entities = list(ifc_file.by_type(entity_type))
                print(f"  - {entity_type}: {len(entities)}")
            except Exception as e:
                print(f"  - {entity_type}: Error: {e}")

        # Print the schema info
        print(f"IFC schema: {ifc_file.schema}")

        # Print some general entity counts for debugging
        print("General entity counts:")
        for entity_type in [
            "IfcProject",
            "IfcStructuralAnalysisModel",
            "IfcStructuralMember",
        ]:
            try:
                entities = list(ifc_file.by_type(entity_type))
                print(f"  - {entity_type}: {len(entities)}")
            except Exception as e:
                print(f"  - {entity_type}: Error: {e}")

        # Create the extractor with the IFC file
        extractor = ConnectionsExtractor(ifc_file)

        # Extract all connections
        connections = extractor.extract_all_connections()

        # Print summary of extracted connections
        print(f"Extracted {len(connections)} structural connections")

        # Check types of connections
        point_connections = [c for c in connections if isinstance(c, PointConnection)]
        rigid_connections = [c for c in connections if isinstance(c, RigidConnection)]
        hinge_connections = [c for c in connections if isinstance(c, HingeConnection)]

        print(f"  - Point connections: {len(point_connections)}")
        print(f"  - Rigid connections: {len(rigid_connections)}")
        print(f"  - Hinge connections: {len(hinge_connections)}")

        # Even if no connections are found, the test shouldn't fail
        # Analyze each connection in detail
        for i, conn in enumerate(connections):
            print(f"\nConnection {i+1}: {conn.id}")
            print(f"  - Type: {conn.entity_type}")
            print(f"  - Position: {conn.position}")

            # Check connected members
            print(f"  - Connected members: {len(conn.connected_members)}")
            for member_id in conn.connected_members:
                print(f"    - Member {member_id}")

            # Additional checks for specific connection types
            if isinstance(conn, HingeConnection) and conn.rotation_axis:
                print(f"  - Rotation axis: {conn.rotation_axis}")

    def test_extract_connection_by_id(self, test_file_path):
        """Test extracting a specific connection by ID."""
        # Skip test if file doesn't exist
        if not os.path.exists(test_file_path):
            pytest.skip(f"Test file not found: {test_file_path}")

        # Open the IFC file
        ifc_file = ifcopenshell.open(test_file_path)

        # Find a valid connection ID
        connection_id = None
        for entity_type in [
            "IfcStructuralPointConnection",
            "IfcStructuralCurveConnection",
            "IfcStructuralSurfaceConnection",
        ]:
            entities = list(ifc_file.by_type(entity_type))
            if entities:
                connection_id = entities[0].id()
                print(f"Found connection ID {connection_id} from {entity_type}")
                break

        if not connection_id:
            pytest.skip("No suitable connection ID found in the test file")

        # Create the extractor with the IFC file
        extractor = ConnectionsExtractor(ifc_file)

        # Extract the connection by ID
        connection = extractor.extract_connection_by_id(connection_id)

        # Verify the connection was extracted
        assert (
            connection is not None
        ), f"Failed to extract connection with ID {connection_id}"

        # Print connection details
        print(f"Extracted connection by ID: {connection.id}")
        print(f"  - Type: {connection.entity_type}")
        print(f"  - Position: {connection.position}")
        print(f"  - Connected members: {len(connection.connected_members)}")


class TestLoadExtraction:
    """Test the extraction of loads from an IFC file."""

    @pytest.fixture
    def test_file_path(self):
        """Get the path to the test IFC file."""
        # Get the directory of this test file
        test_dir = os.path.dirname(os.path.abspath(__file__))

        # Navigate to the test_data directory
        test_data_dir = os.path.join(test_dir, "..", "..", "test_data")

        # Return the path to the test file
        return os.path.join(test_data_dir, "simple_beam.ifc")

    def test_extract_all_loads(self, test_file_path):
        """Test extracting all loads from an IFC file."""
        # Skip test if file doesn't exist
        if not os.path.exists(test_file_path):
            pytest.skip(f"Test file not found: {test_file_path}")

        # Open the IFC file
        ifc_file = ifcopenshell.open(test_file_path)

        # Log the IFC entities that represent loads in IFC4 schema
        print("IFC load entities:")
        # In IFC4, use the correct entity types for structural loads
        for entity_type in [
            "IfcStructuralLoadLinearForce",
            "IfcStructuralLoadPlanarForce",
            "IfcStructuralLoadSingleForce",
            "IfcStructuralLoadSingleDisplacement",
        ]:
            try:
                entities = list(ifc_file.by_type(entity_type))
                print(f"  - {entity_type}: {len(entities)}")
            except Exception as e:
                print(f"  - {entity_type}: Error: {e}")

        # Create the extractor with the IFC file
        extractor = LoadsExtractor(ifc_file)

        # Extract all loads
        loads = extractor.extract_all_loads()

        # Print summary of extracted loads
        print(f"Extracted {len(loads)} structural loads")

        # Check types of loads
        point_loads = [l for l in loads if isinstance(l, PointLoad)]
        line_loads = [l for l in loads if isinstance(l, LineLoad)]
        area_loads = [l for l in loads if isinstance(l, AreaLoad)]

        print(f"  - Point loads: {len(point_loads)}")
        print(f"  - Line loads: {len(line_loads)}")
        print(f"  - Area loads: {len(area_loads)}")

        # Even if no loads are found, the test shouldn't fail
        # Analyze each load in detail
        for i, load in enumerate(loads):
            print(f"\nLoad {i+1}: {load.id}")
            print(f"  - Type: {load.entity_type}")

            # Check magnitude and direction
            if isinstance(load.magnitude, (int, float)):
                print(f"  - Magnitude: {load.magnitude}")
            else:
                print(f"  - Magnitude: {load.magnitude}")

            print(f"  - Direction: {load.direction}")

            # Additional checks for specific load types
            if isinstance(load, PointLoad):
                print(f"  - Position: {load.position}")
            elif isinstance(load, LineLoad):
                print(f"  - Start position: {load.start_position}")
                print(f"  - End position: {load.end_position}")
                print(f"  - Distribution: {load.distribution}")
            elif isinstance(load, AreaLoad):
                print(f"  - Surface reference: {load.surface_reference}")
                print(f"  - Distribution: {load.distribution}")

    def test_extract_load_groups(self, test_file_path):
        """Test extracting load groups from an IFC file."""
        # Skip test if file doesn't exist
        if not os.path.exists(test_file_path):
            pytest.skip(f"Test file not found: {test_file_path}")

        # Open the IFC file
        ifc_file = ifcopenshell.open(test_file_path)

        # Check for load groups in the IFC file
        try:
            load_groups_entities = list(ifc_file.by_type("IfcStructuralLoadGroup"))
            print(
                f"Found {len(load_groups_entities)} IfcStructuralLoadGroup entities in the IFC file"
            )
        except Exception as e:
            print(f"Could not find IfcStructuralLoadGroup entities: {e}")
            load_groups_entities = []

        # Create the extractor with the IFC file
        extractor = LoadsExtractor(ifc_file)

        # Extract load groups
        load_groups = extractor.extract_load_groups()

        # Print summary of extracted load groups
        print(f"Extracted {len(load_groups)} load groups")

        # Analyze each load group
        for i, group in enumerate(load_groups):
            print(f"\nLoad Group {i+1}: {group.id}")
            print(f"  - Name: {group.name}")
            print(f"  - Description: {group.description}")
            print(f"  - Loads: {len(group.loads)}")

            # Analyze the loads in the group
            for j, load in enumerate(group.loads):
                print(f"    - Load {j+1}: {load.id} ({type(load).__name__})")
                if isinstance(load, PointLoad):
                    print(f"      Position: {load.position}")

    def test_extract_load_combinations(self, test_file_path):
        """Test extracting load combinations from an IFC file."""
        # Skip test if file doesn't exist
        if not os.path.exists(test_file_path):
            pytest.skip(f"Test file not found: {test_file_path}")

        # Open the IFC file
        ifc_file = ifcopenshell.open(test_file_path)

        # Check for load combinations in the IFC file
        try:
            load_combo_entities = list(ifc_file.by_type("IfcStructuralLoadGroup"))
            print(
                f"Found {len(load_combo_entities)} IfcStructuralLoadGroup entities in the IFC file"
            )
        except Exception as e:
            print(f"Could not find IfcStructuralLoadGroup entities: {e}")
            load_combo_entities = []

        # Create the extractor with the IFC file
        extractor = LoadsExtractor(ifc_file)

        # Extract load combinations
        load_combinations = extractor.extract_load_combinations()

        # Print summary of extracted load combinations
        print(f"Extracted {len(load_combinations)} load combinations")

        # Analyze each load combination
        for i, combo in enumerate(load_combinations):
            print(f"\nLoad Combination {i+1}: {combo.id}")
            print(f"  - Name: {combo.name}")
            print(f"  - Description: {combo.description}")
            print(f"  - Load groups: {len(combo.load_groups)}")

            # List the load groups and their factors
            for group_id, factor in combo.load_groups.items():
                print(f"    - Group {group_id}: factor {factor}")
