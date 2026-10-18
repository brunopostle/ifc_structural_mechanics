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


def _unreadable(entity, what: str, error: Exception) -> str:
    """The message of an E-IFC-005: which entity, what was being read, why."""
    if isinstance(entity, ifcopenshell.entity_instance):
        name = f"#{entity.id()} {entity.is_a()}"
        guid = getattr(entity, "GlobalId", None)
        if guid:
            name += f" {guid}"
    else:
        name = type(entity).__name__
    return f"{name}: {what} cannot be read. {type(error).__name__}: {error}"


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
            _unreadable(entity, "whether it is a structural member", e),
            code="E-IFC-005",
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
            _unreadable(entity, "whether it is a structural curve member", e),
            code="E-IFC-005",
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
            _unreadable(entity, "whether it is a structural surface member", e),
            code="E-IFC-005",
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
            _unreadable(entity, "whether it is a structural connection", e),
            code="E-IFC-005",
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
        raise ModelExtractionError(
            _unreadable(point, "its coordinates", e), code="E-IFC-005"
        ) from e


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
        raise ModelExtractionError(
            _unreadable(entity, "the members it connects", e), code="E-IFC-005"
        ) from e


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


def _placement_error(message: str) -> ModelExtractionError:
    return ModelExtractionError(message, code="E-IFC-003")


def _straight_axis(curve):
    """A point and the direction of a straight grid axis curve, in its grid's axes.

    The direction is the curve's own sense. Grid axes are 2D curves; any third
    coordinate is ignored.
    """
    if curve.is_a("IfcLine"):
        point = np.array(curve.Pnt.Coordinates[:2], dtype=float)
        direction = np.array(curve.Dir.Orientation.DirectionRatios[:2], dtype=float)
    elif curve.is_a("IfcPolyline") or curve.is_a("IfcIndexedPolyCurve"):
        if curve.is_a("IfcPolyline"):
            points = [p.Coordinates[:2] for p in curve.Points]
        else:
            if curve.Segments and any(
                segment.is_a("IfcArcIndex") for segment in curve.Segments
            ):
                raise _placement_error(
                    f"Grid axis curve #{curve.id()} has arcs; only straight grid "
                    "axes are supported."
                )
            points = [p[:2] for p in curve.Points.CoordList]
        points = np.array(points, dtype=float)
        point = points[0]
        direction = points[-1] - points[0]
        length = np.linalg.norm(direction)
        if length > 0:
            across = (points - point) @ _left_of(direction / length)
            if np.max(np.abs(across)) > 1e-6 * length:
                raise _placement_error(
                    f"Grid axis curve #{curve.id()} is a polyline that is not "
                    "straight; only straight grid axes are supported."
                )
    elif curve.is_a("IfcTrimmedCurve"):
        point, direction = _straight_axis(curve.BasisCurve)
        if not curve.SenseAgreement:
            direction = -direction
    elif curve.is_a("IfcOffsetCurve2D"):
        point, direction = _straight_axis(curve.BasisCurve)
        point = point + curve.Distance * _left_of(direction)
    else:
        raise _placement_error(
            f"Grid axis curve #{curve.id()} is an {curve.is_a()}; only straight "
            "grid axes are supported."
        )
    length = np.linalg.norm(direction)
    if not length > 0:
        raise _placement_error(f"Grid axis curve #{curve.id()} has no direction.")
    return point, direction / length


def _left_of(direction):
    """The direction turned anticlockwise through 90 degrees, as IFC offsets go."""
    return np.array([-direction[1], direction[0]])


def _grid_of(axis):
    grids = {
        grid.id(): grid
        for attribute in ("PartOfU", "PartOfV", "PartOfW")
        for grid in (getattr(axis, attribute, None) or ())
    }
    if len(grids) != 1:
        raise _placement_error(
            f"Grid axis #{axis.id()} {axis.AxisTag or ''} belongs to "
            f"{len(grids)} grids; it must belong to one."
        )
    return next(iter(grids.values()))


def _virtual_grid_intersection(intersection):
    """Where an IfcVirtualGridIntersection is, in the axes of its grid.

    Returns:
        The grid, the point (x, y, z) and the direction of the first axis
        there.
    """
    axes = list(intersection.IntersectingAxes)
    grids = [_grid_of(axis) for axis in axes]
    if grids[0] != grids[1]:
        raise _placement_error(
            f"Grid intersection #{intersection.id()} joins axes of two grids."
        )
    offsets = list(intersection.OffsetDistances or ())
    lines = []
    for n, axis in enumerate(axes):
        point, direction = _straight_axis(axis.AxisCurve)
        if axis.SameSense is False:
            direction = -direction
        if n < len(offsets):
            # To the left of the axis as it runs, so SameSense turns it over
            point = point + offsets[n] * _left_of(direction)
        lines.append((point, direction))
    (p1, t1), (p2, t2) = lines
    determinant = t1[0] * t2[1] - t1[1] * t2[0]
    if abs(determinant) < 1e-9:
        raise _placement_error(
            f"Grid intersection #{intersection.id()}: the axes "
            f"{axes[0].AxisTag} and {axes[1].AxisTag} are parallel."
        )
    gap = p2 - p1
    along = (gap[0] * t2[1] - gap[1] * t2[0]) / determinant
    point = p1 + along * t1
    height = offsets[2] if len(offsets) > 2 else 0.0
    return grids[0], np.array([point[0], point[1], height]), t1


def _grid_placement_matrix(placement):
    """The matrix of an IfcGridPlacement: a point and a direction on a grid.

    The grid axes lie in the xy plane of the grid's ObjectPlacement, and so
    do the x and y axes of the placement.
    """
    grid, origin, x_axis = _virtual_grid_intersection(placement.PlacementLocation)
    grid_matrix = _placement_matrix(grid.ObjectPlacement)

    # IFC4.3 adds PlacementRelTo, which is to be the grid's placement
    relative_to = getattr(placement, "PlacementRelTo", None)
    if relative_to is not None and not np.allclose(
        _placement_matrix(relative_to), grid_matrix
    ):
        raise _placement_error(
            f"Grid placement #{placement.id()} is placed relative to something "
            "other than the placement of its grid."
        )

    reference = placement.PlacementRefDirection
    if reference is not None:
        if reference.is_a("IfcDirection"):
            # Only x and y count, as the placement lies in the grid's plane
            x_axis = np.array(reference.DirectionRatios[:2], dtype=float)
        else:
            other_grid, other, _ = _virtual_grid_intersection(reference)
            if other_grid != grid:
                raise _placement_error(
                    f"Grid placement #{placement.id()} takes its direction from "
                    "an intersection on another grid."
                )
            x_axis = (other - origin)[:2]
        length = np.linalg.norm(x_axis)
        if not length > 1e-12:
            raise _placement_error(
                f"Grid placement #{placement.id()} has no direction in the "
                "plane of its grid."
            )
        x_axis = x_axis / length

    local = np.eye(4)
    local[:3, 0] = [x_axis[0], x_axis[1], 0.0]
    local[:3, 1] = [-x_axis[1], x_axis[0], 0.0]
    local[:3, 3] = origin
    return grid_matrix @ local


def _placement_matrix(placement):
    """The 4x4 matrix of an object placement and everything it is relative to."""
    import ifcopenshell.util.placement

    if placement is None:
        return np.eye(4)
    if placement.is_a("IfcGridPlacement"):
        return _grid_placement_matrix(placement)
    if not placement.is_a("IfcLocalPlacement"):
        raise _placement_error(
            f"Its placement is an {placement.is_a()}; only IfcLocalPlacement "
            "and IfcGridPlacement are supported."
        )
    parent = _placement_matrix(placement.PlacementRelTo)
    # get_placement() replaced get_axis2placement() in later IfcOpenShell
    # releases; both give the matrix in the file's own units
    parse = getattr(ifcopenshell.util.placement, "get_placement", None)
    if parse is None:
        parse = ifcopenshell.util.placement.get_axis2placement
    return parent @ np.array(parse(placement.RelativePlacement), dtype=float)


def get_transformation(placement, length_scale: float = 1.0):
    """
    Get the transformation an IFC placement stands for.

    The whole chain of ``PlacementRelTo`` is followed, so the result takes the
    item's own coordinates to the global ones. A grid placement is the
    intersection of two straight grid axes, with their offsets, in the axes
    of the grid's own placement.

    Args:
        placement: The IFC placement object
        length_scale: Factor from the file's length unit to metres. The
            offset is returned in metres, so apply the transformation to
            coordinates that are in metres already (or leave this at 1.0 and
            scale afterwards).

    Returns:
        Dictionary with location and rotation matrix, or None if identity transform

    Raises:
        ModelExtractionError: If the placement is neither an IfcLocalPlacement
            nor an IfcGridPlacement on straight axes, or cannot be read.
    """
    if not placement:
        return None

    try:
        # Parallel axes divide by zero in there (NaN), or in later IfcOpenShell
        # releases leave zero axes; either is reported below
        with np.errstate(invalid="ignore", divide="ignore"):
            matrix = _placement_matrix(placement)
        rotation = matrix[:3, :3]
        if not np.all(np.isfinite(matrix)) or not np.allclose(
            rotation.T @ rotation, np.eye(3), atol=1e-6
        ):
            raise ModelExtractionError(
                "The axes of its placement cannot be read (Axis and "
                "RefDirection are parallel).",
                code="E-IFC-003",
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
        raise ModelExtractionError(
            _unreadable(placement, "its placement", e), code="E-IFC-005"
        ) from e


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
        raise ModelExtractionError(
            f"Coordinates cannot be moved by their placement: {type(e).__name__}: {e}",
            code="E-IFC-005",
        ) from e


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
                f"A member's local axes cannot be worked out from its Axis: "
                f"{type(e).__name__}: {e}",
                code="E-IFC-005",
            ) from e

    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(
            f"A member's local axes cannot be worked out from its Axis: "
            f"{type(e).__name__}: {e}",
            code="E-IFC-005",
        ) from e


def analyze_connection_type(connection: Optional[ifcopenshell.entity_instance]) -> str:
    """
    Determine the type of a structural connection from the kind of entity it is.

    Its ``AppliedCondition`` has no say in this. That is what the connection
    holds against the ground; how a member is joined to it is the
    ``AppliedCondition`` of the member's ``IfcRelConnectsStructuralMember``.
    A condition with a free rotation once made the connection a "hinge",
    which released every member meeting at a pinned support: a beam running
    on over it was analysed as two simply supported ones (``aiz.78``).

    Args:
        connection (Optional[ifcopenshell.entity_instance]): IFC connection entity

    Returns:
        str: Connection type ("point" or "rigid")
    """
    if connection is None:
        return "point"

    try:
        if not is_structural_connection(connection):
            return "point"

        if connection.is_a("IfcStructuralPointConnection"):
            return "point"
        elif connection.is_a("IfcStructuralCurveConnection"):
            return "rigid"
        elif connection.is_a("IfcStructuralSurfaceConnection"):
            return "rigid"

        return "point"

    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(
            _unreadable(connection, "what kind of connection it is", e),
            code="E-IFC-005",
        ) from e


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

    # The powers of length in each stiffness: a force over a length at a
    # point, over a length per length along a curve, per area over a surface
    # (a modulus of subgrade reaction); a moment per radian at a point, per
    # length along a curve. Faces have no rotational stiffness.
    names = {
        "point": ("TranslationalStiffness{}", "RotationalStiffness{}"),
        "line": ("TranslationalStiffnessByLength{}", "RotationalStiffnessByLength{}"),
        "surface": ("TranslationalStiffnessByArea{}", None),
    }
    length_powers = {"point": (-1, 1), "line": (-2, 0), "surface": (-3, None)}
    if geometryType not in names:
        return None
    try:
        condition = connection.AppliedCondition
        result = {}
        for kind, (template, power) in enumerate(
            zip(names[geometryType], length_powers[geometryType])
        ):
            for axis in "XYZ":
                key = ("d" if kind == 0 else "dr") + axis.lower()
                if template is None:
                    continue
                attribute = template.format(axis)
                if not hasattr(condition, attribute):
                    result[key] = 0.0
                    continue
                value = getattr(condition, attribute)
                if value is None:
                    raise ModelExtractionError(
                        f"Its {condition.is_a()} gives no {attribute}.",
                        code="E-SUP-007",
                    )
                result[key] = _ifc_stiffness_to_float(
                    getattr(value, "wrappedValue", value),
                    lambda v, f, u, p=power: v * f * u**p,
                    force_scale,
                    unit_scale,
                )
        return result
    except ModelExtractionError:
        raise
    except Exception as e:
        raise ModelExtractionError(
            _unreadable(connection, "its AppliedCondition", e), code="E-IFC-005"
        ) from e
