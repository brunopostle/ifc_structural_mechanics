"""
Properties extraction module for structural analysis.

This module contains the PropertiesExtractor class which extracts material,
section, and other properties from IFC files and converts them to domain model objects.

Note: This code is optimized for IFC4 only.
"""

import logging
import uuid
from typing import Optional, Union, Dict

import ifcopenshell

from ..domain.property import Material, Section, Thickness
from ..utils.units import (
    convert_length,
    convert_area,
    convert_moment_of_inertia,
    convert_elastic_modulus,
    convert_density,
)


class PropertiesExtractor:
    """
    Extracts property information from an IFC file or model.

    This class provides methods to extract different types of properties
    from an IFC file and convert them to domain model objects.
    """

    def __init__(
        self,
        ifc_file: Union[str, ifcopenshell.file],
        unit_scales: Optional[Dict[str, float]] = None,
    ):
        """
        Initialize a PropertiesExtractor.

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
            except Exception as e:
                self.logger.error(f"Failed to open IFC file: {e}")
                raise FileNotFoundError(f"Could not open IFC file: {ifc_file}")
        elif hasattr(ifc_file, "by_type") and callable(ifc_file.by_type):
            # This is likely an ifcopenshell.file object or a valid mock
            self.ifc = ifc_file
        else:
            raise ValueError(
                "ifc_file must be a file path or an ifcopenshell.file object"
            )

        # Store unit scales
        self.unit_scales = unit_scales or {}
        self.length_scale = self.unit_scales.get("LENGTHUNIT", 1.0)
        self.force_scale = self.unit_scales.get("FORCEUNIT", 1.0)
        self.mass_scale = self.unit_scales.get("MASSUNIT", 1.0)

    def extract_material(
        self, entity: ifcopenshell.entity_instance
    ) -> Optional[Material]:
        """
        Extract material properties from an IFC entity.

        Args:
            entity: IFC entity

        Returns:
            Material domain object with properties in SI units, or None if extraction fails
        """
        try:
            # Find related material
            material_entity = self._find_related_material(entity)
            if not material_entity:
                self.logger.debug(f"No material found for entity {entity.id()}")
                return None

            # Extract material properties
            psets = []
            if hasattr(material_entity, "HasProperties"):
                psets = material_entity.HasProperties

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

            # Create material with extracted properties (converted to SI units) or defaults
            return Material(
                id=(
                    material_entity.id()
                    if hasattr(material_entity, "id") and callable(material_entity.id)
                    else str(uuid.uuid4())
                ),
                name=(
                    material_entity.Name
                    if hasattr(material_entity, "Name")
                    else "Unknown Material"
                ),
                density=density,
                elastic_modulus=elastic_modulus,
                poisson_ratio=poisson_ratio,
            )

        except Exception as e:
            self.logger.error(
                f"Error extracting material for entity {entity.id()}: {e}"
            )
            # Create default material converted to SI units
            default_density = convert_density(
                7850.0, self.length_scale, self.mass_scale
            )
            default_elastic_modulus = convert_elastic_modulus(
                210e9, self.force_scale, self.length_scale
            )

            return Material(
                id=str(uuid.uuid4()),
                name="Default Material",
                density=default_density,
                elastic_modulus=default_elastic_modulus,
                poisson_ratio=0.3,
            )

    def extract_section(
        self, entity: ifcopenshell.entity_instance
    ) -> Optional[Section]:
        """
        Extract section properties from an IFC entity.

        Args:
            entity: IFC entity

        Returns:
            Section domain object with properties in SI units, or None if extraction fails
        """
        try:
            # Find related profile
            profile = self._find_related_profile(entity)
            if not profile:
                self.logger.debug(f"No profile found for entity {entity.id()}")
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
                    web_thickness = convert_length(
                        profile.WebThickness, self.length_scale
                    )
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

            # Default rectangular section for unsupported profile types
            # Convert default dimensions to SI units
            default_width = convert_length(0.1, self.length_scale)
            default_height = convert_length(0.2, self.length_scale)

            return Section.create_rectangular_section(
                id=str(uuid.uuid4()),
                name="Default Section",
                width=default_width,
                height=default_height,
            )

        except Exception as e:
            self.logger.error(f"Error extracting section for entity {entity.id()}: {e}")
            # Return default section with SI units
            default_width = convert_length(0.1, self.length_scale)
            default_height = convert_length(0.2, self.length_scale)

            return Section.create_rectangular_section(
                id=str(uuid.uuid4()),
                name="Default Section",
                width=default_width,
                height=default_height,
            )

    def extract_thickness(
        self, entity: ifcopenshell.entity_instance
    ) -> Optional[Thickness]:
        """
        Extract thickness properties from an IFC entity.

        Args:
            entity: IFC entity

        Returns:
            Thickness domain object with value in SI units, or None if extraction fails
        """
        try:
            # Check for direct thickness attribute
            if hasattr(entity, "Thickness") and entity.Thickness is not None:
                # Convert thickness to SI units
                thickness_value = convert_length(entity.Thickness, self.length_scale)

                return Thickness(
                    id=f"thickness_{entity.id() if hasattr(entity, 'id') and callable(entity.id) else uuid.uuid4()}",
                    name=(
                        entity.Name if hasattr(entity, "Name") else "Surface Thickness"
                    ),
                    value=thickness_value,
                )

            # Look for thickness in property sets
            psets = self._find_related_properties(entity)
            for pset in psets:
                if hasattr(pset, "HasProperties"):
                    for prop in pset.HasProperties:
                        if prop.Name in ["Thickness", "Width"] and hasattr(
                            prop, "NominalValue"
                        ):
                            # Convert thickness to SI units
                            thickness_value = convert_length(
                                prop.NominalValue.wrappedValue, self.length_scale
                            )

                            return Thickness(
                                id=f"thickness_{entity.id() if hasattr(entity, 'id') and callable(entity.id) else uuid.uuid4()}",
                                name=(
                                    entity.Name
                                    if hasattr(entity, "Name")
                                    else "Surface Thickness"
                                ),
                                value=thickness_value,
                            )

            # No thickness found
            self.logger.debug(f"No thickness found for entity {entity.id()}")
            # Convert default thickness to SI units
            default_thickness = convert_length(0.2, self.length_scale)

            return Thickness(
                id=f"thickness_{uuid.uuid4()}",
                name="Default Thickness",
                value=default_thickness,
            )

        except Exception as e:
            self.logger.error(
                f"Error extracting thickness for entity {entity.id()}: {e}"
            )
            # Convert default thickness to SI units
            default_thickness = convert_length(0.2, self.length_scale)

            return Thickness(
                id=f"thickness_{uuid.uuid4()}",
                name="Default Thickness",
                value=default_thickness,
            )

    def _find_related_material(self, entity):
        """
        Find the material associated with an entity.

        Args:
            entity: IFC entity

        Returns:
            Material entity or None
        """
        if not hasattr(entity, "HasAssociations"):
            return None

        for association in entity.HasAssociations:
            if not association.is_a("IfcRelAssociatesMaterial"):
                continue

            material = association.RelatingMaterial
            if material.is_a("IfcMaterialProfileSet"):
                # For now, we only deal with a single profile
                if hasattr(material, "MaterialProfiles") and material.MaterialProfiles:
                    return material.MaterialProfiles[0].Material

            if material.is_a("IfcMaterialProfileSetUsage"):
                if hasattr(material, "ForProfileSet") and material.ForProfileSet:
                    if (
                        hasattr(material.ForProfileSet, "MaterialProfiles")
                        and material.ForProfileSet.MaterialProfiles
                    ):
                        return material.ForProfileSet.MaterialProfiles[0].Material

            if material.is_a("IfcMaterial"):
                return material

        return None

    def _find_related_profile(self, entity):
        """
        Find the profile associated with an entity.

        Args:
            entity: IFC entity

        Returns:
            Profile entity or None
        """
        if not hasattr(entity, "HasAssociations"):
            return None

        for association in entity.HasAssociations:
            if not association.is_a("IfcRelAssociatesMaterial"):
                continue

            material = association.RelatingMaterial
            if material.is_a("IfcMaterialProfileSet"):
                # For now, we only deal with a single profile
                if hasattr(material, "MaterialProfiles") and material.MaterialProfiles:
                    return material.MaterialProfiles[0].Profile

            if material.is_a("IfcMaterialProfileSetUsage"):
                if hasattr(material, "ForProfileSet") and material.ForProfileSet:
                    if (
                        hasattr(material.ForProfileSet, "MaterialProfiles")
                        and material.ForProfileSet.MaterialProfiles
                    ):
                        return material.ForProfileSet.MaterialProfiles[0].Profile

        # Try to find profile in representation
        if hasattr(entity, "Representation") and entity.Representation:
            for rep in entity.Representation.Representations:
                if hasattr(rep, "Items") and rep.Items:
                    for item in rep.Items:
                        if item.is_a("IfcExtrudedAreaSolid") and hasattr(
                            item, "SweptArea"
                        ):
                            return item.SweptArea

        return None

    def _find_related_properties(self, entity):
        """
        Find property sets associated with an entity.

        Args:
            entity: IFC entity

        Returns:
            List of property sets
        """
        psets = []

        # Look for properties via IsDefinedBy relationship
        if hasattr(entity, "IsDefinedBy"):
            for rel in entity.IsDefinedBy:
                if (
                    hasattr(rel, "RelatingPropertyDefinition")
                    and rel.RelatingPropertyDefinition
                ):
                    psets.append(rel.RelatingPropertyDefinition)

        # Some IFC files use HasProperties directly
        if hasattr(entity, "HasProperties"):
            psets.extend(entity.HasProperties)

        return psets

    def get_pset_property(self, psets, pset_name, prop_name):
        """
        Get a specific property from property sets.

        Args:
            psets: List of property sets
            pset_name: Name of the property set to look in
            prop_name: Name of the property to find

        Returns:
            Property value or None
        """
        for pset in psets:
            if pset.Name == pset_name or pset_name is None:
                for prop in pset.Properties:
                    if prop.Name == prop_name:
                        return prop.NominalValue.wrappedValue
        return None

    def get_pset_properties(self, psets, pset_name):
        """
        Get all properties from a property set.

        Args:
            psets: List of property sets
            pset_name: Name of the property set to extract

        Returns:
            Dictionary of property names and values
        """
        for pset in psets:
            if pset.Name == pset_name or pset_name is None:
                props = {}
                for prop in pset.Properties:
                    propName = prop.Name[0].lower() + prop.Name[1:]
                    props[propName] = prop.NominalValue.wrappedValue
                return props
        return {}
