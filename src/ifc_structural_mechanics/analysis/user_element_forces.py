"""Nodal forces of CalculiX's U1 beam element, from its displacements.

CalculiX gets the force on a node of a U1 element wrong (``aiz.19``):
``resultsmech_u1.f`` adds the section forces at both ends of each element to
its nodes with the same sign, where the first end's should be turned round,
and works them out from shape functions with ``1/(1 - phi)`` that do not
match the element's stiffness. A cantilever's root printed -1500 N where
statics gives +1500 N, and with a realistic shear factor 728 N.

The displacements are right, and so is the element's own stiffness as far as
equilibrium goes: it gives no force under a rigid movement. Its matrix times
its nodal displacements is the force the element puts on its nodes, and the
sum of those at a node is the force inside the structure there, which is
what the solver's ``RF`` is for every other element. ``u1_local_stiffness()``
is the matrix of ``e_c3d_u1.f`` as it is, not the textbook Timoshenko beam
(its shear terms differ; it converges to the same beam as the mesh is
refined), so that the forces are those of the model that was solved.
"""

from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np


def u1_local_stiffness(
    modulus: float,
    poisson: float,
    area: float,
    inertia_11: float,
    inertia_22: float,
    shear_factor: float,
    length: float,
) -> np.ndarray:
    """The 12 x 12 stiffness of a U1 element in its own axes.

    Copied from CalculiX's ``e_c3d_u1.f``. The degrees of freedom are the
    three translations and three rotations of the first node, then of the
    second, along the element (1), the section's 1-direction (2) and their
    cross product (3). ``inertia_11`` resists bending across the 1-direction.

    Args:
        modulus: Young's modulus E.
        poisson: Poisson's ratio, which gives the shear modulus.
        area: Cross-section area.
        inertia_11: I11 of the ``*BEAM SECTION, SECTION=GENERAL`` card.
        inertia_22: I22 of that card.
        shear_factor: The shear factor k of that card.
        length: Length of the element.

    Returns:
        np.ndarray: The symmetric stiffness matrix.
    """
    e, a, dl, xk = modulus, area, length, shear_factor
    um = e / (1.0 + poisson) / 2.0
    ga = xk * um * a
    s = np.zeros((12, 12))

    def bending(inertia: float):
        ei = e * inertia
        y1 = ga * ei * (12.0 * ei + ga * dl * dl)
        y2 = (12.0 * ei - ga * dl * dl) ** 2
        y3 = 4.0 * ei * (ga**2 * dl**4 + 3.0 * ga * dl * dl * ei + 36.0 * ei**2)
        far = -2.0 * ei * (72.0 * ei**2 - ga**2 * dl**4 - 30.0 * ga * dl * dl * ei)
        return y1, y2, y3, far / (dl * y2)

    y1, y2, y3, y_far = bending(inertia_11)
    z1, z2, z3, z_far = bending(inertia_22)
    # Indices are those of e_c3d_u1.f less one
    s[0, 0] = e * a / dl
    s[0, 6] = -s[0, 0]
    s[1, 1] = 12.0 * y1 / (dl * y2)
    s[1, 5] = 6.0 * y1 / y2
    s[1, 7] = -s[1, 1]
    s[1, 11] = s[1, 5]
    s[2, 2] = 12.0 * z1 / (dl * z2)
    s[2, 4] = -6.0 * z1 / z2
    s[2, 8] = -s[2, 2]
    s[2, 10] = s[2, 4]
    s[3, 3] = um * (inertia_11 + inertia_22) / dl
    s[3, 9] = -s[3, 3]
    s[4, 4] = z3 / (dl * z2)
    s[4, 8] = 6.0 * z1 / z2
    s[4, 10] = z_far
    s[5, 5] = y3 / (dl * y2)
    s[5, 7] = -6.0 * y1 / y2
    s[5, 11] = y_far
    s[6, 6] = s[0, 0]
    s[7, 7] = s[1, 1]
    s[7, 11] = -6.0 * y1 / y2
    s[8, 8] = s[2, 2]
    s[8, 10] = 6.0 * z1 / z2
    s[9, 9] = s[3, 3]
    s[10, 10] = s[4, 4]
    s[11, 11] = s[5, 5]
    return np.triu(s) + np.triu(s, 1).T


def u1_element_forces(
    element: Mapping, displacements: Mapping[int, Sequence[float]]
) -> Dict[int, np.ndarray]:
    """The force a U1 element puts on each of its two nodes, in global axes.

    Args:
        element: What the input writer recorded for the element
            (``StructuralModel.user_elements``): ``nodes``, ``positions``,
            ``direction`` (the section's 1-direction as written),
            ``modulus``, ``poisson``, ``area``, ``inertia_11``,
            ``inertia_22`` and ``shear_factor``.
        displacements: Node number to its six displacements and rotations.

    Returns:
        Dict[int, np.ndarray]: Node number to ``[fx, fy, fz, mx, my, mz]``.
    """
    first, second = element["nodes"]
    start, end = (np.array(p, dtype=float) for p in element["positions"])
    along = end - start
    length = float(np.linalg.norm(along))
    along /= length
    across = np.array(element["direction"], dtype=float)
    # As CalculiX does: the 1-direction is taken as written
    axes = np.array([along, across, np.cross(along, across)])
    turn = np.kron(np.eye(4), axes)
    local = u1_local_stiffness(
        element["modulus"],
        element["poisson"],
        element["area"],
        element["inertia_11"],
        element["inertia_22"],
        element["shear_factor"],
        length,
    )
    moved = np.concatenate(
        [
            np.asarray(displacements[first], float),
            np.asarray(displacements[second], float),
        ]
    )
    forces = turn.T @ (local @ (turn @ moved))
    return {first: forces[:6], second: forces[6:]}


def u1_nodal_forces(
    elements: Mapping[int, Mapping],
    displacements: Mapping[int, Sequence[float]],
    nodes: Iterable[int],
) -> Dict[int, np.ndarray]:
    """The force inside the structure at some nodes of U1 elements.

    The sum, over every U1 element at the node, of the force the element
    puts on it. Where only U1 elements meet the node this is what the
    solver's ``RF`` should have been: at a support node, the reaction plus
    any load applied there.

    Args:
        elements: Element number to its record (see ``u1_element_forces``).
        displacements: Node number to its six displacements and rotations.
        nodes: The nodes wanted.

    Returns:
        Dict[int, np.ndarray]: Node number to ``[fx, fy, fz, mx, my, mz]``.
    """
    wanted = set(nodes)
    totals: Dict[int, np.ndarray] = {node: np.zeros(6) for node in wanted}
    for element in elements.values():
        if not wanted.intersection(element["nodes"]):
            continue
        for node, force in u1_element_forces(element, displacements).items():
            if node in wanted:
                totals[node] += force
    return totals


def u1_section_forces(
    element: Mapping,
    displacements: Mapping[int, Sequence[float]],
    loads: Optional[Sequence[float]],
    axis: Sequence[float],
) -> List[Dict]:
    """Section forces at the two ends of a U1 element.

    A U1 element carries no load of its own: what acts along it was written
    as forces on its nodes. What the element's nodes put on it is its
    stiffness times their displacements; less its share of those loads, it
    is the force on the element itself at either end, in equilibrium with
    the load along it. In a statically determinate member that is exact at
    every node, whatever the mesh.

    The records are those of ``section_forces.element_section_forces``: at
    each end, what the part of the member beyond the cross-section (along
    ``axis``) exerts on the part before it, in the section's axes and as
    vectors in global axes, the moment about the node.

    Args:
        element: The element's record (see ``u1_element_forces``).
        displacements: Node number to its six displacements and rotations.
        loads: The element's share of the loads along it, ``[fx, fy, fz,
            mx, my, mz]`` at its first node and then at its second, in
            global axes, or None.
        axis: Direction of the member; ``position`` -1 is the end it starts
            from.

    Returns:
        Two dicts with ``position``, ``centre``, ``N``, ``Vf1``, ``Vf2``,
        ``T``, ``Mf1``, ``Mf2``, ``force`` and ``moment``.
    """
    on_nodes = u1_element_forces(element, displacements)
    shares = np.zeros(12) if loads is None else np.asarray(loads, dtype=float)
    first, second = element["nodes"]
    start, end = (np.array(p, dtype=float) for p in element["positions"])
    t = np.array(axis, dtype=float)
    t /= np.linalg.norm(t)
    e1 = np.array(element["direction"], dtype=float)
    e1 = e1 - np.dot(e1, t) * t
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(t, e1)
    forward = float(np.dot(end - start, t)) > 0.0

    records = []
    for node, centre, share, is_first in (
        (first, start, shares[:6], True),
        (second, end, shares[6:], False),
    ):
        # What the node puts on the element, the load along it taken off
        on_element = on_nodes[node] - share
        # The element lies beyond its first node when it points the way
        # the member does: what is beyond the cross-section there is the
        # element, which puts the opposite on the node
        beyond_is_element = is_first == forward
        acting = -on_element if beyond_is_element else on_element
        force, moment = acting[:3], acting[3:]
        records.append(
            {
                "position": -1.0 if beyond_is_element else 1.0,
                "centre": [float(v) for v in centre],
                "N": float(force @ t),
                "Vf1": float(force @ e1),
                "Vf2": float(force @ e2),
                "T": float(moment @ t),
                "Mf1": float(-(moment @ e2)),
                "Mf2": float(moment @ e1),
                "force": [float(v) for v in force],
                "moment": [float(v) for v in moment],
            }
        )
    return sorted(records, key=lambda r: r["position"])
