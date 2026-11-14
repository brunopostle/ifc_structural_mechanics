"""Eccentric member ends given only in ``IfcRelConnectsWithEccentricity`` (d36).

A member end that stops short of its joint is drawn so in most files: the
member's edge ends where the member does, the connection's vertex is the joint,
and the writer bridges the gap with a rigid link. Some files draw the member
right up to the joint and state the offset only in the relation's
``ConnectionConstraint``: RFEM 6 does. Here the member's end is moved back to
the point the constraint gives, and the writer links it to the joint as it
would a drawn gap.

Writers disagree about ``PointOnRelatingElement``. IFC puts it in the member's
local axes, with the origin at the start of its reference curve (u = 0, the
start vertex of a plain ``IfcEdge``). ifc2ca measures it from the member's
start joint and RFEM from the connection. ifc2ca always draws its gaps, so the
geometry decides there and the constraint is not read. Where the member
reaches the connection, the point is taken from the first of these readings to
put it on the member: IFC's, then the ``EccentricityInX/Y/Z`` of an
``IfcConnectionPointEccentricity`` (from the connection to the member's point,
in the member's axes, as IFC says), then measured from the connection, with
``W-JNT-011``. A point on the member under none of them stops the analysis
(``E-JNT-006``), as does an eccentricity not along the member, of a surface
member, or at a connection that is not a point.

See ``docs/design/connections.md``.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..domain.structural_member import CurveMember, SurfaceMember
from ..utils.error_handling import ModelExtractionError
from ..utils.messages import warning
from .entity_identifier import get_item_transformation, get_representation

# How far a member end may be from its connection and still reach it, and a
# point from a member and still be on it, in metres. Drawn eccentricities are
# 0.1 m and more in every example; coordinates written in single precision are
# a few micrometres out.
_REACH = 1e-4


def apply_eccentricities(ifc_file, model, length_scale: float) -> List[Dict[str, Any]]:
    """Move member ends to the eccentric points their relations give.

    Args:
        ifc_file: The IFC file the model was read from.
        model: The structural model, whose curve members' geometry is changed.
        length_scale: Factor from the file's length unit to metres.

    Returns:
        The warnings to pass on (``W-JNT-011``), one for the whole model.

    Raises:
        ModelExtractionError: ``E-JNT-006`` for an eccentricity that cannot be
            read or analysed.
    """
    from_connection: List[Tuple[str, str]] = []
    for relation in ifc_file.by_type("IfcRelConnectsWithEccentricity"):
        ifc_member = relation.RelatingStructuralMember
        ifc_connection = relation.RelatedStructuralConnection
        member = model.get_member(getattr(ifc_member, "GlobalId", None))
        connection = model.get_connection(getattr(ifc_connection, "GlobalId", None))
        # Not in the model analysed, or a connection that does nothing
        if member is None or connection is None:
            continue
        guids = [ifc_member.GlobalId, ifc_connection.GlobalId, relation.GlobalId]
        try:
            read_from_connection = _apply_one(
                relation, ifc_member, member, connection, length_scale
            )
        except ModelExtractionError as error:
            raise ModelExtractionError(
                f"Member {ifc_member.GlobalId} cannot be joined to connection "
                f"{ifc_connection.GlobalId} as relation {relation.GlobalId} "
                f"says. {error.message}",
                code=error.code,
                ifc_guids=[*guids, *error.ifc_guids],
            ) from error
        if read_from_connection:
            from_connection.append((ifc_member.GlobalId, ifc_connection.GlobalId))

    warnings = _join_surfaces_at_lone_joints(model)
    if not from_connection:
        return warnings
    members = sorted({m for m, _ in from_connection})
    return warnings + [
        warning(
            "W-JNT-011",
            f"{len(from_connection)} member end(s) are eccentric to their "
            f"connection by a PointOnRelatingElement measured from the "
            f"connection, not from the start of the member's reference curve "
            f"as IFC says ({', '.join(members[:3])}"
            f"{', ...' if len(members) > 3 else ''}); measured the IFC way it "
            "lies off the member. They are cut back to that point and joined "
            "to the connection by a rigid link.",
            ifc_guids=sorted({g for pair in from_connection for g in pair}),
        )
    ]


def _join_surfaces_at_lone_joints(model) -> List[Dict[str, Any]]:
    """Join a joint one eccentric member stops short of to the surface it is on.

    A point connection joined to one member that does not reach it leaves the
    rigid link of that member's end nothing to bridge to: the eccentricity
    would do nothing and the member end hang free. Where the connection lies
    on a surface member, the joint is in that surface (a column top framed into
    a slab: RFEM relates the column to the joint and not the slab), and the
    surface is joined to it, rigidly, with ``W-JNT-012``. Only one member: where
    several meet, they are linked to each other already.
    """
    joined: List[Tuple[str, List[str]]] = []
    for connection in model.connections:
        if getattr(connection, "edge", None) is not None:
            continue
        if getattr(connection, "face", None) is not None:
            continue
        members = [model.get_member(m) for m in connection.connected_members]
        if len(members) != 1 or members[0] is None or _touches(members[0], connection):
            continue
        surfaces = [
            m.id
            for m in model.members
            if isinstance(m, SurfaceMember)
            and m.id not in connection.connected_members
            and _touches(m, connection)
        ]
        for surface in surfaces:
            connection.connect_member(surface)
        if surfaces:
            joined.append((connection.id, surfaces))
    if not joined:
        return []
    ids = [c for c, _ in joined]
    surfaces = sorted({s for _, found in joined for s in found})
    return [
        warning(
            "W-JNT-012",
            f"{len(joined)} point connection(s) are joined to one member that "
            f"stops short of them and to nothing else, and lie on a surface "
            f"member ({', '.join(ids[:3])}{', ...' if len(ids) > 3 else ''}); "
            f"they are joined rigidly to that surface member "
            f"({', '.join(surfaces[:3])}{', ...' if len(surfaces) > 3 else ''}), "
            "and the member's end to them by a rigid link.",
            ifc_guids=[*ids, *surfaces],
        )
    ]


def _apply_one(relation, ifc_member, member, connection, length_scale) -> bool:
    """Move one member end; whether its point was measured from the connection."""
    constraint = relation.ConnectionConstraint
    is_point = (
        getattr(connection, "edge", None) is None
        and getattr(connection, "face", None) is None
    )
    if isinstance(member, CurveMember) and is_point:
        return _apply_to_curve_member(
            constraint, ifc_member, member, connection, length_scale
        )

    # What is not read must at least be drawn
    if not _touches(member, connection):
        return False
    if _states_no_offset(constraint):
        return False
    kind = "a surface member" if isinstance(member, SurfaceMember) else "this member"
    raise ModelExtractionError(
        f"The member reaches the connection, and the eccentricity of "
        f"{kind} at a {'point' if is_point else 'line or surface'} connection "
        f"({constraint.is_a()}) is not read. Draw the member where it is, "
        "apart from the connection.",
        code="E-JNT-006",
    )


def _apply_to_curve_member(
    constraint, ifc_member, member, connection, length_scale
) -> bool:
    """Cut a curve member's end back to its eccentric point; see the module."""
    if not constraint.is_a("IfcConnectionPointGeometry"):
        if not _touches(member, connection):
            return False
        raise ModelExtractionError(
            f"Its ConnectionConstraint is an {constraint.is_a()}, not an "
            "IfcConnectionPointGeometry, at a point connection.",
            code="E-JNT-006",
        )
    start, end = (
        np.array(p, dtype=float) for p in (member.geometry[0], member.geometry[-1])
    )
    joint = np.array(connection.position, dtype=float)
    length = float(np.linalg.norm(end - start))
    reach = _REACH + 1e-6 * length
    at_start = np.linalg.norm(joint - start) <= reach
    at_end = np.linalg.norm(joint - end) <= reach
    if not (at_start or at_end):
        if _distance_to_segment(joint, start, end) > reach:
            return False  # drawn apart: the geometry is the eccentricity
        readings = _readings(constraint, ifc_member, member, joint, length_scale)
        if any(
            point is not None and np.linalg.norm(point - joint) <= reach
            for point, _ in readings
        ):
            return False
        raise ModelExtractionError(
            "The connection lies along the member's span, and an eccentric "
            "joint there is not analysed. Draw the member where it is, apart "
            "from the connection.",
            code="E-JNT-006",
        )

    axis = (end - start) / length
    for point, from_connection in _readings(
        constraint, ifc_member, member, joint, length_scale
    ):
        if point is None:
            continue
        along = float((point - start) @ axis)
        off = float(np.linalg.norm(point - start - along * axis))
        if off > reach or along < -reach or along > length + reach:
            continue
        if np.linalg.norm(point - joint) <= reach:
            return False  # no eccentricity
        # The other end must stay where it is, with the member in between
        if (at_end and along <= reach) or (at_start and along >= length - reach):
            continue
        index = len(member.geometry) - 1 if at_end else 0
        member.geometry[index] = [float(v) for v in point]
        return from_connection
    raise ModelExtractionError(
        "The point its ConnectionConstraint gives lies off the member however "
        "PointOnRelatingElement is read (in the member's axes from the start "
        "of its reference curve, as IFC says, or from the connection), and "
        "an eccentricity across a member is not analysed. Draw the member "
        "where it is, apart from the connection.",
        code="E-JNT-006",
    )


def _readings(
    constraint, ifc_member, member, joint, length_scale
) -> List[Tuple[Optional[np.ndarray], bool]]:
    """The member points a point constraint can mean, in the order tried.

    Each is (global point in metres or None, whether measured from the
    connection).
    """
    transformation = get_item_transformation(ifc_member, length_scale)
    rotation = transformation["rotationMatrix"] if transformation else np.eye(3)

    def placed(point):
        point = np.array(point, dtype=float)
        if transformation:
            point = rotation @ point + transformation["location"]
        return point

    origin, x_axis = _curve_origin(ifc_member, member, length_scale, placed)
    axes = _member_axes(ifc_member, x_axis, rotation)
    relating = _coordinates(constraint.PointOnRelatingElement) * length_scale
    related = constraint.PointOnRelatedElement
    readings: List[Tuple[Optional[np.ndarray], bool]] = []
    readings.append((_in_axes(origin, axes, relating), False))
    # Only eccentricities that state an offset: unset or zero ones would say
    # there is none, which the point does not
    stated = constraint.is_a("IfcConnectionPointEccentricity") and any(
        getattr(constraint, f"EccentricityIn{c}", None) for c in "XYZ"
    )
    if stated:
        offsets = [
            getattr(constraint, f"EccentricityIn{c}", None) or 0.0 for c in "XYZ"
        ]
        offset = np.array(offsets, dtype=float) * length_scale
        readings.append((_in_axes(joint, axes, offset), False))
    # Nor from the connection where they do: a zero point read so would say
    # there is none
    if not stated and (related is None or not np.any(_coordinates(related))):
        readings.append((_in_axes(joint, axes, relating), True))
    return readings


def _curve_origin(ifc_member, member, length_scale, placed):
    """The origin and x direction of a curve member's local axes, global.

    The u = 0 point of its reference curve: the start vertex of a plain
    ``IfcEdge``, the ``Pnt`` of an ``IfcLine``. None for curves of other kinds,
    whose parametrisation is not read.
    """
    start, end = (
        np.array(p, dtype=float) for p in (member.geometry[0], member.geometry[-1])
    )
    representation = get_representation(ifc_member, "Edge")
    item = representation.Items[0] if representation else None
    if item is not None and item.is_a("IfcOrientedEdge"):
        item = item.EdgeElement
    curve = getattr(item, "EdgeGeometry", None) if item is not None else None
    if curve is None:
        return start, (end - start) / np.linalg.norm(end - start)
    if curve.is_a("IfcLine"):
        origin = placed(_coordinates(curve.Pnt) * length_scale)
        direction = placed(curve.Dir.Orientation.DirectionRatios) - placed(
            [0.0, 0.0, 0.0]
        )
        return origin, direction / np.linalg.norm(direction)
    return None, (end - start) / np.linalg.norm(end - start)


def _member_axes(ifc_member, x_axis, rotation) -> Optional[np.ndarray]:
    """The columns x, y, z of a curve member's local axes; z from ``Axis``.

    Only x when it has no usable Axis: y and z are then NaN, and a reading
    with a component across the member is not on it.
    """
    axes = np.full((3, 3), np.nan)
    axes[:, 0] = x_axis
    axis = getattr(ifc_member, "Axis", None)
    if axis is None:
        return axes
    z = rotation @ np.array(axis.DirectionRatios, dtype=float)
    z = z - (z @ x_axis) * x_axis
    if np.linalg.norm(z) < 1e-9:
        return axes
    z /= np.linalg.norm(z)
    axes[:, 2] = z
    axes[:, 1] = np.cross(z, x_axis)
    return axes


def _in_axes(origin, axes, local) -> Optional[np.ndarray]:
    """A point given in local axes from an origin, global; None if unknown."""
    if origin is None:
        return None
    result = np.array(origin, dtype=float)
    for i in range(3):
        if local[i] != 0.0:
            result = result + local[i] * axes[:, i]
    if not np.all(np.isfinite(result)):
        return None
    return result


def _coordinates(point) -> np.ndarray:
    """The coordinates of an IfcCartesianPoint or IfcVertexPoint, padded to 3."""
    if point.is_a("IfcVertexPoint"):
        point = point.VertexGeometry
    if not point.is_a("IfcCartesianPoint"):
        raise ModelExtractionError(
            f"A point of its ConnectionConstraint is an {point.is_a()}; only "
            "IfcCartesianPoint and IfcVertexPoint are read.",
            code="E-JNT-006",
        )
    values = [float(v) for v in point.Coordinates]
    return np.array((values + [0.0, 0.0, 0.0])[:3])


def _states_no_offset(constraint) -> bool:
    """Whether a constraint says plainly that there is no eccentricity."""
    if not constraint.is_a("IfcConnectionPointEccentricity"):
        return False
    if constraint.PointOnRelatedElement is not None:
        return False
    return all(not getattr(constraint, f"EccentricityIn{c}", None) for c in "XYZ")


def _touches(member, connection) -> bool:
    """Whether a connection's point or edge lies on a member's reference."""
    edge = getattr(connection, "edge", None)
    points = edge if edge is not None else [connection.position]
    if getattr(connection, "face", None) is not None:
        points = connection.face
    points = [np.array(p, dtype=float) for p in points]
    geometry = [np.array(p, dtype=float) for p in member.geometry]
    if isinstance(member, CurveMember):
        return all(
            _distance_to_segment(p, geometry[0], geometry[-1]) <= _REACH for p in points
        )
    return all(_on_polygon(p, geometry) for p in points)


def _distance_to_segment(point, start, end) -> float:
    """The distance from a point to a straight segment."""
    span = end - start
    t = float(np.clip((point - start) @ span / (span @ span), 0.0, 1.0))
    return float(np.linalg.norm(point - start - t * span))


def _on_polygon(point, corners) -> bool:
    """Whether a point lies in a plane polygon or on its boundary."""
    origin = corners[0]
    normal = np.zeros(3)
    for a, b in zip(corners, corners[1:] + corners[:1]):
        normal += np.cross(a - origin, b - origin)
    if np.linalg.norm(normal) < 1e-12:
        return False
    normal /= np.linalg.norm(normal)
    if abs((point - origin) @ normal) > _REACH:
        return False
    if any(
        _distance_to_segment(point, a, b) <= _REACH
        for a, b in zip(corners, corners[1:] + corners[:1])
    ):
        return True
    u = corners[1] - origin
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    flat = [((c - origin) @ u, (c - origin) @ v) for c in corners]
    x, y = (point - origin) @ u, (point - origin) @ v
    inside = False
    for (x1, y1), (x2, y2) in zip(flat, flat[1:] + flat[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside
