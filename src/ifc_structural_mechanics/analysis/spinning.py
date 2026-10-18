"""Members free to spin about their own axis in a space structure (``aiz.79``).

``UnifiedCalculixWriter._hold_spinning_members`` takes a member as held in
torsion when it joins a member across it without a torsional release. That
member may itself give way: a beam on ball supports at its two ends with a
column hanging from one of them turns about its axis, and the column swings
with it. ``free_runs()`` finds such runs by counting what is left free when
every member and joint is a rigid body, as ``plane_structure`` does in a
plane.

Every member and joint has six movements: a translation and a rotation. A
member is tied to each of its joints in translation at the joint, and in
each rotation it is not released in; a support ties its joint to the ground
in what it resists. Bodies joined rigidly are one body, which keeps the
count small in a framed building.

The count must know every tie, or it finds freedoms that the mesh does not
have and holds members that need no help, which adds a restraint that
carries moment. What it cannot model (a member tied to a surface by a shared
node, a line bearing or a connection; a member joined to one that is no
body here, such as a user element) is taken as held by the ground. So it
can miss a mechanism through a surface, never invent one.
"""

from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

from .boundary_condition_handling import (
    _across,
    released_rotation_axes,
    support_resistance,
)

_GROUND = ("ground",)
_TINY = 1e-9


class _Bodies:
    """Rigid bodies merged by rigid ties, and the ties left between them."""

    def __init__(self):
        self.parent: Dict[tuple, tuple] = {_GROUND: _GROUND}
        # (body, body, point, translation rows, rotation rows)
        self.ties: List[Tuple[tuple, tuple, np.ndarray, np.ndarray, np.ndarray]] = []

    def find(self, key: tuple) -> tuple:
        self.parent.setdefault(key, key)
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def merge(self, a: tuple, b: tuple) -> None:
        a, b = self.find(a), self.find(b)
        if a == b:
            return
        # The ground stays the root of what joins it
        if b == _GROUND:
            a, b = b, a
        self.parent[b] = a

    def tie(self, a, b, point, translations, rotations) -> None:
        translations = np.asarray(translations, dtype=float).reshape(-1, 3)
        rotations = np.asarray(rotations, dtype=float).reshape(-1, 3)
        if len(translations) or len(rotations):
            self.ties.append((a, b, np.asarray(point, float), translations, rotations))


def _held_rotations(connection, member_id: str) -> Optional[np.ndarray]:
    """The rotations a member passes on at a joint; None for all three."""
    if connection.entity_type == "hinge" and len(connection.connected_members) > 1:
        return np.zeros((0, 3))
    released = released_rotation_axes(connection, member_id)
    if not len(released):
        return None
    return _across(released)


def free_runs(
    domain_model,
    directions: Dict[str, np.ndarray],
    runs: Sequence[List[str]],
    held: Iterable[int],
    grounded: Set[str],
    mesh_joints: Iterable[Tuple[str, str, np.ndarray]],
    preferred: Iterable[int] = (),
) -> List[int]:
    """The runs that can still turn about their own axis without straining.

    Args:
        domain_model: The model; its connections give the joints and supports.
        directions: The unit axis of each curve member counted, by id.
        runs: Members joined end to end in a straight line, which turn
            together (``_hold_spinning_members``).
        held: Indices of the runs that are held in torsion already.
        grounded: Members tied to something the count does not model,
            taken as held in every movement.
        mesh_joints: ``(member id, member id, point)`` where two members
            share a mesh node no connection accounts for: a rigid joint.
        preferred: Runs to name first where several turn in one movement:
            those that can be held.

    Returns:
        Indices of runs, of those not in *held*, whose turning about their
        axis nothing stops, in order. Holding each in torsion stops the
        movements found; a run whose turning goes with one found earlier is
        not listed again.
    """
    bodies = _Bodies()
    for member_id in grounded:
        bodies.merge(("m", member_id), _GROUND)

    for conn in domain_model.connections:
        attached = list(conn.connected_members or [])
        counted = [m for m in attached if m in directions]
        if not counted:
            continue
        if len(counted) < len(attached):
            # A surface, a user element: something not modelled here
            for member_id in counted:
                bodies.merge(("m", member_id), _GROUND)
            continue
        point = np.array([float(v) for v in conn.position])
        restraint = support_resistance(conn)
        edge = getattr(conn, "edge", None)
        if edge is not None:
            # A line support holds its members along the whole edge
            if restraint is None:
                continue
            for member_id in counted:
                for end in edge:
                    bodies.tie(("m", member_id), _GROUND, end, restraint[0], [])
                bodies.tie(("m", member_id), _GROUND, point, [], restraint[1])
            continue
        joint = ("j", conn.id)
        if restraint is not None:
            bodies.tie(joint, _GROUND, point, restraint[0], restraint[1])
        for member_id in counted:
            rotations = _held_rotations(conn, member_id)
            if rotations is None:
                bodies.merge(("m", member_id), joint)
            else:
                bodies.tie(("m", member_id), joint, point, np.eye(3), rotations)

    for a, b, _ in mesh_joints:
        if a in directions and b in directions:
            bodies.merge(("m", a), ("m", b))
        else:
            for member_id in (a, b):
                if member_id in directions:
                    bodies.merge(("m", member_id), _GROUND)

    held = set(held)
    for index in held:
        for member_id in runs[index]:
            bodies.tie(
                ("m", member_id), _GROUND, np.zeros(3), [], directions[member_id]
            )

    return _turning_runs(bodies, directions, runs, held, set(preferred))


def _turning_runs(bodies: _Bodies, directions, runs, held, preferred) -> List[int]:
    """The free runs, solved one group of bodies tied together at a time."""
    groups: Dict[tuple, List[int]] = {}
    for index, members in enumerate(runs):
        if index in held:
            continue
        body = bodies.find(("m", members[0]))
        if body != _GROUND:
            groups.setdefault(body, []).append(index)
    if not groups:
        return []

    # Bodies that tie to each other turn together; each set is solved alone
    linked = _Bodies()
    for a, b, *_ in bodies.ties:
        a, b = bodies.find(a), bodies.find(b)
        if a != _GROUND and b != _GROUND:
            linked.merge(a, b)
    sets: Dict[tuple, List[int]] = {}
    for body, indices in groups.items():
        sets.setdefault(linked.find(body), []).extend(indices)

    points = [point for _, _, point, _, _ in bodies.ties]
    scale = float(np.abs(np.array(points)).max()) if points else 1.0
    scale = scale or 1.0

    found: List[int] = []
    for root, indices in sets.items():
        members = {
            bodies.find(("m", member_id))
            for index in indices
            for member_id in runs[index]
        }
        column: Dict[tuple, int] = {}
        rows = []
        for a, b, point, translations, rotations in bodies.ties:
            a, b = bodies.find(a), bodies.find(b)
            if a == b:
                continue
            if linked.find(a if a != _GROUND else b) != root:
                continue
            for body in (a, b):
                if body != _GROUND:
                    column.setdefault(body, len(column))
            for direction in translations:
                row = {}
                lever = np.cross(point / scale, direction)
                for sign, body in ((1.0, a), (-1.0, b)):
                    if body != _GROUND:
                        row[body] = sign * np.concatenate([direction, lever])
                rows.append(row)
            for direction in rotations:
                row = {}
                for sign, body in ((1.0, a), (-1.0, b)):
                    if body != _GROUND:
                        row[body] = sign * np.concatenate([np.zeros(3), direction])
                rows.append(row)
        for body in members:
            column.setdefault(body, len(column))

        matrix = np.zeros((len(rows), 6 * len(column)))
        for i, row in enumerate(rows):
            for body, values in row.items():
                start = 6 * column[body]
                matrix[i, start : start + 6] += values
        basis = _null_space(matrix)

        def twist(index: int) -> np.ndarray:
            """How much each free movement turns the run about its axis."""
            member_id = runs[index][0]
            start = 6 * column[bodies.find(("m", member_id))]
            return directions[member_id] @ basis[start + 3 : start + 6]

        for index in sorted(indices, key=lambda i: (i not in preferred, i)):
            if not basis.shape[1]:
                break
            turning = twist(index)
            if np.abs(turning).max() <= _TINY:
                continue
            found.append(index)
            # Holding it takes that movement out of what is free
            pivot = int(np.argmax(np.abs(turning)))
            moved = basis[:, pivot] / turning[pivot]
            basis = np.delete(basis - np.outer(moved, turning), pivot, axis=1)
    return sorted(found)


def _null_space(matrix: np.ndarray) -> np.ndarray:
    """An orthonormal basis of the movements no row restrains, as columns."""
    if matrix.shape[0] == 0:
        return np.eye(matrix.shape[1])
    _, singular, vh = np.linalg.svd(matrix, full_matrices=True)
    rank = int((singular > _TINY * max(float(singular.max()), 1.0)).sum())
    return vh[rank:].T
