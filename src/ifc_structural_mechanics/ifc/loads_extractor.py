"""
Loads extractor for IFC4 structural analysis models - CLEANED VERSION.

This module contains the LoadsExtractor class which is responsible for
extracting structural loads, load groups, and load combinations from IFC files
and converting them into domain model objects with proper unit conversion.
"""

import logging
import uuid
from typing import Dict, List, Optional, Tuple, Union

import ifcopenshell
import numpy as np

from ..domain.load import (
    AreaLoad,
    LineLoad,
    Load,
    LoadCombination,
    LoadGroup,
    PointLoad,
)
from ..utils.error_handling import ModelExtractionError
from .entity_identifier import find_member_endpoints


class LoadsExtractor:
    """
    Extracts loads, load groups, and load combinations from IFC4 models.

    This class provides methods to extract structural loads from
    IFC files and convert them to domain model objects.
    """

    # IFC4 entity types for structural loads
    POINT_LOAD_TYPE = "IfcStructuralPointAction"
    LINE_LOAD_TYPE = "IfcStructuralLinearAction"
    CURVE_LOAD_TYPE = "IfcStructuralCurveAction"
    AREA_LOAD_TYPE = "IfcStructuralPlanarAction"
    LOAD_GROUP_TYPE = "IfcStructuralLoadGroup"
    LOAD_CASE_TYPE = "IfcStructuralLoadCase"

    def __init__(
        self,
        ifc_file: Union[str, ifcopenshell.file],
        unit_scales: Optional[Dict[str, float]] = None,
    ):
        """
        Initialize a LoadsExtractor.

        Args:
            ifc_file: Path to an IFC file or an ifcopenshell.file object
            unit_scales: Dictionary of unit scale factors for different unit types

        Raises:
            ValueError: If ifc_file is invalid
            FileNotFoundError: If the IFC file does not exist
        """
        self.logger = logging.getLogger(__name__)

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
            raise ModelExtractionError(
                "ifc_file must be a file path or an ifcopenshell.file object"
            )

        # Store unit scales - only keep the ones actually used
        self.unit_scales = unit_scales or {}
        self.length_scale = self.unit_scales.get("LENGTHUNIT", 1.0)
        self.force_scale = self.unit_scales.get("FORCEUNIT", 1.0)

        # Cache for already extracted loads to avoid duplications
        self._load_cache = {}

        # What the analysis will not do exactly as the file says; the
        # Extractor passes these on to the results
        self.warnings: List[str] = []

    def extract_all_loads(self) -> List[Load]:
        """
        Extract all structural loads from the IFC file.

        Returns:
            List of extracted loads as domain objects
        """
        self.logger.info("Extracting all structural loads")
        load_entities = []

        # Get all IFC4 structural load entities
        for entity_type in [
            self.POINT_LOAD_TYPE,
            self.LINE_LOAD_TYPE,
            self.CURVE_LOAD_TYPE,
            self.AREA_LOAD_TYPE,
        ]:
            entities = self._entities_of_type(entity_type)
            load_entities.extend(entities)
            self.logger.info(f"Found {len(entities)} {entity_type} entities")

        # Convert entities to domain objects
        loads = []
        for entity in load_entities:
            load = self._create_domain_load(entity)
            loads.append(load)
            # Cache the load for future reference
            self._load_cache[getattr(entity, "GlobalId", str(uuid.uuid4()))] = load

        self.logger.info(f"Extracted {len(loads)} structural loads")
        return loads

    def _entities_of_type(self, entity_type: str) -> list:
        """Entities of a type, or none where the file's schema has no such type.

        IFC2X3 has no ``IfcStructuralLoadCase`` or ``IfcStructuralCurveAction``;
        asking for them raises ``RuntimeError``, and there is nothing to read.
        """
        try:
            return list(self.ifc.by_type(entity_type))
        except RuntimeError:
            self.logger.debug(f"The schema of this file has no {entity_type}")
            return []

    def extract_load_groups(self) -> List[LoadGroup]:
        """
        Extract all load groups from the IFC file.

        Returns:
            List of extracted load groups as domain objects
        """
        self.logger.info("Extracting load groups")

        # Collect all load group entities (both regular load groups and load cases)
        load_group_entities = []
        load_case_entities = []

        # Find all load groups (excluding combinations and load cases).
        # PredefinedType can be LOAD_GROUP, GRAVITY, VARIABLE_Q,
        # PRESTRESS_LOAD, etc.: all are valid load-bearing groups.
        for group_entity in self._entities_of_type(self.LOAD_GROUP_TYPE):
            if not group_entity.is_a(
                "IfcStructuralLoadCombination"
            ) and not group_entity.is_a("IfcStructuralLoadCase"):
                load_group_entities.append(group_entity)
        self.logger.info(f"Found {len(load_group_entities)} load groups")

        load_case_entities = self._entities_of_type(self.LOAD_CASE_TYPE)
        self.logger.info(f"Found {len(load_case_entities)} load cases")

        # Create domain objects for each load group and load case
        all_groups = {}  # Map from GlobalId to LoadGroup

        # First create all simple load groups
        for group_entity in load_group_entities:
            group_id = group_entity.GlobalId
            group_name = getattr(group_entity, "Name", f"Group-{group_id[:8]}")
            group_description = getattr(group_entity, "Description", None)

            # Create the domain load group
            load_group = LoadGroup(
                id=group_id, name=group_name, description=group_description
            )
            all_groups[group_id] = load_group

        # Then create all load cases
        for case_entity in load_case_entities:
            case_id = case_entity.GlobalId
            case_name = getattr(case_entity, "Name", f"Case-{case_id[:8]}")
            case_description = getattr(case_entity, "Description", None)

            # Create the domain load case (which is also a LoadGroup)
            load_case = LoadGroup(
                id=case_id,
                name=case_name,
                description=case_description,
                is_load_case=True,
            )
            all_groups[case_id] = load_case

        # Process direct assignments of loads to regular load groups
        for group_entity in load_group_entities:
            group_id = group_entity.GlobalId
            load_group = all_groups[group_id]

            # Look for directly assigned loads via IfcRelAssignsToGroup
            for rel in self.ifc.by_type("IfcRelAssignsToGroup"):
                if (
                    hasattr(rel, "RelatingGroup")
                    and hasattr(rel.RelatingGroup, "GlobalId")
                    and rel.RelatingGroup.GlobalId == group_id
                ):
                    # Add each related load if it's a structural action
                    for obj in rel.RelatedObjects:
                        if (
                            hasattr(obj, "GlobalId")
                            and hasattr(obj, "is_a")
                            and callable(obj.is_a)
                            # Any action: point, curve/linear, surface/planar
                            and obj.is_a("IfcStructuralAction")
                        ):
                            load_group.add_load(self._create_domain_load(obj))

        # Process load cases - they can have both direct loads and references to load groups
        for case_entity in load_case_entities:
            case_id = case_entity.GlobalId
            load_case = all_groups[case_id]

            # Process direct assignments via IfcRelAssignsToGroup
            for rel in self.ifc.by_type("IfcRelAssignsToGroup"):
                if (
                    hasattr(rel, "RelatingGroup")
                    and hasattr(rel.RelatingGroup, "GlobalId")
                    and rel.RelatingGroup.GlobalId == case_id
                ):
                    for obj in rel.RelatedObjects:
                        if hasattr(obj, "GlobalId"):
                            # Check for directly assigned loads
                            if (
                                hasattr(obj, "is_a")
                                and callable(obj.is_a)
                                # Any action: point, curve/linear,
                                # surface/planar. Listing subtypes here once
                                # dropped IfcStructuralCurveAction, so loads
                                # assigned straight to a load case lost its name.
                                and obj.is_a("IfcStructuralAction")
                            ):
                                load_case.add_load(self._create_domain_load(obj))

                            # Check for referenced load groups (any PredefinedType)
                            elif (
                                hasattr(obj, "is_a")
                                and callable(obj.is_a)
                                and obj.is_a("IfcStructuralLoadGroup")
                                and not obj.is_a("IfcStructuralLoadCombination")
                                and obj.GlobalId in all_groups
                            ):
                                # Get all loads from the referenced group
                                referenced_group = all_groups[obj.GlobalId]
                                for load in referenced_group.loads:
                                    load_case.add_load(load)

        # Return all populated groups
        return list(all_groups.values())

    def extract_load_combinations(self) -> List[LoadCombination]:
        """
        Extract all load combinations from the IFC file.

        Returns:
            List of extracted load combinations as domain objects
        """
        self.logger.info("Extracting load combinations")

        # Get all load groups first (we need them for mapping)
        all_groups = self.extract_load_groups()
        group_map = {group.id: group for group in all_groups}

        # Find all load combination entities
        load_combinations = []

        try:
            # Find all entities that are load combinations
            combination_entities = []
            for entity in self.ifc.by_type(self.LOAD_GROUP_TYPE):
                if (
                    hasattr(entity, "PredefinedType")
                    and entity.PredefinedType == "LOAD_COMBINATION"
                ):
                    combination_entities.append(entity)

            self.logger.info(
                f"Found {len(combination_entities)} load combination entities"
            )

            # Process each combination entity
            for combo_entity in combination_entities:
                try:
                    # Extract basic properties
                    combo_id = combo_entity.GlobalId
                    combo_name = getattr(combo_entity, "Name", f"Combo-{combo_id[:8]}")
                    combo_description = getattr(combo_entity, "Description", None)

                    # Create the domain load combination
                    load_combination = LoadCombination(
                        id=combo_id, name=combo_name, description=combo_description
                    )

                    # Look for load cases included in this combination via IfcRelAssignsToGroup
                    for rel in self.ifc.by_type("IfcRelAssignsToGroup"):
                        if (
                            hasattr(rel, "RelatingGroup")
                            and hasattr(rel.RelatingGroup, "GlobalId")
                            and rel.RelatingGroup.GlobalId == combo_id
                        ):
                            # Get the factor if available
                            factor = 1.0
                            if hasattr(rel, "Factor") and rel.Factor is not None:
                                factor = float(rel.Factor)

                            # Process each related object - only allow load cases
                            for obj in rel.RelatedObjects:
                                if (
                                    hasattr(obj, "GlobalId")
                                    and obj.is_a(self.LOAD_CASE_TYPE)
                                    and obj.GlobalId in group_map
                                ):
                                    # Add to combination with factor
                                    load_combination.add_load_group(
                                        obj.GlobalId, factor
                                    )
                                    self.logger.debug(
                                        f"Added load case {obj.GlobalId} to combination {combo_id} with factor {factor}"
                                    )

                    # Add the combination to our result list if it has any load groups
                    if len(load_combination.load_groups) > 0:
                        load_combinations.append(load_combination)
                        self.logger.debug(
                            f"Created load combination: {combo_name} ({combo_id})"
                        )
                except ModelExtractionError:
                    raise
                except Exception as e:
                    raise ModelExtractionError(
                        f"Error creating load combination from {getattr(combo_entity, 'GlobalId', 'unknown')}: {e}"
                    ) from e
        except ModelExtractionError:
            raise
        except Exception as e:
            raise ModelExtractionError(
                f"Error extracting load combinations: {e}"
            ) from e

        self.logger.info(f"Extracted {len(load_combinations)} load combinations")
        return load_combinations

    def _create_domain_load(self, ifc_load):
        """
        Create a domain load object from an IFC load entity.

        Args:
            ifc_load: IFC load entity

        Returns:
            Domain load object

        Raises:
            ModelExtractionError: If the load cannot be read or is of a kind
                the analysis does not support. A load is never left out: the
                results would be those of a different loading.
        """
        load_id = getattr(ifc_load, "GlobalId", None) or "?"
        try:
            return self._build_domain_load(ifc_load)
        except ModelExtractionError as error:
            raise ModelExtractionError(
                f"Load {load_id} cannot be analysed. {error.message}"
            ) from error
        except Exception as error:
            raise ModelExtractionError(
                f"Load {load_id} cannot be read from the IFC file: "
                f"{type(error).__name__}: {error}"
            ) from error

    @staticmethod
    def _refuse_moments(applied_load, attributes) -> None:
        """Raise if an applied load carries a moment; they are not analysed."""
        present = [
            name
            for name in attributes
            if isinstance(getattr(applied_load, name, None), (int, float))
            and getattr(applied_load, name) != 0
        ]
        if present:
            raise ModelExtractionError(
                f"It applies a moment ({', '.join(present)}); applied moments "
                "are not supported."
            )

    def _build_domain_load(self, ifc_load):
        """Create the domain load of an IFC action; see ``_create_domain_load``."""
        load_id = getattr(ifc_load, "GlobalId", None) or str(uuid.uuid4())
        applied_load = getattr(ifc_load, "AppliedLoad", None)
        if applied_load is None:
            raise ModelExtractionError("It has no AppliedLoad.")

        # For structural point actions
        if ifc_load.is_a("IfcStructuralPointAction"):
            if not applied_load.is_a("IfcStructuralLoadSingleForce"):
                raise ModelExtractionError(
                    f"Its applied load is an {applied_load.is_a()}; on a point "
                    "action only IfcStructuralLoadSingleForce is supported."
                )
            self._refuse_moments(applied_load, ("MomentX", "MomentY", "MomentZ"))
            force_x = getattr(applied_load, "ForceX", 0.0) or 0.0
            force_y = getattr(applied_load, "ForceY", 0.0) or 0.0
            force_z = getattr(applied_load, "ForceZ", 0.0) or 0.0
            force_vector = [f * self.force_scale for f in (force_x, force_y, force_z)]

            # Extract position
            position = self._extract_load_position(ifc_load)

            # Calculate direction
            magnitude = np.array(force_vector, dtype=float)
            norm = np.linalg.norm(magnitude)

            if norm > 1e-10:
                direction = magnitude / norm
            else:
                # Default direction if magnitude is near zero
                direction = np.array([0.0, 0.0, -1.0], dtype=float)

            # Create the point load
            return PointLoad(
                id=load_id,
                magnitude=magnitude,
                direction=direction,
                position=position,
            )

        # For line loads (IfcStructuralLinearAction or IfcStructuralCurveAction)
        elif ifc_load.is_a("IfcStructuralLinearAction") or ifc_load.is_a(
            "IfcStructuralCurveAction"
        ):
            force_vector, is_per_length = self._extract_line_force_vector(applied_load)

            # Apply appropriate unit scale
            if is_per_length:
                # Linear force (force/length): scale = force_scale / length_scale
                scale = self.force_scale / self.length_scale
            else:
                # Concentrated force: scale = force_scale
                scale = self.force_scale
            force_vector = [f * scale for f in force_vector]

            # Extract start and end positions
            start_pos, end_pos = self._extract_load_line(ifc_load)

            # Calculate direction
            magnitude = np.array(force_vector, dtype=float)
            norm = np.linalg.norm(magnitude)

            if norm > 1e-10:
                direction = magnitude / norm
            else:
                # Default direction
                direction = np.array([0.0, 0.0, -1.0], dtype=float)

            # Create the line load
            line_load = LineLoad(
                id=load_id,
                magnitude=magnitude,
                direction=direction,
                start_position=start_pos,
                end_position=end_pos,
            )

            # Extract member reference from AssignedToStructuralItem
            member_ref = self._get_member_reference(ifc_load)
            if member_ref:
                line_load.member_reference = member_ref
            line_load.coordinate_system = self._coordinate_system(ifc_load)

            return line_load

        # For area loads
        elif ifc_load.is_a("IfcStructuralPlanarAction"):
            if hasattr(applied_load, "PlanarForceX"):
                # IFC standard: IfcStructuralLoadPlanarForce uses PlanarForceX/Y/Z
                force_x = getattr(applied_load, "PlanarForceX", 0.0) or 0.0
                force_y = getattr(applied_load, "PlanarForceY", 0.0) or 0.0
                force_z = getattr(applied_load, "PlanarForceZ", 0.0) or 0.0
                force_vector = [force_x, force_y, force_z]

                # Planar force is force/area: scale = force_scale / length_scale^2
                area_scale = self.force_scale / (self.length_scale**2)
                force_vector = [f * area_scale for f in force_vector]
            elif hasattr(applied_load, "ForceX"):
                # Fallback: IfcStructuralLoadSingleForce uses ForceX/Y/Z
                force_x = getattr(applied_load, "ForceX", 0.0) or 0.0
                force_y = getattr(applied_load, "ForceY", 0.0) or 0.0
                force_z = getattr(applied_load, "ForceZ", 0.0) or 0.0
                force_vector = [force_x, force_y, force_z]

                # Apply force scale
                force_vector = [f * self.force_scale for f in force_vector]
            else:
                raise ModelExtractionError(
                    f"Its applied load is an {applied_load.is_a()}; on a planar "
                    "action only IfcStructuralLoadPlanarForce is supported."
                )

            # Find related surface
            surface_ref = self._get_surface_reference(ifc_load)

            # Calculate direction
            magnitude = np.array(force_vector, dtype=float)
            norm = np.linalg.norm(magnitude)

            if norm > 1e-10:
                direction = magnitude / norm
            else:
                # Default direction
                direction = np.array([0.0, 0.0, -1.0], dtype=float)

            # Create the area load
            area_load = AreaLoad(
                id=load_id,
                magnitude=magnitude,
                direction=direction,
                surface_reference=surface_ref,
            )
            area_load.coordinate_system = self._coordinate_system(ifc_load)
            return area_load

        raise ModelExtractionError(
            f"It is an {ifc_load.is_a()}; only point, linear, curve and planar "
            "actions are supported."
        )

    @staticmethod
    def _coordinate_system(ifc_load) -> str:
        """Return "local" for an action given in its member's axes, else "global"."""
        value = getattr(ifc_load, "GlobalOrLocal", None)
        return "local" if value == "LOCAL_COORDS" else "global"

    def _get_member_reference(self, ifc_load) -> Optional[str]:
        """
        Get the GlobalId of the structural member this load is applied to.

        Uses the IFC AssignedToStructuralItem inverse relationship.

        Args:
            ifc_load: IFC structural action entity

        Returns:
            GlobalId of the related structural member, or None
        """
        if hasattr(ifc_load, "AssignedToStructuralItem"):
            for rel in ifc_load.AssignedToStructuralItem:
                if rel.is_a("IfcRelConnectsStructuralActivity"):
                    element = getattr(rel, "RelatingElement", None)
                    if element and hasattr(element, "GlobalId"):
                        return element.GlobalId
        return None

    def _extract_line_force_vector(self, applied_load) -> Tuple[List[float], bool]:
        """
        Extract force vector from a line load's applied load entity.

        Handles multiple IFC load types:
        - IfcStructuralLoadLinearForce: has LinearForceX/Y/Z (force per length)
        - IfcStructuralLoadSingleForce: has ForceX/Y/Z (concentrated force)
        - IfcStructuralLoadConfiguration: contains Values list of the above

        Args:
            applied_load: IFC applied load entity

        Returns:
            Tuple of ([fx, fy, fz] in project units, is_per_length flag)
        """
        # Handle IfcStructuralLoadConfiguration (wraps multiple load values).
        # Average all values so that linearly-varying (trapezoidal) loads get
        # the correct resultant rather than just using the value at one end.
        if applied_load.is_a("IfcStructuralLoadConfiguration"):
            values = list(getattr(applied_load, "Values", None) or [])
            if not values:
                raise ModelExtractionError("Its load configuration has no values.")
            vectors = []
            last_is_per_length = False
            for v in values:
                vec, ipl = self._extract_line_force_vector(v)
                vectors.append(vec)
                last_is_per_length = ipl
            n = len(vectors)
            avg = [sum(v[i] for v in vectors) / n for i in range(3)]
            if any(not np.allclose(v, vectors[0]) for v in vectors):
                self.warnings.append(
                    "A load that varies along its member (an "
                    "IfcStructuralLoadConfiguration with differing values) is "
                    "applied as a uniform load of its mean value: the total is "
                    "kept, its distribution is not."
                )
            return avg, last_is_per_length

        # Handle IfcStructuralLoadLinearForce (force per unit length)
        if hasattr(applied_load, "LinearForceX"):
            self._refuse_moments(
                applied_load, ("LinearMomentX", "LinearMomentY", "LinearMomentZ")
            )
            force_x = getattr(applied_load, "LinearForceX", 0.0) or 0.0
            force_y = getattr(applied_load, "LinearForceY", 0.0) or 0.0
            force_z = getattr(applied_load, "LinearForceZ", 0.0) or 0.0
            return [force_x, force_y, force_z], True

        # Handle IfcStructuralLoadSingleForce (concentrated force)
        if hasattr(applied_load, "ForceX"):
            self._refuse_moments(applied_load, ("MomentX", "MomentY", "MomentZ"))
            force_x = getattr(applied_load, "ForceX", 0.0) or 0.0
            force_y = getattr(applied_load, "ForceY", 0.0) or 0.0
            force_z = getattr(applied_load, "ForceZ", 0.0) or 0.0
            return [force_x, force_y, force_z], False

        raise ModelExtractionError(
            f"Its applied load is an {applied_load.is_a()}; on a linear or curve "
            "action only linear forces, single forces and configurations of "
            "them are supported."
        )

    def _get_surface_reference(self, ifc_load) -> str:
        """
        Get the surface reference for an area load.

        Args:
            ifc_load: IFC area load entity

        Returns:
            ID of the referenced surface
        """
        # Method 1: Check AssignedToStructuralItem (IFC4 pattern)
        if hasattr(ifc_load, "AssignedToStructuralItem"):
            for rel in ifc_load.AssignedToStructuralItem:
                if rel.is_a("IfcRelConnectsStructuralActivity"):
                    if hasattr(rel, "RelatingElement") and rel.RelatingElement:
                        element = rel.RelatingElement
                        if hasattr(element, "GlobalId"):
                            self.logger.debug(
                                f"Found surface reference via AssignedToStructuralItem: {element.GlobalId}"
                            )
                            return element.GlobalId

        # Method 2: Use inverse relationships to find IfcRelConnectsStructuralActivity
        if hasattr(self.ifc, "get_inverse"):
            inverse_rels = self.ifc.get_inverse(ifc_load)
            for rel in inverse_rels:
                if rel.is_a("IfcRelConnectsStructuralActivity"):
                    if hasattr(rel, "RelatingElement") and rel.RelatingElement:
                        element = rel.RelatingElement
                        if hasattr(element, "GlobalId"):
                            self.logger.debug(
                                f"Found surface reference via inverse relationship: {element.GlobalId}"
                            )
                            return element.GlobalId

        raise ModelExtractionError(
            "It is not assigned to a structural member "
            "(no IfcRelConnectsStructuralActivity)."
        )

    def _extract_load_position(self, ifc_load) -> List[float]:
        """
        Extract the position for a point load.

        The position is the load's own vertex, or the vertex of the item the
        load is assigned to (a point connection). The placement of a member
        is not a position for a load and is not used as one.

        Args:
            ifc_load: IFC point load entity

        Returns:
            [x, y, z] position coordinates in SI units

        Raises:
            ModelExtractionError: If neither gives a position.
        """
        candidates = [getattr(ifc_load, "PointLocation", None)]
        items = [ifc_load] + [
            rel.RelatingElement
            for rel in getattr(ifc_load, "AssignedToStructuralItem", None) or []
            if getattr(rel, "RelatingElement", None) is not None
        ]
        for item in items:
            representation = getattr(item, "Representation", None)
            for rep in getattr(representation, "Representations", None) or []:
                if rep.RepresentationType != "Vertex":
                    continue
                candidates.extend(
                    getattr(vertex, "VertexGeometry", None) for vertex in rep.Items
                )
        for location in candidates:
            coords = getattr(location, "Coordinates", None)
            if coords:
                padded = [float(c) for c in coords] + [0.0, 0.0]
                return [c * self.length_scale for c in padded[:3]]
        raise ModelExtractionError(
            "Its position cannot be found: it has no vertex of its own and "
            "is not assigned to an item that has one."
        )

    def _extract_load_line(self, ifc_load) -> Tuple[List[float], List[float]]:
        """
        Extract the start and end positions for a line load.

        They are the ends of the curve member the load is assigned to.

        Args:
            ifc_load: IFC line load entity

        Returns:
            Tuple of (start_position, end_position) in SI units

        Raises:
            ModelExtractionError: If the load is not assigned to a curve
                member whose ends can be read.
        """
        for rel in getattr(ifc_load, "AssignedToStructuralItem", None) or []:
            endpoints = find_member_endpoints(
                getattr(rel, "RelatingElement", None), self.length_scale
            )
            if len(endpoints) >= 2:
                return list(endpoints[0]), list(endpoints[1])
        raise ModelExtractionError(
            "It is not assigned to a curve member whose ends can be read."
        )
