"""
Entity identification and relationship navigation utilities for IFC structural analysis.

This module provides functions to identify and extract information about
structural analysis-related IFC entities.
"""

import logging
from typing import List, Optional

import ifcopenshell
import numpy as np

from ..utils.error_handling import ModelExtractionError
from ..utils.units import (
    convert_coordinates,
)

logger = logging.getLogger(__name__)


def is_structural_member(entity: Optional[ifcopenshell.entity_instance]) -> bool:
    """
    Check if the given entity is a structural member.

    Args:
        entity (Optional[ifcopenshell.entity_instance]): IFC entity to check

    Returns:
        bool: True if the entity is a structural member, False otherwise
    """
    if entity is None:
        return False

    try:
        if not hasattr(entity, "is_a") or not callable(entity.is_a):
            return False

        structural_member_types = [
            "IfcStructuralCurveMember",
            "IfcStructuralSurfaceMember",
            "IfcBeam",
            "IfcColumn",
            "IfcWall",
            "IfcSlab",
        ]

        return entity.is_a() in structural_member_types
    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(
            f"Error checking if entity is structural member: {e}"
        ) from e


def is_structural_curve_member(entity: Optional[ifcopenshell.entity_instance]) -> bool:
    """
    Check if the given entity is a structural curve member.

    Args:
        entity (Optional[ifcopenshell.entity_instance]): IFC entity to check

    Returns:
        bool: True if the entity is a structural curve member, False otherwise
    """
    if entity is None:
        return False

    try:
        if not hasattr(entity, "is_a") or not callable(entity.is_a):
            return False

        curve_member_types = ["IfcStructuralCurveMember", "IfcBeam", "IfcColumn"]
        return entity.is_a() in curve_member_types
    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(
            f"Error checking if entity is structural curve member: {e}"
        ) from e


def is_structural_surface_member(
    entity: Optional[ifcopenshell.entity_instance],
) -> bool:
    """
    Check if the given entity is a structural surface member.

    Args:
        entity (Optional[ifcopenshell.entity_instance]): IFC entity to check

    Returns:
        bool: True if the entity is a structural surface member, False otherwise
    """
    if entity is None:
        return False

    try:
        if not hasattr(entity, "is_a") or not callable(entity.is_a):
            return False

        surface_member_types = ["IfcStructuralSurfaceMember", "IfcWall", "IfcSlab"]
        return entity.is_a() in surface_member_types
    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(
            f"Error checking if entity is structural surface member: {e}"
        ) from e


def is_structural_connection(entity: Optional[ifcopenshell.entity_instance]) -> bool:
    """
    Check if the given entity is a structural connection.

    Args:
        entity (Optional[ifcopenshell.entity_instance]): IFC entity to check

    Returns:
        bool: True if the entity is a structural connection, False otherwise
    """
    if entity is None:
        return False

    try:
        if not hasattr(entity, "is_a") or not callable(entity.is_a):
            return False

        connection_types = [
            "IfcStructuralPointConnection",
            "IfcStructuralCurveConnection",
            "IfcStructuralSurfaceConnection",
        ]
        return entity.is_a() in connection_types
    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(
            f"Error checking if entity is structural connection: {e}"
        ) from e


def is_structural_load(entity: Optional[ifcopenshell.entity_instance]) -> bool:
    """
    Check if the given entity is a structural load.

    Args:
        entity (Optional[ifcopenshell.entity_instance]): IFC entity to check

    Returns:
        bool: True if the entity is a structural load, False otherwise
    """
    if entity is None:
        return False

    try:
        if not hasattr(entity, "is_a") or not callable(entity.is_a):
            return False

        load_types = [
            "IfcStructuralPointAction",
            "IfcStructuralLinearAction",
            "IfcStructuralPlanarAction",
            "IfcStructuralLoadCase",
        ]
        return entity.is_a() in load_types
    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(
            f"Error checking if entity is structural load: {e}"
        ) from e


def get_coordinate(point, unit_scale: float = 1.0):
    """
    Extract coordinates from an IfcCartesianPoint with robust validation.

    Args:
        point: The IfcCartesianPoint entity
        unit_scale: Scale factor to convert to SI units

    Returns:
        List of coordinate values in SI units, or None if invalid
    """
    if point is None:
        logger.warning("get_coordinate called with None point")
        return None

    try:
        if not hasattr(point, "is_a") or not callable(point.is_a):
            logger.warning(f"Invalid point object: {type(point)}")
            return None

        if point.is_a("IfcCartesianPoint") and hasattr(point, "Coordinates"):
            coords = list(point.Coordinates)

            # Validate that all coordinates are numbers, not None
            if any(coord is None for coord in coords):
                logger.warning(f"Found None coordinates in point: {coords}")
                return None

            # Validate that all coordinates are numeric
            try:
                numeric_coords = [float(coord) for coord in coords]
            except (ValueError, TypeError) as e:
                logger.warning(f"Non-numeric coordinates found: {coords}, error: {e}")
                return None

            # Convert to SI units - now safe since we validated the coordinates
            return convert_coordinates(numeric_coords, unit_scale)

        logger.warning(
            f"Point is not IfcCartesianPoint or missing Coordinates: {point}"
        )
        return None

    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(f"Error extracting coordinates: {e}") from e


def get_representation(element, rep_type):
    """
    Find representation of specific type from an entity with fallbacks.

    Args:
        element: IFC entity
        rep_type: Representation type to find

    Returns:
        Representation instance or None if not found
    """
    if not hasattr(element, "Representation") or not element.Representation:
        return None

    # First try with "Reference" identifier (common for structural)
    for representation in element.Representation.Representations:
        if (
            hasattr(representation, "RepresentationIdentifier")
            and representation.RepresentationIdentifier == "Reference"
            and hasattr(representation, "RepresentationType")
            and representation.RepresentationType == rep_type
        ):
            return representation

        # Check if it's a MappedRepresentation that contains the type we're looking for
        if (
            hasattr(representation, "RepresentationIdentifier")
            and representation.RepresentationIdentifier == "Reference"
            and hasattr(representation, "RepresentationType")
            and representation.RepresentationType == "MappedRepresentation"
        ):
            # Try to find the representation type inside the MappedRepresentation
            mapped_rep = get_specific_representation(
                representation, "Reference", rep_type
            )
            if mapped_rep:
                return mapped_rep

    # Then try without rep identifier
    for representation in element.Representation.Representations:
        if (
            hasattr(representation, "RepresentationType")
            and representation.RepresentationType == rep_type
        ):
            return representation

        # Check if it's a MappedRepresentation that contains the type we're looking for
        if (
            hasattr(representation, "RepresentationType")
            and representation.RepresentationType == "MappedRepresentation"
        ):
            # Try to find the representation type inside the MappedRepresentation
            mapped_rep = get_specific_representation(representation, None, rep_type)
            if mapped_rep:
                return mapped_rep

    return None


def get_specific_representation(representation, rep_id, rep_type):
    """
    Extract a specific representation type from a representation.

    Args:
        representation: IFC representation entity
        rep_id: Representation identifier or None
        rep_type: Representation type

    Returns:
        The representation if found, None otherwise
    """
    if (
        representation.RepresentationIdentifier == rep_id or rep_id is None
    ) and representation.RepresentationType == rep_type:
        return representation

    if representation.RepresentationType == "MappedRepresentation":
        if len(representation.Items) > 0:
            if (
                hasattr(representation.Items[0], "MappingSource")
                and representation.Items[0].MappingSource
            ):
                if hasattr(
                    representation.Items[0].MappingSource, "MappedRepresentation"
                ):
                    return get_specific_representation(
                        representation.Items[0].MappingSource.MappedRepresentation,
                        rep_id,
                        rep_type,
                    )
    return None


def find_connected_elements(
    entity: Optional[ifcopenshell.entity_instance],
) -> List[str]:
    """
    Find elements connected to the given entity.

    Args:
        entity (Optional[ifcopenshell.entity_instance]): IFC entity to find connected elements for

    Returns:
        List[str]: List of connected element IDs
    """
    if entity is None:
        return []

    try:
        connected_elements = []

        # For connections, find connected structural members
        if is_structural_connection(entity):
            if hasattr(entity, "ConnectsStructuralMembers"):
                for rel in entity.ConnectsStructuralMembers:
                    if (
                        hasattr(rel, "RelatingStructuralMember")
                        and rel.RelatingStructuralMember
                    ):
                        connected_elements.append(rel.RelatingStructuralMember.GlobalId)

        # For members, find connected connections
        elif is_structural_member(entity):
            if hasattr(entity, "ConnectedBy"):
                for rel in entity.ConnectedBy:
                    if (
                        hasattr(rel, "RelatedStructuralConnection")
                        and rel.RelatedStructuralConnection
                    ):
                        connected_elements.append(
                            rel.RelatedStructuralConnection.GlobalId
                        )

        return connected_elements
    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(f"Error finding connected elements: {e}") from e


def find_member_endpoints(
    member: Optional[ifcopenshell.entity_instance], unit_scale: float = 1.0
) -> List[List[float]]:
    """
    Find the endpoints of a structural member.

    Args:
        member (Optional[ifcopenshell.entity_instance]): IFC member entity
        unit_scale: Scale factor to convert to SI units

    Returns:
        List[List[float]]: List of endpoint coordinates in SI units, in the
            global axes
    """
    if member is None or not is_structural_curve_member(member):
        return []

    representation = get_representation(member, "Edge")
    if representation and representation.Items:
        item = representation.Items[0]
        if item.is_a("IfcEdge"):
            start = get_coordinate(item.EdgeStart.VertexGeometry, unit_scale)
            end = get_coordinate(item.EdgeEnd.VertexGeometry, unit_scale)
            if start and end:
                return transform_vectors(
                    [start, end], get_item_transformation(member, unit_scale)
                )
    return []


def get_transformation(placement, length_scale: float = 1.0):
    """
    Get the transformation an IFC placement stands for.

    The whole chain of ``PlacementRelTo`` is followed, so the result takes the
    item's own coordinates to the global ones.

    Args:
        placement: The IFC placement object
        length_scale: Factor from the file's length unit to metres. The
            offset is returned in metres, so apply the transformation to
            coordinates that are in metres already (or leave this at 1.0 and
            scale afterwards).

    Returns:
        Dictionary with location and rotation matrix, or None if identity transform

    Raises:
        ModelExtractionError: If the placement is not an IfcLocalPlacement or
            cannot be read.
    """
    if not placement:
        return None

    try:
        if not placement.is_a("IfcLocalPlacement"):
            raise ModelExtractionError(
                f"Its placement is an {placement.is_a()}; only "
                "IfcLocalPlacement is supported."
            )

        import ifcopenshell.util.placement

        # Parallel axes divide by zero in there; that is reported below
        with np.errstate(invalid="ignore", divide="ignore"):
            matrix = np.array(
                ifcopenshell.util.placement.get_local_placement(placement),
                dtype=float,
            )
        if not np.all(np.isfinite(matrix)):
            raise ModelExtractionError(
                "The axes of its placement cannot be read (Axis and "
                "RefDirection are parallel)."
            )
        if np.allclose(matrix, np.eye(4)):
            return None
        return {
            "location": matrix[:3, 3] * length_scale,
            "rotationMatrix": matrix[:3, :3],
        }
    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(f"Error getting transformation: {e}") from e


def get_item_transformation(item, length_scale: float = 1.0):
    """
    Get the transformation of a structural item's or activity's ObjectPlacement.

    Everything an item gives (the points of its representation, its ``Axis``,
    its ``ConditionCoordinateSystem``, the forces of a load in "global"
    coordinates) is in the axes of that placement, not in the global ones.

    Args:
        item: An IfcStructuralItem or IfcStructuralActivity (or None)
        length_scale: Factor from the file's length unit to metres

    Returns:
        As ``get_transformation``; None when there is nothing to apply.
    """
    return get_transformation(getattr(item, "ObjectPlacement", None), length_scale)


def transform_vectors(geometry, transformation, include_translation=True):
    """
    Transform vectors.

    Args:
        geometry: The geometry to transform (point or list of points)
        transformation: The transformation to apply
        include_translation: Whether to include translation

    Returns:
        Transformed geometry
    """
    if not transformation:
        return geometry

    try:
        result = []
        for p in geometry:
            # Make sure p is a numpy array
            p_array = np.array(p)
            # Apply rotation
            transformed = transformation["rotationMatrix"].dot(p_array)
            # Add translation if needed
            if include_translation:
                transformed += transformation["location"]
            result.append(transformed.tolist())
        return result

    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(f"Error transforming vectors: {e}") from e


def get_0D_orientation(axes):
    """
    Get the orientation for a 0D element.

    Args:
        axes: The coordinate system

    Returns:
        List of orientation vectors or None
    """
    if axes and axes.Axis and axes.RefDirection:
        xAxis = np.array(axes.RefDirection.DirectionRatios)
        zAxis = np.array(axes.Axis.DirectionRatios)
        zAxis /= np.linalg.norm(zAxis)
        yAxis = np.cross(zAxis, xAxis)
        yAxis /= np.linalg.norm(yAxis)
        xAxis = np.cross(yAxis, zAxis)
        xAxis /= np.linalg.norm(xAxis)

        return [xAxis.tolist(), yAxis.tolist(), zAxis.tolist()]
    else:
        return None  # Return None to copy the element's orientation


def get_1D_orientation(geometry, zAxis):
    """
    Get the orientation for a 1D element with robust null checking.

    Args:
        geometry: The geometry of the element
        zAxis: The Z axis direction (IFC entity with DirectionRatios attribute)

    Returns:
        List of orientation vectors or None if input is invalid
    """
    # Validate inputs
    if not geometry or len(geometry) < 2:
        logger.warning("Invalid geometry for 1D orientation calculation")
        return None

    if not zAxis:
        logger.warning("No zAxis provided for 1D orientation calculation")
        return None

    try:
        # Extract direction ratios safely
        direction_ratios = None
        if hasattr(zAxis, "DirectionRatios"):
            direction_ratios = zAxis.DirectionRatios
        else:
            logger.warning("zAxis does not have DirectionRatios attribute")
            return None

        # Check if direction_ratios is None or empty
        if direction_ratios is None:
            logger.warning("DirectionRatios is None")
            return None

        # Convert to numpy array and validate
        try:
            z_direction = np.array(direction_ratios, dtype=float)
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid DirectionRatios: {direction_ratios}, error: {e}")
            return None

        # Validate that we have numeric values
        if np.any(np.isnan(z_direction)) or np.any(np.isinf(z_direction)):
            logger.warning(f"Invalid DirectionRatios contain NaN or inf: {z_direction}")
            return None

        # Calculate x-axis from geometry
        try:
            point1 = np.array(geometry[0], dtype=float)
            point2 = np.array(geometry[1], dtype=float)

            # Check for None values in geometry points
            if np.any(np.isnan(point1)) or np.any(np.isnan(point2)):
                logger.warning("Geometry points contain NaN values")
                return None

            xAxis = point2 - point1
            x_norm = np.linalg.norm(xAxis)

            if x_norm < 1e-10:
                logger.warning("Geometry points are too close together")
                return None

            xAxis = xAxis / x_norm
        except (ValueError, TypeError, IndexError) as e:
            logger.warning(f"Error processing geometry points: {e}")
            return None

        # Normalize z-axis
        z_norm = np.linalg.norm(z_direction)
        if z_norm < 1e-10:
            logger.warning("Z direction vector is too small")
            return None

        zAxis_normalized = z_direction / z_norm

        # Calculate y-axis using cross product
        try:
            yAxis = np.cross(zAxis_normalized, xAxis)
            y_norm = np.linalg.norm(yAxis)

            if y_norm < 1e-10:
                logger.warning(
                    "X and Z axes are parallel, cannot form orthogonal system"
                )
                return None

            yAxis = yAxis / y_norm

            # Recalculate z-axis to ensure orthogonality
            zAxis_final = np.cross(xAxis, yAxis)
            z_final_norm = np.linalg.norm(zAxis_final)

            if z_final_norm < 1e-10:
                logger.warning("Cannot form orthogonal coordinate system")
                return None

            zAxis_final = zAxis_final / z_final_norm

            return [xAxis.tolist(), yAxis.tolist(), zAxis_final.tolist()]

        except ModelExtractionError:
            raise
        except Exception as e:
            raise ModelExtractionError(
                f"Unexpected error in cross product calculation: {e}"
            ) from e

    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(
            f"Unexpected error in 1D orientation calculation: {e}"
        ) from e


def get_2D_orientation(representation):
    """
    Get the orientation for a 2D element.

    Args:
        representation: The representation of the element

    Returns:
        List of orientation vectors
    """
    if not representation or not representation.Items:
        return np.eye(3).tolist()

    item = representation.Items[0]
    if item.is_a("IfcFaceSurface"):
        sameSense = item.SameSense
        axes = item.FaceSurface.Position
        orientation = get_0D_orientation(axes)
        if orientation and not sameSense:
            orientation = [[-v for v in vec] for vec in orientation]
        return orientation
    return np.eye(3).tolist()


def analyze_connection_type(connection: Optional[ifcopenshell.entity_instance]) -> str:
    """
    Determine the type of a structural connection (rigid, hinge, etc.).

    Args:
        connection (Optional[ifcopenshell.entity_instance]): IFC connection entity

    Returns:
        str: Connection type ("point", "rigid", or "hinge")
    """
    if connection is None:
        return "point"

    try:
        if not is_structural_connection(connection):
            return "point"

        if hasattr(connection, "AppliedCondition") and connection.AppliedCondition:
            condition = connection.AppliedCondition

            # Check for rotational freedom to identify hinges
            has_rotational_freedom = False

            for attr_name in [
                "RotationalStiffnessX",
                "RotationalStiffnessY",
                "RotationalStiffnessZ",
            ]:
                if hasattr(condition, attr_name):
                    attr_value = getattr(condition, attr_name)
                    if attr_value is not None:
                        # Check if attribute has a numeric value attribute
                        if hasattr(attr_value, "wrappedValue"):
                            # A value of 0 indicates a free rotation
                            if attr_value.wrappedValue == 0:
                                has_rotational_freedom = True
                                break
                        # Sometimes the value is set directly
                        elif attr_value == 0:
                            has_rotational_freedom = True
                            break

            if has_rotational_freedom:
                return "hinge"
            else:
                return "rigid"

        # Default types based on connection entity type
        if connection.is_a("IfcStructuralPointConnection"):
            return "point"
        elif connection.is_a("IfcStructuralCurveConnection"):
            return "rigid"  # Default for curve connections
        elif connection.is_a("IfcStructuralSurfaceConnection"):
            return "rigid"  # Default for surface connections

        return "point"  # Default fallback

    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(f"Error analyzing connection type: {e}") from e


def _ifc_stiffness_to_float(
    raw_value, convert_fn, force_scale: float, unit_scale: float
) -> float:
    """
    Convert an IFC stiffness value (numeric or IfcBoolean) to SI float.

    ``IfcBoundaryNodeCondition`` allows stiffness attributes to be either a
    numeric measure *or* an ``IfcBoolean``:
      - ``True``  → rigid/fixed  → treat as effectively infinite stiffness (1e20)
      - ``False`` → free/released → treat as 0.0
      - numeric   → apply the supplied unit-conversion function normally
    """
    if isinstance(raw_value, bool):
        return 1e20 if raw_value else 0.0
    return convert_fn(raw_value, force_scale, unit_scale)


def get_connection_input(
    connection, geometryType, unit_scale: float = 1.0, force_scale: float = 1.0
):
    """
    Extract connection input properties.

    Args:
        connection: The connection entity
        geometryType: Type of geometry ("point", "line", "surface")
        unit_scale: Scale factor to convert length to SI units
        force_scale: Scale factor to convert force to SI units

    Returns:
        Dictionary of connection properties with values in SI units, or None
    """
    if not connection.AppliedCondition:
        return None

    try:
        from ..utils.units import convert_linear_stiffness, convert_rotational_stiffness

        if geometryType == "point":
            if hasattr(connection.AppliedCondition, "TranslationalStiffnessX"):
                dx = connection.AppliedCondition.TranslationalStiffnessX.wrappedValue
                dx = _ifc_stiffness_to_float(
                    dx, convert_linear_stiffness, force_scale, unit_scale
                )
            else:
                dx = 0.0

            if hasattr(connection.AppliedCondition, "TranslationalStiffnessY"):
                dy = connection.AppliedCondition.TranslationalStiffnessY.wrappedValue
                dy = _ifc_stiffness_to_float(
                    dy, convert_linear_stiffness, force_scale, unit_scale
                )
            else:
                dy = 0.0

            if hasattr(connection.AppliedCondition, "TranslationalStiffnessZ"):
                dz = connection.AppliedCondition.TranslationalStiffnessZ.wrappedValue
                dz = _ifc_stiffness_to_float(
                    dz, convert_linear_stiffness, force_scale, unit_scale
                )
            else:
                dz = 0.0

            if hasattr(connection.AppliedCondition, "RotationalStiffnessX"):
                drx = connection.AppliedCondition.RotationalStiffnessX.wrappedValue
                drx = _ifc_stiffness_to_float(
                    drx, convert_rotational_stiffness, force_scale, unit_scale
                )
            else:
                drx = 0.0

            if hasattr(connection.AppliedCondition, "RotationalStiffnessY"):
                dry = connection.AppliedCondition.RotationalStiffnessY.wrappedValue
                dry = _ifc_stiffness_to_float(
                    dry, convert_rotational_stiffness, force_scale, unit_scale
                )
            else:
                dry = 0.0

            if hasattr(connection.AppliedCondition, "RotationalStiffnessZ"):
                drz = connection.AppliedCondition.RotationalStiffnessZ.wrappedValue
                drz = _ifc_stiffness_to_float(
                    drz, convert_rotational_stiffness, force_scale, unit_scale
                )
            else:
                drz = 0.0

            return {"dx": dx, "dy": dy, "dz": dz, "drx": drx, "dry": dry, "drz": drz}

        if geometryType == "line":
            if hasattr(connection.AppliedCondition, "TranslationalStiffnessByLengthX"):
                dx = (
                    connection.AppliedCondition.TranslationalStiffnessByLengthX.wrappedValue
                )
                dx = _ifc_stiffness_to_float(
                    dx, convert_linear_stiffness, force_scale, unit_scale
                )
            else:
                dx = 0.0

            if hasattr(connection.AppliedCondition, "TranslationalStiffnessByLengthY"):
                dy = (
                    connection.AppliedCondition.TranslationalStiffnessByLengthY.wrappedValue
                )
                dy = _ifc_stiffness_to_float(
                    dy, convert_linear_stiffness, force_scale, unit_scale
                )
            else:
                dy = 0.0

            if hasattr(connection.AppliedCondition, "TranslationalStiffnessByLengthZ"):
                dz = (
                    connection.AppliedCondition.TranslationalStiffnessByLengthZ.wrappedValue
                )
                dz = _ifc_stiffness_to_float(
                    dz, convert_linear_stiffness, force_scale, unit_scale
                )
            else:
                dz = 0.0

            if hasattr(connection.AppliedCondition, "RotationalStiffnessByLengthX"):
                drx = (
                    connection.AppliedCondition.RotationalStiffnessByLengthX.wrappedValue
                )
                drx = _ifc_stiffness_to_float(
                    drx, convert_rotational_stiffness, force_scale, unit_scale
                )
            else:
                drx = 0.0

            if hasattr(connection.AppliedCondition, "RotationalStiffnessByLengthY"):
                dry = (
                    connection.AppliedCondition.RotationalStiffnessByLengthY.wrappedValue
                )
                dry = _ifc_stiffness_to_float(
                    dry, convert_rotational_stiffness, force_scale, unit_scale
                )
            else:
                dry = 0.0

            if hasattr(connection.AppliedCondition, "RotationalStiffnessByLengthZ"):
                drz = (
                    connection.AppliedCondition.RotationalStiffnessByLengthZ.wrappedValue
                )
                drz = _ifc_stiffness_to_float(
                    drz, convert_rotational_stiffness, force_scale, unit_scale
                )
            else:
                drz = 0.0

            return {"dx": dx, "dy": dy, "dz": dz, "drx": drx, "dry": dry, "drz": drz}

        if geometryType == "surface":
            if hasattr(connection.AppliedCondition, "TranslationalStiffnessByAreaX"):
                dx = (
                    connection.AppliedCondition.TranslationalStiffnessByAreaX.wrappedValue
                )
                dx = _ifc_stiffness_to_float(
                    dx, convert_linear_stiffness, force_scale, unit_scale
                )
            else:
                dx = 0.0

            if hasattr(connection.AppliedCondition, "TranslationalStiffnessByAreaY"):
                dy = (
                    connection.AppliedCondition.TranslationalStiffnessByAreaY.wrappedValue
                )
                dy = _ifc_stiffness_to_float(
                    dy, convert_linear_stiffness, force_scale, unit_scale
                )
            else:
                dy = 0.0

            if hasattr(connection.AppliedCondition, "TranslationalStiffnessByAreaZ"):
                dz = (
                    connection.AppliedCondition.TranslationalStiffnessByAreaZ.wrappedValue
                )
                dz = _ifc_stiffness_to_float(
                    dz, convert_linear_stiffness, force_scale, unit_scale
                )
            else:
                dz = 0.0
            return {"dx": dx, "dy": dy, "dz": dz}

    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(f"Error extracting connection input: {e}") from e

    return None
