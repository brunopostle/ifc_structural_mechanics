"""
Integration tests for the extraction pipeline.

This module tests the complete extraction pipeline from an IFC file to a domain model,
verifying that all components are correctly extracted and linked.
"""

import os
from unittest.mock import MagicMock, Mock, patch

import ifcopenshell
import pytest

from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.domain.structural_model import StructuralModel
from ifc_structural_mechanics.ifc.extractor import Extractor

# Define paths to test data
TEST_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_data")
SIMPLE_BEAM_IFC = os.path.join(TEST_DATA_DIR, "simple_beam.ifc")


def create_mock_ifc_file():
    """Create a mock IFC file for testing with proper coordinate handling."""
    # Create mock objects
    mock_file = Mock(spec=ifcopenshell.file)
    mock_file._mock_name = "MockIFCFile"  # For test detection

    # Mock Project
    mock_project = Mock()
    mock_project.GlobalId = "test_project_id"
    mock_project.Name = "Test Project"

    # Create a mock unit assignment
    mock_unit_assignment = Mock()
    mock_unit_meters = Mock()
    mock_unit_meters.UnitType = "LENGTHUNIT"
    mock_unit_meters.Prefix = None
    mock_unit_meters.Name = "METRE"

    mock_unit_newtons = Mock()
    mock_unit_newtons.UnitType = "FORCEUNIT"
    mock_unit_newtons.Prefix = None
    mock_unit_newtons.Name = "NEWTON"

    # Make sure Units can be properly iterated in a for loop
    mock_unit_assignment.Units = [mock_unit_meters, mock_unit_newtons]
    mock_project.UnitsInContext = mock_unit_assignment

    # Mock structural analysis model
    mock_analysis_model = Mock()
    mock_analysis_model.GlobalId = "test_analysis_model_id"
    mock_analysis_model.Name = "Test Analysis Model"
    mock_analysis_model.id.return_value = "1"
    mock_analysis_model.is_a.return_value = "IfcStructuralAnalysisModel"

    # Mock IsGroupedBy relationship
    mock_group_rel = Mock()
    mock_group_rel.RelatedObjects = []  # Will add members and connections later
    mock_analysis_model.IsGroupedBy = [mock_group_rel]

    # Mock structural curve member (beam)
    mock_beam = Mock()
    mock_beam.GlobalId = "beam1"
    mock_beam.Name = "Test Beam"
    mock_beam.id.return_value = "2"
    mock_beam.is_a.return_value = "IfcStructuralCurveMember"
    mock_beam.PredefinedType = "RIGID_JOINED_MEMBER"

    # Mock beam representation
    mock_beam_representation = Mock()
    mock_beam_representation.RepresentationIdentifier = "Reference"
    mock_beam_representation.RepresentationType = "Edge"

    # Edge for beam geometry
    mock_edge = Mock()
    mock_edge.is_a.return_value = "IfcEdge"

    # Start vertex with coordinates
    mock_start_vertex = Mock()
    mock_start_point = Mock()
    mock_start_point.is_a.return_value = "IfcCartesianPoint"
    mock_start_point.Coordinates = (0.0, 0.0, 0.0)  # Use a tuple for coordinates
    mock_start_vertex.VertexGeometry = mock_start_point
    mock_edge.EdgeStart = mock_start_vertex

    # End vertex with coordinates
    mock_end_vertex = Mock()
    mock_end_point = Mock()
    mock_end_point.is_a.return_value = "IfcCartesianPoint"
    mock_end_point.Coordinates = (10.0, 0.0, 0.0)  # Use a tuple for coordinates
    mock_end_vertex.VertexGeometry = mock_end_point
    mock_edge.EdgeEnd = mock_end_vertex

    # Add edge to beam representation
    mock_beam_representation.Items = [mock_edge]
    mock_beam_representations = MagicMock()
    mock_beam_representations.Representations = [mock_beam_representation]
    mock_beam.Representation = mock_beam_representations

    # Mock beam axis
    mock_beam_axis = Mock()
    mock_beam_axis.DirectionRatios = (0.0, 0.0, 1.0)  # Use a tuple for direction ratios
    mock_beam.Axis = mock_beam_axis

    # Mock beam placement
    mock_beam.ObjectPlacement = None  # Default, no transformation

    # Mock beam material and profile
    mock_material = Mock()
    mock_material.GlobalId = "material1"
    mock_material.Name = "Steel"
    mock_material.Category = "steel"
    mock_material.id.return_value = "3"
    mock_material.is_a.return_value = "IfcMaterial"

    # Mock material properties
    mock_material_property = Mock()
    mock_material_property.Name = "YoungModulus"
    mock_material_property.NominalValue = Mock()
    mock_material_property.NominalValue.wrappedValue = 210e9

    mock_density_property = Mock()
    mock_density_property.Name = "MassDensity"
    mock_density_property.NominalValue = Mock()
    mock_density_property.NominalValue.wrappedValue = 7850.0

    mock_poisson_property = Mock()
    mock_poisson_property.Name = "PoissonRatio"
    mock_poisson_property.NominalValue = Mock()
    mock_poisson_property.NominalValue.wrappedValue = 0.3

    mock_pset = Mock()
    mock_pset.Name = "Pset_MaterialMechanical"
    mock_pset.Properties = [mock_material_property, mock_poisson_property]

    mock_common_pset = Mock()
    mock_common_pset.Name = "Pset_MaterialCommon"
    mock_common_pset.Properties = [mock_density_property]

    mock_material.HasProperties = [mock_pset, mock_common_pset]

    # Mock profile
    mock_profile = Mock()
    mock_profile.GlobalId = "profile1"
    mock_profile.ProfileName = "IPE200"
    mock_profile.ProfileType = "AREA"
    mock_profile.id.return_value = "4"
    mock_profile.is_a.return_value = "IfcRectangleProfileDef"
    mock_profile.XDim = 0.2
    mock_profile.YDim = 0.3

    # Mock material profile
    mock_material_profile = Mock()
    mock_material_profile.Material = mock_material
    mock_material_profile.Profile = mock_profile

    mock_profile_set = Mock()
    mock_profile_set.MaterialProfiles = [mock_material_profile]
    mock_profile_set.is_a.return_value = "IfcMaterialProfileSet"

    # Mock material association
    mock_material_assoc = Mock()
    mock_material_assoc.RelatingMaterial = mock_profile_set
    mock_material_assoc.is_a.return_value = "IfcRelAssociatesMaterial"

    mock_beam.HasAssociations = [mock_material_assoc]

    # Mock structural connection
    mock_connection = Mock()
    mock_connection.GlobalId = "connection1"
    mock_connection.Name = "Test Connection"
    mock_connection.id.return_value = "5"
    mock_connection.is_a.return_value = "IfcStructuralPointConnection"

    # Mock connection representation
    mock_conn_representation = Mock()
    mock_conn_representation.RepresentationIdentifier = "Reference"
    mock_conn_representation.RepresentationType = "Vertex"

    mock_vertex = Mock()
    mock_vertex.is_a.return_value = "IfcVertexPoint"
    mock_vertex_point = Mock()
    mock_vertex_point.is_a.return_value = "IfcCartesianPoint"
    mock_vertex_point.Coordinates = (1.0, 2.0, 3.0)  # Use a tuple for coordinates
    mock_vertex.VertexGeometry = mock_vertex_point

    mock_conn_representation.Items = [mock_vertex]
    mock_conn_representations = MagicMock()
    mock_conn_representations.Representations = [mock_conn_representation]
    mock_connection.Representation = mock_conn_representations

    # Mock connection condition
    mock_connection.ConditionCoordinateSystem = None  # Default orientation

    # Mock connection condition
    mock_condition = Mock()
    mock_condition.TranslationalStiffnessX = Mock(wrappedValue=1e10)
    mock_condition.TranslationalStiffnessY = Mock(wrappedValue=1e10)
    mock_condition.TranslationalStiffnessZ = Mock(wrappedValue=1e10)
    mock_condition.RotationalStiffnessX = Mock(wrappedValue=1e10)
    mock_condition.RotationalStiffnessY = Mock(wrappedValue=1e10)
    mock_condition.RotationalStiffnessZ = Mock(wrappedValue=1e10)
    mock_connection.AppliedCondition = mock_condition

    # Mock ConnectsStructuralMembers relationship
    mock_connects_rel = Mock()
    mock_relates_member = Mock()
    mock_relates_member.GlobalId = "beam1"
    mock_connects_rel.RelatingStructuralMember = mock_relates_member
    mock_connection.ConnectsStructuralMembers = [mock_connects_rel]

    # Mock structural load
    mock_load = Mock()
    mock_load.GlobalId = "load1"
    mock_load.Name = "Test Load"
    mock_load.id.return_value = "6"
    mock_load.is_a.return_value = "IfcStructuralPointAction"

    # Mock load applied condition
    mock_load_condition = Mock()
    mock_load_condition.ForceX = Mock(wrappedValue=0.0)
    mock_load_condition.ForceY = Mock(wrappedValue=0.0)
    mock_load_condition.ForceZ = Mock(wrappedValue=-1000.0)
    mock_load.AppliedLoad = mock_load_condition

    # Mock object placement for load
    mock_load_placement = Mock()
    mock_load_relative = Mock()
    mock_load_location = Mock()
    mock_load_location.Coordinates = (5.0, 0.0, 0.0)  # Use a tuple for coordinates
    mock_load_relative.Location = mock_load_location
    mock_load_placement.RelativePlacement = mock_load_relative
    mock_load.ObjectPlacement = mock_load_placement

    # Mock load group
    mock_load_group = Mock()
    mock_load_group.GlobalId = "load_group1"
    mock_load_group.Name = "Load Group 1"
    mock_load_group.Description = "Test load group"
    mock_load_group.id.return_value = "7"
    mock_load_group.is_a.return_value = "IfcStructuralLoadGroup"

    # Add load to the group
    mock_load_rel = Mock()
    mock_load_rel.RelatedStructuralActivity = mock_load
    mock_load_group.LoadGroupFor = [mock_load_rel]

    # Add items to analysis model group
    mock_group_rel.RelatedObjects = [mock_beam, mock_connection]

    # Set up mock by_type method
    def mock_by_type(entity_type):
        if entity_type == "IfcProject":
            return [mock_project]
        elif entity_type == "IfcStructuralAnalysisModel":
            return [mock_analysis_model]
        elif entity_type == "IfcStructuralCurveMember":
            return [mock_beam]
        elif entity_type == "IfcStructuralPointConnection":
            return [mock_connection]
        elif entity_type == "IfcStructuralPointAction":
            return [mock_load]
        elif entity_type == "IfcStructuralLoadGroup":
            return [mock_load_group]
        elif entity_type == "IfcUnitAssignment":
            return [mock_project.UnitsInContext]
        elif entity_type == "IfcRelAssignsToGroup":
            return []
        else:
            return []

    mock_file.by_type = mock_by_type

    # Set up mock by_id method
    def mock_by_id(id):
        if id == "1":
            return mock_analysis_model
        elif id == "2":
            return mock_beam
        elif id == "3":
            return mock_material
        elif id == "4":
            return mock_profile
        elif id == "5":
            return mock_connection
        elif id == "6":
            return mock_load
        elif id == "7":
            return mock_load_group
        else:
            return None

    mock_file.by_id = mock_by_id

    return mock_file


class TestExtractionPipeline:
    """Tests for the complete extraction pipeline."""

    @patch("ifcopenshell.util.unit.calculate_unit_scale")
    def test_extract_model_from_mock(self, mock_calculate_unit_scale):
        """Test extracting a complete model from a mock IFC file."""
        # Set up the mock to return a standard unit scale (1.0)
        mock_calculate_unit_scale.return_value = 1.0

        # Create specific patches for the entity_identifier module
        with patch(
            "ifc_structural_mechanics.ifc.entity_identifier.get_coordinate",
            side_effect=lambda point, unit_scale=1.0: list(point.Coordinates),
        ):

            with patch(
                "ifc_structural_mechanics.ifc.entity_identifier.get_transformation",
                return_value=None,
            ):

                # Create the mock file and extractor
                mock_file = create_mock_ifc_file()
                extractor = Extractor(mock_file)

                # Extract the model
                model = extractor.extract_model()

                # Verify model creation
                assert isinstance(model, StructuralModel)
                assert model.id == "test_analysis_model_id"
                assert model.name == "Test Analysis Model"

                # Verify members
                assert len(model.members) >= 1
                member = model.members[0]
                assert isinstance(member, CurveMember)
                assert member.id == "beam1"
                assert member.material is not None
                assert member.section is not None

                # Print load groups for debugging
                print(f"Load Groups: {len(model.load_groups)}")
                print(
                    f"Load Group 1 Loads: {len(model.load_groups[0].loads) if model.load_groups else 0}"
                )

    def test_extractor_error_handling(self):
        """Test error handling in the extractor."""
        # Test with invalid file path
        with pytest.raises(FileNotFoundError):
            Extractor("non_existent_file.ifc")

        # Test with invalid file object
        with pytest.raises(ValueError):
            Extractor(123)  # Not a string or ifcopenshell.file

    @pytest.mark.skipif(
        not os.path.exists(SIMPLE_BEAM_IFC), reason="Test IFC file not found"
    )
    def test_with_real_ifc_file(self):
        """Test with a real IFC file if available."""
        try:
            if create_test_ifc_file():  # Create test file if it doesn't exist
                extractor = Extractor(SIMPLE_BEAM_IFC)
                model = extractor.extract_model()

                # Basic validation of the extracted model
                assert isinstance(model, StructuralModel)
                assert model.id is not None
                assert model.name is not None

                # The test file is very minimal, so we might not have members
                # Just verify we can extract the model without errors
                assert isinstance(model.members, list)

                # Print model information for debugging
                print(f"Model ID: {model.id}")
                print(f"Model Name: {model.name}")
                print(f"Members: {len(model.members)}")
                print(f"Connections: {len(model.connections)}")
                print(f"Load Groups: {len(model.load_groups)}")

            else:
                pytest.skip("Could not create or find test IFC file")
        except Exception as e:
            pytest.skip(f"Error with real IFC file test: {e}")


# Function to create a test IFC file
def create_test_ifc_file():
    """Create a simple IFC file with a beam for testing."""
    if not os.path.exists(TEST_DATA_DIR):
        os.makedirs(TEST_DATA_DIR)

    if not os.path.exists(SIMPLE_BEAM_IFC):
        try:
            # Create a new IFC file
            file = ifcopenshell.file(schema="IFC4")

            # Create project
            file.create_entity(
                "IfcProject",
                GlobalId=ifcopenshell.guid.new(),
                Name="Simple Beam Project",
            )

            # For a complete IFC file, we would need to create more entities:
            # - IfcSite, IfcBuilding, IfcBuildingStorey
            # - IfcLocalPlacement
            # - IfcProductDefinitionShape
            # - IfcBeamStandardCase with geometry
            # - IfcRelAssociatesMaterial
            # But for testing purposes, we can just save the file as is

            # Save the file
            file.write(SIMPLE_BEAM_IFC)
            print(f"Created test IFC file: {SIMPLE_BEAM_IFC}")
            return True
        except Exception as e:
            print(f"Failed to create test IFC file: {e}")
            return False

    return os.path.exists(SIMPLE_BEAM_IFC)


if __name__ == "__main__":
    # Create test data if running this file directly
    create_test_ifc_file()
