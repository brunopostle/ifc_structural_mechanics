"""Plane trusses and frames: finding them, and whether they can fall over.

A structure drawn in one plane and loaded in it is usually given the supports
of its two-dimensional textbook picture: nothing holds it out of the plane,
pinned joints leave every bar free to spin, and the analysis in three
dimensions is of a mechanism. Its member forces come out right; its
displacements include whatever the mechanism does.

``plane_normal()`` says whether a model is such a structure, in a plane of
any direction, walls in it included, and ``out_of_plane_freedoms()`` counts
the ways it can move out of its plane without straining. The writer holds a
model that has any (``UnifiedCalculixWriter._hold_plane_structure``).

The count treats every member and every joint as a rigid body out of the
plane, with three movements each: the translation across the plane and the
rotations about two axes in it. A member is tied to each of its joints in
that translation, and a curve member in each of those rotations it is not
released in. A surface member is tied in translation only: what its edge or
corner passes on in rotation is not looked into, which can only make the
count larger. A support ties its joint to the ground in what it restrains.
What is left of the movements after the ties is what nothing holds. Members
that share a mesh node where no connection of the file joins them (a member
ending on the span of another, two that cross) are joined rigidly there, as
the mesh joins them; the writer passes those joints in (``mesh_joints``,
``aiz.81``). Left out, they made the count too large and a frame joined that
way was held in its plane when it stood up on its own.
"""

from typing import List, Optional, Sequence, Tuple, Union

import numpy as np

from ..domain.structural_member import CurveMember, SurfaceMember
from ..domain.structural_model import StructuralModel
from .boundary_condition_handling import (
    _across,
    _global_force_vector,
    _to_global_axes,
    released_rotation_axes,
    share_in_span,
    support_resistance,
)

AXIS_NAMES = ("X", "Y", "Z")
_FLAT = 1e-6

Normal = Union[int, Sequence[float], np.ndarray]


def _member_points(member) -> List[np.ndarray]:
    """The points of a curve member, or the outline of a surface member."""
    geometry = getattr(member, "geometry", None)
    if isinstance(geometry, dict):
        geometry = (geometry.get("boundaries") or [None])[0]
    if not isinstance(geometry, (list, tuple)) or len(geometry) < 2:
        return []
    try:
        points = [np.array([float(v) for v in point]) for point in geometry]
    except (TypeError, ValueError):
        return []
    return [point for point in points if point.shape == (3,)]


def _unit(normal: Normal) -> np.ndarray:
    """A normal given as a global axis or as a direction, as a unit vector."""
    if isinstance(normal, (int, np.integer)):
        return np.eye(3)[int(normal)]
    vector = np.array(normal, dtype=float)
    return vector / np.linalg.norm(vector)


def global_axis(normal: Normal) -> Optional[int]:
    """The global axis (0, 1, 2) a normal is, or None for a skew one."""
    vector = _unit(normal)
    axis = int(np.argmax(np.abs(vector)))
    return axis if abs(abs(float(vector[axis])) - 1.0) <= _FLAT else None


def _snap(vector: np.ndarray) -> np.ndarray:
    """A unit vector, exactly a global axis when it is one to ``_FLAT``,
    and with its largest component positive."""
    vector = vector / np.linalg.norm(vector)
    axis = int(np.argmax(np.abs(vector)))
    if np.abs(np.delete(vector, axis)).max() <= _FLAT:
        return np.eye(3)[axis]
    return vector if vector[axis] > 0 else -vector


def in_plane_axes(normal: Normal) -> np.ndarray:
    """Two orthonormal directions in the plane, as rows.

    The other two global axes, in order, for a plane parallel to them; else
    the horizontal direction in the plane first (X when it is horizontal).
    """
    axis = global_axis(normal)
    if axis is not None:
        return np.delete(np.eye(3), axis, axis=0)
    n = _unit(normal)
    first = np.cross(np.eye(3)[2], n)
    if np.linalg.norm(first) <= _FLAT:
        first = np.cross(n, np.eye(3)[1])
    first = first / np.linalg.norm(first)
    return np.array([first, np.cross(n, first)])


def describe_plane(normal: Normal) -> str:
    """The plane in words: ``parallel to global X and Z``, or its normal."""
    axis = global_axis(normal)
    if axis is not None:
        named = [AXIS_NAMES[i] for i in range(3) if i != axis]
        return f"parallel to global {named[0]} and {named[1]}"
    n = _unit(normal)
    return "across which the normal is ({:.4g}, {:.4g}, {:.4g})".format(
        *(0.0 if abs(v) < 5e-5 else float(v) for v in n)
    )


def _scaled(vectors: List[np.ndarray]) -> List[np.ndarray]:
    """Vectors of one kind divided by the largest of them."""
    largest = max((float(np.linalg.norm(v)) for v in vectors), default=0.0)
    if largest <= 0.0:
        return []
    return [v / largest for v in vectors if np.linalg.norm(v) > _FLAT * largest]


def _one_direction(vectors: List[np.ndarray]) -> Optional[np.ndarray]:
    """The direction all of *vectors* lie along, or None if they do not."""
    if not vectors:
        return None
    _, singular, vh = np.linalg.svd(np.array(vectors), full_matrices=True)
    if len(singular) > 1 and singular[1] > _FLAT * singular[0]:
        return None
    return vh[0]


def plane_normal(
    domain_model: StructuralModel, gravity_direction: Optional[List[float]] = None
) -> Optional[np.ndarray]:
    """The unit normal of the plane of a plane structure.

    A model is a plane structure when all of this holds:

    - its members, curve members and surface members, all lie in one plane;
    - every load acts in that plane, and so does the self-weight a load case
      includes and gravity, when ``gravity_direction`` is given; an applied
      moment is about the normal, and a temperature difference bends in the
      plane (a surface member's, across its thickness, does not);
    - every curve member's section has its own axes in and across the plane;
    - so has every support: what it holds is in the plane or across it.

    A model that lies along a single line is in many such planes; it counts
    as plane when its loads across the line all act along one direction,
    and the plane is the one they act in (or, with no such loads, when its
    applied moments are about one axis across the line, which is the
    normal).

    Returns:
        The normal, exactly a global axis when the plane is parallel to two
        of them, with its largest component positive; or None.
    """
    members = list(domain_model.members)
    if not members or not all(
        isinstance(m, (CurveMember, SurfaceMember)) for m in members
    ):
        return None
    points = [point for member in members for point in _member_points(member)]
    if len(points) < 2:
        return None
    points_array = np.array(points)
    size = float(np.ptp(points_array, axis=0).max())
    if size <= 0:
        return None
    centred = points_array - points_array.mean(axis=0)
    _, _, vh = np.linalg.svd(centred, full_matrices=True)
    flat = [row for row in vh if np.abs(centred @ row).max() <= _FLAT * size]

    # Loads are forces, self-weight is a direction, a support displacement
    # a length and a temperature difference a gradient, which bends its
    # member along it: each kind is judged against its own largest
    forces = []
    weights = []
    moments = []
    shifts = []
    turns = []
    bends = []
    for group in domain_model.load_groups:
        for temperature in getattr(group, "temperature_loads", None) or ():
            gradient = _temperature_gradient(domain_model, temperature)
            if gradient is not None:
                bends.append(gradient)
        for displacement in getattr(group, "support_displacements", None) or ():
            shift = np.array(displacement.translation, dtype=float)
            turn = np.array(displacement.rotation, dtype=float)
            if displacement.coordinate_system == "local":
                connection = domain_model.get_connection(displacement.connection_id)
                axes = getattr(connection, "local_axes", None)
                if axes is not None:
                    axes = np.array(axes, dtype=float)
                    shift, turn = axes.T @ shift, axes.T @ turn
            shifts.append(shift)
            turns.append(turn)
        if getattr(group, "includes_self_weight", False):
            weights.append(np.array(group.self_weight_coefficients, dtype=float))
        for load in group.loads:
            vector = _global_force_vector(load, domain_model)
            if vector is None:
                return None
            forces.append(np.array(vector, dtype=float))
            if getattr(load, "moment", None) is not None:
                moment = _to_global_axes(load, load.moment, domain_model)
                if moment is None:
                    return None
                moments.append(np.array(moment, dtype=float))
    if gravity_direction is not None:
        weights.append(np.array(gravity_direction, dtype=float))
    loaded = [v for kind in (forces, weights, shifts, bends) for v in _scaled(kind)]
    about = [v for kind in (moments, turns) for v in _scaled(kind)]

    if len(flat) == 1:
        normal = flat[0]
    elif len(flat) == 2:
        # Along one line: the plane is that of the loads across it
        line = np.cross(flat[0], flat[1])

        def across_line(vectors):
            return [
                v - (v @ line) * line
                for v in vectors
                if np.linalg.norm(v - (v @ line) * line) > _FLAT
            ]

        across = across_line(loaded)
        if across:
            direction = _one_direction(across)
            if direction is None:
                return None
            normal = np.cross(line, direction)
        else:
            # Or that of its applied moments, when they are all about one
            normal = _one_direction(across_line(about))
            if normal is None:
                return None
    else:
        return None
    normal = _snap(normal)
    if any(abs(float(v @ normal)) > _FLAT for v in loaded):
        return None
    # A moment, or a support turned, keeps the structure in its plane when
    # it is about the normal
    if any(np.linalg.norm(v - (v @ normal) * normal) > _FLAT for v in about):
        return None

    for member in members:
        if not isinstance(member, CurveMember):
            continue
        axes = getattr(member, "local_axis", None)
        if axes is None:
            continue
        try:
            depth = np.array(axes, dtype=float)[2]
        except (TypeError, ValueError, IndexError):
            return None
        if not _in_or_across(depth / float(np.linalg.norm(depth)) @ normal):
            return None
    for connection in domain_model.connections:
        for held in support_resistance(connection) or ():
            if not _in_or_across(share_in_span(held, normal)):
                return None
    return normal


def _in_or_across(cosine: float) -> bool:
    """Whether a direction at this cosine to the normal is in the plane or
    across it, the angle away from either at most ``_FLAT``."""
    cosine = min(abs(float(cosine)), 1.0)
    return cosine <= _FLAT or (1.0 - cosine * cosine) ** 0.5 <= _FLAT


def _connection_points(connection) -> List[np.ndarray]:
    """Where a connection joins: the corners of its face, the ends of its
    edge, or its position."""
    for corners in (
        getattr(connection, "face", None),
        getattr(connection, "edge", None),
    ):
        if corners is not None:
            return [np.array([float(v) for v in point]) for point in corners]
    return [np.array([float(v) for v in connection.position])]


def _within_plane(rows: np.ndarray, normal: np.ndarray) -> np.ndarray:
    """Orthonormal rows spanning the directions of *rows* that lie in the
    plane: those whose part along the normal is not needed."""
    rows = np.array(rows, dtype=float).reshape(-1, 3)
    return _across(np.vstack([_across(rows), normal]))


class _OutOfPlane:
    """The movements out of its plane that a plane structure is free to make.

    Unknowns: for every member and every joint, its translation across the
    plane at the origin and its rotations about the two axes of
    ``in_plane_axes``.
    """

    def __init__(
        self, domain_model: StructuralModel, normal: Normal, mesh_joints: Sequence = ()
    ):
        self.normal = _unit(normal)
        self.in_plane = in_plane_axes(self.normal)
        self.members = {member.id: member for member in domain_model.members}
        self.bodies: dict = {}
        # Where each joint is: its rows are taken about the first point, so
        # that a joint at one point has no rotation unless one is tied
        self.joint_points: dict = {}
        self.rows: List[list] = []
        # (member id, connection, pinned there, connection is a support)
        self.ends: List[tuple] = []
        points = [p for m in self.members.values() for p in _member_points(m)]
        self.scale = float(np.abs(np.array(points)).max()) or 1.0

        for member_id in self.members:
            self._body(("member", member_id))
        for connection in domain_model.connections:
            attached = [
                m for m in (connection.connected_members or []) if m in self.members
            ]
            if not attached:
                continue
            at = _connection_points(connection)
            key = ("joint", connection.id)
            joint = self._body(key)
            self.joint_points[key] = at
            restraint = support_resistance(connection)
            held, turning = restraint if restraint is not None else ((), ())
            fixed = len(held) or len(turning)
            for member_id in attached:
                index = self.bodies[("member", member_id)]
                for point in at:
                    self.rows.append(
                        [(index, self._across(point)), (joint, self._at(key, point))]
                    )
                if not isinstance(self.members[member_id], CurveMember):
                    continue
                # Tied in every rotation in the plane that the release and
                # a turn about the normal, which is no movement out of it,
                # cannot make up between them
                released = released_rotation_axes(connection, member_id)
                tied = _across(np.vstack([released.reshape(-1, 3), self.normal]))
                for direction in tied:
                    self.rows.append(
                        [(index, self._turn(direction)), (joint, self._turn(direction))]
                    )
                self.ends.append((member_id, connection, not len(tied), bool(fixed)))
            # A skew support in the plane holds these as a global one does
            if share_in_span(held, self.normal) > 1.0 - _FLAT:
                for point in at:
                    self.rows.append([(joint, self._at(key, point))])
            if len(turning):
                for direction in _within_plane(turning, self.normal):
                    self.rows.append([(joint, self._turn(direction))])
        # A shared node is a rigid joint: no release, and no support of its own
        for member_a, member_b, point in mesh_joints:
            if member_a not in self.members or member_b not in self.members:
                continue
            point = np.array([float(v) for v in point])
            key = ("mesh", member_a, member_b)
            joint = self._body(key)
            self.joint_points[key] = [point]
            for member_id in (member_a, member_b):
                index = self.bodies[("member", member_id)]
                self.rows.append(
                    [(index, self._across(point)), (joint, self._at(key, point))]
                )
                for direction in self.in_plane:
                    self.rows.append(
                        [(index, self._turn(direction)), (joint, self._turn(direction))]
                    )

    def _body(self, key) -> int:
        return self.bodies.setdefault(key, len(self.bodies))

    def _at(self, key, point: np.ndarray) -> np.ndarray:
        """Movement across the plane at *point* of a joint."""
        return self._across(point - self.joint_points[key][0])

    def _across(self, point: np.ndarray) -> np.ndarray:
        """Movement across the plane at *point*."""
        row = np.array([1.0, 0.0, 0.0])
        for k, axis in enumerate(self.in_plane):
            row[1 + k] = float(np.cross(axis, point) @ self.normal) / self.scale
        return row

    def _turn(self, direction: np.ndarray) -> np.ndarray:
        """Rotation about *direction*, of which the part in the plane counts."""
        return np.concatenate([[0.0], self.in_plane @ direction])

    def hold_every_node(self) -> None:
        """Add the restraint of every member and joint across the plane."""
        for key, index in self.bodies.items():
            if key[0] == "member":
                for point in _member_points(self.members[key[1]]):
                    self.rows.append([(index, self._across(point))])
            else:
                for point in self.joint_points[key]:
                    self.rows.append([(index, self._at(key, point))])

    def twist(self, member_id: str) -> np.ndarray:
        """The row that gives a member's rotation about its own axis."""
        points = _member_points(self.members[member_id])
        axis = points[-1] - points[0]
        axis = axis / np.linalg.norm(axis)
        row = np.zeros(3 * len(self.bodies))
        index = self.bodies[("member", member_id)]
        row[3 * index + 1 : 3 * index + 3] = self.in_plane @ axis
        return row

    def free_movements(self) -> np.ndarray:
        """A basis of the movements no tie or support restrains, as columns.

        The two members of each tie move alike, so the second has the sign
        of its part turned. Rotations of a joint that nothing is tied to do
        not exist in the mesh (a joint at a point that only pins, a line
        joint about its line when nothing holds it so) and are held at zero.
        """
        unknowns = 3 * len(self.bodies)
        matrix = np.zeros((len(self.rows), unknowns))
        for i, parts in enumerate(self.rows):
            for position, (index, values) in enumerate(parts):
                sign = -1.0 if position else 1.0
                matrix[i, 3 * index : 3 * index + 3] += sign * values
        unused = []
        for (kind, *_), index in self.bodies.items():
            if kind == "member":
                continue
            columns = matrix[:, 3 * index + 1 : 3 * index + 3]
            _, singular, vh = np.linalg.svd(
                np.vstack([columns, np.zeros((2, 2))]), full_matrices=True
            )
            for combination in vh[int((singular > 1e-12).sum()) :]:
                row = np.zeros(unknowns)
                row[3 * index + 1 : 3 * index + 3] = combination
                unused.append(row)
        if unused:
            matrix = np.vstack([matrix] + unused)
        if matrix.shape[0] == 0:
            return np.eye(unknowns)
        _, singular, vh = np.linalg.svd(matrix, full_matrices=True)
        rank = int((singular > 1e-9 * max(singular.max(), 1.0)).sum())
        return vh[rank:].T


def out_of_plane_freedoms(
    domain_model: StructuralModel, normal: Normal, mesh_joints: Sequence = ()
) -> int:
    """How many ways a plane structure can move out of its plane unstrained.

    Args:
        domain_model: A model for which ``plane_normal()`` gave *normal*.
        normal: The normal of the plane, or the global axis it is.
        mesh_joints: ``(member id, member id, point)`` where two members share
            a mesh node that no connection of the file accounts for: a rigid
            joint.

    Returns:
        The number of independent movements nothing restrains; 0 for a
        structure that stands up on its own.
    """
    return int(_OutOfPlane(domain_model, normal, mesh_joints).free_movements().shape[1])


def spinning_members(
    domain_model: StructuralModel, normal: Normal, mesh_joints: Sequence = ()
) -> List[Tuple]:
    """Where to hold the members that can still spin once every node is held.

    Holding every node across the plane leaves a curve member one movement
    out of it: turning about its own axis. A pinned bar does, and so does a
    straight run of members joined rigidly end to end. Each such movement is
    stopped by holding one member at one of its connections. A surface
    member has nodes off any line, and holding them holds it.

    Members that share a mesh node (``mesh_joints``, as for
    ``out_of_plane_freedoms()``) are joined rigidly there, but are never held
    at such a joint: it is no connection.

    Returns:
        ``(connection, member id)`` pairs. The connection is one where the
        member is pinned if it has one (nothing but its spin is restrained by
        holding it there), else a support, else any of its connections.
    """
    system = _OutOfPlane(domain_model, normal, mesh_joints)
    system.hold_every_node()
    basis = system.free_movements()
    ends_of: dict = {}
    for member_id, connection, pinned, support in system.ends:
        ends_of.setdefault(member_id, []).append((connection, pinned, support))
    twists = {
        member_id: system.twist(member_id)
        for member_id in system.members
        if member_id in ends_of
    }
    holds = []
    while basis.shape[1]:
        best = None
        for member_id, row in twists.items():
            turning = row @ basis
            if np.abs(turning).max() <= 1e-9:
                continue
            for connection, pinned, support in ends_of[member_id]:
                rank = 0 if pinned else 1 if support else 2
                if best is None or rank < best[0]:
                    best = (rank, member_id, connection, turning)
        if best is None:
            break
        _, member_id, connection, turning = best
        holds.append((connection, member_id))
        # Take that movement out of what is free
        pivot = int(np.argmax(np.abs(turning)))
        column = basis[:, pivot] / turning[pivot]
        basis = np.delete(basis - np.outer(column, turning), pivot, axis=1)
    return holds


def _temperature_gradient(domain_model, temperature) -> Optional[np.ndarray]:
    """The gradient (K/m) of a temperature difference across a member, in
    global axes: across a curve member's section, or a surface member's
    thickness along its normal. None for none, or where the member has no
    axes or depth (the writer refuses those)."""
    if not (temperature.delta_t_y or temperature.delta_t_z):
        return None
    member = domain_model.get_member(temperature.member_id)
    if isinstance(member, SurfaceMember):
        normal = getattr(member, "normal", None)
        thickness = getattr(getattr(member, "thickness", None), "value", None)
        if normal is None or not thickness or not temperature.delta_t_z:
            return None
        return temperature.delta_t_z / thickness * np.array(normal, dtype=float)
    axes = getattr(member, "local_axis", None)
    section = getattr(member, "section", None)
    if axes is None or section is None:
        return None
    depth_y, depth_z = section.get_depths()
    axes = np.array(axes, dtype=float)
    gradient = np.zeros(3)
    for delta, depth, axis in (
        (temperature.delta_t_y, depth_y, axes[1]),
        (temperature.delta_t_z, depth_z, axes[2]),
    ):
        if delta:
            if not depth:
                return None
            gradient += delta / depth * axis
    return gradient
