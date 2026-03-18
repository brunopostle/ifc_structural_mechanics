"""
Detailed test for debugging IFC simple beam parsing with extensive logging.
"""

import logging
import os

import ifcopenshell
import pytest

from ifc_structural_mechanics.domain.load import PointLoad
from ifc_structural_mechanics.domain.structural_member import CurveMember
from ifc_structural_mechanics.ifc.extractor import Extractor

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class TestSimpleBeamParsing:
    """
    Comprehensive test for parsing a simple beam IFC model.
    """

    @pytest.fixture
    def ifc_file_path(self):
        """Fixture to get the path to the simple beam IFC file."""
        ifc_path = os.path.join("tests", "test_data", "simple_beam.ifc")
        assert os.path.exists(ifc_path), f"Test IFC file not found: {ifc_path}"
        return ifc_path

    @pytest.fixture
    def ifc_model(self, ifc_file_path):
        """Fixture to load the IFC file."""
        return ifcopenshell.open(ifc_file_path)

    def test_detailed_extraction_debug(self, ifc_file_path):
        """
        Detailed debug test to understand model extraction.
        """
        # Run the extractor
        extractor = Extractor(ifc_file_path)
        structural_model = extractor.extract_model()

        # Detailed logging of extracted components
        logger.info("DETAILED MODEL EXTRACTION DEBUG")
        logger.info("=" * 40)

        # Log members
        logger.info(f"Total Members: {len(structural_model.members)}")
        for i, member in enumerate(structural_model.members):
            logger.info(f"Member {i}:")
            logger.info(f"  ID: {member.id}")
            logger.info(f"  Type: {type(member)}")
            logger.info(f"  Geometry: {member.geometry}")

            # Log material details if available
            if hasattr(member, "material") and member.material is not None:
                logger.info(
                    f"  Material: {member.material.name if hasattr(member.material, 'name') else member.material}"
                )

            # Log section details for curve members
            if (
                isinstance(member, CurveMember)
                and hasattr(member, "section")
                and member.section is not None
            ):
                logger.info(
                    f"  Section: {member.section.name if hasattr(member.section, 'name') else member.section}"
                )

        # Log connections
        logger.info(f"Total Connections: {len(structural_model.connections)}")
        for i, connection in enumerate(structural_model.connections):
            logger.info(f"Connection {i}:")
            logger.info(f"  Type: {type(connection)}")
            logger.info(f"  ID: {connection.id}")
            logger.info(f"  Connection Type: {connection.entity_type}")
            logger.info(f"  Position: {connection.position}")
            logger.info(f"  Connected Members: {connection.connected_members}")

        # Log loads in detail
        logger.info(f"Total Load Groups: {len(structural_model.load_groups)}")
        for i, load_group in enumerate(structural_model.load_groups):
            logger.info(f"Load Group {i}:")
            logger.info(f"  ID: {load_group.id}")
            logger.info(f"  Name: {load_group.name}")
            logger.info(f"  Description: {getattr(load_group, 'description', 'N/A')}")
            logger.info(f"  Total Loads: {len(load_group.loads)}")

            for j, load in enumerate(load_group.loads):
                logger.info(f"  Load {j}:")
                logger.info(f"    Type: {type(load)}")
                logger.info(f"    ID: {load.id}")
                if hasattr(load, "position"):
                    logger.info(f"    Position: {load.position}")
                logger.info(f"    Magnitude: {load.magnitude}")
                logger.info(f"    Direction: {load.direction}")

        # Basic assertions
        assert len(structural_model.members) > 0, "No members extracted"
        assert len(structural_model.connections) > 0, "No connections extracted"
        assert len(structural_model.load_groups) > 0, "No load groups extracted"

        # Structural model checks specific to simple_beam.ifc
        assert len(structural_model.members) == 1, "Expected 1 beam member"
        assert (
            len(structural_model.connections) == 2
        ), "Expected 2 connections (start/end supports)"

        # Verify loads from simple_beam.ifc
        assert len(structural_model.load_groups) > 0, "No load groups found"

        # Find the load group with the point action
        point_action_group = None
        for group in structural_model.load_groups:
            for load in group.loads:
                if isinstance(load, PointLoad):
                    point_action_group = group
                    break
            if point_action_group:
                break

        assert point_action_group is not None, "No load group with point load found"

    def test_ifc_entity_types(self, ifc_model, ifc_file_path):
        """
        Debug IFC file entity types to understand the structure.
        """
        # Detailed logging of all IFC entity types
        all_entities = {}
        for entity_type in ifc_model.types():
            entities = list(ifc_model.by_type(entity_type))
            if entities:
                all_entities[entity_type] = len(entities)

        logger.info("IFC FILE ENTITY TYPES")
        logger.info("=" * 40)
        for entity_type, count in sorted(
            all_entities.items(), key=lambda x: x[1], reverse=True
        ):
            logger.info(f"{entity_type}: {count}")

        # Special focus on structural entities
        structural_entity_types = [
            "IfcStructuralCurveMember",
            "IfcStructuralPointConnection",
            "IfcStructuralPointAction",
            "IfcStructuralLoadSingleForce",
            "IfcStructuralLoadGroup",
            "IfcRelAssignsToGroup",
        ]

        for entity_type in structural_entity_types:
            entities = list(ifc_model.by_type(entity_type))
            logger.info(f"\n{entity_type} Details:")
            for entity in entities:
                logger.info(f"ID: {entity.id()}")

                # Safely access attributes
                if hasattr(entity, "GlobalId"):
                    logger.info(f"Global ID: {entity.GlobalId}")

                if hasattr(entity, "Name"):
                    logger.info(f"Name: {entity.Name}")
                else:
                    logger.info("Name: N/A")

                # Additional context for each entity type
                if entity_type == "IfcStructuralCurveMember":
                    if hasattr(entity, "PredefinedType"):
                        logger.info(f"Predefined Type: {entity.PredefinedType}")

                # Print force values for loads
                if entity_type == "IfcStructuralLoadSingleForce":
                    if hasattr(entity, "ForceX"):
                        logger.info(f"ForceX: {entity.ForceX}")
                    if hasattr(entity, "ForceY"):
                        logger.info(f"ForceY: {entity.ForceY}")
                    if hasattr(entity, "ForceZ"):
                        logger.info(f"ForceZ: {entity.ForceZ}")

                # Print relationship info
                if entity_type == "IfcRelAssignsToGroup":
                    if hasattr(entity, "RelatingGroup"):
                        relating_group = entity.RelatingGroup
                        if hasattr(relating_group, "GlobalId"):
                            logger.info(f"Relating Group: {relating_group.GlobalId}")
                        if hasattr(relating_group, "Name"):
                            logger.info(f"Relating Group Name: {relating_group.Name}")

                    if hasattr(entity, "RelatedObjects"):
                        for i, obj in enumerate(entity.RelatedObjects):
                            if hasattr(obj, "GlobalId"):
                                logger.info(
                                    f"Related Object {i} GlobalId: {obj.GlobalId}"
                                )
                            logger.info(f"Related Object {i} Type: {obj.is_a()}")

                logger.info("-" * 20)
