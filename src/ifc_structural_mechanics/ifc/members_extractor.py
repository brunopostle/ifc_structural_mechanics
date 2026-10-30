"""
Member extraction module for structural analysis.

This module contains the MembersExtractor class which extracts structural
members from IFC files and converts them to domain model objects.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional, Union

import ifcopenshell
import numpy as np

from ..domain.property import Material, Section, Thickness
from ..domain.structural_member import CurveMember, StructuralMember, SurfaceMember
from ..ifc.entity_identifier import (
    face_loops,
    get_1D_orientation,
    get_coordinate,
    get_item_transformation,
    get_representation,
    transform_vectors,
)
from ..utils.error_handling import ModelExtractionError
from ..utils.messages import warning
from ..utils.units import (
    convert_length,
)

logger = logging.getLogger(__name__)


# What a density given with no unit can be, in kg/m3
MIN_DENSITY, MAX_DENSITY = 1.0, 1.0e6

# How far a profile's stated value may be from its dimensions'. The fillets of
# a rolled section add a few percent to its inertia and a fifth to its torsion.
PSET_AGREEMENT = 1.5


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
            raise ModelExtractionError(
                "ifc_file must be a file path or an ifcopenshell.file object",
                code="E-GEN-001",
            )

        # Store unit scales
        self.unit_scales = unit_scales or {}
        self.length_scale = self.unit_scales.get("LENGTHUNIT", 1.0)
        self.area_scale = self.unit_scales.get("AREAUNIT", self.length_scale**2)
        self.force_scale = self.unit_scales.get("FORCEUNIT", 1.0)
        self.density_scale = self.unit_scales.get("MASSDENSITYUNIT")
        self.inertia_scale = self.unit_scales.get("MOMENTOFINERTIAUNIT", 1.0)
        self.pressure_scale = self.unit_scales.get("PRESSUREUNIT", 1.0)
        # Kelvin per unit of the file: a difference of temperature
        self.temperature_scale = self.unit_scales.get(
            "THERMODYNAMICTEMPERATUREUNIT", 1.0
        )

        # What the analysis will not do exactly as the file says; the
        # Extractor passes these on to the results
        # Warnings for the results (``utils.messages.warning``)
        self.warnings: List[Dict[str, Any]] = []
        self._disagreeing_psets: List[str] = []

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

        Raises:
            ModelExtractionError: If any of them cannot be analysed.
        """
        members = [
            self._create_curve_member(entity)
            for entity in self.ifc.by_type("IfcStructuralCurveMember")
        ]
        self.logger.info(f"Extracted {len(members)} curve members")
        return members

    def extract_surface_members(self) -> List[SurfaceMember]:
        """
        Extract all surface members (walls, slabs, etc.) from the IFC file.

        Returns:
            List of SurfaceMember domain objects

        Raises:
            ModelExtractionError: If any of them cannot be analysed.
        """
        members = [
            self._create_surface_member(entity)
            for entity in self.ifc.by_type("IfcStructuralSurfaceMember")
        ]
        self.logger.info(f"Extracted {len(members)} surface members")
        return members

    def _create_member(self, entity, build):
        """Build a member, turning any failure into an error that names it.

        A member is never left out and never given a made-up material,
        section or thickness: the analysis would then be of another structure.
        """
        entity_id = getattr(entity, "GlobalId", None) or "?"
        try:
            return build(entity)
        except ModelExtractionError as error:
            raise ModelExtractionError(
                f"Member {entity_id} cannot be analysed. {error.message}",
                code=error.code,
                ifc_guids=[entity_id, *error.ifc_guids],
            ) from error
        except Exception as error:
            raise ModelExtractionError(
                f"Member {entity_id} cannot be read from the IFC file: "
                f"{type(error).__name__}: {error}",
                code="E-IFC-005",
                ifc_guids=[entity_id],
            ) from error

    def _create_curve_member(self, entity) -> CurveMember:
        """
        Create a CurveMember domain object from an IFC entity.

        Args:
            entity: IFC entity representing a curve member

        Returns:
            The curve member

        Raises:
            ModelExtractionError: If it has no usable geometry, material or
                profile, or the profile is of a kind that is not supported.
        """
        return self._create_member(entity, self._build_curve_member)

    def _create_surface_member(self, entity) -> SurfaceMember:
        """
        Create a SurfaceMember domain object from an IFC entity.

        Args:
            entity: IFC entity representing a surface member

        Returns:
            The surface member

        Raises:
            ModelExtractionError: If it has no usable geometry, material or
                thickness.
        """
        return self._create_member(entity, self._build_surface_member)

    def _build_curve_member(self, entity) -> CurveMember:
        """Create a curve member; see ``_create_curve_member``."""
        representation = get_representation(entity, "Edge")
        if not representation:
            raise ModelExtractionError(
                "It has no edge representation.", code="E-IFC-002"
            )

        material_profile = self._get_material_profile(entity)
        material = getattr(material_profile, "Material", None)
        profile = getattr(material_profile, "Profile", None)
        if material is None or profile is None:
            raise ModelExtractionError(
                "It has no material profile (an IfcMaterialProfileSet with a "
                "material and a profile).",
                code="E-SEC-001",
            )

        geometry = self._extract_geometry(representation, self.length_scale)
        if not geometry:
            raise ModelExtractionError(
                "The ends of its edge cannot be read.", code="E-IFC-002"
            )

        orientation = None
        if getattr(entity, "Axis", None) is not None:
            orientation = get_1D_orientation(geometry, entity.Axis)

        # The geometry is in metres by now, so the offset has to be too
        transformation = get_item_transformation(entity, self.length_scale)
        if transformation:
            geometry = transform_vectors(geometry, transformation)
            if orientation:
                orientation = transform_vectors(
                    orientation, transformation, include_translation=False
                )

        return CurveMember(
            id=entity.GlobalId,
            geometry=geometry,
            material=self._create_material(material),
            section=self._create_section(profile),
            ifc_guid=entity.GlobalId,
            local_axis=tuple(orientation) if orientation is not None else None,
        )

    def _build_surface_member(self, entity) -> SurfaceMember:
        """Create a surface member; see ``_create_surface_member``."""
        representation = get_representation(entity, "Face")
        if not representation:
            raise ModelExtractionError(
                "It has no face representation.", code="E-IFC-002"
            )

        material = self._get_surface_material(entity)
        if material is None:
            raise ModelExtractionError("It has no material.", code="E-MAT-001")

        geometry = self._extract_geometry(representation, self.length_scale)
        if not geometry:
            raise ModelExtractionError(
                "The outline of its face cannot be read.", code="E-IFC-002"
            )

        _, holes = self._face_loops(representation.Items[0], self.length_scale)
        transformation = get_item_transformation(entity, self.length_scale)
        if transformation:
            geometry = transform_vectors(geometry, transformation)
            holes = [transform_vectors(hole, transformation) for hole in holes]
        self._check_holes(geometry, holes)

        thickness_value = convert_length(
            getattr(entity, "Thickness", None) or 0.0, self.length_scale
        )
        if thickness_value <= 0:
            raise ModelExtractionError("It has no thickness.", code="E-SEC-003")

        member = SurfaceMember(
            id=entity.GlobalId,
            geometry=geometry,
            material=self._create_material(material),
            thickness=Thickness(
                id=f"thickness_{entity.GlobalId}",
                name="Surface Thickness",
                value=thickness_value,
            ),
            ifc_guid=entity.GlobalId,
        )
        member.normal = self._surface_normal(representation, transformation)
        member.holes = [[[float(v) for v in corner] for corner in h] for h in holes]
        return member

    @staticmethod
    def _face_loops(face, unit_scale: float) -> tuple:
        """``face_loops()``, its failures as this stage's error."""
        try:
            return face_loops(face, unit_scale)
        except ValueError as error:
            raise ModelExtractionError(str(error), code="E-IFC-002") from error

    @staticmethod
    def _check_holes(geometry: Any, holes: List[Any]) -> None:
        """Refuse holes that do not lie clear inside a face, and apart.

        Gmsh would mesh some of them into something else without a word.

        Raises:
            ModelExtractionError: If a hole has fewer than three corners, is
                out of the face's plane, or touches or leaves the outline or
                another hole.
        """
        if not holes:
            return

        def refuse(reason: str) -> None:
            raise ModelExtractionError(
                f"An opening of its face {reason}", code="E-IFC-002"
            )

        outline = np.array(geometry, dtype=float)
        normal = np.zeros(3)
        for i in range(len(outline)):
            normal += np.cross(outline[i], outline[(i + 1) % len(outline)])
        length = float(np.linalg.norm(normal))
        if length < 1e-12:
            raise ModelExtractionError("Its face has no area.", code="E-IFC-002")
        normal /= length
        keep = [i for i in range(3) if i != int(np.argmax(np.abs(normal)))]

        loops = [outline[:, keep]]
        for hole in holes:
            corners = np.array(hole, dtype=float)
            if len(corners) < 3:
                refuse("has fewer than three corners.")
            if np.abs((corners - outline[0]) @ normal).max() > 1e-3:
                refuse("is not in the plane of the face.")
            loops.append(corners[:, keep])

        def inside(point: np.ndarray, loop: np.ndarray) -> bool:
            result = False
            for (x0, y0), (x1, y1) in zip(loop, np.roll(loop, -1, axis=0)):
                if (y0 > point[1]) != (y1 > point[1]) and point[0] < x0 + (
                    point[1] - y0
                ) * (x1 - x0) / (y1 - y0):
                    result = not result
            return result

        def off_segment(point: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
            t = float(np.clip((point - a) @ (b - a) / ((b - a) @ (b - a)), 0.0, 1.0))
            return float(np.linalg.norm(a + t * (b - a) - point))

        def segments_meet(p0, p1, q0, q1) -> bool:
            def side(a, b, c):
                return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

            if (side(p0, p1, q0) > 0) != (side(p0, p1, q1) > 0) and (
                side(q0, q1, p0) > 0
            ) != (side(q0, q1, p1) > 0):
                return True
            return (
                min(
                    off_segment(q0, p0, p1),
                    off_segment(q1, p0, p1),
                    off_segment(p0, q0, q1),
                    off_segment(p1, q0, q1),
                )
                < 1e-6
            )

        def edges(loop: np.ndarray):
            return list(zip(loop, np.roll(loop, -1, axis=0)))

        for index, hole in enumerate(loops[1:], start=1):
            if not inside(hole[0], loops[0]):
                refuse("lies outside its outline.")
            for other_index, other in enumerate(loops[:index]):
                if any(
                    segments_meet(p0, p1, q0, q1)
                    for p0, p1 in edges(hole)
                    for q0, q1 in edges(other)
                ):
                    refuse(
                        "touches or crosses "
                        + ("its outline." if other_index == 0 else "another opening.")
                    )
                if other_index and (inside(hole[0], other) or inside(other[0], hole)):
                    refuse("lies inside another opening.")

    @staticmethod
    def _surface_normal(representation, transformation) -> Optional[List[float]]:
        """The local z of a surface member: the normal of its face's plane.

        As for surface connections, a face whose sense opposes its plane's
        turns it over. None when the face has no plane.
        """
        item = representation.Items[0]
        surface = getattr(item, "FaceSurface", None)
        if surface is None or not surface.is_a("IfcPlane"):
            return None
        axis = surface.Position.Axis
        normal = np.array(
            axis.DirectionRatios if axis else (0.0, 0.0, 1.0), dtype=float
        )
        if not getattr(item, "SameSense", True):
            normal = -normal
        if transformation:
            normal = np.array(transformation["rotationMatrix"], dtype=float) @ normal
        length = float(np.linalg.norm(normal))
        if not length > 0:
            return None
        return [float(v) for v in normal / length]

    def _extract_geometry(self, representation, unit_scale: float = 1.0):
        """
        Extract geometry from a representation.

        Args:
            representation: IFC representation
            unit_scale: Scale factor to convert to SI units

        Returns:
            The two ends of an edge, or the corners of a face, in SI units.
            None when the representation holds neither.

        Raises:
            ModelExtractionError: If a point of the edge or face has no
                usable coordinates. A face is never returned with a corner
                missing.
        """
        if not representation or not representation.Items:
            return None

        item = representation.Items[0]

        if item.is_a("IfcEdge"):
            ends = [
                get_coordinate(vertex.VertexGeometry, unit_scale)
                for vertex in (item.EdgeStart, item.EdgeEnd)
            ]
            if any(end is None for end in ends):
                raise ModelExtractionError(
                    "An end of its edge has no coordinates.", code="E-IFC-002"
                )
            return ends

        if item.is_a("IfcFaceSurface") and item.Bounds:
            outline, _ = self._face_loops(item, unit_scale)
            return outline or None

        return None

    def _warn_once(self, code: str, message: str) -> None:
        """Record a warning for the results, once however many members share it."""
        if all(found["message"] != message for found in self.warnings):
            self.logger.warning(f"[{code}] {message}")
            self.warnings.append(warning(code, message))

    def _get_surface_material(self, element):
        """Return the IfcMaterial of a surface member, or None.

        Surface members reference a plain ``IfcMaterial``, a layer set (the
        first layer is used) or a constituent set, never a profile set.
        """
        for association in getattr(element, "HasAssociations", None) or []:
            if not association.is_a("IfcRelAssociatesMaterial"):
                continue
            material = association.RelatingMaterial
            if material.is_a("IfcMaterial"):
                return material
            if material.is_a("IfcMaterialLayerSetUsage"):
                material = material.ForLayerSet
            if material.is_a("IfcMaterialLayerSet") and material.MaterialLayers:
                return material.MaterialLayers[0].Material
            if material.is_a("IfcMaterialLayer"):
                return material.Material
            if (
                material.is_a("IfcMaterialConstituentSet")
                and material.MaterialConstituents
            ):
                return material.MaterialConstituents[0].Material
            if material.is_a("IfcMaterialProfileSetUsage"):
                material = material.ForProfileSet
            if material.is_a("IfcMaterialProfileSet") and material.MaterialProfiles:
                return material.MaterialProfiles[0].Material
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
        poisson_ratio = mechProps.get("poissonRatio")
        shear_modulus_raw = mechProps.get("shearModulus")
        expansion_raw = mechProps.get("thermalExpansionCoefficient")

        # Second pass: if key properties still missing, search all psets by property name
        if None in (
            elastic_modulus_raw,
            density_raw,
            poisson_ratio,
            shear_modulus_raw,
            expansion_raw,
        ):
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
                    ) and poisson_ratio is None:
                        poisson_ratio = value
                    elif "shearmodulus" in lower_name and shear_modulus_raw is None:
                        shear_modulus_raw = value
                    elif (
                        "thermalexpansioncoefficient" in lower_name
                        and expansion_raw is None
                    ):
                        expansion_raw = value

        name = getattr(material, "Name", None) or "unnamed"
        if elastic_modulus_raw is None:
            raise ModelExtractionError(
                f"Its material '{name}' has no Young's modulus "
                "(Pset_MaterialMechanical.YoungModulus).",
                code="E-MAT-002",
            )
        elastic_modulus = elastic_modulus_raw * self.pressure_scale

        # Without a density the member weighs nothing, and the user is told:
        # that is wrong under gravity and harmless otherwise
        density = None
        if density_raw is not None:
            density = self._density_in_si(density_raw, name)
        else:
            self._warn_once(
                "W-MAT-001",
                f"Material '{name}' has no mass density "
                "(Pset_MaterialCommon.MassDensity); its members are analysed "
                "as weightless.",
            )
        # An isotropic material has G = E / 2(1 + nu): a shear modulus given
        # in place of Poisson's ratio is the same information
        if poisson_ratio is None and shear_modulus_raw is not None:
            if not shear_modulus_raw > 0:
                raise ModelExtractionError(
                    f"Its material '{name}' has a shear modulus of "
                    f"{shear_modulus_raw} and no Poisson's ratio.",
                    code="E-MAT-004",
                )
            poisson_ratio = elastic_modulus_raw / (2.0 * shear_modulus_raw) - 1.0
            if not -1.0 < poisson_ratio < 0.5:
                raise ModelExtractionError(
                    f"Its material '{name}' has no Poisson's ratio, and its "
                    f"Young's modulus {elastic_modulus_raw} and shear modulus "
                    f"{shear_modulus_raw} give {poisson_ratio:.4g}, which no "
                    "isotropic material has.",
                    code="E-MAT-004",
                )
        elif poisson_ratio is not None and shear_modulus_raw is not None:
            implied = elastic_modulus_raw / (2.0 * (1.0 + poisson_ratio))
            if abs(implied - shear_modulus_raw) > 0.01 * abs(implied):
                self._warn_once(
                    "W-MAT-003",
                    f"Material '{name}' has a shear modulus of "
                    f"{shear_modulus_raw}, where its Young's modulus and "
                    f"Poisson's ratio {poisson_ratio} give {implied:.6g}; the "
                    "material is analysed as isotropic with the Poisson's ratio.",
                )
        if poisson_ratio is None:
            poisson_ratio = 0.3
            self._warn_once(
                "W-MAT-002",
                f"Material '{name}' has no Poisson's ratio "
                "(Pset_MaterialMechanical.PoissonRatio) and no shear modulus; "
                "0.3 is assumed.",
            )

        # Yield stress, where the file gives one (Pset_MaterialSteel). A
        # concrete's compressive strength is not used: it is not a limit on
        # the normal stress of a member.
        yield_strength = None
        for pset in psets:
            for prop in getattr(pset, "Properties", None) or []:
                if getattr(prop, "Name", "") != "YieldStress":
                    continue
                try:
                    value = float(prop.NominalValue.wrappedValue)
                except (AttributeError, TypeError, ValueError):
                    continue
                if value > 0:
                    yield_strength = value * self.pressure_scale

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
            yield_strength=yield_strength,
            # Per unit of the file's temperature: strain is alpha times a
            # difference of temperature
            thermal_expansion_coefficient=(
                float(expansion_raw) / self.temperature_scale
                if expansion_raw is not None
                else None
            ),
        )

    def _take_mechanical_properties(self, section: Section, profile) -> None:
        """
        Give a section the values its profile's Pset_ProfileMechanical states.

        They include the fillets of a rolled section, which the dimensions do
        not. A value far from what the dimensions give is in another unit than
        the file declares or about another axis, so the dimensions stand and
        the user is told.

        Args:
            section: The section, with the properties of its dimensions
            profile: The IFC profile
        """
        stated = {}
        for pset in getattr(profile, "HasProperties", None) or []:
            if pset.Name == "Pset_ProfileMechanical":
                for prop in pset.Properties:
                    stated[prop.Name] = prop.NominalValue.wrappedValue

        for name, attribute, scale in (
            ("CrossSectionArea", "area", self.area_scale),
            ("MomentOfInertiaY", "moment_of_inertia_y", self.inertia_scale),
            ("MomentOfInertiaZ", "moment_of_inertia_z", self.inertia_scale),
            ("TorsionalConstantX", "torsional_constant", self.inertia_scale),
        ):
            if name not in stated:
                continue
            value = stated[name] * scale
            from_dimensions = getattr(section, attribute)
            if 1 / PSET_AGREEMENT <= value / from_dimensions <= PSET_AGREEMENT:
                setattr(section, attribute, value)
            else:
                disagreement = (
                    f"{name} of '{section.name}' is {value:.4g} in SI units, "
                    f"where its dimensions give {from_dimensions:.4g}"
                )
                if disagreement not in self._disagreeing_psets:
                    self._disagreeing_psets.append(disagreement)

        if self._disagreeing_psets:
            self.warnings = [
                found for found in self.warnings if found["code"] != "W-SEC-005"
            ]
            self.warnings.append(
                warning(
                    "W-SEC-005",
                    f"{len(self._disagreeing_psets)} value(s) of "
                    "Pset_ProfileMechanical are far from what the profile's "
                    "dimensions give, and the dimensions are used instead: "
                    + "; ".join(self._disagreeing_psets[:3])
                    + ". Check the file's units.",
                )
            )

    def _density_in_si(self, value: float, material_name: str) -> float:
        """
        A material's mass density in kg/m3.

        IFC does not say what a density is in when the project assigns no
        MASSDENSITYUNIT, only that it is usually kg/m3, which is what Bonsai's
        projects in millimetres have. A value that cannot be that is in another
        unit, and reading it so would make a member weigh nothing or a billion
        times too much.

        Args:
            value: The density as the file gives it
            material_name: Name of the material, for the error

        Returns:
            The density in kg/m3
        """
        if self.density_scale is not None:
            return value * self.density_scale
        if value != 0 and not MIN_DENSITY <= value <= MAX_DENSITY:
            raise ModelExtractionError(
                f"Its material '{material_name}' has a mass density of {value} "
                "and the file assigns no MASSDENSITYUNIT, so it would be "
                f"{value} kg/m3, which no material is. Assign the unit it is in.",
                code="E-MAT-005",
            )
        return value

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

        def profile_id():
            if hasattr(profile, "id") and callable(profile.id):
                return profile.id()
            return str(uuid.uuid4())

        # The hollow profiles are subtypes of the solid ones in IFC, so
        # is_a() on the solid type matches them too: test them first.
        if profile.is_a("IfcCircleHollowProfileDef"):
            return Section.create_hollow_circular_section(
                id=profile_id(),
                name=getattr(profile, "ProfileName", None) or "Pipe Section",
                outer_radius=convert_length(profile.Radius, self.length_scale),
                thickness=convert_length(profile.WallThickness, self.length_scale),
            )

        elif profile.is_a("IfcRectangleHollowProfileDef"):
            return Section.create_hollow_rectangular_section(
                id=profile_id(),
                name=getattr(profile, "ProfileName", None) or "Box Section",
                outer_width=convert_length(profile.XDim, self.length_scale),
                outer_height=convert_length(profile.YDim, self.length_scale),
                thickness=convert_length(profile.WallThickness, self.length_scale),
            )

        elif profile.is_a("IfcCircleProfileDef"):
            return Section.create_circular_section(
                id=profile_id(),
                name=getattr(profile, "ProfileName", None) or "Circular Section",
                radius=convert_length(profile.Radius, self.length_scale),
            )

        elif profile.is_a("IfcRectangleProfileDef"):
            return Section.create_rectangular_section(
                id=profile_id(),
                name=getattr(profile, "ProfileName", None) or "Rectangular Section",
                width=convert_length(profile.XDim, self.length_scale),
                height=convert_length(profile.YDim, self.length_scale),
            )

        # Handle I-shape profile (symmetric)
        elif profile.is_a("IfcIShapeProfileDef"):
            width = convert_length(profile.OverallWidth, self.length_scale)
            height = convert_length(profile.OverallDepth, self.length_scale)
            web_thickness = convert_length(profile.WebThickness, self.length_scale)
            flange_thickness = convert_length(
                profile.FlangeThickness, self.length_scale
            )
            fillet_radius = convert_length(
                getattr(profile, "FilletRadius", None) or 0.0, self.length_scale
            )

            section = Section(
                id=profile_id(),
                name=getattr(profile, "ProfileName", None) or "I-Section",
                section_type="i",
                area=(
                    2 * width * flange_thickness
                    + web_thickness * (height - 2 * flange_thickness)
                ),
                dimensions={
                    "width": width,
                    "height": height,
                    "web_thickness": web_thickness,
                    "flange_thickness": flange_thickness,
                    "fillet_radius": fillet_radius,
                },
            )
            self._take_mechanical_properties(section, profile)
            return section

        # Handle asymmetric I-shape (averaged flanges → stored as "i")
        elif profile.is_a("IfcAsymmetricIShapeProfileDef"):
            b_bot = convert_length(
                getattr(profile, "BottomFlangeWidth", 0.1), self.length_scale
            )
            b_top = convert_length(
                getattr(profile, "TopFlangeWidth", b_bot), self.length_scale
            )
            h = convert_length(getattr(profile, "OverallDepth", 0.2), self.length_scale)
            tw = convert_length(
                getattr(profile, "WebThickness", 0.01), self.length_scale
            )
            tf_bot = convert_length(
                getattr(profile, "BottomFlangeThickness", 0.01), self.length_scale
            )
            tf_top = convert_length(
                getattr(profile, "TopFlangeThickness", tf_bot), self.length_scale
            )
            bf = (b_bot + b_top) / 2.0
            tf = (tf_bot + tf_top) / 2.0
            h_web = max(h - tf_bot - tf_top, 0.0)
            area = b_bot * tf_bot + b_top * tf_top + tw * h_web
            return Section(
                id=str(uuid.uuid4()),
                name=getattr(profile, "ProfileName", "Asymmetric-I"),
                section_type="i",
                area=max(1e-6, area),
                dimensions={
                    "width": bf,
                    "height": h,
                    "web_thickness": tw,
                    "flange_thickness": tf,
                    "fillet_radius": 0.0,
                },
            )

        # Handle L-shape (angle) profile
        elif profile.is_a("IfcLShapeProfileDef"):
            depth = convert_length(getattr(profile, "Depth", 0.1), self.length_scale)
            width = convert_length(getattr(profile, "Width", depth), self.length_scale)
            thickness = convert_length(
                getattr(profile, "Thickness", 0.01), self.length_scale
            )
            area = (depth + width - thickness) * thickness
            return Section(
                id=str(uuid.uuid4()),
                name=getattr(profile, "ProfileName", "L-Section"),
                section_type="l",
                area=max(1e-6, area),
                dimensions={
                    "width": width,
                    "height": depth,
                    "thickness": thickness,
                },
            )

        # Handle T-shape profile
        elif profile.is_a("IfcTShapeProfileDef"):
            depth = convert_length(getattr(profile, "Depth", 0.2), self.length_scale)
            flange_width = convert_length(
                getattr(profile, "FlangeWidth", 0.1), self.length_scale
            )
            web_thickness = convert_length(
                getattr(profile, "WebThickness", 0.01), self.length_scale
            )
            flange_thickness = convert_length(
                getattr(profile, "FlangeThickness", 0.01), self.length_scale
            )
            web_height = max(depth - flange_thickness, 0.0)
            area = flange_width * flange_thickness + web_height * web_thickness
            return Section(
                id=str(uuid.uuid4()),
                name=getattr(profile, "ProfileName", "T-Section"),
                section_type="t",
                area=max(1e-6, area),
                dimensions={
                    "width": flange_width,
                    "height": depth,
                    "web_thickness": web_thickness,
                    "flange_thickness": flange_thickness,
                },
            )

        # Handle channel profile (IfcUShapeProfileDef; there is no
        # IfcChannelProfileDef in IFC)
        elif profile.is_a("IfcUShapeProfileDef"):
            depth = convert_length(getattr(profile, "Depth", 0.2), self.length_scale)
            flange_width = convert_length(
                getattr(profile, "FlangeWidth", 0.1), self.length_scale
            )
            web_thickness = convert_length(
                getattr(profile, "WebThickness", 0.01), self.length_scale
            )
            flange_thickness = convert_length(
                getattr(profile, "FlangeThickness", 0.01), self.length_scale
            )
            web_height = max(depth - 2 * flange_thickness, 0.0)
            area = web_thickness * web_height + 2 * flange_width * flange_thickness
            return Section(
                id=str(uuid.uuid4()),
                name=getattr(profile, "ProfileName", "C-Section"),
                section_type="c",
                area=max(1e-6, area),
                dimensions={
                    "width": flange_width,
                    "height": depth,
                    "web_thickness": web_thickness,
                    "flange_thickness": flange_thickness,
                },
            )

        # Analysing some other section in its place would give results that
        # look like answers and are not.
        raise ModelExtractionError(
            f"Profile {getattr(profile, 'ProfileName', None)!r} is an "
            f"{profile.is_a()}, which is not supported. Supported profiles: "
            "rectangle, circle, hollow rectangle, hollow circle, I, asymmetric "
            "I, T, L and U (channel).",
            code="E-SEC-002",
        )
