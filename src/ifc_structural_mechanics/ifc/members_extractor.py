"""
Member extraction module for structural analysis.

This module contains the MembersExtractor class which extracts structural
members from IFC files and converts them to domain model objects.
"""

import logging
import uuid
from typing import List, Optional, Union, Dict

import ifcopenshell
import numpy as np

from ..domain.structural_member import StructuralMember, CurveMember, SurfaceMember
from ..domain.property import Material, Section, Thickness
from ..ifc.entity_identifier import (
    is_structural_member,
    is_structural_curve_member,
    is_structural_surface_member,
    get_representation,
    get_transformation,
    transform_vectors,
    get_coordinate,
    get_1D_orientation,
    get_2D_orientation,
)
from ..utils.units import (
    convert_length,
    convert_coordinates,
    convert_point_list,
    convert_moment_of_inertia,
    convert_area,
    convert_elastic_modulus,
    convert_density,
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

        # Tolerance for geometry calculations
        self.tol = 1e-06

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

    def extract_member_by_id(self, entity_id: str) -> Optional[StructuralMember]:
        """
        Extract a specific member by its ID.

        Args:
            entity_id (str): ID of the entity to extract

        Returns:
            Optional[StructuralMember]: The extracted member or None if not a valid structural member
        """
        try:
            # Get the entity by ID
            logger.info(f"Extracting member with ID {entity_id}")

            # First try to find by GlobalId
            entity = None
            for entity_type in [
                "IfcStructuralCurveMember",
                "IfcStructuralSurfaceMember",
            ]:
                for ent in self.ifc.by_type(entity_type):
                    if ent.GlobalId == entity_id:
                        entity = ent
                        break
                if entity:
                    break

            # If not found by GlobalId, try by ID
            if not entity:
                try:
                    entity = self.ifc.by_id(entity_id)
                except:
                    logger.warning(f"Failed to get entity by ID {entity_id}")
                    return None

            # Check if it's a structural member
            if not is_structural_member(entity):
                logger.warning(f"Entity {entity_id} is not a structural member")
                return None

            # Check if it's a curve or surface member
            if is_structural_curve_member(entity):
                return self._create_curve_member(entity)
            elif is_structural_surface_member(entity):
                return self._create_surface_member(entity)

            # If neither curve nor surface, return None
            logger.warning(f"Entity {entity_id} is not a valid curve or surface member")
            return None

        except Exception as e:
            logger.error(f"Error extracting member by ID {entity_id}: {e}")
            return None

    def _create_curve_member(self, entity) -> Optional[CurveMember]:
        """
        Create a CurveMember domain object from an IFC entity.

        Args:
            entity: IFC entity representing a curve member

        Returns:
            Optional[CurveMember]: The created curve member or None if creation fails
        """
        try:
            # Extract representation
            representation = get_representation(entity, "Edge")
            if not representation:
                self.logger.warning(f"No representation found for {entity.GlobalId}")
                return None

            # Extract material and profile
            material_profile = self._get_material_profile(entity)
            if not material_profile:
                self.logger.warning(f"No material profile found for {entity.GlobalId}")
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
            geometry = self._extract_geometry(representation, self.length_scale)
            if not geometry:
                self.logger.warning(f"Failed to extract geometry for {entity.GlobalId}")
                return None

            # Get orientation
            orientation = (
                get_1D_orientation(geometry, entity.Axis)
                if hasattr(entity, "Axis")
                else None
            )

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

            # Create and return domain object
            if material and profile:
                # Create domain material and section with unit conversion
                domain_material = self._create_material(material)
                domain_section = self._create_section(profile)

                return CurveMember(
                    id=entity.GlobalId,
                    geometry=geometry,
                    material=domain_material,
                    section=domain_section,
                )
            else:
                # Create with default material and section
                # Also converted to SI units
                elastic_modulus = convert_elastic_modulus(
                    210e9, self.force_scale, self.length_scale
                )
                density = convert_density(7850.0, self.length_scale, self.mass_scale)

                default_width = convert_length(0.1, self.length_scale)
                default_height = convert_length(0.2, self.length_scale)

                return CurveMember(
                    id=entity.GlobalId,
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
                )

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
                )
            else:
                # Create with default material
                # Convert default properties to SI units
                elastic_modulus = convert_elastic_modulus(
                    210e9, self.force_scale, self.length_scale
                )
                density = convert_density(7850.0, self.length_scale, self.mass_scale)

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
            return None

        item = representation.Items[0]

        if item.is_a("IfcEdge"):
            # Get coordinates and convert to SI units
            start_coord = get_coordinate(item.EdgeStart.VertexGeometry, unit_scale)
            end_coord = get_coordinate(item.EdgeEnd.VertexGeometry, unit_scale)
            return [start_coord, end_coord]

        elif item.is_a("IfcFaceSurface"):
            if hasattr(item, "Bounds") and item.Bounds and len(item.Bounds) > 0:
                if hasattr(item.Bounds[0], "Bound") and hasattr(
                    item.Bounds[0].Bound, "EdgeList"
                ):
                    edges = item.Bounds[0].Bound.EdgeList
                    coords = []
                    for edge in edges:
                        if hasattr(edge, "EdgeElement") and hasattr(
                            edge.EdgeElement, "EdgeStart"
                        ):
                            # Get coordinates and convert to SI units
                            coord = get_coordinate(
                                edge.EdgeElement.EdgeStart.VertexGeometry, unit_scale
                            )
                            coords.append(coord)
                    return coords

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

        # Get mechanical properties
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

        # Get default values or extracted values
        density = commonProps.get("massDensity", 7850.0)
        elastic_modulus = mechProps.get("youngModulus", 210e9)
        poisson_ratio = mechProps.get("poissonRatio", 0.3)

        # Convert to SI units
        density = convert_density(density, self.length_scale, self.mass_scale)
        elastic_modulus = convert_elastic_modulus(
            elastic_modulus, self.force_scale, self.length_scale
        )

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
                Iy = (width * height ** 3) / 12 - (width - web_thickness) * (
                    (height - 2 * flange_thickness) ** 3
                ) / 12
                Iz = (2 * flange_thickness) * (width ** 3) / 12 + (
                    height - 2 * flange_thickness
                ) * (web_thickness ** 3) / 12
                Jx = (
                    1
                    / 3
                    * (
                        (height - flange_thickness) * (web_thickness ** 3)
                        + 2 * width * (flange_thickness ** 3)
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
            fillet_radius = convert_length(
                profile.FilletRadius if hasattr(profile, "FilletRadius") else 0.0,
                self.length_scale,
            )

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

        # Default rectangular section
        # Convert default dimensions to SI units
        default_width = convert_length(0.1, self.length_scale)
        default_height = convert_length(0.2, self.length_scale)

        return Section.create_rectangular_section(
            id=str(uuid.uuid4()),
            name="Default Section",
            width=default_width,
            height=default_height,
        )
