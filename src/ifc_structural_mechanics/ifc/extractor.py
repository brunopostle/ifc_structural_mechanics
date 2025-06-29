"""
Main extractor coordinator for IFC structural analysis models.

This module contains the Extractor class which coordinates the extraction of
structural analysis models from IFC files, using specialized extractors for
different parts of the model.
"""

import logging
import os
from typing import List, Optional, Union, Dict
import uuid

import ifcopenshell
import ifcopenshell.util.unit

from ..domain.structural_model import StructuralModel

from .members_extractor import MembersExtractor
from .properties_extractor import PropertiesExtractor
from .connections_extractor import ConnectionsExtractor
from .loads_extractor import LoadsExtractor
from .entity_identifier import (
    is_structural_member,
    is_structural_connection,
    is_structural_load,
    is_structural_curve_member,
    is_structural_surface_member,
)


class Extractor:
    """
    Coordinator for extracting a complete structural model from an IFC file.

    This class orchestrates the extraction process using specialized extractors
    for different parts of the structural model (members, connections, loads, etc.).
    """

    def __init__(self, ifc_file: Union[str, ifcopenshell.file]):
        """
        Initialize an Extractor.

        Args:
            ifc_file: Path to an IFC file or an ifcopenshell.file object

        Raises:
            ValueError: If ifc_file is invalid
            FileNotFoundError: If the IFC file does not exist
        """
        self.logger = logging.getLogger(__name__)
        self.warnings = []  # Store warnings for reporting

        # Handle different input types
        if isinstance(ifc_file, str):
            try:
                self.ifc = ifcopenshell.open(ifc_file)
                self.logger.info(f"Opened IFC file: {ifc_file}")
            except Exception as e:
                self.logger.error(f"Failed to open IFC file: {e}")
                raise FileNotFoundError(f"Could not open IFC file: {ifc_file}")
        elif hasattr(ifc_file, "by_type") and callable(ifc_file.by_type):
            # This is likely an ifcopenshell.file object or a valid mock
            self.ifc = ifc_file
            self.logger.info("Using provided ifcopenshell.file object")
        else:
            self.logger.error("Invalid IFC file parameter provided")
            raise ValueError(
                "ifc_file must be a file path or an ifcopenshell.file object"
            )

        # Get unit scale factors for different unit types
        self.unit_scales = self._get_unit_scales()

        # Initialize specialized extractors with unit scales
        self.members_extractor = MembersExtractor(self.ifc, self.unit_scales)
        self.properties_extractor = PropertiesExtractor(self.ifc, self.unit_scales)
        self.connections_extractor = ConnectionsExtractor(self.ifc, self.unit_scales)
        self.loads_extractor = LoadsExtractor(self.ifc, self.unit_scales)

    def _get_unit_scales(self) -> Dict[str, float]:
        """
        Calculate unit scale factors for different unit types.

        Returns:
            Dict[str, float]: Dictionary of unit scale factors
        """
        unit_scales = {}

        try:
            # Common unit types used in structural analysis
            unit_types = [
                "LENGTHUNIT",
                "FORCEUNIT",
                "PRESSUREUNIT",
                "MOMENTUNIT",
                "MASSUNIT",
                "TIMEUNIT",
            ]

            for unit_type in unit_types:
                try:
                    scale = ifcopenshell.util.unit.calculate_unit_scale(
                        self.ifc, unit_type
                    )
                    unit_scales[unit_type] = scale
                    self.logger.info(f"Unit scale for {unit_type}: {scale}")
                except Exception as e:
                    # If we can't get a specific unit, use default scale (1.0)
                    unit_scales[unit_type] = 1.0
                    self.logger.warning(
                        f"Could not determine scale for {unit_type}, using 1.0: {e}"
                    )

            # If we couldn't get any units, use defaults
            if not unit_scales:
                unit_scales = {
                    "LENGTHUNIT": 1.0,  # Default: meters
                    "FORCEUNIT": 1.0,  # Default: newtons
                    "PRESSUREUNIT": 1.0,  # Default: pascals
                    "MOMENTUNIT": 1.0,  # Default: newton meters
                    "MASSUNIT": 1.0,  # Default: kilograms
                    "TIMEUNIT": 1.0,  # Default: seconds
                }
                self.logger.warning(
                    "Could not determine unit scales, using default values (SI units)"
                )

        except Exception as e:
            self.logger.error(f"Error getting unit scales: {e}")
            # Use default values
            unit_scales = {
                "LENGTHUNIT": 1.0,
                "FORCEUNIT": 1.0,
                "PRESSUREUNIT": 1.0,
                "MOMENTUNIT": 1.0,
                "MASSUNIT": 1.0,
                "TIMEUNIT": 1.0,
            }

        return unit_scales

    def extract_model(
        self, model_id: Optional[str] = None, name: Optional[str] = None
    ) -> StructuralModel:
        """
        Extract a complete structural model from the IFC file.

        Args:
            model_id: Optional ID for the model (will be generated if not provided)
            name: Optional name for the model (will be extracted from IFC if not provided)

        Returns:
            A complete StructuralModel containing all extracted information
        """
        self.logger.info("Extracting complete structural model")

        # Find structural analysis model in IFC
        analysis_models = list(self.ifc.by_type("IfcStructuralAnalysisModel"))

        if analysis_models:
            self.logger.info(f"Found {len(analysis_models)} structural analysis models")
            # Use the first analysis model if multiple are present
            analysis_model = analysis_models[0]

            # Use analysis model ID and name if not provided
            if model_id is None:
                model_id = analysis_model.GlobalId
            if name is None:
                name = analysis_model.Name or "Structural Analysis Model"

            # Get all structural items from the model
            model = StructuralModel(model_id, name)

            # Extract items from the analysis model's groups
            self._extract_items_from_analysis_model(analysis_model, model)

            # Extract loads and load groups
            self._extract_loads_for_model(model)

            self._extract_properties_for_model(model)

        else:
            self.logger.info(
                "No IfcStructuralAnalysisModel found, extracting structural elements directly"
            )
            # Create a new model with provided or default ID/name
            if model_id is None:
                model_id = self._generate_model_id()
            if name is None:
                name = self._extract_model_name() or "Structural Analysis Model"

            # Create a new structural model
            model = StructuralModel(model_id, name)

            # Extract structural elements directly
            self._extract_items_directly(model)

            # Extract loads and load groups
            self._extract_loads_for_model(model)

            self._extract_properties_for_model(model)

        return model

    def _extract_items_from_analysis_model(self, analysis_model, model):
        """
        Extract structural items from an analysis model by traversing its groups.

        Args:
            analysis_model: The IfcStructuralAnalysisModel entity
            model: The domain model to populate
        """
        # Get all structural items grouped in the analysis model
        for group in analysis_model.IsGroupedBy:
            if hasattr(group, "RelatedObjects"):
                for item in group.RelatedObjects:
                    if is_structural_member(item):
                        try:
                            if is_structural_curve_member(item):
                                member = self.members_extractor._create_curve_member(
                                    item
                                )
                                if member:
                                    model.add_member(member)
                            elif is_structural_surface_member(item):
                                member = self.members_extractor._create_surface_member(
                                    item
                                )
                                if member:
                                    model.add_member(member)
                        except Exception as e:
                            self.warnings.append(
                                f"Failed to extract member {item.GlobalId}: {e}"
                            )
                            self.logger.error(f"Failed to extract member: {e}")

                    elif is_structural_connection(item):
                        try:
                            connection = (
                                self.connections_extractor._create_domain_connection(
                                    item
                                )
                            )
                            if connection:
                                model.add_connection(connection)
                        except Exception as e:
                            self.warnings.append(
                                f"Failed to extract connection {item.GlobalId}: {e}"
                            )
                            self.logger.error(f"Failed to extract connection: {e}")

                    elif is_structural_load(item):
                        # Extract load directly
                        try:
                            load = self.loads_extractor._create_domain_load(item)
                            if load:
                                # We'll handle adding to load groups later
                                pass
                        except Exception as e:
                            self.warnings.append(
                                f"Failed to extract load {item.GlobalId}: {e}"
                            )
                            self.logger.error(f"Failed to extract load: {e}")

        # Report results
        self.logger.info(f"Added {len(model.members)} structural members to the model")
        self.logger.info(
            f"Added {len(model.connections)} structural connections to the model"
        )

    def _extract_items_directly(self, model):
        """
        Extract structural items directly from the IFC file when no analysis model is present.

        Args:
            model: The domain model to populate
        """
        # Extract members
        try:
            curve_members = []
            for entity in self.ifc.by_type("IfcStructuralCurveMember"):
                try:
                    member = self.members_extractor._create_curve_member(entity)
                    if member:
                        curve_members.append(member)
                        model.add_member(member)
                except Exception as e:
                    self.warnings.append(
                        f"Failed to extract curve member {entity.GlobalId}: {e}"
                    )
                    self.logger.warning(f"Failed to extract curve member: {e}")

            surface_members = []
            for entity in self.ifc.by_type("IfcStructuralSurfaceMember"):
                try:
                    member = self.members_extractor._create_surface_member(entity)
                    if member:
                        surface_members.append(member)
                        model.add_member(member)
                except Exception as e:
                    self.warnings.append(
                        f"Failed to extract surface member {entity.GlobalId}: {e}"
                    )
                    self.logger.warning(f"Failed to extract surface member: {e}")

            self.logger.info(
                f"Added {len(curve_members) + len(surface_members)} structural members to the model"
            )
        except Exception as e:
            self.logger.error(f"Failed to extract members: {e}")
            self.warnings.append(f"Failed to extract members: {e}")

        # Extract connections
        try:
            connections = []
            for entity_type in [
                "IfcStructuralPointConnection",
                "IfcStructuralCurveConnection",
                "IfcStructuralSurfaceConnection",
            ]:
                for entity in self.ifc.by_type(entity_type):
                    try:
                        connection = (
                            self.connections_extractor._create_domain_connection(entity)
                        )
                        if connection:
                            connections.append(connection)
                            model.add_connection(connection)
                    except Exception as e:
                        self.warnings.append(
                            f"Failed to extract connection {entity.GlobalId}: {e}"
                        )
                        self.logger.warning(f"Failed to extract connection: {e}")

            self.logger.info(
                f"Added {len(connections)} structural connections to the model"
            )
        except Exception as e:
            self.logger.error(f"Failed to extract connections: {e}")
            self.warnings.append(f"Failed to extract connections: {e}")

    def _extract_loads_for_model(self, model):
        """
        Extract loads, load groups, and load combinations for the model.

        Args:
            model: The domain model to populate with loads and load groups
        """
        try:
            # Extract load groups
            self.logger.info("Extracting load groups")
            load_groups = self.loads_extractor.extract_load_groups()
            self.logger.info(f"Extracted {len(load_groups)} load groups from IFC")

            # Add all valid load groups to the model
            valid_group_count = 0
            for group in load_groups:
                if len(group.loads) > 0:
                    model.add_load_group(group)
                    valid_group_count += 1
                    self.logger.info(
                        f"Added load group '{group.name}' with {len(group.loads)} loads"
                    )

            # If we didn't add any groups but have some load groups,
            # something might be wrong with the load assignments
            if valid_group_count == 0 and load_groups:
                # Create a basic integrity test - extract all loads directly
                # and see if we can assign them to groups
                all_loads = self.loads_extractor.extract_all_loads()
                if all_loads:
                    # Create a default group for these loads
                    from ..domain.load import LoadGroup
                    import uuid

                    default_group = LoadGroup(
                        id=str(uuid.uuid4()),
                        name="Default Load Group",
                        description="Automatically created for unassigned loads",
                    )

                    for load in all_loads:
                        default_group.add_load(load)

                    model.add_load_group(default_group)
                    self.logger.info(
                        f"Created default load group with {len(all_loads)} loads"
                    )
                    valid_group_count += 1

            # Extract load combinations
            self.logger.info("Extracting load combinations")
            load_combinations = self.loads_extractor.extract_load_combinations()

            # Add all combinations to the model
            for combo in load_combinations:
                model.add_load_combination(combo)
                self.logger.info(f"Added load combination '{combo.name}'")

                # Make sure the referenced load groups exist in the model
                for group_id in combo.load_groups.keys():
                    if model.get_load_group(group_id) is None:
                        # This load group doesn't exist, find it in the original load_groups list
                        for group in load_groups:
                            if group.id == group_id:
                                # Add this group to the model even if it has no loads
                                model.add_load_group(group)
                                self.logger.info(
                                    f"Added load group '{group.name}' referenced by combination"
                                )
                                break

            # Report results
            self.logger.info(f"Added {len(model.load_groups)} load groups to the model")
            self.logger.info(
                f"Added {len(model.load_combinations)} load combinations to the model"
            )

        except Exception as e:
            self.logger.error(f"Failed to extract loads for model: {e}")
            self.warnings.append(f"Failed to extract loads: {e}")

    def _extract_properties_for_model(self, model):
        """Extract material and section properties for all members."""
        try:
            materials_extracted = 0
            sections_extracted = 0

            # Extract properties for each member
            for member in model.members:
                # Get the original IFC entity for this member
                ifc_entity = self._find_ifc_entity_by_id(member.id)
                if not ifc_entity:
                    continue

                # Extract material if not already set
                if not hasattr(member, "material") or member.material is None:
                    material = self.properties_extractor.extract_material(ifc_entity)
                    if material:
                        member.material = material
                        materials_extracted += 1

                # Extract section if not already set
                if not hasattr(member, "section") or member.section is None:
                    section = self.properties_extractor.extract_section(ifc_entity)
                    if section:
                        member.section = section
                        sections_extracted += 1

                # For surface members, extract thickness
                if hasattr(member, "member_type") and member.member_type == "surface":
                    if not hasattr(member, "thickness") or member.thickness is None:
                        thickness = self.properties_extractor.extract_thickness(
                            ifc_entity
                        )
                        if thickness:
                            member.thickness = thickness

            self.logger.info(
                f"Extracted {materials_extracted} materials and {sections_extracted} sections"
            )

        except Exception as e:
            self.logger.error(f"Failed to extract properties: {e}")
            self.warnings.append(f"Failed to extract properties: {e}")

    def _find_ifc_entity_by_id(self, entity_id):
        """Find IFC entity by GlobalId."""
        try:
            # Search through relevant IFC entity types
            entity_types = [
                "IfcStructuralCurveMember",
                "IfcStructuralSurfaceMember",
                "IfcStructuralPointConnection",
                "IfcStructuralCurveConnection",
                "IfcStructuralSurfaceConnection",
            ]

            for entity_type in entity_types:
                for entity in self.ifc.by_type(entity_type):
                    if hasattr(entity, "GlobalId") and entity.GlobalId == entity_id:
                        return entity

        except Exception as e:
            self.logger.warning(f"Error finding IFC entity for ID {entity_id}: {e}")

        return None

    def _generate_model_id(self) -> str:
        """
        Generate a unique ID for the model.

        Returns:
            A unique ID string
        """
        return str(uuid.uuid4())

    def _extract_model_name(self) -> Optional[str]:
        """
        Extract a name for the model from the IFC file.

        Returns:
            A name string or None if extraction fails
        """
        try:
            # Try to get name from project
            projects = list(self.ifc.by_type("IfcProject"))
            if projects and hasattr(projects[0], "Name") and projects[0].Name:
                return projects[0].Name

            # Try to get name from the filename
            if hasattr(self.ifc, "wrapped_data") and hasattr(
                self.ifc.wrapped_data, "filename"
            ):
                filename = self.ifc.wrapped_data.filename
                return os.path.splitext(os.path.basename(filename))[0]

            return None
        except Exception as e:
            self.logger.warning(f"Failed to extract model name: {e}")
            return None

    def get_warnings(self) -> List[str]:
        """
        Get a list of warnings encountered during extraction.

        Returns:
            List of warning messages
        """
        return self.warnings
