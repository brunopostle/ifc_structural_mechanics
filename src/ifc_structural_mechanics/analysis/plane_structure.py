"""Plane trusses and frames: finding them, and whether they can fall over.

A structure drawn in one plane and loaded in it is usually given the supports
of its two-dimensional textbook picture: nothing holds it out of the plane,
pinned joints leave every bar free to spin, and the analysis in three
dimensions is of a mechanism. Its member forces come out right; its
displacements include whatever the mechanism does.

``plane_normal()`` says whether a model is such a structure and
``out_of_plane_freedoms()`` counts the ways it can move out of its plane
without straining. The writer holds a model that has any
(``UnifiedCalculixWriter._hold_plane_structure``).

The count treats every member and every joint as a rigid body out of the
plane, with three movements each: the translation across the plane and the
rotations about the two global axes in it. A member is tied to each of its
joints in that translation, and in each of those rotations it is not released
in. A support ties its joint to the ground in what it restrains. What is left
of the movements after the ties is what nothing holds. Members that share a
point without a connection of the file are not known to be joined here, which
can only make the count too large; holding a plane structure that did not need
it changes nothing in its plane.
"""

from typing import List, Optional, Tuple

import numpy as np

from ..domain.structural_member import CurveMember
from ..domain.structural_model import StructuralModel
from .boundary_condition_handling import (
    _global_force_vector,
    get_released_rotations,
    share_in_span,
    support_restraint,
)

AXIS_NAMES = ("X", "Y", "Z")
_FLAT = 1e-6


def _member_points(member) -> List[np.ndarray]:
    geometry = getattr(member, "geometry", None)
    if not isinstance(geometry, (list, tuple)) or len(geometry) < 2:
        return []
    try:
        points = [np.array([float(v) for v in point]) for point in geometry]
    except (TypeError, ValueError):
        return []
    return [point for point in points if point.shape == (3,)]


def plane_normal(
    domain_model: StructuralModel, gravity_direction: Optional[List[float]] = None
) -> Optional[int]:
    """The global axis (0, 1, 2) across the plane of a plane structure.

    A model is a plane structure when all of this holds:

    - it has curve members only, and all of them lie in one plane parallel to
      two global axes;
    - every load acts in that plane, and so does the self-weight a load case
      includes and gravity, when ``gravity_direction`` is given;
    - every member's section has its own axes in and across the plane;
    - so has every support: what it holds is in the plane or across it.

    A model that lies along a single global axis is in two such planes; it
    counts as plane when its loads all act along one of the other two axes,
    and the plane is the one they act in.

    Returns:
        The index of the axis across the plane, or None.
    """
    members = list(domain_model.members)
    if not members or not all(isinstance(m, CurveMember) for m in members):
        return None
    points = [point for member in members for point in _member_points(member)]
    if len(points) < 2:
        return None
    points_array = np.array(points)
    extent = points_array.max(axis=0) - points_array.min(axis=0)
    size = float(extent.max())
    if size <= 0:
        return None
    flat = [axis for axis in range(3) if extent[axis] <= _FLAT * size]

    # Loads are forces and self-weight is a direction: each kind is judged
    # against its own largest
    forces = []
    weights = []
    for group in domain_model.load_groups:
        if getattr(group, "includes_self_weight", False):
            weights.append(
                np.abs(np.array(group.self_weight_coefficients, dtype=float))
            )
        for load in group.loads:
            vector = _global_force_vector(load, domain_model)
            if vector is None:
                return None
            forces.append(np.abs(np.array(vector, dtype=float)))
    if gravity_direction is not None:
        weights.append(np.abs(np.array(gravity_direction, dtype=float)))
    loaded = []
    for vectors in (forces, weights):
        largest = max((float(vector.max()) for vector in vectors), default=0.0)
        loaded += [
            axis
            for axis in range(3)
            if any(vector[axis] > _FLAT * largest for vector in vectors)
        ]

    if len(flat) == 1:
        normal = flat[0]
    elif len(flat) == 2:
        # Along one axis: the plane is that of the loads across it
        across = [axis for axis in flat if axis in loaded]
        if len(across) != 1:
            return None
        normal = [axis for axis in flat if axis != across[0]][0]
    else:
        return None
    if normal in loaded:
        return None

    for member in members:
        axes = getattr(member, "local_axis", None)
        if axes is None:
            continue
        try:
            depth = np.array(axes, dtype=float)[2]
        except (TypeError, ValueError, IndexError):
            return None
        across_plane = abs(float(depth[normal]))
        if _FLAT < across_plane < 1.0 - _FLAT:
            return None
    for connection in domain_model.connections:
        for held in support_restraint(connection) or ():
            if _FLAT < share_in_span(held, np.eye(3)[normal]) < 1.0 - _FLAT:
                return None
    return normal


class _OutOfPlane:
    """The movements out of its plane that a plane structure is free to make.

    Unknowns: for every member, its translation across the plane at the
    origin and its rotations about the two global axes in the plane; for
    every joint, the same three about its own position.
    """

    def __init__(self, domain_model: StructuralModel, normal: int):
        self.normal = normal
        self.in_plane = [axis for axis in range(3) if axis != normal]
        self.members = {member.id: member for member in domain_model.members}
        self.bodies: dict = {}
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
            point = np.array([float(v) for v in connection.position])
            joint = self._body(("joint", connection.id))
            restraint = support_restraint(connection)
            held, turning = restraint if restraint is not None else ((), ())
            fixed = len(held) or len(turning)
            for member_id in attached:
                index = self.bodies[("member", member_id)]
                released = get_released_rotations(connection, member_id)
                # A release in skew axes has no global equivalent: take it
                # as a full one
                released = {4, 5, 6} if released is None else set(released)
                self.rows.append(
                    [(index, self._across(point)), (joint, self._across(None))]
                )
                pinned = True
                for k, axis in enumerate(self.in_plane):
                    if 4 + axis in released:
                        continue
                    pinned = False
                    self.rows.append([(index, self._turn(k)), (joint, self._turn(k))])
                self.ends.append((member_id, connection, pinned, bool(fixed)))
            # A skew support in the plane holds these as a global one does
            if share_in_span(held, np.eye(3)[normal]) > 1.0 - _FLAT:
                self.rows.append([(joint, self._across(None))])
            for k, axis in enumerate(self.in_plane):
                if share_in_span(turning, np.eye(3)[axis]) > 1.0 - _FLAT:
                    self.rows.append([(joint, self._turn(k))])

    def _body(self, key) -> int:
        return self.bodies.setdefault(key, len(self.bodies))

    def _across(self, point: Optional[np.ndarray]) -> np.ndarray:
        """Movement across the plane at *point* (None: where the body is)."""
        row = np.array([1.0, 0.0, 0.0])
        if point is not None:
            for k, axis in enumerate(self.in_plane):
                rotation = np.zeros(3)
                rotation[axis] = 1.0
                row[1 + k] = float(np.cross(rotation, point)[self.normal]) / self.scale
        return row

    @staticmethod
    def _turn(k: int) -> np.ndarray:
        row = np.zeros(3)
        row[1 + k] = 1.0
        return row

    def hold_every_node(self) -> None:
        """Add the restraint of every member and joint across the plane."""
        for (kind, key), index in self.bodies.items():
            if kind == "joint":
                self.rows.append([(index, self._across(None))])
                continue
            for point in _member_points(self.members[key]):
                self.rows.append([(index, self._across(point))])

    def twist(self, member_id: str) -> np.ndarray:
        """The row that gives a member's rotation about its own axis."""
        points = _member_points(self.members[member_id])
        axis = points[-1] - points[0]
        axis = axis / np.linalg.norm(axis)
        row = np.zeros(3 * len(self.bodies))
        index = self.bodies[("member", member_id)]
        for k, global_axis in enumerate(self.in_plane):
            row[3 * index + 1 + k] = axis[global_axis]
        return row

    def free_movements(self) -> np.ndarray:
        """A basis of the movements no tie or support restrains, as columns.

        The two members of each tie move alike, so the second has the sign
        of its part turned. Rotations of a joint that nothing is tied to do
        not exist in the mesh and are left out.
        """
        unknowns = 3 * len(self.bodies)
        matrix = np.zeros((len(self.rows), unknowns))
        for i, parts in enumerate(self.rows):
            for position, (index, values) in enumerate(parts):
                sign = -1.0 if position else 1.0
                matrix[i, 3 * index : 3 * index + 3] += sign * values
        used = np.ones(unknowns, dtype=bool)
        for (kind, _), index in self.bodies.items():
            if kind == "joint":
                columns = slice(3 * index + 1, 3 * index + 3)
                used[columns] = np.abs(matrix[:, columns]).sum(axis=0) > 0
        basis = np.zeros((unknowns, 0))
        if used.any():
            reduced = matrix[:, used]
            if reduced.shape[0] == 0:
                free = np.eye(reduced.shape[1])
            else:
                _, singular, vh = np.linalg.svd(reduced, full_matrices=True)
                rank = int((singular > 1e-9 * max(singular.max(), 1.0)).sum())
                free = vh[rank:].T
            basis = np.zeros((unknowns, free.shape[1]))
            basis[used, :] = free
        return basis


def out_of_plane_freedoms(domain_model: StructuralModel, normal: int) -> int:
    """How many ways a plane structure can move out of its plane unstrained.

    Args:
        domain_model: A model for which ``plane_normal()`` gave *normal*.
        normal: The global axis across the plane.

    Returns:
        The number of independent movements nothing restrains; 0 for a
        structure that stands up on its own.
    """
    return int(_OutOfPlane(domain_model, normal).free_movements().shape[1])


def spinning_members(domain_model: StructuralModel, normal: int) -> List[Tuple]:
    """Where to hold the members that can still spin once every node is held.

    Holding every node across the plane leaves a member one movement out of
    it: turning about its own axis. A pinned bar does, and so does a straight
    run of members joined rigidly end to end. Each such movement is stopped
    by holding one member at one of its connections.

    Returns:
        ``(connection, member id)`` pairs. The connection is one where the
        member is pinned if it has one (nothing but its spin is restrained by
        holding it there), else a support, else any of its connections.
    """
    system = _OutOfPlane(domain_model, normal)
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
