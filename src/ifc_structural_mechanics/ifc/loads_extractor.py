"""
Loads extractor for IFC4 structural analysis models - CLEANED VERSION.

This module contains the LoadsExtractor class which is responsible for
extracting structural loads, load groups, and load combinations from IFC files
and converting them into domain model objects with proper unit conversion.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

import ifcopenshell
import numpy as np

from ..domain.load import (
    HALF_WAVE_MEANS,
    HALF_WAVES,
    AreaLoad,
    LineLoad,
    Load,
    LoadCombination,
    LoadGroup,
    PointLoad,
)
from ..utils.error_handling import ModelExtractionError
from .entity_identifier import (
    find_member_endpoints,
    get_item_transformation,
    transform_vectors,
)


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
        listed = set()

        # Get all IFC4 structural load entities. A linear action is a curve
        # action as well, and is listed once.
        for entity_type in [
            self.POINT_LOAD_TYPE,
            self.LINE_LOAD_TYPE,
            self.CURVE_LOAD_TYPE,
            self.AREA_LOAD_TYPE,
        ]:
            entities = [
                entity
                for entity in self._entities_of_type(entity_type)
                if getattr(entity, "GlobalId", None) not in listed
            ]
            listed.update(getattr(entity, "GlobalId", None) for entity in entities)
            listed.discard(None)
            load_entities.extend(entities)
            self.logger.info(f"Found {len(entities)} {entity_type} entities")

        # Convert entities to domain objects
        loads = []
        for entity in load_entities:
            for load in self._create_domain_loads(entity):
                loads.append(load)
                # Cache the load for future reference
                self._load_cache[load.id] = load

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
            coefficients = case_entity.SelfWeightCoefficients
            if coefficients is not None:
                load_case.self_weight_coefficients = [float(c) for c in coefficients]
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
                            for load in self._create_domain_loads(obj):
                                load_group.add_load(load)

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
                                for load in self._create_domain_loads(obj):
                                    load_case.add_load(load)

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

        A combination is an ``IfcStructuralLoadGroup`` with the predefined
        type ``LOAD_COMBINATION``. Each ``IfcRelAssignsToGroup`` that fills it
        gives its load cases a factor: ``Factor`` of an
        ``IfcRelAssignsToGroupByFactor``, otherwise 1. The combination's own
        ``Coefficient`` multiplies all of them, and a case assigned twice has
        its factors added.

        A combination that names no load case, or something that is not a
        load case, cannot be formed: it is left out, and a warning says so.

        Returns:
            List of extracted load combinations as domain objects
        """
        self.logger.info("Extracting load combinations")

        load_case_ids = {
            case.GlobalId for case in self._entities_of_type(self.LOAD_CASE_TYPE)
        }
        assignments: Dict[str, List[Any]] = {}
        for rel in self.ifc.by_type("IfcRelAssignsToGroup"):
            group = rel.RelatingGroup
            if group is not None and group.is_a(self.LOAD_GROUP_TYPE):
                assignments.setdefault(group.GlobalId, []).append(rel)

        load_combinations = []
        empty = []
        not_cases = []
        for entity in self._entities_of_type(self.LOAD_GROUP_TYPE):
            if entity.PredefinedType != "LOAD_COMBINATION":
                continue
            combination = LoadCombination(
                id=entity.GlobalId,
                name=entity.Name or f"Combo-{entity.GlobalId[:8]}",
                description=entity.Description,
            )
            coefficient = entity.Coefficient
            scale = 1.0 if coefficient is None else float(coefficient)
            strangers = []
            for rel in assignments.get(entity.GlobalId, []):
                factor = scale
                if rel.is_a("IfcRelAssignsToGroupByFactor"):
                    factor *= float(rel.Factor)
                for obj in rel.RelatedObjects:
                    if obj.GlobalId in load_case_ids:
                        combination.add_load_group(
                            obj.GlobalId,
                            factor + combination.load_groups.get(obj.GlobalId, 0.0),
                        )
                    else:
                        strangers.append(obj)
            label = f"{combination.name} ({entity.GlobalId})"
            if strangers:
                not_cases.append(
                    f"{label}: {strangers[0].is_a()} {strangers[0].GlobalId}"
                )
            elif not combination.load_groups:
                empty.append(label)
            else:
                load_combinations.append(combination)

        if empty:
            self.warnings.append(
                f"{len(empty)} load combination(s) name no load case and have "
                f"no results: {', '.join(empty[:3])}"
                + (" ..." if len(empty) > 3 else "")
                + "."
            )
        if not_cases:
            self.warnings.append(
                f"{len(not_cases)} load combination(s) include something that "
                "is not a load case and have no results (the combination and "
                f"what it includes): {'; '.join(not_cases[:3])}"
                + (" ..." if len(not_cases) > 3 else "")
                + "."
            )

        self.logger.info(f"Extracted {len(load_combinations)} load combinations")
        return load_combinations

    def _create_domain_loads(self, ifc_load) -> List[Load]:
        """
        Create the domain loads of an IFC load entity.

        Args:
            ifc_load: IFC load entity

        Returns:
            Its domain loads: one, or one for each force of a curve action
            that is a series of point forces (DISCRETE).

        Raises:
            ModelExtractionError: If the load cannot be read or is of a kind
                the analysis does not support. A load is never left out: the
                results would be those of a different loading.
        """
        load_id = getattr(ifc_load, "GlobalId", None) or "?"
        try:
            loads = self._build_domain_load(ifc_load)
            return loads if isinstance(loads, list) else [loads]
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
    def _components(applied_load, attributes) -> List[float]:
        """Three values of an applied load; one that is not given is zero."""
        return [float(getattr(applied_load, name, None) or 0.0) for name in attributes]

    def _refuse_moments(self, applied_load, attributes, why: str) -> None:
        """Raise if an applied load carries a moment where none can be applied."""
        present = [
            name
            for name, value in zip(
                attributes, self._components(applied_load, attributes)
            )
            if value != 0
        ]
        if present:
            raise ModelExtractionError(
                f"It applies a moment ({', '.join(present)}) {why}, which is not "
                "supported."
            )

    def _build_domain_load(self, ifc_load):
        """Create the domain load(s) of an IFC action; see ``_create_domain_loads``."""
        load_id = getattr(ifc_load, "GlobalId", None) or str(uuid.uuid4())
        applied_load = getattr(ifc_load, "AppliedLoad", None)
        if applied_load is None:
            raise ModelExtractionError("It has no AppliedLoad.")
        for varying in (
            "IfcStructuralLinearActionVarying",
            "IfcStructuralPlanarActionVarying",
        ):
            # IFC2X3; the further values are not in AppliedLoad
            if ifc_load.is_a(varying):
                raise ModelExtractionError(
                    f"It is an {varying}; the varying actions of IFC2X3 are not "
                    "supported."
                )

        # For structural point actions
        if ifc_load.is_a("IfcStructuralPointAction"):
            if not applied_load.is_a("IfcStructuralLoadSingleForce"):
                raise ModelExtractionError(
                    f"Its applied load is an {applied_load.is_a()}; on a point "
                    "action only IfcStructuralLoadSingleForce is supported."
                )
            return self._point_load(
                ifc_load, applied_load, load_id, self._extract_load_position(ifc_load)
            )

        # For line loads (IfcStructuralLinearAction or IfcStructuralCurveAction)
        elif ifc_load.is_a("IfcStructuralLinearAction") or ifc_load.is_a(
            "IfcStructuralCurveAction"
        ):
            # Extract start and end positions
            start_pos, end_pos = self._extract_load_line(ifc_load)
            axis = np.array(end_pos, dtype=float) - np.array(start_pos, dtype=float)
            length = float(np.linalg.norm(axis))
            distribution = getattr(ifc_load, "PredefinedType", None) or "CONST"
            if distribution == "DISCRETE":
                return self._point_loads_along(
                    ifc_load, applied_load, load_id, start_pos, axis, length
                )

            # Force per length: scale = force_scale / length_scale
            scale = self.force_scale / self.length_scale
            samples = [
                (
                    location * self.length_scale,
                    self._per_true_length(
                        ifc_load,
                        self._in_global_axes(ifc_load, [f * scale for f in vector]),
                        axis / length if length > 0 else axis,
                    ),
                )
                for location, vector in self._extract_line_samples(
                    ifc_load, applied_load, length / self.length_scale
                )
            ]
            force_vector = [
                float(np.mean([vector[i] for _, vector in samples])) for i in range(3)
            ]

            half_wave = distribution.lower() if len(samples) == 1 else None
            if half_wave in HALF_WAVES:
                # The value is the largest, at the middle of the member
                peak = np.array(force_vector, dtype=float)
                force_vector = [HALF_WAVE_MEANS[half_wave] * f for f in force_vector]
            else:
                half_wave = None

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
            if len(samples) > 1:
                line_load.samples = [
                    (location, np.array(vector, dtype=float))
                    for location, vector in samples
                ]
            elif half_wave:
                line_load.half_wave, line_load.peak = half_wave, peak
                self._refuse_moments(
                    applied_load, self._LINEAR_MOMENTS, "that varies along its member"
                )
            else:
                # Moment per length: a force times a length, per length
                moment = self._in_global_axes(
                    ifc_load,
                    [
                        m * self.force_scale
                        for m in self._components(applied_load, self._LINEAR_MOMENTS)
                    ],
                )
                if any(moment):
                    if getattr(ifc_load, "ProjectedOrTrue", None) == "PROJECTED_LENGTH":
                        raise ModelExtractionError(
                            "It applies a moment per projected length, which is "
                            "not supported."
                        )
                    line_load.moment = np.array(moment, dtype=float)

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
            else:
                raise ModelExtractionError(
                    f"Its applied load is an {applied_load.is_a()}; on a planar "
                    "action only IfcStructuralLoadPlanarForce is supported."
                )

            force_vector = self._in_global_axes(ifc_load, force_vector)

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

    def _point_load(self, ifc_load, applied_load, load_id: str, position) -> PointLoad:
        """The point load of a single force of an action, at a position in metres.

        Raises:
            ModelExtractionError: If the applied load is not a single force,
                or has a warping moment.
        """
        if not applied_load.is_a("IfcStructuralLoadSingleForce"):
            raise ModelExtractionError(
                f"Its applied load is an {applied_load.is_a()}; "
                + (
                    "on a point action"
                    if ifc_load.is_a("IfcStructuralPointAction")
                    else "as a point force on a curve action"
                )
                + " only IfcStructuralLoadSingleForce is supported."
            )
        if getattr(applied_load, "WarpingMoment", None):
            raise ModelExtractionError(
                "It applies a warping moment, which is not supported."
            )
        force_vector = self._in_global_axes(
            ifc_load,
            [
                f * self.force_scale
                for f in self._components(applied_load, ("ForceX", "ForceY", "ForceZ"))
            ],
        )
        # A moment is a force times a length
        moment = self._in_global_axes(
            ifc_load,
            [
                m * self.force_scale * self.length_scale
                for m in self._components(
                    applied_load, ("MomentX", "MomentY", "MomentZ")
                )
            ],
        )

        magnitude = np.array(force_vector, dtype=float)
        norm = np.linalg.norm(magnitude)
        if norm > 1e-10:
            direction = magnitude / norm
        else:
            # Default direction if magnitude is near zero
            direction = np.array([0.0, 0.0, -1.0], dtype=float)

        point_load = PointLoad(
            id=load_id,
            magnitude=magnitude,
            direction=direction,
            position=position,
        )
        if any(moment):
            point_load.moment = np.array(moment, dtype=float)
        return point_load

    def _point_loads_along(
        self, ifc_load, applied_load, load_id: str, start, axis, length: float
    ) -> List[PointLoad]:
        """The point loads of a curve action that is a series of forces.

        A DISCRETE action has an ``IfcStructuralLoadConfiguration`` of single
        forces, each with its location along the member from its start.

        Args:
            ifc_load: The curve action.
            applied_load: Its ``AppliedLoad``.
            load_id: Its GlobalId; the loads are numbered after it.
            start: Start of the member, in metres.
            axis: From there to its end, in metres.
            length: Length of the member, in metres.

        Raises:
            ModelExtractionError: For forces that are not single forces with
                a location on the member each.
        """
        if not applied_load.is_a("IfcStructuralLoadConfiguration"):
            raise ModelExtractionError(
                "Its distribution is DISCRETE, which needs an "
                f"IfcStructuralLoadConfiguration and has an {applied_load.is_a()}."
            )
        values = list(getattr(applied_load, "Values", None) or [])
        if not values:
            raise ModelExtractionError("Its load configuration has no values.")
        if getattr(applied_load, "Locations", None) is None:
            raise ModelExtractionError(
                f"Its load configuration has {len(values)} point force(s) and no "
                "Locations to say where along the member they are."
            )
        places = [
            at * self.length_scale
            for at in self._locations(applied_load, len(values), length)
        ]
        loads = []
        for number, (value, place) in enumerate(zip(values, places), start=1):
            position = np.array(start, dtype=float) + axis * (place / length)
            load = self._point_load(
                ifc_load,
                value,
                f"{load_id}#{number}",
                [float(c) for c in position],
            )
            load.action_id = load_id
            # In LOCAL_COORDS the forces are in the axes of the member
            load.coordinate_system = self._coordinate_system(ifc_load)
            load.member_reference = self._get_member_reference(ifc_load)
            loads.append(load)
        return loads

    def _locations(self, configuration, count: int, length: float) -> List[float]:
        """Where along the member the values of a load configuration are.

        Args:
            configuration: The ``IfcStructuralLoadConfiguration``.
            count: Number of its values.
            length: Length of the member, in metres.

        Returns:
            The locations in the file's unit, in ascending order.

        Raises:
            ModelExtractionError: If there is not one location on the member
                for each value, or they are out of order.
        """
        locations = getattr(configuration, "Locations", None)
        length /= self.length_scale
        if locations is None:
            if count != 2:
                raise ModelExtractionError(
                    f"Its load configuration has {count} values and no "
                    "Locations to say where along the member they are."
                )
            return [0.0, length]
        if len(locations) != count or any(len(at) != 1 for at in locations):
            raise ModelExtractionError(
                "Its load configuration does not have one location along the "
                "member for each value."
            )
        places = [float(at[0]) for at in locations]
        tolerance = 1e-6 * max(length, 1.0)
        if any(b < a for a, b in zip(places, places[1:])):
            raise ModelExtractionError(
                f"The locations of its values are not in ascending order: {places}."
            )
        if places[0] < -tolerance or places[-1] > length + tolerance:
            raise ModelExtractionError(
                f"The locations of its values, {places[0]:g} to {places[-1]:g}, are "
                f"not on its member, which is {length:g} long."
            )
        return places

    def _in_global_axes(self, ifc_load, force_vector: List[float]) -> List[float]:
        """Turn a force given in "global" coordinates to the global axes.

        IFC's GLOBAL_COORDS are the axes of the action's ObjectPlacement,
        which need not be the global ones. A load in LOCAL_COORDS is in its
        member's axes and is turned when it is written.
        """
        if self._coordinate_system(ifc_load) == "local":
            return force_vector
        transformation = get_item_transformation(ifc_load)
        if not transformation:
            return force_vector
        return transform_vectors(
            [force_vector], transformation, include_translation=False
        )[0]

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

    # Distributions of a curve action that are a list of samples
    _SAMPLED_DISTRIBUTIONS = ("LINEAR", "POLYGONAL")
    # and those that are one value: all along, or the peak of a half wave
    _SINGLE_VALUE_DISTRIBUTIONS = ("CONST", "SINUS", "PARABOLA")
    _LINEAR_MOMENTS = ("LinearMomentX", "LinearMomentY", "LinearMomentZ")

    def _extract_line_samples(
        self, ifc_load, applied_load, length: float
    ) -> List[Tuple[float, List[float]]]:
        """The force per length of a curve action, where along its member.

        A constant load is one value, and so is a half wave (SINUS, PARABOLA):
        its largest, at the middle of the member. A load that varies
        (``PredefinedType`` LINEAR or POLYGONAL) is an ``IfcStructuralLoadConfiguration``: values
        with their locations, measured along the member from its start. The
        load is linear between them and "the first and the last load item
        define the extent of the load distribution", so it may cover part of
        the member only.

        Args:
            ifc_load: The curve action.
            applied_load: Its ``AppliedLoad``.
            length: Length of the member, in the file's unit.

        Returns:
            ``[(location, [fx, fy, fz])]`` in the file's units: one item with
            location 0 for a load that is the same all along the member or
            is a half wave, else
            two or more in ascending order of location.

        Raises:
            ModelExtractionError: For a distribution or a load type that is
                not supported, and for samples that cannot be placed.
        """
        distribution = getattr(ifc_load, "PredefinedType", None) or "CONST"
        if not applied_load.is_a("IfcStructuralLoadConfiguration"):
            if distribution in self._SAMPLED_DISTRIBUTIONS:
                raise ModelExtractionError(
                    f"Its distribution is {distribution}, which needs an "
                    "IfcStructuralLoadConfiguration and has an "
                    f"{applied_load.is_a()}."
                )
            if distribution not in self._SINGLE_VALUE_DISTRIBUTIONS:
                raise ModelExtractionError(
                    f"Its distribution is {distribution}; only CONST, LINEAR, "
                    "POLYGONAL, DISCRETE, SINUS and PARABOLA are supported."
                )
            return [(0.0, self._linear_force(applied_load))]

        if distribution not in self._SAMPLED_DISTRIBUTIONS:
            raise ModelExtractionError(
                f"Its distribution is {distribution} with a list of values; only "
                "LINEAR, POLYGONAL and DISCRETE ones have one."
            )
        values = list(getattr(applied_load, "Values", None) or [])
        if len(values) < 2:
            raise ModelExtractionError(
                f"Its load configuration has {len(values)} value(s); a load that "
                "varies needs two or more."
            )
        vectors = [self._linear_force(value) for value in values]
        for value in values:
            self._refuse_moments(
                value, self._LINEAR_MOMENTS, "that varies along its member"
            )

        places = self._locations(applied_load, len(values), length * self.length_scale)
        length = float(length)
        tolerance = 1e-6 * max(length, 1.0)
        if places[-1] - places[0] <= tolerance:
            raise ModelExtractionError(
                f"Its values are all at one location, {places[0]:g}: it has no "
                "length to act on."
            )

        whole_member = places[0] <= tolerance and places[-1] >= length - tolerance
        if whole_member and all(np.allclose(v, vectors[0]) for v in vectors):
            return [(0.0, vectors[0])]
        return list(zip(places, vectors))

    def _linear_force(self, applied_load) -> List[float]:
        """The three components of an ``IfcStructuralLoadLinearForce``."""
        if not applied_load.is_a("IfcStructuralLoadLinearForce"):
            raise ModelExtractionError(
                f"Its applied load is an {applied_load.is_a()}; on a linear or "
                "curve action only linear forces, and configurations of them, "
                "are supported."
            )
        return self._components(
            applied_load, ("LinearForceX", "LinearForceY", "LinearForceZ")
        )

    def _per_true_length(self, ifc_load, vector: List[float], axis) -> List[float]:
        """Turn a load given per projected length into one per true length.

        With ``ProjectedOrTrue`` PROJECTED_LENGTH (snow on a rafter) the value
        is per length of the member as seen along the load. Only a load in
        global directions can be given that way.
        """
        if getattr(ifc_load, "ProjectedOrTrue", None) != "PROJECTED_LENGTH":
            return vector
        if self._coordinate_system(ifc_load) == "local":
            raise ModelExtractionError(
                "It is given per projected length and in local coordinates; only "
                "a load in global directions can be."
            )
        force = np.array(vector, dtype=float)
        size = float(np.linalg.norm(force))
        if size < 1e-30:
            return vector
        along = float(np.dot(force / size, axis))
        return [float(v) for v in force * np.sqrt(max(0.0, 1.0 - along**2))]

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
        candidates = [(ifc_load, getattr(ifc_load, "PointLocation", None))]
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
                    (item, getattr(vertex, "VertexGeometry", None))
                    for vertex in rep.Items
                )
        for item, location in candidates:
            coords = getattr(location, "Coordinates", None)
            if coords:
                padded = [float(c) for c in coords] + [0.0, 0.0]
                # A vertex is in the axes of the placement of its own item
                return transform_vectors(
                    [[c * self.length_scale for c in padded[:3]]],
                    get_item_transformation(item, self.length_scale),
                )[0]
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
