"""Beam section forces recovered from the stresses of expanded beam elements.

CalculiX expands every beam element into a solid with the beam's rectangular
cross-section and reports stresses at the solid's nodes. It can report section
forces itself, but only in its two-dimensional output mode, where shell
stresses are averaged through the thickness and their bending part is lost.
So the forces are integrated here from the three-dimensional results instead:
at each cross-section of an element that has nodes (both ends, and the middle
of a quadratic element), the nodal stresses are interpolated over the
rectangle and integrated.

For a member analysed as an equivalent rectangle the stresses are those of
the stand-in rectangle and mean nothing by themselves, but their resultants
are the member's real section forces.

Conventions, in the section's own axes: ``x`` along the member in the
direction given, ``1`` along the section's first direction (the depth) and
``2 = x cross 1`` across it. Each force is the resultant of what the part of
the member beyond the cross-section (further along ``x``) exerts on the part
before it:

* ``N``: axial force, tension positive
* ``Vf1``, ``Vf2``: shear forces along 1 and along 2
* ``Mf1``: bending moment from stress varying along 1 (strong-axis bending
  of a section deeper than wide; pairs with ``moment_of_inertia_y``),
  positive when the fibres on the +1 side are in tension
* ``Mf2``: bending moment from stress varying along 2, positive when the
  fibres on the +2 side are in tension
* ``T``: torque about ``x``, right-handed

``N``, ``Mf1`` and ``Mf2`` do not depend on which way ``x`` points; the shear
forces and the torque change sign with it. The caller passes the member's
direction, so that signs are the same all along a member.
"""

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# Stress components as CalculiX lists them: xx, yy, zz, xy, yz, zx
_TENSOR_INDEX = ((0, 3, 5), (3, 1, 4), (5, 4, 2))


def _stations(offsets: np.ndarray) -> List[Tuple[float, np.ndarray]]:
    """Group an element's nodes into cross-sections by position along the axis.

    Returns ``(position, node indices)`` for the start, the middle (quadratic
    elements only) and the end, with ``position`` from -1 to 1.
    """
    half = (offsets.max() - offsets.min()) / 2.0
    if half < 1e-12:
        return []
    relative = (offsets - (offsets.max() + offsets.min()) / 2.0) / half
    stations = []
    for position in (-1.0, 0.0, 1.0):
        members = np.where(np.abs(relative - position) < 0.25)[0]
        if len(members) >= 4:
            stations.append((position, members))
    return stations


def _integrate(
    y: np.ndarray, z: np.ndarray, values: np.ndarray
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Integrate nodal values over a rectangular cross-section.

    The values are interpolated with the polynomial the nodes determine: the
    eight-node serendipity basis for a quadratic element's end face, bilinear
    for four corner nodes. ``y`` and ``z`` are measured from the centre.

    Returns:
        ``(integral, first moment in y, first moment in z)`` of each column of
        ``values``, or None if the nodes do not span a rectangle.
    """
    half_y, half_z = float(np.abs(y).max()), float(np.abs(z).max())
    if half_y < 1e-12 or half_z < 1e-12:
        return None
    ones = np.ones_like(y)
    if len(y) >= 8:
        basis = np.column_stack([ones, y, z, y * z, y * y, z * z, y * y * z, y * z * z])
    else:
        basis = np.column_stack([ones, y, z, y * z])
    coefficients, *_ = np.linalg.lstsq(basis, values, rcond=None)
    area = 4.0 * half_y * half_z
    second_y = area * half_y**2 / 3.0  # integral of y^2
    second_z = area * half_z**2 / 3.0
    mixed = area * half_y**2 * half_z**2 / 9.0  # integral of y^2 z^2
    integral = coefficients[0] * area
    moment_y = coefficients[1] * second_y
    moment_z = coefficients[2] * second_z
    if len(y) >= 8:
        integral = integral + coefficients[4] * second_y + coefficients[5] * second_z
        moment_y = moment_y + coefficients[7] * mixed
        moment_z = moment_z + coefficients[6] * mixed
    return integral, moment_y, moment_z


def element_section_forces(
    node_ids: Sequence[int],
    coordinates: Dict[int, Sequence[float]],
    stresses: Dict[int, Sequence[float]],
    axis: Sequence[float],
    direction_1: Sequence[float],
) -> List[Dict[str, float]]:
    """Section forces at each cross-section of one expanded beam element.

    Args:
        node_ids: Nodes of the solid element, from the result file.
        coordinates: Node positions from the result file.
        stresses: Six stress components per node (xx, yy, zz, xy, yz, zx).
        axis: Direction of the member.
        direction_1: The section's first direction, as written on the
            ``*BEAM SECTION`` card.

    Returns:
        One dict per cross-section with ``position`` (-1 start, 0 middle,
        1 end, along ``axis``), ``centre`` (the cross-section's centre) and
        ``N``, ``Vf1``, ``Vf2``, ``T``, ``Mf1``, ``Mf2``. Empty if a node or
        its stress is missing. ``force`` and ``moment`` are the same
        resultants as vectors in global axes, the moment about ``centre``:
        what the part of the member beyond the cross-section (along ``axis``)
        exerts on the part before it.
    """
    try:
        points = np.array([coordinates[n] for n in node_ids], dtype=float)
        tensors = np.array([stresses[n] for n in node_ids], dtype=float)
    except KeyError:
        return []
    t = np.array(axis, dtype=float)
    t /= np.linalg.norm(t)
    e1 = np.array(direction_1, dtype=float)
    e1 = e1 - np.dot(e1, t) * t
    if np.linalg.norm(e1) < 1e-9:
        return []
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(t, e1)

    # Traction on the cross-section, in section axes, at every node
    full = tensors[:, _TENSOR_INDEX]  # (n, 3, 3)
    traction = full @ t
    local = np.column_stack([traction @ t, traction @ e1, traction @ e2])

    forces = []
    for position, members in _stations(points @ t):
        section_points = points[members]
        centre = section_points.mean(axis=0)
        y = (section_points - centre) @ e1
        z = (section_points - centre) @ e2
        integrated = _integrate(y, z, local[members])
        if integrated is None:
            continue
        integral, moment_y, moment_z = integrated
        forces.append(
            {
                "position": position,
                "centre": [float(v) for v in centre],
                "N": float(integral[0]),
                "Vf1": float(integral[1]),
                "Vf2": float(integral[2]),
                "T": float(moment_y[2] - moment_z[1]),
                "Mf1": float(moment_y[0]),
                "Mf2": float(moment_z[0]),
                "force": [
                    float(v)
                    for v in integral[0] * t + integral[1] * e1 + integral[2] * e2
                ],
                "moment": [
                    float(v)
                    for v in (moment_y[2] - moment_z[1]) * t
                    + moment_z[0] * e1
                    - moment_y[0] * e2
                ],
            }
        )
    return forces
