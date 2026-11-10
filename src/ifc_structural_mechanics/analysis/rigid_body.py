"""Movements of the whole structure that no support resists (``zb7``).

The structure is taken as one rigid body, however its members are joined. A
rigid movement of it that nothing resists is a mechanism whatever happens
inside: no joint can stop it. ``Two_Span_Beam.ifc`` had three supports all
free along the beam, and CalculiX solved it without a word, with the whole
beam moved 5.8 mm along its length (an arbitrary amount: nothing loaded it
that way).

Taking it as one body can only miss a mechanism (a part free inside the
structure, which ``analysis/spinning.py`` and ``plane_structure.py`` look
for), never find one that is not there.

A rigid movement is a translation ``t`` and a rotation ``w`` about a centre
``c``: the point ``p`` moves by ``t + w x (p - c)``. A support at ``p`` that
resists translation along ``d`` stops ``d . t + ((p - c) x d) . w``; one that
resists rotation about ``r`` stops ``r . w``.
"""

from typing import Iterable, List, Optional, Tuple

import numpy as np

from .boundary_condition_handling import support_resistance
from .plane_structure import _connection_points, _member_points

# What is left of a movement that the supports resist, relative to the
# largest: below it, the movement is free
_TINY = 1e-9


def free_movements(
    domain_model,
    plane_normal: Optional[np.ndarray] = None,
    held_rotations: Iterable[np.ndarray] = (),
) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """The rigid movements of the whole model that nothing resists.

    Args:
        domain_model: The model; its connections' support conditions,
            springs and the writer's holds about a member's axis
            (``torsion_hold_axes``) are what resists.
        plane_normal: Where the writer holds every node across a plane
            (``_hold_plane_structure``), that plane's unit normal.
        held_rotations: Axes about which the writer holds rotations of its
            own, at some node (``*BOUNDARY`` on a rotation, spin arms).

    Returns:
        One ``(translation, rotation, centre)`` for each independent free
        movement: the free translations first, as unit directions with no
        rotation; then rotations, as a unit axis with the translation of
        ``centre``, the point of the model's middle, that goes with it.
    """
    points = [
        point for member in domain_model.members for point in _member_points(member)
    ]
    if not points:
        return []
    centre = np.mean(points, axis=0)
    # Rotations are measured by what they move at the model's edge, so that
    # translations and rotations are compared on one scale
    size = max(float(np.max(np.linalg.norm(np.array(points) - centre, axis=1))), 1.0)

    rows: List[np.ndarray] = []

    def holds_translation(point: np.ndarray, direction: np.ndarray) -> None:
        lever = np.cross(point - centre, direction) * size
        rows.append(np.concatenate([direction, lever]))

    def holds_rotation(axis: np.ndarray) -> None:
        rows.append(np.concatenate([np.zeros(3), np.asarray(axis, float) * size]))

    for conn in domain_model.connections:
        resisted = support_resistance(conn)
        if resisted is None:
            continue
        translations, rotations = (
            np.asarray(rows_, dtype=float).reshape(-1, 3) for rows_ in resisted
        )
        for point in _connection_points(conn):
            for direction in translations:
                holds_translation(point, direction)
        for axis in rotations:
            holds_rotation(axis)
    if plane_normal is not None:
        normal = np.asarray(plane_normal, dtype=float)
        for point in points:
            holds_translation(point, normal)
    for axis in held_rotations:
        holds_rotation(axis)

    free = _null_space(np.array(rows) if rows else np.zeros((0, 6)))
    if not free.shape[1]:
        return []
    return _described(free, size, centre)


def _null_space(matrix: np.ndarray) -> np.ndarray:
    """An orthonormal basis of what ``matrix`` leaves at zero, as columns."""
    if not len(matrix):
        return np.eye(6)
    _, singular, vt = np.linalg.svd(matrix)
    largest = singular[0] if len(singular) else 0.0
    rank = int(np.sum(singular > _TINY * max(largest, 1.0)))
    return vt[rank:].T


def _described(
    free: np.ndarray, size: float, centre: np.ndarray
) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Free translations first, then the rotations that are left."""
    rotation_parts = free[3:]
    # Combinations of the free movements with no rotation in them
    _, singular, vt = np.linalg.svd(rotation_parts)
    rank = int(np.sum(singular > _TINY))
    pure = free @ vt[rank:].T
    found = []
    for column in pure.T:
        direction = column[:3] / np.linalg.norm(column[:3])
        direction = direction * _sense(direction)
        found.append((_snapped(direction), np.zeros(3), centre))
    # What is left, orthogonal to those, turns
    turning = free @ vt[:rank].T
    for column in turning.T:
        # The rows have the rotation times ``size``, so the unknown is the
        # rotation over it
        rotation = column[3:] * size
        translation = column[:3]
        # One factor for both: turned the other way, the translation that
        # goes with it is the other way too, or the axis moves
        factor = _sense(rotation) / np.linalg.norm(rotation)
        found.append((translation * factor, _snapped(rotation * factor), centre))
    return found


def _sense(direction: np.ndarray) -> float:
    """1 or -1, so that the largest component of a direction is positive."""
    return 1.0 if direction.max() >= -direction.min() else -1.0


def _snapped(direction: np.ndarray) -> np.ndarray:
    """A unit direction, made exactly a global axis where it is one."""
    for axis in range(3):
        if abs(abs(direction[axis]) - 1.0) < 1e-9:
            snapped = np.zeros(3)
            snapped[axis] = np.sign(direction[axis])
            return snapped
    return direction


def describe(movement: Tuple[np.ndarray, np.ndarray, np.ndarray]) -> str:
    """A free movement in words: along x, about an axis along z through ...."""
    translation, rotation, centre = movement
    if not np.any(rotation):
        return f"along {_direction_name(translation)}"
    # The axis passes through the point that the movement leaves where it
    # is, as far as anything does: centre + (w x t) / |w|^2
    through = centre + np.cross(rotation, translation) / float(rotation @ rotation)
    # To the micrometre, which takes off the rounding of the solution
    point = ", ".join(f"{v:.3g}" for v in np.round(through, 6) + 0.0)
    return f"about an axis along {_direction_name(rotation)} through ({point}) m"


def _direction_name(direction: np.ndarray) -> str:
    for axis, name in enumerate("xyz"):
        if abs(abs(direction[axis]) - 1.0) < 1e-9:
            return name
    return "(" + ", ".join(f"{v:.3g}" for v in direction + 0.0) + ")"
