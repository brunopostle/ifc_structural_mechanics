"""
Entity identification and relationship navigation utilities for IFC structural analysis.

This module provides functions to identify and extract information about
structural analysis-related IFC entities.
"""

import logging
import math
from typing import Dict, List, Optional, Set

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


def face_loops(face, unit_scale: float = 1.0) -> tuple:
    """The corners of the outer bound of an ``IfcFace`` and of its other bounds.

    Args:
        face: The IfcFace.
        unit_scale: Scale factor to convert to SI units.

    Returns:
        (outline, holes): a list of corners and a list of lists of them, each
        in the sense of its bound.

    Raises:
        ValueError: If the face has no bound, no one bound is its outer one, a
            corner has no coordinates, or a bound is neither a list of edges
            nor a polygon. The caller raises its own stage's error with this
            message.
    """
    bounds = list(face.Bounds or [])
    if not bounds:
        raise ValueError("Its face has no bound.")
    outer = [bound for bound in bounds if bound.is_a("IfcFaceOuterBound")]
    if len(bounds) == 1:
        outer = bounds
    if len(outer) != 1:
        raise ValueError(
            f"Its face has {len(bounds)} bounds and {len(outer)} marked as the "
            "outer one (IfcFaceOuterBound), so its outline cannot be told from "
            "its openings."
        )

    def corners(bound) -> list:
        loop = bound.Bound
        if loop.is_a("IfcEdgeLoop"):
            points = []
            for edge in loop.EdgeList:
                element = edge.EdgeElement if edge.is_a("IfcOrientedEdge") else edge
                forward = getattr(edge, "Orientation", True)
                vertex = element.EdgeStart if forward else element.EdgeEnd
                points.append(get_coordinate(vertex.VertexGeometry, unit_scale))
        elif loop.is_a("IfcPolyLoop"):
            points = [get_coordinate(point, unit_scale) for point in loop.Polygon]
        else:
            raise ValueError(
                f"The bound of its face is an {loop.is_a()}, which is not supported."
            )
        if any(point is None for point in points):
            raise ValueError("A corner of its face has no coordinates.")
        if not bound.Orientation:
            points = points[::-1]
        return [list(point) for point in points]

    return corners(outer[0]), [corners(b) for b in bounds if b is not outer[0]]


#: How far, in metres, a corner of a face may be from its plane
FACE_PLANE_TOLERANCE = 1e-3


def implied_face_axes(corners) -> tuple:
    """The axes of the plane through a face's corners, for an ``IfcFace``.

    IFC wants an ``IfcFaceSurface`` for a structural surface item, whose
    plane gives its axes; a plain ``IfcFace`` has none. Its corners give
    the plane, the right-hand winding of its outer bound gives z (the sense
    the topology has), and x is what ``IfcAxis2Placement3D`` implies when
    only its ``Axis`` is given: global x, or global y when z is along x,
    made square to z.

    Args:
        corners: The outer bound's corners in its own sense, in metres, in
            the axes the face is given in.

    Returns:
        (x, z): unit vectors in those axes.

    Raises:
        ValueError: If the face has no area or is not plane. The caller
            raises its own stage's error with this message.
    """
    points = np.array(corners, dtype=float)
    normal = np.zeros(3)
    for i in range(len(points)):
        normal += np.cross(points[i], points[(i + 1) % len(points)])
    length = float(np.linalg.norm(normal))
    if len(points) < 3 or length < 1e-12:
        raise ValueError("Its face has no area.")
    z_axis = normal / length
    off = float(np.abs((points - points.mean(axis=0)) @ z_axis).max())
    if off > FACE_PLANE_TOLERANCE:
        raise ValueError(
            f"Its face is an IfcFace with no surface and is not plane (a corner "
            f"is {off:.3g} m off the plane of the others). Give it an "
            "IfcFaceSurface on an IfcPlane."
        )
    x_axis = np.array([1.0, 0.0, 0.0])
    if abs(z_axis @ x_axis) > 1.0 - 1e-9:
        x_axis = np.array([0.0, 1.0, 0.0])
    x_axis = x_axis - (x_axis @ z_axis) * z_axis
    return x_axis / np.linalg.norm(x_axis), z_axis


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


# An edge shorter than this has no length: nothing structural is a hundredth
# of a millimetre long, and the mesh merges points closer than it
MIN_EDGE_LENGTH = 1e-5


def missing_edge_message(element, item: str) -> str:
    """What to say of a curve member or connection with no edge (94g.28).

    Names the representations it has, so a user can see what was written in
    the edge's place (Bonsai can leave a Body and an Axis only).
    """
    found = [
        f"{rep.RepresentationIdentifier or 'no identifier'}/"
        f"{rep.RepresentationType or 'no type'}"
        for rep in (
            getattr(getattr(element, "Representation", None), "Representations", None)
            or []
        )
    ]
    has = (
        f"Its representations are {', '.join(found)}"
        if found
        else "It has no representation"
    )
    return (
        f"It has no edge representation. {has}; it needs an "
        "IfcTopologyRepresentation 'Reference' of type 'Edge' holding an IfcEdge "
        f"whose vertices are the ends of the {item}."
    )


def edge_without_length(start, end, item: str) -> Optional[str]:
    """What to say of an edge whose ends are one point, or None if it has length.

    Such an edge once got past extraction and stopped the mesh with "Start and
    end points of line should be different" (94g.28).

    Args:
        start: Its first end, in metres and global coordinates
        end: Its other end, likewise
        item: "member" or "connection", for the message
    """
    length = math.dist(start, end)
    if length >= MIN_EDGE_LENGTH:
        return None
    where = ", ".join(f"{value:.6g}" for value in start)
    return (
        f"Its edge has no length: both ends are at ({where}) m, {length:.3g} m "
        f"apart. Give it an IfcEdge from one end of the {item} to the other."
    )


def _unset_stiffness_message(condition, unset: List[str], ifc2x3: bool) -> str:
    """What to say of a boundary condition with values left unset (94g.31).

    IFC gives an unset value no meaning, so it is neither free nor fixed.
    """
    how = (
        "a stiffness, 0 for free or -1 for fixed"
        if ifc2x3
        else "IfcBoolean false for free, true for fixed, or a stiffness"
    )
    return (
        f"Its {condition.is_a()} gives no {', '.join(unset)}. IFC does not say "
        f"what an unset value means: set each to {how}."
    )


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

    # Last, a topology representation that does not say its type (RFEM writes
    # $ for both identifier and type): its items say it
    item_class = _TOPOLOGY_ITEMS.get(rep_type)
    for representation in element.Representation.Representations:
        if (
            item_class
            and representation.is_a("IfcTopologyRepresentation")
            and not representation.RepresentationType
            and representation.Items
            and all(item.is_a(item_class) for item in representation.Items)
        ):
            return representation

    return None


# The topological item of each type of IfcTopologyRepresentation that
# get_representation() is asked for
_TOPOLOGY_ITEMS = {"Vertex": "IfcVertex", "Edge": "IfcEdge", "Face": "IfcFace"}


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

    A structural item with no ObjectPlacement is in the axes of its analysis
    model's ``SharedPlacement``, which IFC says "shall be common to all items"
    of the model: RFEM places its curve members and connections there, with Z
    down, and its surface members nowhere (``unplaced_items()``, W-IFC-007).

    Returns:
        As ``get_transformation``; None when there is nothing to apply.

    Raises:
        ModelExtractionError: If an unplaced item is in several analysis
            models whose SharedPlacements differ.
    """
    if item is None:
        return None
    placement = getattr(item, "ObjectPlacement", None)
    if placement is None and item.is_a("IfcStructuralItem"):
        placement = shared_placement_of(item)
    return get_transformation(placement, length_scale)


def shared_placement_of(item):
    """The SharedPlacement of the analysis models a structural item is in.

    Returns:
        The placement, or None if the item is in no model or its models have
        none (IFC2X3).

    Raises:
        ModelExtractionError: If its models have different SharedPlacements.
    """
    placements = []
    for rel in getattr(item, "HasAssignments", None) or []:
        if rel.is_a("IfcRelAssignsToGroup") and rel.RelatingGroup.is_a(
            "IfcStructuralAnalysisModel"
        ):
            placement = getattr(rel.RelatingGroup, "SharedPlacement", None)
            if placement is not None and placement not in placements:
                placements.append(placement)
    if len(placements) > 1:
        matrices = [_placement_matrix(placement) for placement in placements]
        if any(not np.allclose(m, matrices[0]) for m in matrices[1:]):
            raise ModelExtractionError(
                "It has no ObjectPlacement and is in several analysis models "
                "whose SharedPlacements differ, so its coordinates could be in "
                "the axes of either. Give it an ObjectPlacement.",
                code="E-IFC-006",
            )
    return placements[0] if placements else None


def unplaced_items(ifc_file) -> List:
    """The structural items with no ObjectPlacement that their model places.

    Those whose model's SharedPlacement is the identity are not listed: the
    placement changes nothing for them.
    """
    found = []
    for item in ifc_file.by_type("IfcStructuralItem"):
        if getattr(item, "ObjectPlacement", None) is not None:
            continue
        placement = shared_placement_of(item)
        if placement is not None and not np.allclose(
            _placement_matrix(placement), np.eye(4)
        ):
            found.append(item)
    return found


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
    connection,
    geometryType,
    unit_scale: float = 1.0,
    force_scale: float = 1.0,
    unit_scales: Optional[Dict[str, float]] = None,
    undeclared_units: Optional[Set[str]] = None,
):
    """
    Extract connection input properties.

    Args:
        connection: The connection entity
        geometryType: Type of geometry ("point", "line", "surface")
        unit_scale: Scale factor to convert length to SI units
        force_scale: Scale factor to convert force to SI units
        unit_scales: The scales of the units the file declares; a stiffness
            whose unit it does not declare is made of length and force
        undeclared_units: If given, gets the unit types the file does not
            declare in which a stiffness that depends on the length unit was
            read (a number other than zero; 94g.32)

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
    units = {
        "point": ("LINEARSTIFFNESSUNIT", "ROTATIONALSTIFFNESSUNIT"),
        "line": (
            "MODULUSOFLINEARSUBGRADEREACTIONUNIT",
            "MODULUSOFROTATIONALSUBGRADEREACTIONUNIT",
        ),
        "surface": ("MODULUSOFSUBGRADEREACTIONUNIT", None),
    }
    if geometryType not in names:
        return None
    try:
        condition = connection.AppliedCondition
        # IFC2X3 calls translations "Linear", has numbers only and -1 for rigid;
        # IFC4 forbids that -1, where a negative stiffness is a real one
        ifc2x3 = condition.file.schema == "IFC2X3"
        # Every value left unset, so that one message names them all
        unset = []
        for template in names[geometryType]:
            for axis in "XYZ" if template else "":
                attribute = template.format(axis)
                if ifc2x3:
                    attribute = attribute.replace("Translational", "Linear")
                if getattr(condition, attribute, False) is None:
                    unset.append(attribute)
        if unset:
            raise ModelExtractionError(
                _unset_stiffness_message(condition, unset, ifc2x3),
                code="E-SUP-007",
            )
        result = {}
        for kind, (template, power, unit) in enumerate(
            zip(names[geometryType], length_powers[geometryType], units[geometryType])
        ):
            declared = (unit_scales or {}).get(unit)
            for axis in "XYZ":
                key = ("d" if kind == 0 else "dr") + axis.lower()
                if template is None:
                    continue
                attribute = template.format(axis)
                if ifc2x3:
                    attribute = attribute.replace("Translational", "Linear")
                if not hasattr(condition, attribute):
                    raise ModelExtractionError(
                        f"Its {condition.is_a()} has no {attribute}, so it is not "
                        f"a condition for a {geometryType} connection.",
                        code="E-SUP-007",
                    )
                value = getattr(condition, attribute)
                value = getattr(value, "wrappedValue", value)
                if (
                    undeclared_units is not None
                    and declared is None
                    and power != 0
                    and not isinstance(value, bool)
                    and not (ifc2x3 and value == -1)
                    and value != 0
                ):
                    undeclared_units.add(unit)
                result[key] = _ifc_stiffness_to_float(
                    True if ifc2x3 and value == -1 else value,
                    lambda v, f, u, p=power, d=declared: (
                        v * d if d is not None else v * f * u**p
                    ),
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
