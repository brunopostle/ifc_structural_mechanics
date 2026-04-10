"""
Properties extraction module for structural analysis.

This module contains the PropertiesExtractor class which extracts material,
section, and other properties from IFC files and converts them to domain model objects.

Note: This code is optimized for IFC4 only.

FIXED: ImportError issue resolved by ensuring proper class definition and imports.
"""

import logging
import math
import uuid
from typing import Dict, Optional, Union

import ifcopenshell

from ..domain.property import Material, Section, Thickness
from ..utils.units import (
    convert_density,
    convert_length,
)

logger = logging.getLogger(__name__)


class PropertiesExtractor:
    """
    Extracts property information from an IFC file or model.

    This class provides methods to extract different types of properties
    from an IFC file and convert them to domain model objects.

    FIXED: Ensures class is properly defined and exportable.
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
                self.logger.info(f"Opened IFC file: {ifc_file}")
            except Exception as e:
                self.logger.error(f"Failed to open IFC file: {e}")
                raise FileNotFoundError(f"Could not open IFC file: {ifc_file}")
        elif hasattr(ifc_file, "by_type") and callable(ifc_file.by_type):
            # This is likely an ifcopenshell.file object or a valid mock
            self.ifc = ifc_file
            self.logger.info("Using provided ifcopenshell.file object")
        else:
            raise ValueError(
                "ifc_file must be a file path or an ifcopenshell.file object"
            )

        # Store unit scales with safe defaults
        self.unit_scales = unit_scales or {}
        self.length_scale = self._safe_get_scale("LENGTHUNIT", 1.0)
        self.force_scale = self._safe_get_scale("FORCEUNIT", 1.0)
        self.mass_scale = self._safe_get_scale("MASSUNIT", 1.0)
        self.pressure_scale = self._safe_get_scale("PRESSUREUNIT", 1.0)

    def _safe_get_scale(self, unit_type: str, default: float) -> float:
        """Safely get unit scale with validation."""
        try:
            scale = self.unit_scales.get(unit_type, default)
            if scale is None or scale <= 0:
                self.logger.warning(
                    f"Invalid scale for {unit_type}: {scale}, using default: {default}"
                )
                return default
            return float(scale)
        except (ValueError, TypeError) as e:
            self.logger.warning(
                f"Error getting scale for {unit_type}: {e}, using default: {default}"
            )
            return default

    def _safe_get_property_value(self, prop, default_value=None, expected_type=float):
        """
        Safely extract a property value with null checking.

        Args:
            prop: Property object
            default_value: Default value to use if property is null/missing
            expected_type: Expected type for validation

        Returns:
            Property value or default if null/invalid
        """
        try:
            if prop is None:
                self.logger.debug(f"Property is None, using default: {default_value}")
                return default_value

            if hasattr(prop, "NominalValue"):
                nominal_value = prop.NominalValue
                if nominal_value is None:
                    self.logger.debug(
                        f"NominalValue is None, using default: {default_value}"
                    )
                    return default_value

                if hasattr(nominal_value, "wrappedValue"):
                    wrapped_value = nominal_value.wrappedValue
                    if wrapped_value is None:
                        self.logger.debug(
                            f"wrappedValue is None, using default: {default_value}"
                        )
                        return default_value

                    # Type validation
                    if expected_type and not isinstance(wrapped_value, expected_type):
                        try:
                            converted_value = expected_type(wrapped_value)
                            self.logger.debug(
                                f"Converted {wrapped_value} to {expected_type.__name__}: {converted_value}"
                            )
                            return converted_value
                        except (ValueError, TypeError) as e:
                            self.logger.warning(
                                f"Failed to convert {wrapped_value} to {expected_type.__name__}: {e}, using default: {default_value}"
                            )
                            return default_value

                    return wrapped_value
                else:
                    # Direct nominal value
                    if nominal_value is None:
                        return default_value
                    return nominal_value
            else:
                # Property might be a direct value
                if prop is None:
                    return default_value
                return prop

        except Exception as e:
            self.logger.warning(
                f"Error extracting property value: {e}, using default: {default_value}"
            )
            return default_value

    def _safe_get_attribute(self, obj, attr_name, default_value=None):
        """
        Safely get an attribute from an object.

        Args:
            obj: Object to get attribute from
            attr_name: Name of the attribute
            default_value: Default value if attribute missing or None

        Returns:
            Attribute value or default
        """
        try:
            if obj is None:
                return default_value

            if hasattr(obj, attr_name):
                value = getattr(obj, attr_name)
                return value if value is not None else default_value
            else:
                return default_value

        except Exception as e:
            self.logger.warning(
                f"Error getting attribute {attr_name}: {e}, using default: {default_value}"
            )
            return default_value

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
                return self._create_default_material()

            # Extract material properties with safe handling
            psets = []
            if hasattr(material_entity, "HasProperties"):
                psets = self._safe_get_attribute(material_entity, "HasProperties", [])

            mechProps = {}
            commonProps = {}

            # First pass: standard pset names (preferred)
            for pset in psets:
                try:
                    pset_name = self._safe_get_attribute(pset, "Name", "")

                    if pset_name in ["Pset_MaterialMechanical", "Pset_MaterialCommon"]:
                        properties = self._safe_get_attribute(pset, "Properties", [])

                        for prop in properties:
                            try:
                                prop_name = self._safe_get_attribute(prop, "Name", "")
                                if prop_name:
                                    # Convert property name to camelCase
                                    prop_name_camel = (
                                        prop_name[0].lower() + prop_name[1:]
                                        if len(prop_name) > 1
                                        else prop_name.lower()
                                    )

                                    # Safely extract property value
                                    value = self._safe_get_property_value(
                                        prop, default_value=0.0, expected_type=float
                                    )

                                    if pset_name == "Pset_MaterialMechanical":
                                        mechProps[prop_name_camel] = value
                                    else:
                                        commonProps[prop_name_camel] = value

                            except Exception as e:
                                self.logger.debug(
                                    f"Error extracting property from {pset_name}: {e}"
                                )
                                continue

                except Exception as e:
                    self.logger.debug(f"Error processing property set: {e}")
                    continue

            # Get extracted values (None if not found in IFC)
            density_raw = commonProps.get("massDensity")
            elastic_modulus_raw = mechProps.get("youngModulus")
            poisson_ratio_raw = mechProps.get("poissonRatio")

            # Second pass: if key properties still missing, search all psets by property name
            if elastic_modulus_raw is None or density_raw is None:
                for pset in psets:
                    try:
                        properties = self._safe_get_attribute(
                            pset,
                            "Properties",
                            self._safe_get_attribute(pset, "HasProperties", []),
                        )
                        for prop in properties:
                            try:
                                prop_name = self._safe_get_attribute(prop, "Name", "")
                                lower_name = prop_name.lower()
                                value = self._safe_get_property_value(
                                    prop, default_value=None, expected_type=float
                                )
                                if value is None:
                                    continue
                                if (
                                    "youngmodulus" in lower_name
                                    or "elasticmodulus" in lower_name
                                ) and elastic_modulus_raw is None:
                                    elastic_modulus_raw = value
                                elif (
                                    "massdensity" in lower_name
                                    or lower_name == "density"
                                ) and density_raw is None:
                                    density_raw = value
                                elif (
                                    "poissonratio" in lower_name
                                    or "poisson" in lower_name
                                ) and poisson_ratio_raw is None:
                                    poisson_ratio_raw = value
                            except Exception:
                                continue
                    except Exception:
                        continue

            # Only convert values extracted from IFC (they're in project units).
            # Use SI defaults directly when not found.
            try:
                if density_raw is not None:
                    density = max(0.1, float(density_raw))
                    density = convert_density(
                        density, self.length_scale, self.mass_scale
                    )
                else:
                    density = 7850.0  # kg/m³, already SI

                if elastic_modulus_raw is not None:
                    elastic_modulus = max(1e6, float(elastic_modulus_raw))
                    elastic_modulus = elastic_modulus * self.pressure_scale
                else:
                    elastic_modulus = 210e9  # Pa, already SI
            except Exception as e:
                self.logger.warning(f"Error converting material units: {e}")
                density = 7850.0
                elastic_modulus = 210e9

            poisson_ratio = (
                max(0.0, min(0.5, float(poisson_ratio_raw)))
                if poisson_ratio_raw
                else 0.3
            )

            # Create material with extracted properties
            material_id = (
                str(material_entity.id())
                if hasattr(material_entity, "id") and callable(material_entity.id)
                else str(uuid.uuid4())
            )
            material_name = self._safe_get_attribute(
                material_entity, "Name", "Unknown Material"
            )

            return Material(
                id=material_id,
                name=material_name,
                density=density,
                elastic_modulus=elastic_modulus,
                poisson_ratio=poisson_ratio,
            )

        except Exception as e:
            self.logger.error(
                f"Error extracting material for entity {entity.id()}: {e}"
            )
            return self._create_default_material()

    def _create_default_material(self) -> Material:
        """Create a default material with SI units (no conversion needed)."""
        return Material(
            id="default_material",
            name="Default Steel",
            density=7850.0,  # kg/m³
            elastic_modulus=210e9,  # Pa
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
                return self._create_default_section()

            # Handle rectangular profile
            if profile.is_a("IfcRectangleProfileDef"):
                # Safely extract dimensions
                width = self._safe_get_attribute(profile, "XDim", 0.1)
                height = self._safe_get_attribute(profile, "YDim", 0.2)

                # Validate and convert dimensions
                width = max(0.001, float(width)) if width else 0.1
                height = max(0.001, float(height)) if height else 0.2

                try:
                    width = convert_length(width, self.length_scale)
                    height = convert_length(height, self.length_scale)
                except Exception as e:
                    self.logger.warning(f"Error converting section dimensions: {e}")
                    width = convert_length(0.1, 1.0)
                    height = convert_length(0.2, 1.0)

                profile_id = (
                    str(profile.id())
                    if hasattr(profile, "id") and callable(profile.id)
                    else str(uuid.uuid4())
                )
                profile_name = self._safe_get_attribute(
                    profile, "ProfileName", "Rectangular Section"
                )

                return Section.create_rectangular_section(
                    id=profile_id,
                    name=profile_name,
                    width=width,
                    height=height,
                )

            # Handle hollow circular profile (pipe/tube)
            elif profile.is_a("IfcCircleHollowProfileDef"):
                outer_r = self._safe_get_attribute(profile, "Radius", 0.05)
                wall_t = self._safe_get_attribute(profile, "WallThickness", 0.005)
                outer_r = max(0.001, float(outer_r)) if outer_r else 0.05
                wall_t = max(0.0001, float(wall_t)) if wall_t else 0.005
                try:
                    outer_r = convert_length(outer_r, self.length_scale)
                    wall_t = convert_length(wall_t, self.length_scale)
                except Exception as e:
                    self.logger.warning(f"Error converting pipe dimensions: {e}")
                inner_r = outer_r - wall_t
                area = math.pi * (outer_r ** 2 - inner_r ** 2)
                profile_id = (
                    str(profile.id())
                    if hasattr(profile, "id") and callable(profile.id)
                    else str(uuid.uuid4())
                )
                profile_name = self._safe_get_attribute(
                    profile, "ProfileName", "Pipe Section"
                )
                return Section(
                    id=profile_id,
                    name=profile_name,
                    section_type="pipe",
                    area=area,
                    dimensions={"outer_radius": outer_r, "inner_radius": inner_r},
                )

            # Handle hollow rectangular profile (RHS/box)
            elif profile.is_a("IfcRectangleHollowProfileDef"):
                w = self._safe_get_attribute(profile, "XDim", 0.1)
                h = self._safe_get_attribute(profile, "YDim", 0.2)
                t = self._safe_get_attribute(profile, "WallThickness", 0.005)
                w = max(0.001, float(w)) if w else 0.1
                h = max(0.001, float(h)) if h else 0.2
                t = max(0.0001, float(t)) if t else 0.005
                try:
                    w = convert_length(w, self.length_scale)
                    h = convert_length(h, self.length_scale)
                    t = convert_length(t, self.length_scale)
                except Exception as e:
                    self.logger.warning(f"Error converting box dimensions: {e}")
                area = w * h - (w - 2 * t) * (h - 2 * t)
                profile_id = (
                    str(profile.id())
                    if hasattr(profile, "id") and callable(profile.id)
                    else str(uuid.uuid4())
                )
                profile_name = self._safe_get_attribute(
                    profile, "ProfileName", "Box Section"
                )
                return Section(
                    id=profile_id,
                    name=profile_name,
                    section_type="box",
                    area=area,
                    dimensions={"width": w, "height": h, "wall_thickness": t},
                )

            # Handle I-shape profile
            elif profile.is_a("IfcIShapeProfileDef"):
                return self._create_i_section(profile)

            else:
                self.logger.debug(f"Unsupported profile type: {profile.is_a()}")
                return self._create_default_section()

        except Exception as e:
            self.logger.error(f"Error extracting section for entity {entity.id()}: {e}")
            return self._create_default_section()

    def _create_i_section(self, profile):
        """Create I-section with safe property extraction."""
        try:
            # Extract dimensions with safe handling and validation
            overall_width = self._safe_get_attribute(profile, "OverallWidth", 0.1)
            overall_depth = self._safe_get_attribute(profile, "OverallDepth", 0.2)
            web_thickness = self._safe_get_attribute(profile, "WebThickness", 0.01)
            flange_thickness = self._safe_get_attribute(
                profile, "FlangeThickness", 0.01
            )
            fillet_radius = self._safe_get_attribute(profile, "FilletRadius", 0.0)

            # Validate dimensions
            overall_width = max(0.001, float(overall_width)) if overall_width else 0.1
            overall_depth = max(0.001, float(overall_depth)) if overall_depth else 0.2
            web_thickness = max(0.001, float(web_thickness)) if web_thickness else 0.01
            flange_thickness = (
                max(0.001, float(flange_thickness)) if flange_thickness else 0.01
            )
            fillet_radius = max(0.0, float(fillet_radius)) if fillet_radius else 0.0

            # Convert to SI units
            try:
                width = convert_length(overall_width, self.length_scale)
                height = convert_length(overall_depth, self.length_scale)
                web_thick = convert_length(web_thickness, self.length_scale)
                flange_thick = convert_length(flange_thickness, self.length_scale)
                fillet_rad = convert_length(fillet_radius, self.length_scale)
            except Exception as e:
                self.logger.warning(f"Error converting I-section dimensions: {e}")
                # Use defaults
                width = convert_length(0.1, 1.0)
                height = convert_length(0.2, 1.0)
                web_thick = convert_length(0.01, 1.0)
                flange_thick = convert_length(0.01, 1.0)
                fillet_rad = 0.0

            # Calculate area and moments of inertia with safe operations
            try:
                flange_area = width * flange_thick * 2
                web_area = web_thick * (height - 2 * flange_thick)
                area = flange_area + web_area

                # Calculate moments of inertia
                Iy = (width * height**3) / 12 - (width - web_thick) * (
                    (height - 2 * flange_thick) ** 3
                ) / 12
                Iz = (2 * flange_thick) * (width**3) / 12 + (
                    height - 2 * flange_thick
                ) * (web_thick**3) / 12

                # Ensure positive values
                area = max(1e-6, area)
                Iy = max(1e-12, Iy)
                Iz = max(1e-12, Iz)

            except Exception as e:
                self.logger.warning(f"Error calculating I-section properties: {e}")
                # Use simplified rectangular calculation
                area = width * height
                Iy = width * height**3 / 12
                Iz = height * width**3 / 12

            profile_id = (
                str(profile.id())
                if hasattr(profile, "id") and callable(profile.id)
                else str(uuid.uuid4())
            )
            profile_name = self._safe_get_attribute(profile, "ProfileName", "I-Section")

            return Section(
                id=profile_id,
                name=profile_name,
                section_type="i",
                area=area,
                dimensions={
                    "width": width,
                    "height": height,
                    "web_thickness": web_thick,
                    "flange_thickness": flange_thick,
                    "fillet_radius": fillet_rad,
                },
            )

        except Exception as e:
            self.logger.warning(f"Error creating I-section: {e}")
            return self._create_default_section()

    def _create_default_section(self) -> Section:
        """Create a default rectangular section with SI units (no conversion needed)."""
        return Section.create_rectangular_section(
            id=str(uuid.uuid4()),
            name="Default Rectangular Section",
            width=0.1,  # m
            height=0.2,  # m
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
            thickness_value = self._safe_get_attribute(entity, "Thickness", None)

            if thickness_value is not None:
                # Convert thickness to SI units
                thickness_value = (
                    max(0.001, float(thickness_value)) if thickness_value else 0.2
                )

                try:
                    thickness_value = convert_length(thickness_value, self.length_scale)
                except Exception as e:
                    self.logger.warning(f"Error converting thickness: {e}")
                    thickness_value = 0.2  # Default in SI units

                entity_id = (
                    str(entity.id())
                    if hasattr(entity, "id") and callable(entity.id)
                    else str(uuid.uuid4())
                )
                entity_name = self._safe_get_attribute(
                    entity, "Name", "Surface Thickness"
                )

                return Thickness(
                    id=f"thickness_{entity_id}",
                    name=entity_name,
                    value=thickness_value,
                )

            # Look for thickness in property sets
            psets = self._find_related_properties(entity)
            for pset in psets:
                properties = self._safe_get_attribute(pset, "HasProperties", [])
                for prop in properties:
                    prop_name = self._safe_get_attribute(prop, "Name", "")
                    if prop_name in ["Thickness", "Width"]:
                        value = self._safe_get_property_value(
                            prop, default_value=0.2, expected_type=float
                        )

                        # Validate and convert thickness
                        thickness_value = max(0.001, float(value)) if value else 0.2

                        try:
                            thickness_value = convert_length(
                                thickness_value, self.length_scale
                            )
                        except Exception as e:
                            self.logger.warning(f"Error converting thickness: {e}")
                            thickness_value = 0.2

                        entity_id = (
                            str(entity.id())
                            if hasattr(entity, "id") and callable(entity.id)
                            else str(uuid.uuid4())
                        )
                        entity_name = self._safe_get_attribute(
                            entity, "Name", "Surface Thickness"
                        )

                        return Thickness(
                            id=f"thickness_{entity_id}",
                            name=entity_name,
                            value=thickness_value,
                        )

            # No thickness found - return default
            self.logger.debug(f"No thickness found for entity {entity.id()}")
            return self._create_default_thickness()

        except Exception as e:
            self.logger.error(
                f"Error extracting thickness for entity {entity.id()}: {e}"
            )
            return self._create_default_thickness()

    def _create_default_thickness(self) -> Thickness:
        """Create a default thickness with SI units (no conversion needed)."""
        return Thickness(
            id=f"thickness_{uuid.uuid4()}",
            name="Default Thickness",
            value=0.2,  # m
        )

    def _find_related_material(self, entity):
        """
        Find the material associated with an entity.

        Args:
            entity: IFC entity

        Returns:
            Material entity or None
        """
        try:
            associations = self._safe_get_attribute(entity, "HasAssociations", [])

            for association in associations:
                try:
                    if not association.is_a("IfcRelAssociatesMaterial"):
                        continue

                    material = self._safe_get_attribute(
                        association, "RelatingMaterial", None
                    )

                    if not material:
                        continue

                    # Handle different material types
                    if material.is_a("IfcMaterialProfileSet"):
                        material_profiles = self._safe_get_attribute(
                            material, "MaterialProfiles", []
                        )
                        if material_profiles:
                            return self._safe_get_attribute(
                                material_profiles[0], "Material", None
                            )

                    elif material.is_a("IfcMaterialProfileSetUsage"):
                        for_profile_set = self._safe_get_attribute(
                            material, "ForProfileSet", None
                        )
                        if for_profile_set:
                            material_profiles = self._safe_get_attribute(
                                for_profile_set, "MaterialProfiles", []
                            )
                            if material_profiles:
                                return self._safe_get_attribute(
                                    material_profiles[0], "Material", None
                                )

                    elif material.is_a("IfcMaterial"):
                        return material

                except Exception as e:
                    self.logger.debug(f"Error processing material association: {e}")
                    continue

        except Exception as e:
            self.logger.warning(f"Error finding related material: {e}")

        return None

    def _find_related_profile(self, entity):
        """
        Find the profile associated with an entity.

        Args:
            entity: IFC entity

        Returns:
            Profile entity or None
        """
        try:
            associations = self._safe_get_attribute(entity, "HasAssociations", [])

            for association in associations:
                try:
                    if not association.is_a("IfcRelAssociatesMaterial"):
                        continue

                    material = self._safe_get_attribute(
                        association, "RelatingMaterial", None
                    )

                    if not material:
                        continue

                    # Handle different material types
                    if material.is_a("IfcMaterialProfileSet"):
                        material_profiles = self._safe_get_attribute(
                            material, "MaterialProfiles", []
                        )
                        if material_profiles:
                            return self._safe_get_attribute(
                                material_profiles[0], "Profile", None
                            )

                    elif material.is_a("IfcMaterialProfileSetUsage"):
                        for_profile_set = self._safe_get_attribute(
                            material, "ForProfileSet", None
                        )
                        if for_profile_set:
                            material_profiles = self._safe_get_attribute(
                                for_profile_set, "MaterialProfiles", []
                            )
                            if material_profiles:
                                return self._safe_get_attribute(
                                    material_profiles[0], "Profile", None
                                )

                except Exception as e:
                    self.logger.debug(f"Error processing profile association: {e}")
                    continue

            # Try to find profile in representation
            representation = self._safe_get_attribute(entity, "Representation", None)
            if representation:
                representations = self._safe_get_attribute(
                    representation, "Representations", []
                )
                for rep in representations:
                    items = self._safe_get_attribute(rep, "Items", [])
                    for item in items:
                        if item.is_a("IfcExtrudedAreaSolid"):
                            swept_area = self._safe_get_attribute(
                                item, "SweptArea", None
                            )
                            if swept_area:
                                return swept_area

        except Exception as e:
            self.logger.warning(f"Error finding related profile: {e}")

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

        try:
            # Look for properties via IsDefinedBy relationship
            is_defined_by = self._safe_get_attribute(entity, "IsDefinedBy", [])
            for rel in is_defined_by:
                relating_prop_def = self._safe_get_attribute(
                    rel, "RelatingPropertyDefinition", None
                )
                if relating_prop_def:
                    psets.append(relating_prop_def)

            # Some IFC files use HasProperties directly
            has_properties = self._safe_get_attribute(entity, "HasProperties", [])
            psets.extend(has_properties)

        except Exception as e:
            self.logger.warning(f"Error finding related properties: {e}")

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
        try:
            for pset in psets:
                pset_name_actual = self._safe_get_attribute(pset, "Name", "")
                if pset_name_actual == pset_name or pset_name is None:
                    properties = self._safe_get_attribute(pset, "Properties", [])
                    for prop in properties:
                        prop_name_actual = self._safe_get_attribute(prop, "Name", "")
                        if prop_name_actual == prop_name:
                            return self._safe_get_property_value(prop)
        except Exception as e:
            self.logger.warning(
                f"Error getting property {prop_name} from {pset_name}: {e}"
            )

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
        try:
            for pset in psets:
                pset_name_actual = self._safe_get_attribute(pset, "Name", "")
                if pset_name_actual == pset_name or pset_name is None:
                    props = {}
                    properties = self._safe_get_attribute(pset, "Properties", [])
                    for prop in properties:
                        prop_name = self._safe_get_attribute(prop, "Name", "")
                        if prop_name:
                            prop_name_camel = (
                                prop_name[0].lower() + prop_name[1:]
                                if len(prop_name) > 1
                                else prop_name.lower()
                            )
                            value = self._safe_get_property_value(prop)
                            if value is not None:
                                props[prop_name_camel] = value
                    return props
        except Exception as e:
            self.logger.warning(f"Error getting properties from {pset_name}: {e}")

        return {}


# Make sure the class is properly exported
__all__ = ["PropertiesExtractor"]
