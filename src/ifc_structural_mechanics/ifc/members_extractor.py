"""
Member extraction module for structural analysis.

This module contains the MembersExtractor class which extracts structural
members from IFC files and converts them to domain model objects.
"""

import logging
import math
import uuid
from typing import Dict, List, Optional, Union

import ifcopenshell

from ..domain.property import Material, Section, Thickness
from ..domain.structural_member import CurveMember, StructuralMember, SurfaceMember
from ..ifc.entity_identifier import (
    get_1D_orientation,
    get_2D_orientation,
    get_coordinate,
    get_representation,
    get_transformation,
    transform_vectors,
)
from ..utils.units import (
    convert_area,
    convert_density,
    convert_length,
    convert_moment_of_inertia,
)

logger = logging.getLogger(__name__)


class MembersExtractor:
    """
    Extracts structural members from an IFC file or model.

    This class provides methods to extract different types of structural
    members from an IFC file and convert them to domain model objects.
    """

    def __init__(
        self,
        ifc_file: Union[str, ifcopenshell.file],
        unit_scales: Optional[Dict[str, float]] = None,
    ):
        """
        Initialize a MembersExtractor.

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
            raise ValueError(
                "ifc_file must be a file path or an ifcopenshell.file object"
            )

        # Store unit scales
        self.unit_scales = unit_scales or {}
        self.length_scale = self.unit_scales.get("LENGTHUNIT", 1.0)
        self.force_scale = self.unit_scales.get("FORCEUNIT", 1.0)
        self.mass_scale = self.unit_scales.get("MASSUNIT", 1.0)
        self.pressure_scale = self.unit_scales.get("PRESSUREUNIT", 1.0)

    def extract_all_members(self) -> List[StructuralMember]:
        """
        Extract all structural members from the IFC file.

        Returns:
            List of StructuralMember domain objects with valid geometry
        """
        logger.info("Extracting all structural members")

        members = []
        processed_ids = set()

        # Extract using dedicated methods for specific member types
        curve_members = self.extract_curve_members()
        surface_members = self.extract_surface_members()

        # Add curve members
        for member in curve_members:
            if member.id not in processed_ids:
                members.append(member)
                processed_ids.add(member.id)

        # Add surface members
        for member in surface_members:
            if member.id not in processed_ids:
                members.append(member)
                processed_ids.add(member.id)

        # Report results
        if members:
            logger.info(
                f"Successfully extracted {len(members)} members with valid geometry"
            )
        else:
            logger.warning("No members with valid geometry were found")

        return members

    def extract_curve_members(self) -> List[CurveMember]:
        """
        Extract all curve members (beams, columns, etc.) from the IFC file.

        Returns:
            List of CurveMember domain objects
        """
        self.logger.info("Extracting curve structural members")

        curve_members = []

        # Extract IfcStructuralCurveMembers
        try:
            for entity in self.ifc.by_type("IfcStructuralCurveMember"):
                try:
                    member = self._create_curve_member(entity)
                    if member:
                        curve_members.append(member)
                except TypeError as e:
                    if "unsupported operand type" in str(e):
                        self.logger.error(
                            f"Coordinate calculation error for curve member {entity.id()}: {e}"
                        )
                        # Add more debug info about the entity
                        self.logger.error(
                            f"Entity type: {entity.is_a() if hasattr(entity, 'is_a') else 'unknown'}"
                        )
                        self.logger.error(f"Has Axis: {hasattr(entity, 'Axis')}")
                        if hasattr(entity, "Axis"):
                            self.logger.error(f"Axis: {entity.Axis}")
                            if entity.Axis:
                                self.logger.error(
                                    f"Axis DirectionRatios: {getattr(entity.Axis, 'DirectionRatios', 'No DirectionRatios')}"
                                )
                    else:
                        self.logger.warning(
                            f"Failed to extract curve member {entity.id()}: {e}"
                        )
                except Exception as e:
                    self.logger.warning(
                        f"Failed to extract curve member {entity.id()}: {e}"
                    )
        except Exception as e:
            self.logger.warning(f"Error extracting IfcStructuralCurveMembers: {e}")

        self.logger.info(f"Extracted {len(curve_members)} curve members")
        return curve_members

    def extract_surface_members(self) -> List[SurfaceMember]:
        """
        Extract all surface members (walls, slabs, etc.) from the IFC file.

        Returns:
            List of SurfaceMember domain objects
        """
        self.logger.info("Extracting surface structural members")

        surface_members = []

        # Extract IfcStructuralSurfaceMembers
        try:
            for entity in self.ifc.by_type("IfcStructuralSurfaceMember"):
                try:
                    member = self._create_surface_member(entity)
                    if member:
                        surface_members.append(member)
                except Exception as e:
                    self.logger.warning(
                        f"Failed to extract surface member {entity.id()}: {e}"
                    )
        except Exception as e:
            self.logger.warning(f"Error extracting IfcStructuralSurfaceMembers: {e}")

        self.logger.info(f"Extracted {len(surface_members)} surface members")
        return surface_members

    def _create_curve_member(self, entity) -> Optional[CurveMember]:
        """
        Create a CurveMember domain object from an IFC entity.

        Args:
            entity: IFC entity representing a curve member

        Returns:
            Optional[CurveMember]: The created curve member or None if creation fails
        """
        try:
            entity_id = getattr(entity, "GlobalId", "unknown")
            self.logger.debug(f"Creating curve member for entity {entity_id}")

            # Extract representation
            representation = get_representation(entity, "Edge")
            if not representation:
                self.logger.warning(f"No representation found for {entity_id}")
                return None

            # Extract material and profile
            material_profile = self._get_material_profile(entity)
            if not material_profile:
                self.logger.warning(f"No material profile found for {entity_id}")
                material = None
                profile = None
            else:
                material = (
                    material_profile.Material
                    if hasattr(material_profile, "Material")
                    else None
                )
                profile = (
                    material_profile.Profile
                    if hasattr(material_profile, "Profile")
                    else None
                )

            # Extract geometry using entity_identifier get_coordinate, passing unit_scale
            self.logger.debug(f"Extracting geometry for {entity_id}")
            geometry = self._extract_geometry(representation, self.length_scale)
            if not geometry:
                self.logger.warning(f"Failed to extract geometry for {entity_id}")
                return None
            if any(coord is None for coord in geometry if coord is not None):
                self.logger.warning(
                    f"Geometry contains invalid coordinates for {entity_id}"
                )
                return None

            self.logger.debug(
                f"Geometry extracted successfully for {entity_id}: {geometry}"
            )

            # Get orientation - THIS IS WHERE THE ERROR LIKELY OCCURS
            orientation = None
            try:
                self.logger.debug(f"Checking for Axis attribute on entity {entity_id}")
                if hasattr(entity, "Axis"):
                    axis_value = entity.Axis
                    self.logger.debug(f"Entity {entity_id} has Axis: {axis_value}")

                    if axis_value is not None:
                        self.logger.debug(
                            f"Entity {entity_id} Axis is not None, calling get_1D_orientation"
                        )
                        # Log more details about the axis
                        if hasattr(axis_value, "DirectionRatios"):
                            direction_ratios = axis_value.DirectionRatios
                            self.logger.debug(
                                f"Entity {entity_id} DirectionRatios: {direction_ratios}"
                            )
                        else:
                            self.logger.debug(
                                f"Entity {entity_id} Axis has no DirectionRatios attribute"
                            )

                        orientation = get_1D_orientation(geometry, axis_value)
                        self.logger.debug(
                            f"Entity {entity_id} orientation result: {orientation}"
                        )
                    else:
                        self.logger.debug(
                            f"Entity {entity_id} Axis is None, skipping orientation"
                        )
                else:
                    self.logger.debug(f"Entity {entity_id} has no Axis attribute")
            except Exception as e:
                self.logger.error(f"Error getting orientation for {entity_id}: {e}")
                self.logger.error(f"Geometry: {geometry}")
                if hasattr(entity, "Axis"):
                    self.logger.error(f"Axis: {entity.Axis}")
                    if entity.Axis and hasattr(entity.Axis, "DirectionRatios"):
                        self.logger.error(
                            f"DirectionRatios: {entity.Axis.DirectionRatios}"
                        )
                # Continue without orientation
                orientation = None

            # Apply transformation if needed
            transformation = None
            try:
                self.logger.debug(f"Checking for transformation on entity {entity_id}")
                if hasattr(entity, "ObjectPlacement") and entity.ObjectPlacement:
                    transformation = get_transformation(entity.ObjectPlacement)
                    if transformation:
                        self.logger.debug(
                            f"Applying transformation to geometry for {entity_id}"
                        )
                        geometry = transform_vectors(geometry, transformation)
                        if orientation:
                            self.logger.debug(
                                f"Applying transformation to orientation for {entity_id}"
                            )
                            orientation = transform_vectors(
                                [orientation], transformation, include_translation=False
                            )[0]
            except Exception as e:
                self.logger.error(f"Error applying transformation for {entity_id}: {e}")
                # Continue with original geometry and orientation

            # Create and return domain object
            if material and profile:
                # Create domain material and section with unit conversion
                domain_material = self._create_material(material)
                domain_section = self._create_section(profile)

                return CurveMember(
                    id=entity_id,
                    geometry=geometry,
                    material=domain_material,
                    section=domain_section,
                    ifc_guid=entity.GlobalId if hasattr(entity, "GlobalId") else None,
                    local_axis=tuple(orientation) if orientation is not None else None,
                )
            else:
                # Create with default material and section (SI units)
                elastic_modulus = 210e9  # Pa
                density = 7850.0  # kg/m³

                default_width = 0.1  # m
                default_height = 0.2  # m

                return CurveMember(
                    id=entity_id,
                    geometry=geometry,
                    material=Material(
                        id="default_material",
                        name="Default Material",
                        density=density,
                        elastic_modulus=elastic_modulus,
                        poisson_ratio=0.3,
                    ),
                    section=Section.create_rectangular_section(
                        id="default_section",
                        name="Default Section",
                        width=default_width,
                        height=default_height,
                    ),
                    ifc_guid=entity.GlobalId if hasattr(entity, "GlobalId") else None,
                    local_axis=tuple(orientation) if orientation is not None else None,
                )

        except TypeError as e:
            if "unsupported operand type" in str(e):
                self.logger.error(
                    f"DETAILED ERROR for curve member {getattr(entity, 'GlobalId', 'unknown')}: {e}"
                )
                # Add extensive debugging info
                self.logger.error(
                    f"Entity type: {entity.is_a() if hasattr(entity, 'is_a') else 'unknown'}"
                )
                self.logger.error(f"Has Axis: {hasattr(entity, 'Axis')}")
                if hasattr(entity, "Axis"):
                    self.logger.error(f"Axis value: {entity.Axis}")
                    if entity.Axis:
                        self.logger.error(f"Axis type: {type(entity.Axis)}")
                        self.logger.error(
                            f"Has DirectionRatios: {hasattr(entity.Axis, 'DirectionRatios')}"
                        )
                        if hasattr(entity.Axis, "DirectionRatios"):
                            self.logger.error(
                                f"DirectionRatios value: {entity.Axis.DirectionRatios}"
                            )
                            self.logger.error(
                                f"DirectionRatios type: {type(entity.Axis.DirectionRatios)}"
                            )

                # Also check geometry for None values
                try:
                    geometry = self._extract_geometry(
                        get_representation(entity, "Edge"), self.length_scale
                    )
                    self.logger.error(f"Extracted geometry: {geometry}")
                    if geometry:
                        for i, point in enumerate(geometry):
                            self.logger.error(
                                f"Point {i}: {point} (type: {type(point)})"
                            )
                            if point and hasattr(point, "__iter__"):
                                for j, coord in enumerate(point):
                                    self.logger.error(
                                        f"  Coord {j}: {coord} (type: {type(coord)})"
                                    )
                except Exception as geom_e:
                    self.logger.error(
                        f"Error extracting geometry for debugging: {geom_e}"
                    )

                import traceback

                self.logger.error(f"Full traceback: {traceback.format_exc()}")
            else:
                self.logger.warning(
                    f"Failed to extract curve member {getattr(entity, 'GlobalId', 'unknown')}: {e}"
                )
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating curve member: {e}")
            return None

    def _create_surface_member(self, entity) -> Optional[SurfaceMember]:
        """
        Create a SurfaceMember domain object from an IFC entity.

        Args:
            entity: IFC entity representing a surface member

        Returns:
            Optional[SurfaceMember]: The created surface member or None if creation fails
        """
        try:
            # Extract representation
            representation = get_representation(entity, "Face")
            if not representation:
                self.logger.warning(f"No representation found for {entity.GlobalId}")
                return None

            # Extract material
            material_profile = self._get_material_profile(entity)
            material = (
                material_profile
                if material_profile and hasattr(material_profile, "Material")
                else None
            )

            # Extract geometry with unit conversion
            geometry = self._extract_geometry(representation, self.length_scale)
            if not geometry:
                self.logger.warning(f"Failed to extract geometry for {entity.GlobalId}")
                return None

            # Get orientation
            orientation = get_2D_orientation(representation)

            # Apply transformation if needed
            transformation = (
                get_transformation(entity.ObjectPlacement)
                if hasattr(entity, "ObjectPlacement")
                else None
            )
            if transformation:
                geometry = transform_vectors(geometry, transformation)
                if orientation:
                    orientation = transform_vectors(
                        [orientation], transformation, include_translation=False
                    )[0]

            # Get thickness and convert to SI units
            thickness_value = entity.Thickness if hasattr(entity, "Thickness") else 0.0
            thickness_value = convert_length(thickness_value, self.length_scale)

            if thickness_value <= 0:
                logger.warning(
                    f"Surface member {entity.GlobalId} has zero or invalid thickness ({thickness_value}). "
                    f"Applying default thickness of 0.1m."
                )
                thickness_value = 0.1

            # Create and return domain object
            if material:
                # Create domain material with unit conversion
                domain_material = self._create_material(material)

                # Create domain thickness
                domain_thickness = Thickness(
                    id=f"thickness_{entity.GlobalId}",
                    name="Surface Thickness",
                    value=thickness_value,
                )

                return SurfaceMember(
                    id=entity.GlobalId,
                    geometry=geometry,
                    material=domain_material,
                    thickness=domain_thickness,
                    ifc_guid=entity.GlobalId if hasattr(entity, "GlobalId") else None,
                )
            else:
                # Create with default material (SI units)
                elastic_modulus = 210e9  # Pa
                density = 7850.0  # kg/m³

                return SurfaceMember(
                    id=entity.GlobalId,
                    geometry=geometry,
                    material=Material(
                        id="default_material",
                        name="Default Material",
                        density=density,
                        elastic_modulus=elastic_modulus,
                        poisson_ratio=0.3,
                    ),
                    thickness=Thickness(
                        id=f"thickness_{entity.GlobalId}",
                        name="Surface Thickness",
                        value=thickness_value,
                    ),
                    ifc_guid=entity.GlobalId if hasattr(entity, "GlobalId") else None,
                )

        except Exception as e:
            logger.error(f"Unexpected error creating surface member: {e}")
            return None

    def _extract_geometry(self, representation, unit_scale: float = 1.0):
        """
        Extract geometry from a representation.

        Args:
            representation: IFC representation
            unit_scale: Scale factor to convert to SI units

        Returns:
            Geometry data in SI units
        """
        if not representation or not representation.Items:
            self.logger.debug("No representation or items")
            return None

        item = representation.Items[0]
        self.logger.debug(
            f"Processing representation item type: {item.is_a() if hasattr(item, 'is_a') else 'unknown'}"
        )

        if item.is_a("IfcEdge"):
            self.logger.debug("Processing IfcEdge")
            # Get coordinates and convert to SI units
            try:
                self.logger.debug("Getting start coordinate")
                start_coord = get_coordinate(item.EdgeStart.VertexGeometry, unit_scale)
                self.logger.debug(f"Start coordinate: {start_coord}")

                self.logger.debug("Getting end coordinate")
                end_coord = get_coordinate(item.EdgeEnd.VertexGeometry, unit_scale)
                self.logger.debug(f"End coordinate: {end_coord}")

                # Validate coordinates are not None
                if start_coord is None or end_coord is None:
                    self.logger.warning(
                        f"Invalid coordinates found in edge geometry: start={start_coord}, end={end_coord}"
                    )
                    return None

                # Additional validation - check for None values within coordinate lists
                if (
                    isinstance(start_coord, (list, tuple))
                    and any(c is None for c in start_coord)
                ) or (
                    isinstance(end_coord, (list, tuple))
                    and any(c is None for c in end_coord)
                ):
                    self.logger.warning(
                        f"Coordinates contain None values: start={start_coord}, end={end_coord}"
                    )
                    return None

                self.logger.debug(
                    f"Returning edge geometry: [{start_coord}, {end_coord}]"
                )
                return [start_coord, end_coord]

            except Exception as e:
                self.logger.error(f"Error extracting edge coordinates: {e}")
                return None

        elif item.is_a("IfcFaceSurface"):
            self.logger.debug("Processing IfcFaceSurface")
            try:
                if hasattr(item, "Bounds") and item.Bounds and len(item.Bounds) > 0:
                    if hasattr(item.Bounds[0], "Bound") and hasattr(
                        item.Bounds[0].Bound, "EdgeList"
                    ):
                        edges = item.Bounds[0].Bound.EdgeList
                        coords = []
                        for i, edge in enumerate(edges):
                            if hasattr(edge, "EdgeElement") and hasattr(
                                edge.EdgeElement, "EdgeStart"
                            ):
                                # Get coordinates and convert to SI units
                                self.logger.debug(f"Getting coordinate for edge {i}")
                                coord = get_coordinate(
                                    edge.EdgeElement.EdgeStart.VertexGeometry,
                                    unit_scale,
                                )
                                if coord is None:
                                    self.logger.warning(
                                        f"Invalid coordinate found in surface boundary at edge {i}"
                                    )
                                    continue  # Skip this coordinate

                                # Check for None values within coordinate
                                if isinstance(coord, (list, tuple)) and any(
                                    c is None for c in coord
                                ):
                                    self.logger.warning(
                                        f"Coordinate {i} contains None values: {coord}"
                                    )
                                    continue

                                coords.append(coord)

                        if len(coords) > 0:
                            self.logger.debug(
                                f"Returning surface geometry with {len(coords)} coordinates"
                            )
                            return coords
                        else:
                            self.logger.warning("No valid coordinates found in surface")
                            return None
            except Exception as e:
                self.logger.error(f"Error extracting surface coordinates: {e}")
                return None

        self.logger.debug("No valid geometry found")
        return None

    def _get_material_profile(self, element):
        """
        Get material and profile information.

        Args:
            element: IFC element

        Returns:
            Material profile or None
        """
        if not hasattr(element, "HasAssociations"):
            return None

        for association in element.HasAssociations:
            if not association.is_a("IfcRelAssociatesMaterial"):
                continue

            material = association.RelatingMaterial
            if material.is_a("IfcMaterialProfileSet"):
                # For now, we only deal with a single profile
                if hasattr(material, "MaterialProfiles") and material.MaterialProfiles:
                    return material.MaterialProfiles[0]

            if material.is_a("IfcMaterialProfileSetUsage"):
                if hasattr(material, "ForProfileSet") and material.ForProfileSet:
                    if (
                        hasattr(material.ForProfileSet, "MaterialProfiles")
                        and material.ForProfileSet.MaterialProfiles
                    ):
                        return material.ForProfileSet.MaterialProfiles[0]

            if material.is_a("IfcMaterial"):
                return material

        return None

    def _create_material(self, material):
        """
        Create a domain material object from an IFC material.

        Args:
            material: IFC material

        Returns:
            Domain material object with properties in SI units
        """
        if not material:
            return None

        # Extract material properties from property sets
        psets = []
        if hasattr(material, "HasProperties"):
            psets = material.HasProperties

        mechProps = {}
        commonProps = {}

        # First pass: standard pset names (preferred)
        for pset in psets:
            if (
                pset.Name == "Pset_MaterialMechanical"
                or pset.Name == "Pset_MaterialCommon"
            ):
                for prop in pset.Properties:
                    propName = prop.Name[0].lower() + prop.Name[1:]
                    value = prop.NominalValue.wrappedValue
                    if pset.Name == "Pset_MaterialMechanical":
                        mechProps[propName] = value
                    else:
                        commonProps[propName] = value

        # Get extracted values (None if not found in IFC)
        density_raw = commonProps.get("massDensity")
        elastic_modulus_raw = mechProps.get("youngModulus")
        poisson_ratio = mechProps.get("poissonRatio", 0.3)

        # Second pass: if key properties still missing, search all psets by property name
        if elastic_modulus_raw is None or density_raw is None:
            for pset in psets:
                for prop in getattr(
                    pset, "Properties", getattr(pset, "HasProperties", [])
                ):
                    prop_name = getattr(prop, "Name", "")
                    lower_name = prop_name.lower()
                    try:
                        value = prop.NominalValue.wrappedValue
                    except (AttributeError, TypeError):
                        continue
                    if (
                        "youngmodulus" in lower_name or "elasticmodulus" in lower_name
                    ) and elastic_modulus_raw is None:
                        elastic_modulus_raw = value
                    elif (
                        "massdensity" in lower_name or lower_name == "density"
                    ) and density_raw is None:
                        density_raw = value
                    elif (
                        "poissonratio" in lower_name or "poisson" in lower_name
                    ) and poisson_ratio == 0.3:
                        poisson_ratio = value

        # Only convert values extracted from IFC (they're in project units).
        # Use SI defaults directly when not found.
        if density_raw is not None:
            density = convert_density(density_raw, self.length_scale, self.mass_scale)
        else:
            density = 7850.0  # kg/m³, already SI

        if elastic_modulus_raw is not None:
            elastic_modulus = elastic_modulus_raw * self.pressure_scale
        else:
            elastic_modulus = 210e9  # Pa, already SI

        # Create material with extracted properties or defaults, converted to SI units
        return Material(
            id=(
                material.id()
                if hasattr(material, "id") and callable(material.id)
                else str(uuid.uuid4())
            ),
            name=material.Name if hasattr(material, "Name") else "Unknown Material",
            density=density,
            elastic_modulus=elastic_modulus,
            poisson_ratio=poisson_ratio,
        )

    def _create_section(self, profile):
        """
        Create a domain section object from an IFC profile.

        Args:
            profile: IFC profile

        Returns:
            Domain section object with properties in SI units
        """
        if not profile:
            return None

        # Handle rectangular profile
        if profile.is_a("IfcRectangleProfileDef"):
            # Convert dimensions to SI units
            width = convert_length(profile.XDim, self.length_scale)
            height = convert_length(profile.YDim, self.length_scale)

            return Section.create_rectangular_section(
                id=(
                    profile.id()
                    if hasattr(profile, "id") and callable(profile.id)
                    else str(uuid.uuid4())
                ),
                name=(
                    profile.ProfileName
                    if hasattr(profile, "ProfileName")
                    else "Rectangular Section"
                ),
                width=width,
                height=height,
            )

        # Handle hollow circular profile (pipe/tube)
        elif profile.is_a("IfcCircleHollowProfileDef"):
            outer_r = convert_length(profile.Radius, self.length_scale)
            wall_t = convert_length(profile.WallThickness, self.length_scale)
            inner_r = outer_r - wall_t
            area = math.pi * (outer_r ** 2 - inner_r ** 2)
            return Section(
                id=(
                    profile.id()
                    if hasattr(profile, "id") and callable(profile.id)
                    else str(uuid.uuid4())
                ),
                name=(
                    profile.ProfileName
                    if hasattr(profile, "ProfileName")
                    else "Pipe Section"
                ),
                section_type="pipe",
                area=area,
                dimensions={"outer_radius": outer_r, "inner_radius": inner_r},
            )

        # Handle hollow rectangular profile (RHS/box)
        elif profile.is_a("IfcRectangleHollowProfileDef"):
            w = convert_length(profile.XDim, self.length_scale)
            h = convert_length(profile.YDim, self.length_scale)
            t = convert_length(profile.WallThickness, self.length_scale)
            area = w * h - (w - 2 * t) * (h - 2 * t)
            return Section(
                id=(
                    profile.id()
                    if hasattr(profile, "id") and callable(profile.id)
                    else str(uuid.uuid4())
                ),
                name=(
                    profile.ProfileName
                    if hasattr(profile, "ProfileName")
                    else "Box Section"
                ),
                section_type="box",
                area=area,
                dimensions={"width": w, "height": h, "wall_thickness": t},
            )

        # Handle I-shape profile
        elif profile.is_a("IfcIShapeProfileDef"):
            # Extract mechanical properties
            psets = []
            mechProps = {}

            if hasattr(profile, "HasProperties"):
                psets = profile.HasProperties

                for pset in psets:
                    if pset.Name == "Pset_ProfileMechanical":
                        for prop in pset.Properties:
                            propName = prop.Name[0].lower() + prop.Name[1:]
                            mechProps[propName] = prop.NominalValue.wrappedValue

            # If no mechanical properties, calculate them
            if not mechProps:
                # Convert dimensions to SI units first
                flange_thickness = convert_length(
                    profile.FlangeThickness, self.length_scale
                )
                web_thickness = convert_length(profile.WebThickness, self.length_scale)
                height = convert_length(profile.OverallDepth, self.length_scale)
                width = convert_length(profile.OverallWidth, self.length_scale)

                # Calculate area (already in SI units)
                flange_area = width * flange_thickness * 2
                web_area = web_thickness * (height - 2 * flange_thickness)
                area = flange_area + web_area

                # Calculate moments of inertia (already in SI units since dimensions are converted)
                Iy = (width * height**3) / 12 - (width - web_thickness) * (
                    (height - 2 * flange_thickness) ** 3
                ) / 12
                Iz = (2 * flange_thickness) * (width**3) / 12 + (
                    height - 2 * flange_thickness
                ) * (web_thickness**3) / 12
                Jx = (
                    1
                    / 3
                    * (
                        (height - flange_thickness) * (web_thickness**3)
                        + 2 * width * (flange_thickness**3)
                    )
                )

                mechProps = {
                    "crossSectionArea": area,
                    "momentOfInertiaY": Iy,
                    "momentOfInertiaZ": Iz,
                    "torsionalConstantX": Jx,
                }
            else:
                # Convert provided properties to SI units
                if "crossSectionArea" in mechProps:
                    mechProps["crossSectionArea"] = convert_area(
                        mechProps["crossSectionArea"], self.length_scale
                    )
                if "momentOfInertiaY" in mechProps:
                    mechProps["momentOfInertiaY"] = convert_moment_of_inertia(
                        mechProps["momentOfInertiaY"], self.length_scale
                    )
                if "momentOfInertiaZ" in mechProps:
                    mechProps["momentOfInertiaZ"] = convert_moment_of_inertia(
                        mechProps["momentOfInertiaZ"], self.length_scale
                    )
                if "torsionalConstantX" in mechProps:
                    mechProps["torsionalConstantX"] = convert_moment_of_inertia(
                        mechProps["torsionalConstantX"], self.length_scale
                    )

            # Convert dimensions to SI units
            width = convert_length(profile.OverallWidth, self.length_scale)
            height = convert_length(profile.OverallDepth, self.length_scale)
            web_thickness = convert_length(profile.WebThickness, self.length_scale)
            flange_thickness = convert_length(
                profile.FlangeThickness, self.length_scale
            )

            # FIXED: Safely handle FilletRadius that might be None
            fillet_radius_value = 0.0  # Default value
            if hasattr(profile, "FilletRadius"):
                raw_fillet_radius = profile.FilletRadius
                if raw_fillet_radius is not None:
                    fillet_radius_value = raw_fillet_radius

            fillet_radius = convert_length(fillet_radius_value, self.length_scale)

            # Create section
            return Section(
                id=(
                    profile.id()
                    if hasattr(profile, "id") and callable(profile.id)
                    else str(uuid.uuid4())
                ),
                name=(
                    profile.ProfileName
                    if hasattr(profile, "ProfileName")
                    else "I-Section"
                ),
                section_type="i",
                area=mechProps.get("crossSectionArea", 0.0),
                dimensions={
                    "width": width,
                    "height": height,
                    "web_thickness": web_thickness,
                    "flange_thickness": flange_thickness,
                    "fillet_radius": fillet_radius,
                },
            )

        # Default rectangular section (SI units)
        default_width = 0.1  # m
        default_height = 0.2  # m

        return Section.create_rectangular_section(
            id=str(uuid.uuid4()),
            name="Default Section",
            width=default_width,
            height=default_height,
        )
