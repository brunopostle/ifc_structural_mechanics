"""
Enhanced boundary condition handling for the IFC Structural Mechanics Analysis package.

This module improves the boundary condition and load handling in the conversion process
from IFC structural models to CalculiX.
"""

import logging
from typing import Any, Collection, Dict, Iterable, List, Optional, TextIO, Tuple

import numpy as np

from ..domain.load import HALF_WAVES, PointLoad
from ..domain.structural_model import StructuralModel
from ..utils.error_handling import AnalysisError
from ..utils.messages import guids_of, record_warning

# Configure logging
logger = logging.getLogger(__name__)

# Stiffness value above which a DOF is considered rigidly constrained
_RIGID_STIFFNESS_THRESHOLD = 1e12


_STIFFNESS_KEYS = ("dx", "dy", "dz", "drx", "dry", "drz")


def _local_fixity(connection) -> Optional[List[bool]]:
    """Return which of dx..drz a connection's support condition restrains.

    The six flags are in the connection's own axes. None when the connection
    carries no support condition.
    """
    has_stiffness = (
        hasattr(connection, "has_stiffness_properties")
        and connection.has_stiffness_properties()
    )
    if not has_stiffness:
        return None
    stiff = connection.get_stiffness_properties() or {}
    return [
        stiff.get(key, 0.0) >= _RIGID_STIFFNESS_THRESHOLD for key in _STIFFNESS_KEYS
    ]


def _global_axis_of_each_local_axis(local_axes) -> Optional[List[int]]:
    """Return the global axis (0, 1, 2) each of three local axes lies on.

    None when the local axes are not a permutation of the global ones, that
    is, when they are skew. ``local_axes`` of None means the global axes.
    """
    if local_axes is None:
        return [0, 1, 2]
    axes = np.abs(np.array(local_axes, dtype=float))
    nearest = [int(np.argmax(row)) for row in axes]
    aligned = all(axes[i, j] > 1.0 - 1e-6 for i, j in enumerate(nearest))
    if not aligned or sorted(nearest) != [0, 1, 2]:
        return None
    return nearest


def _global_rows(local_axes) -> np.ndarray:
    """Three local axes as rows in global coordinates.

    Axes that are a permutation of the global ones, to the tolerance of
    ``_global_axis_of_each_local_axis``, are returned as exactly that, so that
    what is aligned stays a plain degree of freedom.
    """
    if local_axes is None:
        return np.eye(3)
    aligned = _global_axis_of_each_local_axis(local_axes)
    if aligned is not None:
        rows = np.zeros((3, 3))
        for local, axis in enumerate(aligned):
            rows[local, axis] = 1.0
        return rows
    return np.array(local_axes, dtype=float)


def _reduce(rows) -> Tuple[np.ndarray, List[int]]:
    """The directions spanned by *rows*, reduced so that each has a pivot.

    Gauss-Jordan elimination with full pivoting: every row returned has 1 in
    a column where all the others have 0. Written as a constraint, that
    column is the degree of freedom the row makes depend on the rest, and no
    row uses the dependent one of another. A row with a single entry is a
    global direction.

    Returns:
        A ``(rank, 3)`` array and the pivot column of each of its rows.
    """
    work = np.array(rows, dtype=float).reshape(-1, 3).copy()
    reduced: List[np.ndarray] = []
    pivots: List[int] = []
    for _ in range(3):
        if work.size == 0:
            break
        i, j = np.unravel_index(int(np.argmax(np.abs(work))), work.shape)
        if abs(work[i, j]) < 1e-9:
            break
        pivot = work[i] / work[i, j]
        work = np.delete(work, i, axis=0)
        work = work - np.outer(work[:, j], pivot)
        reduced = [row - row[j] * pivot for row in reduced]
        reduced.append(pivot)
        pivots.append(int(j))
    result = np.array(reduced, dtype=float).reshape(-1, 3)
    result[np.abs(result) < 1e-9] = 0.0
    return result, pivots


def _reduced_rows(rows) -> np.ndarray:
    """The rows of ``_reduce`` without their pivots."""
    return _reduce(rows)[0]


def _across(rows) -> np.ndarray:
    """Orthonormal rows spanning the directions perpendicular to all of *rows*."""
    rows = np.array(rows, dtype=float).reshape(-1, 3)
    if rows.shape[0] == 0:
        return np.eye(3)
    _, singular, vh = np.linalg.svd(rows, full_matrices=True)
    rank = int((singular > 1e-9).sum())
    return vh[rank:]


def share_in_span(rows, direction) -> float:
    """How much of a unit *direction* lies in the span of *rows*, 0 to 1."""
    kept = _across(_across(rows))
    direction = np.array(direction, dtype=float)
    size = float(np.linalg.norm(direction))
    if kept.shape[0] == 0 or size < 1e-12:
        return 0.0
    return float(np.linalg.norm(kept @ (direction / size)))


def _is_skew(rows: np.ndarray) -> bool:
    """Whether any of some reduced rows is not a global direction."""
    return any(int(np.count_nonzero(row)) > 1 for row in rows)


def released_rotation_axes(connection, member_id: str) -> np.ndarray:
    """The axes a member is free to rotate about at a connection.

    The release comes from the member side of the connection
    (``IfcRelConnectsStructuralMember.AppliedCondition``), in the axes of
    that relation.

    Returns:
        A ``(k, 3)`` array of unit vectors in global coordinates; empty when
        the member has no release.
    """
    released = (getattr(connection, "released_dofs_by_member", None) or {}).get(
        member_id
    )
    rotations = sorted({dof - 4 for dof in released or [] if dof in (4, 5, 6)})
    if not rotations:
        return np.zeros((0, 3))
    if len(rotations) == 3:
        return np.eye(3)
    axes = (getattr(connection, "release_axes_by_member", None) or {}).get(member_id)
    return _global_rows(axes)[rotations]


def get_released_rotations(connection, member_id: str) -> Optional[List[int]]:
    """Return the global rotation DOFs (4-6) a member is released in at a connection.

    Returns:
        The released DOFs, empty when the member has no release, or None when
        a partial release is given in skew axes and has no global equivalent
        (``released_rotation_axes`` gives it as directions).
    """
    rows = _reduced_rows(released_rotation_axes(connection, member_id))
    if _is_skew(rows):
        return None
    return sorted(int(np.flatnonzero(row)[0]) + 4 for row in rows)


def support_restraint(connection) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """The directions a support holds, in global coordinates.

    The six flags of the support condition are in the connection's own axes
    (``local_axes``). A support that holds a single member cannot restrain a
    rotation that the member is released in (``released_rotation_axes``): a
    fully fixed support under a column with both bending rotations released
    is a pin that still resists torsion.

    A support at which the writer holds a member against spinning about a
    skew axis (``torsion_hold_axes``, set by
    ``UnifiedCalculixWriter._hold_spinning_members``) holds that rotation as
    well: it is analysed, written and reported as a support that does.

    Returns:
        Two arrays of reduced rows (see ``_reduced_rows``), the directions
        held in translation and the axes held in rotation, or None for a
        connection with no support condition. A row with one entry is a
        global degree of freedom; any other makes the support skew.
    """
    fixed = _local_fixity(connection)
    if fixed is None:
        return None
    if getattr(connection, "face", None) is not None:
        # The rotations of a surface's nodes are held by holding their
        # translations over its area; a face condition has none of its own
        fixed = fixed[:3] + [False, False, False]
    axes = _global_rows(getattr(connection, "local_axes", None))
    translations = axes[[i for i in range(3) if fixed[i]]]
    free = axes[[i for i in range(3) if not fixed[3 + i]]]
    members = list(getattr(connection, "connected_members", []))
    if len(members) == 1:
        free = np.vstack([free, released_rotation_axes(connection, members[0])])
    rotations = _across(free)
    held_by_the_writer = getattr(connection, "torsion_hold_axes", None)
    if held_by_the_writer:
        rotations = np.vstack([rotations, np.array(held_by_the_writer, dtype=float)])
    return _reduced_rows(translations), _reduced_rows(rotations)


def support_springs(
    connection,
) -> Tuple[List[Tuple[np.ndarray, float]], List[Tuple[np.ndarray, float]]]:
    """The elastic part of a support: the directions it holds with a spring.

    A stiffness in the support condition that is neither zero nor rigid
    (``_RIGID_STIFFNESS_THRESHOLD``) is a spring. It is per point, per length
    or per area as the connection is: N/m and N*m/rad at a point
    connection, N/m and N*m/rad per metre along a curve connection, N/m per
    square metre (a modulus of subgrade reaction) over a surface connection.

    A support holding a single member does not turn it about an axis the
    member is released in: a spring in series with a hinge holds nothing, as
    ``support_restraint`` leaves out a rigid rotation there.

    Returns:
        ``(translations, rotations)``, each a list of ``(unit direction in
        global coordinates, stiffness)``.

    Raises:
        AnalysisError: If a stiffness is negative, or a rotational spring
            lies partly about an axis the member is released in.
    """
    translations: List[Tuple[np.ndarray, float]] = []
    rotations: List[Tuple[np.ndarray, float]] = []
    has_stiffness = (
        hasattr(connection, "has_stiffness_properties")
        and connection.has_stiffness_properties()
    )
    if not has_stiffness:
        return translations, rotations
    stiff = connection.get_stiffness_properties() or {}
    axes = _global_rows(getattr(connection, "local_axes", None))
    members = list(getattr(connection, "connected_members", []))
    released = (
        released_rotation_axes(connection, members[0])
        if len(members) == 1
        else np.zeros((0, 3))
    )
    for index, key in enumerate(_STIFFNESS_KEYS):
        value = float(stiff.get(key, 0.0) or 0.0)
        if value < 0.0:
            raise AnalysisError(
                f"Support {connection.id} has a negative stiffness {key} = "
                f"{value}, which cannot be analysed.",
                code="E-SUP-008",
            )
        if value == 0.0 or value >= _RIGID_STIFFNESS_THRESHOLD:
            continue
        direction = axes[index % 3]
        if index < 3:
            translations.append((direction, value))
            continue
        share = share_in_span(released, direction) if len(released) else 0.0
        if share > 1.0 - 1e-6:
            continue
        if share > 1e-6:
            raise AnalysisError(
                f"Support {connection.id} has a rotational spring {key} about "
                "an axis that is partly one its member is released about, "
                "which cannot be analysed.",
                code="E-SUP-008",
            )
        rotations.append((direction, value))
    return translations, rotations


def support_resistance(connection) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """The directions a support resists at all: rigidly or with a spring.

    For the questions of stability (what can still move, what holds a member
    against spinning), where a spring holds as a rigid restraint does.
    ``support_restraint`` is what is written as a restraint.

    Returns:
        As ``support_restraint``, or None for a connection with no support
        condition.
    """
    restraint = support_restraint(connection)
    translations, rotations = support_springs(connection)
    if restraint is None and not translations and not rotations:
        return None
    held, turned = restraint if restraint is not None else (np.zeros((0, 3)),) * 2
    return (
        _reduced_rows(np.vstack([held] + [d for d, _ in translations])),
        _reduced_rows(np.vstack([turned] + [a for a, _ in rotations])),
    )


def support_is_skew(connection) -> bool:
    """True when a support condition cannot be written in global axes alone.

    That is the case when the connection's axes are rotated away from the
    global ones and the condition treats its three translations, or its three
    rotations, differently. A condition that fixes or frees all three alike is
    the same in any axes.
    """
    restraint = support_restraint(connection)
    return restraint is not None and (_is_skew(restraint[0]) or _is_skew(restraint[1]))


def rotation_arm(
    rotations: np.ndarray, drilling=None
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """How to hold the rotations of a skew support with a stiff arm.

    The nodes of CalculiX beams and shells have no rotations to restrain
    about an axis of one's choosing (``*EQUATION`` on DOF 4-6 does nothing).
    A stiff arm fixed to the node does it with translations: the tip of an
    arm along ``b`` moves by ``rotation x b``, so holding it along ``c``
    stops rotation about ``b x c`` and nothing else.

    A node that belongs to shells alone has no rotation about their normal:
    turning there moves nothing of the shell, and an arm fixed to the node
    would swing about it freely. That rotation is held along with the others
    (it took the in-plane displacements of a slab on skew line supports to
    hundreds of kilometres, with the right deflection).

    Args:
        rotations: The reduced rows of the axes held in rotation.
        drilling: The normal of the shells at a node of theirs alone.

    Returns:
        The unit direction of the arm, which is an axis the support leaves
        free, and the directions to hold its tip in, relative to the support
        node, as rows. None when the rotations held are global ones (or
        none, or all, with ``drilling`` or without), which ``*BOUNDARY`` does
        by itself.
    """
    if not _is_skew(rotations):
        return None
    if drilling is not None:
        rotations = np.vstack([rotations, np.array(drilling, dtype=float)])
    free = _across(rotations)
    if free.shape[0] == 0:
        return None
    arm = free[0]
    if free.shape[0] == 1:
        # Two axes held: the tip may not move across the arm at all
        return arm, _across([arm])
    # One axis held: the tip may not move along the other free axis
    return arm, free[1:2]


def get_constrained_dofs(connection) -> List[int]:
    """
    Return the CalculiX DOF numbers that are restrained outright at a support.

    Reads per-DOF stiffness from the connection's stiffness_properties dict
    (keys dx/dy/dz/drx/dry/drz).  A DOF is constrained when its
    stiffness >= _RIGID_STIFFNESS_THRESHOLD.  A connection with no stiffness
    properties restrains nothing, whatever its type.

    The stiffness keys are in the connection's own axes (``local_axes``); the
    DOF numbers returned are global:

        1=UX  2=UY  3=UZ  4=ROTX  5=ROTY  6=ROTZ

    A line support along global Y with ``drx`` fixed therefore restrains DOF 5,
    rotation about the edge. These are the DOFs written as ``*BOUNDARY``. A
    skew support (see ``support_is_skew``) also holds directions that are not
    global ones, which this leaves out: ``support_restraint`` has them all.
    Its rotations are held together by an arm (``rotation_arm``), so none of
    them is returned.
    """
    restraint = support_restraint(connection)
    if restraint is None:
        # No support condition, so no support: IFC expresses a support through
        # the connection's AppliedCondition, which is where the stiffness comes
        # from. A connection without one only joins its members.
        return []
    translations, rotations = restraint
    dofs = [
        int(np.flatnonzero(row)[0]) + 1
        for row in translations
        if np.count_nonzero(row) == 1
    ]
    if not _is_skew(rotations):
        dofs += [int(np.flatnonzero(row)[0]) + 4 for row in rotations]
    return sorted(dofs)


def support_equations(
    connection, node: int, arm_tip: Optional[int] = None, drilling=None
) -> List[List[Tuple[int, int, float]]]:
    """The equations that hold the skew directions of a support at one node.

    A direction that is not a global one is held by an equation between the
    node's own global translations, which leaves the meaning of every load
    and every other equation at the node as it is (``*TRANSFORM`` would
    change it). The reaction comes out as the solver's force at the node,
    like that of a ``*BOUNDARY``.

    Args:
        connection: The support.
        node: One of its mesh nodes.
        arm_tip: The node at the tip of the arm that holds its rotations
            (see ``rotation_arm``), when it has skew ones.
        drilling: The normal of the shells at a node of theirs alone.

    Returns:
        One list of ``(node, dof, coefficient)`` per equation, the dependent
        term first. A single term is a ``*BOUNDARY``: a tip direction that is
        a global one, on a node held in every translation, or the rotations
        of a shell node that are all held once ``drilling`` is.
    """
    restraint = support_restraint(connection)
    if restraint is None:
        return []
    translations, rotations = restraint
    equations = []
    for row, pivot in zip(*_reduce(translations)):
        if np.count_nonzero(row) > 1:
            equations.append(_terms(node, row, pivot))
    arm = rotation_arm(rotations, drilling)
    if arm is None and _is_skew(rotations):
        equations += [[(node, dof, 1.0)] for dof in (4, 5, 6)]
    if arm is not None and arm_tip is not None:
        for row, pivot in zip(*_reduce(arm[1])):
            terms = _terms(arm_tip, row, pivot)
            if translations.shape[0] < 3:
                terms += _terms(node, -row, pivot)
            equations.append(terms)
    return equations


def _terms(node: int, row: np.ndarray, pivot: int) -> List[Tuple[int, int, float]]:
    """A reduced row as equation terms on one node, the pivot first."""
    order = [pivot] + [i for i in range(3) if i != pivot]
    return [(node, i + 1, float(row[i])) for i in order if row[i] != 0.0]


def write_equation(file: TextIO, terms: List[Tuple[int, int, float]]) -> None:
    """Write one ``*EQUATION``; CalculiX takes at most four terms per line."""
    file.write(f"*EQUATION\n{len(terms)}\n")
    for start in range(0, len(terms), 4):
        file.write(
            ",".join(f"{n},{d},{coef:.9g}" for n, d, coef in terms[start : start + 4])
            + "\n"
        )


def write_boundary_conditions(
    file: TextIO,
    domain_model: StructuralModel,
    node_sets: Dict[str, List[int]],
    element_sets: Dict[str, List[int]],
    node_coords: Dict[int, Tuple[float, float, float]],
    rotation_arms: Optional[Dict[str, Dict[int, tuple]]] = None,
    springs: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    member_nodes: Optional[Dict[str, Collection[int]]] = None,
) -> set:
    """
    Write the supports of the model to the CalculiX input file.

    Every connection that restrains something becomes a node set and a
    ``*BOUNDARY`` card. The nodes of all supports are collected in
    ``ALL_BC_NODES``, which the steps use to print the reactions.

    A skew support holds directions that are not global ones. Those are
    written as equations (``support_equations``): between the translations of
    each of its nodes, and for rotations on the tip of a stiff arm the writer
    has fixed to the node. The tips are support nodes too, since part of the
    reaction arrives there.

    Args:
        file (TextIO): The file object to write to.
        domain_model (StructuralModel): The structural domain model.
        node_sets (Dict[str, List[int]]): Dictionary of node sets.
        element_sets (Dict[str, List[int]]): Dictionary of element sets.
        node_coords (Dict[int, Tuple[float, float, float]]): Dictionary of node coordinates.
        rotation_arms: For each support with skew rotations, the arm at each
            of its nodes, ``{support id: {node: (tip, position, drilling)}}``
            (see ``rotation_arm``; no tip where it needs no arm).
        springs: The springs of elastic supports, already written, by
            support (see ``UnifiedCalculixWriter._build_support_springs``).
            They are recorded with the support for its reactions, and their
            nodes are support nodes, so a model held by springs alone has
            supports.
        member_nodes: The nodes of the members each support holds, by
            support (see ``find_connection_support_nodes``).

    Returns:
        The ``(node, dof)`` pairs the equations make depend on others, which
        nothing else may restrain.

    Raises:
        AnalysisError: If a support has no mesh node to act on, or the model
            has no support at all. Neither is replaced by a guess: this
            function used to fix every node at y = 0 when it found no support.
    """
    file.write("** Boundary Conditions\n")

    all_bc_nodes = set()
    unattached = []
    dependent: set = set()
    # What each support restrains, for the reactions in the results
    domain_model.support_nodes = {}

    for connection in domain_model.connections:
        connection_id = connection.id
        set_name = f"BC_{connection_id}"

        restraint = support_restraint(connection)
        elastic = (springs or {}).get(connection_id) or []
        if elastic:
            spring_nodes = [s["spring_node"] for s in elastic]
            all_bc_nodes.update(spring_nodes)

        # A connection that restrains nothing only joins members
        if restraint is None or not (len(restraint[0]) or len(restraint[1])):
            if elastic:
                domain_model.support_nodes[connection_id] = {
                    "nodes": {},
                    "dofs": [],
                    "translations": [],
                    "rotations": [],
                    "springs": elastic,
                }
            continue
        dofs_to_fix = get_constrained_dofs(connection)

        bc_nodes = find_connection_support_nodes(connection, node_coords, member_nodes)
        if not bc_nodes and not getattr(connection, "connected_members", None):
            # It holds no member and lies on none: it supports nothing
            unattached.append(str(connection_id))
            continue
        if not bc_nodes:
            raise AnalysisError(
                f"Support {connection_id} cannot be applied: the mesh has no "
                f"node within {SUPPORT_TOLERANCE} m of its position "
                f"{[round(float(c), 4) for c in connection.position]}. Check "
                "that it lies on a member.",
                code="E-SUP-002",
            )

        arms = (rotation_arms or {}).get(connection_id, {})
        if _is_skew(restraint[1]) and not all(node in arms for node in bc_nodes):
            raise AnalysisError(
                f"Support {connection_id} cannot be applied: it restrains "
                "rotation about an axis that is not parallel to a global one, "
                "which takes a stiff arm at each of its nodes, and none was "
                "built. Arms cannot be used in a model with user elements.",
                code="E-SUP-009",
            )
        equations = []
        tips: Dict[int, tuple] = {}
        for node in bc_nodes:
            tip, position, drilling = arms.get(node, (None, None, None))
            equations += support_equations(connection, node, tip, drilling)
            if tip is not None:
                tips[tip] = position

        node_sets[set_name] = bc_nodes
        all_bc_nodes.update(bc_nodes)
        all_bc_nodes.update(tips)
        positions = {node: node_coords[node] for node in bc_nodes}
        positions.update(tips)
        domain_model.support_nodes[connection_id] = {
            "nodes": {
                int(node): tuple(float(c) for c in xyz)
                for node, xyz in positions.items()
            },
            "dofs": list(dofs_to_fix),
            "translations": restraint[0].tolist(),
            "rotations": restraint[1].tolist(),
        }
        if elastic:
            domain_model.support_nodes[connection_id]["springs"] = elastic

        file.write(f"*NSET, NSET={set_name}\n")
        for i in range(0, len(bc_nodes), 8):
            file.write(", ".join(map(str, bc_nodes[i : i + 8])) + "\n")

        if dofs_to_fix:
            # One line per contiguous range of degrees of freedom
            file.write("*BOUNDARY\n")
            first = prev = dofs_to_fix[0]
            for dof in dofs_to_fix[1:]:
                if dof != prev + 1:
                    file.write(f"{set_name}, {first}, {prev}\n")
                    first = dof
                prev = dof
            file.write(f"{set_name}, {first}, {prev}\n")
        if equations:
            file.write("** Directions it holds that are not global ones\n")
        for terms in equations:
            node, dof, _ = terms[0]
            if len(terms) == 1:
                file.write(f"*BOUNDARY\n{node}, {dof}, {dof}\n")
            else:
                write_equation(file, terms)
                dependent.add((node, dof))
        file.write("\n")

    if unattached:
        _warn_model(
            domain_model,
            "W-SUP-005",
            f"{len(unattached)} support(s) are connected to no member and lie "
            "on none; they support nothing and are left out: "
            + ", ".join(unattached[:5])
            + (", ..." if len(unattached) > 5 else ""),
            ifc_guids=guids_of(domain_model, unattached),
        )

    if not all_bc_nodes:
        raise AnalysisError(
            "The model has no supports: no connection has an AppliedCondition "
            "that restrains anything. It cannot be analysed.",
            code="E-SUP-001",
        )

    file.write("** Combined set of all nodes with boundary conditions\n")
    file.write("*NSET, NSET=ALL_BC_NODES\n")
    bc_nodes_list = sorted(all_bc_nodes)
    for i in range(0, len(bc_nodes_list), 8):
        file.write(", ".join(map(str, bc_nodes_list[i : i + 8])) + "\n")
    file.write("\n")
    node_sets["ALL_BC_NODES"] = bc_nodes_list
    return dependent


# Standard gravity, m/s². IFC gives self-weight as a share of the members'
# weight, not as an acceleration.
STANDARD_GRAVITY = 9.81


def _write_self_weight(
    file: TextIO,
    acceleration,
    u1_node_masses: Optional[Dict[int, float]] = None,
    has_u1_elements: bool = False,
) -> bool:
    """Write the weight of every member under an acceleration, in m/s².

    U1 user elements take no ``*DLOAD GRAV`` (CalculiX's body-force routine
    for them, e_c3d_u1.f, rejects it), so their weight is written as forces
    on their nodes: half of each element's mass at either end.

    Returns:
        Whether anything was written.
    """
    vector = np.array([float(value) for value in acceleration])
    size = float(np.linalg.norm(vector))
    if size < 1e-30:
        return False
    if not has_u1_elements:
        direction = vector / size
        file.write("*DLOAD\n")
        file.write(
            f"EALL, GRAV, {size:.6e}, {direction[0]:.6e}, {direction[1]:.6e}, "
            f"{direction[2]:.6e}\n\n"
        )
    if u1_node_masses:
        # The section forces of U1 elements are worked out with it
        note = getattr(file, "note_user_element_weight", None)
        if note is not None:
            note(vector)
        file.write("** Self-weight for U1 beam elements (equivalent nodal loads)\n")
        file.write("*CLOAD\n")
        for node_id, mass in sorted(u1_node_masses.items()):
            for dof_idx, val in enumerate(mass * vector):
                if abs(val) > 1e-30:
                    file.write(f"{node_id}, {dof_idx + 1}, {val:.6e}\n")
        file.write("\n")
    return True


def _self_weight_acceleration(load_case) -> np.ndarray:
    """Acceleration of the self-weight a load case includes, in m/s².

    ``IfcStructuralLoadCase.SelfWeightCoefficients`` are the shares of the
    members' weight the case includes along global x, y and z: ``(0, 0, -1)``
    is the whole weight, downwards.
    """
    coefficients = getattr(load_case, "self_weight_coefficients", None)
    if not coefficients:
        return np.zeros(3)
    return STANDARD_GRAVITY * np.array([float(c) for c in coefficients])


# Share of a uniform load carried by each node of an element, as fractions of
# the element's length or area, in CalculiX node order. These are the
# work-equivalent ("consistent") loads: a quadratic triangle carries nothing
# at its corners, and a quadratic quadrilateral pulls back at them.
_LINE_NODE_SHARES = {2: (1 / 2, 1 / 2), 3: (1 / 6, 2 / 3, 1 / 6)}
_SURFACE_NODE_SHARES = {
    3: (1 / 3,) * 3,
    6: (0.0,) * 3 + (1 / 3,) * 3,
    4: (1 / 4,) * 4,
    8: (-1 / 12,) * 4 + (1 / 3,) * 4,
}


def _element_measure_and_shares(
    elem: Dict, node_coords: Dict
) -> Optional[Tuple[float, Tuple[float, ...]]]:
    """Return an element's length or area and each node's share of a uniform load."""
    nodes = elem.get("nodes", [])
    try:
        coords = [np.array(node_coords[n], dtype=float) for n in nodes]
    except KeyError:
        return None
    is_surface = str(elem.get("type", "")).startswith("S")
    if is_surface and len(nodes) in _SURFACE_NODE_SHARES:
        corners = coords[: 3 if len(nodes) in (3, 6) else 4]
        area = 0.5 * float(
            np.linalg.norm(np.cross(corners[1] - corners[0], corners[2] - corners[0]))
        )
        if len(corners) == 4:
            area += 0.5 * float(
                np.linalg.norm(
                    np.cross(corners[2] - corners[0], corners[3] - corners[0])
                )
            )
        return area, _SURFACE_NODE_SHARES[len(nodes)]
    if not is_surface and len(nodes) in _LINE_NODE_SHARES:
        # Ends are first and last; a quadratic beam has its middle node second
        return (
            float(np.linalg.norm(coords[-1] - coords[0])),
            _LINE_NODE_SHARES[len(nodes)],
        )
    return None


def _distributed_load_to_nodal_forces(
    element_set_name: str,
    force_vector,
    element_sets: Dict[str, List[int]],
    elements_data: Dict[int, Dict],
    node_coords: Dict,
) -> Dict[int, List[float]]:
    """Turn a uniform distributed load on an element set into nodal forces.

    ``force_vector`` is the load per unit length (beams) or per unit area
    (shells) in global axes. CalculiX's own ``*DLOAD`` types act along the
    element's local axes (``P2`` on a beam, ``P`` normal to a shell), which
    cannot express a load given in global directions, so the work-equivalent
    nodal forces are computed here and written as ``*CLOAD``.

    Returns:
        Dict mapping node_id → [fx, fy, fz] accumulated nodal forces.
    """
    cloads: Dict[int, List[float]] = {}
    try:
        vector = np.array([float(force_vector[i]) for i in range(3)])
    except (TypeError, ValueError, IndexError):
        return cloads
    if float(np.linalg.norm(vector)) < 1e-30:
        return cloads

    for elem_id in element_sets.get(element_set_name, []):
        elem = elements_data.get(elem_id)
        if not elem:
            continue
        measured = _element_measure_and_shares(elem, node_coords)
        if measured is None:
            continue
        measure, shares = measured
        if measure < 1e-12:
            continue
        for nid, share in zip(elem["nodes"], shares):
            if share == 0.0:
                continue
            entry = cloads.setdefault(nid, [0.0, 0.0, 0.0])
            for i in range(3):
                entry[i] += vector[i] * measure * share

    return cloads


# Shape functions of a line element at a fraction of its length, in CalculiX
# node order (a quadratic beam has its middle node second)
_LINE_SHAPES = {
    2: lambda t: (1.0 - t, t),
    3: lambda t: (
        (1.0 - t) * (1.0 - 2.0 * t),
        4.0 * t * (1.0 - t),
        t * (2.0 * t - 1.0),
    ),
}
# Two-point Gauss rule on [0, 1]: exact for a quadratic shape function times a
# load that is linear
_GAUSS_POINTS = (0.5 - 0.5 / np.sqrt(3.0), 0.5 + 0.5 / np.sqrt(3.0))


# Five-point rule on [0, 1] for a load that is a half wave: exact for a
# parabola, and a sine wave on a single element across the whole member comes
# out right to seven figures
_WAVE_GAUSS = tuple(
    (0.5 + 0.5 * float(point), 0.5 * float(weight))
    for point, weight in zip(*np.polynomial.legendre.leggauss(5))
)


def _line_elements_along(
    element_set_name: str,
    start_position,
    end_position,
    element_sets: Dict[str, List[int]],
    elements_data: Dict[int, Dict],
    node_coords: Dict,
):
    """The line elements of a set, placed along the line of their member.

    Yields:
        ``(nodes, first, last)`` for each: its nodes in CalculiX order, and
        the distance of its first and of its last node from
        ``start_position`` towards ``end_position``.
    """
    origin = np.array(start_position, dtype=float)
    axis = np.array(end_position, dtype=float) - origin
    length = float(np.linalg.norm(axis))
    if length < 1e-12:
        return
    axis /= length

    for elem_id in element_sets.get(element_set_name, []):
        elem = elements_data.get(elem_id)
        nodes = (elem or {}).get("nodes", [])
        if len(nodes) not in _LINE_SHAPES or str(elem.get("type", "")).startswith("S"):
            continue
        try:
            first = float(
                (np.array(node_coords[nodes[0]], dtype=float) - origin) @ axis
            )
            last = float(
                (np.array(node_coords[nodes[-1]], dtype=float) - origin) @ axis
            )
        except KeyError:
            continue
        if abs(last - first) < 1e-12:
            continue
        yield nodes, first, last


def _add_element_forces(
    cloads: Dict[int, List[float]], nodes: List[int], forces: np.ndarray
) -> None:
    """Add the forces an element's nodes take of a load to those by node."""
    # A node the load gives nothing gets no line of rounding error
    forces[np.abs(forces) < 1e-12 * np.abs(forces).max(initial=0.0)] = 0.0
    for nid, force in zip(nodes, forces):
        if not force.any():
            continue
        entry = cloads.setdefault(nid, [0.0, 0.0, 0.0])
        for i in range(3):
            entry[i] += float(force[i])


def _varying_line_load_to_nodal_forces(
    element_set_name: str,
    samples: List[Tuple[float, np.ndarray]],
    start_position,
    end_position,
    element_sets: Dict[str, List[int]],
    elements_data: Dict[int, Dict],
    node_coords: Dict,
) -> Dict[int, List[float]]:
    """Turn a line load that varies along its member into nodal forces.

    ``samples`` are ``(distance from start_position, force per length in
    global axes)``: the load is linear between one and the next and there is
    none before the first or after the last, so it may cover part of the
    member. Each element takes the work-equivalent forces of the part of the
    load on it, integrated exactly whether or not the load starts, ends or
    changes slope at a node.

    Returns:
        Dict mapping node_id → [fx, fy, fz] accumulated nodal forces.
    """
    cloads: Dict[int, List[float]] = {}
    for nodes, first, last in _line_elements_along(
        element_set_name,
        start_position,
        end_position,
        element_sets,
        elements_data,
        node_coords,
    ):
        shapes = _LINE_SHAPES[len(nodes)]
        low, high = min(first, last), max(first, last)
        forces = np.zeros((len(nodes), 3))
        for (at_a, load_a), (at_b, load_b) in zip(samples, samples[1:]):
            lower, upper = max(low, at_a), min(high, at_b)
            if upper - lower < 1e-12 or at_b - at_a < 1e-12:
                continue
            for point in _GAUSS_POINTS:
                at = lower + point * (upper - lower)
                load = load_a + (load_b - load_a) * (at - at_a) / (at_b - at_a)
                weights = shapes((at - first) / (last - first))
                forces += 0.5 * (upper - lower) * np.outer(weights, load)
        _add_element_forces(cloads, nodes, forces)

    return cloads


def _half_wave_load_to_nodal_forces(
    element_set_name: str,
    half_wave: str,
    peak: np.ndarray,
    start_position,
    end_position,
    element_sets: Dict[str, List[int]],
    elements_data: Dict[int, Dict],
    node_coords: Dict,
) -> Dict[int, List[float]]:
    """Turn a line load that is a half wave over its member into nodal forces.

    ``half_wave`` is a key of ``HALF_WAVES`` (IFC's SINUS and PARABOLA) and
    ``peak`` the force per length at the middle of the member, in global
    axes; there is none at its ends. Each element takes the work-equivalent
    forces of the part of the wave on it.

    Returns:
        Dict mapping node_id → [fx, fy, fz] accumulated nodal forces.
    """
    cloads: Dict[int, List[float]] = {}
    wave = HALF_WAVES[half_wave]
    length = float(
        np.linalg.norm(
            np.array(end_position, dtype=float) - np.array(start_position, dtype=float)
        )
    )
    for nodes, first, last in _line_elements_along(
        element_set_name,
        start_position,
        end_position,
        element_sets,
        elements_data,
        node_coords,
    ):
        shapes = _LINE_SHAPES[len(nodes)]
        forces = np.zeros((len(nodes), 3))
        for point, weight in _WAVE_GAUSS:
            at = min(max(first + point * (last - first), 0.0), length)
            load = float(wave(at / length)) * peak
            forces += weight * abs(last - first) * np.outer(shapes(point), load)
        _add_element_forces(cloads, nodes, forces)

    return cloads


def _load_to_nodal_forces(
    load,
    element_set_name: str,
    domain_model: StructuralModel,
    element_sets: Dict[str, List[int]],
    elements_data: Dict[int, Dict],
    node_coords: Dict,
) -> Dict[int, List[float]]:
    """The nodal forces of a line or area load, in global axes, by node.

    Raises:
        AnalysisError: If the load is in the local axes of a member that has
            none (it was once applied in global axes, with a warning).
    """
    half_wave = getattr(load, "half_wave", None)
    if half_wave:
        return _half_wave_load_to_nodal_forces(
            element_set_name,
            half_wave,
            _in_global_axes(load, load.peak, domain_model),
            load.start_position,
            load.end_position,
            element_sets,
            elements_data,
            node_coords,
        )
    samples = getattr(load, "samples", None)
    if samples:
        return _varying_line_load_to_nodal_forces(
            element_set_name,
            [
                (float(at), _in_global_axes(load, vector, domain_model))
                for at, vector in samples
            ],
            load.start_position,
            load.end_position,
            element_sets,
            elements_data,
            node_coords,
        )
    return _distributed_load_to_nodal_forces(
        element_set_name,
        _in_global_axes(load, _get_validated_force_vector(load), domain_model),
        element_sets,
        elements_data,
        node_coords,
    )


def _in_global_axes(load, vector, domain_model: StructuralModel) -> np.ndarray:
    """``_to_global_axes``, for a load that is to be applied.

    Raises:
        AnalysisError: If the load is in the local axes of an item that has
            none: its direction is not known.
    """
    turned = _to_global_axes(load, vector, domain_model)
    if turned is None:
        raise AnalysisError(
            f"Load {getattr(load, 'id', '?')} is given in the local axes of "
            "an item that has none, so its direction is not known.",
            code="E-LOD-004",
            ifc_guids=guids_of(domain_model, [getattr(load, "id", "?")]),
        )
    return turned


def _global_force_vector(load, domain_model: StructuralModel) -> Optional[np.ndarray]:
    """Return a distributed load's force vector in global axes.

    Returns None when the load is in the axes of a member that has none.
    """
    return _to_global_axes(load, _get_validated_force_vector(load), domain_model)


def _to_global_axes(
    load, vector, domain_model: StructuralModel
) -> Optional[np.ndarray]:
    """Turn a force or moment of a load to global axes.

    A load given in local axes (``coordinate_system == "local"``, from IFC
    ``GlobalOrLocal``) is in those of the item it is assigned to: a member's
    ``local_axis``, or for a point load on a connection the connection's
    ``local_axes``, which for a point connection with no system of its own
    are the global ones. Returns None when the item has no axes.
    """
    vector = np.array(vector, dtype=float)
    if getattr(load, "coordinate_system", "global") != "local":
        return vector
    item_id = getattr(load, "member_reference", None) or getattr(
        load, "surface_reference", None
    )
    member = domain_model.get_member(item_id) if item_id else None
    axes = getattr(member, "local_axis", None)
    if member is None and item_id:
        connection = domain_model.get_connection(item_id)
        if connection is not None:
            axes = getattr(connection, "local_axes", None)
            if axes is None and getattr(connection, "edge", None) is None:
                return vector
    try:
        axes = np.array(axes, dtype=float)
    except (TypeError, ValueError):
        return None
    if axes.shape != (3, 3):
        return None
    return axes.T.dot(vector)


def _warn_model(
    domain_model: StructuralModel, code: str, message: str, **kwargs: Any
) -> None:
    """Log a warning and record it on the model for ``result["warnings"]``.

    ``code`` is one of ``utils.messages.KINDS``.
    """
    record_warning(domain_model, code, message, **kwargs)


# A component of a support displacement below this (m or rad) moves nothing
_NO_DISPLACEMENT = 1e-12


def support_displacement_values(
    domain_model: StructuralModel,
) -> Dict[Optional[str], Dict[Tuple[str, int], float]]:
    """The value each support displacement gives the DOFs of its support.

    Returns:
        ``{group id: {(support set, dof): value}}`` in metres and radians,
        global DOFs 1 to 6, for every load group with support displacements.
        ``write_boundary_conditions`` has to have run: the support's set and
        what it holds are taken from ``domain_model.support_nodes``.

    Raises:
        AnalysisError: If a displacement moves its support along a direction
            the support does not hold rigidly as a global DOF: one it leaves
            free (that would add a restraint), holds by a spring, or holds
            by equations because it is skew.
    """
    supports = getattr(domain_model, "support_nodes", None) or {}
    values: Dict[Optional[str], Dict[Tuple[str, int], float]] = {}
    for group in getattr(domain_model, "load_groups", None) or []:
        for displacement in getattr(group, "support_displacements", None) or ():
            connection = domain_model.get_connection(displacement.connection_id)
            record = supports.get(displacement.connection_id)
            if connection is None or record is None:
                raise AnalysisError(
                    f"Support displacement {displacement.id} moves connection "
                    f"{displacement.connection_id}, which is not a support of "
                    "the model.",
                    code="E-LOD-007",
                    ifc_guids=guids_of(
                        domain_model, [displacement.id, displacement.connection_id]
                    ),
                )
            vector = np.array(
                [*displacement.translation, *displacement.rotation], dtype=float
            )
            if displacement.coordinate_system == "local":
                # The support's own axes; a point connection with no system
                # of its own has the global ones
                axes = getattr(connection, "local_axes", None)
                if axes is not None:
                    axes = np.array(axes, dtype=float)
                    vector = np.concatenate([axes.T @ vector[:3], axes.T @ vector[3:]])
            held = set(record["dofs"])
            for index, value in enumerate(vector):
                dof = index + 1
                if abs(value) <= _NO_DISPLACEMENT:
                    continue
                if dof not in held:
                    rows = record["translations" if dof <= 3 else "rotations"]
                    axis = np.eye(3)[(dof - 1) % 3]
                    how = (
                        "holds it along a skew direction, by equations"
                        if rows and share_in_span(rows, axis) > 1 - 1e-9
                        else "does not hold it rigidly (it leaves it free or "
                        "holds it by a spring)"
                    )
                    raise AnalysisError(
                        f"Support displacement {displacement.id} moves support "
                        f"{displacement.connection_id} by {value:.6g} "
                        f"{'m' if dof <= 3 else 'rad'} along global DOF {dof}, "
                        f"and the support {how}. Only a direction a support "
                        "holds rigidly in global axes can be given a "
                        "displacement.",
                        code="E-LOD-007",
                        ifc_guids=guids_of(
                            domain_model,
                            [displacement.id, displacement.connection_id],
                        ),
                    )
                key = (f"BC_{displacement.connection_id}", dof)
                case = values.setdefault(group.id, {})
                case[key] = case.get(key, 0.0) + float(value)
    return values


def _write_support_displacements(
    file: TextIO,
    values: Dict[Optional[str], Dict[Tuple[str, int], float]],
    group_ids: Optional[Iterable[str]],
) -> None:
    """Give the supports the displacements of a step's load groups.

    A ``*BOUNDARY`` value stays in force in later steps, so every DOF that
    any group moves is written in every step, with zero where none of this
    step's groups moves it. ``group_ids`` None means all groups.
    """
    every = sorted({key for case in values.values() for key in case})
    if not every:
        return
    step: Dict[Tuple[str, int], float] = {}
    for group_id, case in values.items():
        if group_ids is None or group_id in group_ids:
            for key, value in case.items():
                step[key] = step.get(key, 0.0) + value
    file.write("** Support displacements (zero where this step moves none)\n")
    file.write("*BOUNDARY\n")
    for set_name, dof in every:
        file.write(f"{set_name}, {dof}, {dof}, {step.get((set_name, dof), 0.0):.9e}\n")
    file.write("\n")


def _write_temperatures(
    file: TextIO,
    temperatures: Optional[Dict[Optional[str], Dict[int, Tuple[float, ...]]]],
    group_ids: Optional[Iterable[str]],
) -> None:
    """Give the nodes the temperatures of a step's load groups.

    A temperature stays in force in later steps, so every node that any
    group heats is written in every step, zero where none of this step's
    groups heats it. ``group_ids`` None means all groups. The values are
    changes from the initial zero: the change of temperature, then the
    gradients CalculiX takes across a beam (along its section's 2 and 1
    axes) or a shell (along its normal), in K/m.
    """
    if not temperatures:
        return
    nodes = sorted({node for field in temperatures.values() for node in field})
    step: Dict[int, np.ndarray] = {}
    for group_id, field in temperatures.items():
        if group_ids is None or group_id in group_ids:
            for node, values in field.items():
                step[node] = step.get(node, np.zeros(3)) + np.array(values)
    file.write("** Temperatures (zero where this step heats nothing)\n")
    file.write("*TEMPERATURE\n")
    for node in nodes:
        t, g2, g1 = step.get(node, np.zeros(3))
        file.write(f"{node}, {t:.9e}, {g2:.9e}, {g1:.9e}\n")
    file.write("\n")


def _write_load_reset(file: TextIO) -> None:
    """Clear loads carried over from earlier steps.

    CalculiX keeps every load from previous steps active unless a card with
    ``OP=NEW`` removes them, so without this each load case would be reported
    as the sum of itself and all the cases before it.
    """
    file.write("** Each step is an independent load case\n")
    file.write("*CLOAD, OP=NEW\n")
    file.write("*DLOAD, OP=NEW\n\n")


def _write_step_output_requests(
    file: TextIO,
    has_u1_elements: bool = False,
    has_springs: bool = False,
) -> None:
    """Write standard output requests for a single analysis step.

    Beam section forces are not requested: CalculiX only writes them in its
    two-dimensional output mode, which loses shell bending stress. They are
    integrated from the stresses requested here (``analysis/section_forces``).

    Args:
        file: Output file handle.
        has_u1_elements: When True, suppress ``*EL FILE S, E`` — U1 Timoshenko
            beam elements do not support stress/strain output and CalculiX will
            segfault if it is requested on them.
        has_springs: When True, print the displacements of the springs' own
            nodes (``SPRING_NODES``), from which the reactions of elastic
            supports are worked out.
    """
    # RF in the result file is the force on every node of the solids that
    # beams and shells are expanded into: a support's moment is in those
    file.write("*NODE FILE\n")
    file.write("U, RF\n")
    # The force on each support node, and their total
    file.write("*NODE PRINT, NSET=ALL_BC_NODES, TOTALS=YES\n")
    file.write("RF\n")
    if has_springs:
        file.write("*NODE PRINT, NSET=SPRING_NODES\n")
        file.write("U\n")
    if not has_u1_elements:
        file.write("*EL FILE\n")
        file.write("S, E\n")
    file.write("*END STEP\n\n")


# The comment that introduces the nodal shares of moments per length
_DISTRIBUTED_MOMENTS = "** Distributed moments"
_POINT_LOADS = "** Point loads"


class _StepLoadRecorder:
    """Passes what is written on to the input file and notes each step's loads.

    CalculiX reports the force inside the structure at a support node, not
    the reaction: a load applied at that node in a restrained direction is
    missing from it, and one in a free direction appears in it. The loads on
    support nodes are needed to put that right, and reading them off what is
    written covers every path that writes one.

    A moment applied to a rotation that a support holds goes straight into
    the support. It is noted and not written: the solver has nothing to do
    with it, and says so in a warning of its own for each one.
    """

    def __init__(self, file: TextIO, held_rotations: Optional[set] = None):
        self._file = file
        self._pending = ""
        self._block = ""
        self._held_rotations = held_rotations or set()
        self._shares_follow = False
        self._shares = False
        self._points_follow = False
        self._points = False
        # One per step: {"nodal": {node: [fx, fy, fz, mx, my, mz, sx, sy,
        # sz, px, py, pz]}, "gravity": vector}; s is the node's share of
        # moments per length, p what of f is point loads. "elements" has
        # what each U1 element gives its two nodes of the loads along it,
        # and "user_weight" the acceleration of their self-weight
        self.steps: List[Dict[str, Any]] = []

    def note_element_loads(self, loads: Dict[int, np.ndarray]) -> None:
        """Note the shares of a load along a member that U1 elements give."""
        if not self.steps:
            return
        elements = self.steps[-1]["elements"]
        for element, values in loads.items():
            elements[element] = elements.get(element, np.zeros(12)) + values

    def note_user_element_weight(self, acceleration: np.ndarray) -> None:
        """Note the acceleration of the self-weight written for U1 elements."""
        if self.steps:
            step = self.steps[-1]
            step["user_weight"] = (
                acceleration
                if step["user_weight"] is None
                else step["user_weight"] + acceleration
            )

    def write(self, text: str) -> int:
        self._pending += text
        *lines, self._pending = self._pending.split("\n")
        for line in lines:
            if self._note(line.strip()):
                self._file.write(line + "\n")
        return len(text)

    def finish(self) -> None:
        """Write what has not ended in a new line yet."""
        if self._pending:
            if self._note(self._pending.strip()):
                self._file.write(self._pending)
            self._pending = ""

    def _note(self, line: str) -> bool:
        """Note what a line applies; False for a line that is not to be written."""
        if line.startswith(_DISTRIBUTED_MOMENTS):
            self._shares_follow = True
        if line.startswith(_POINT_LOADS):
            self._points_follow = True
        if not line or line.startswith("**"):
            return True
        if line.startswith("*"):
            self._block = line.split(",")[0].strip().upper()
            self._shares, self._shares_follow = self._shares_follow, False
            self._points, self._points_follow = self._points_follow, False
            if self._block == "*STEP":
                self.steps.append(
                    {"nodal": {}, "gravity": None, "elements": {}, "user_weight": None}
                )
            return True
        if not self.steps:
            return True
        step = self.steps[-1]
        parts = [part.strip() for part in line.split(",")]
        if self._block == "*CLOAD":
            node, dof, value = int(parts[0]), int(parts[1]), float(parts[2])
            # A node's share of a moment per length is noted apart: the
            # section forces at the end of the member have it already, as
            # the moment of a member loaded all along has, and the solver's
            # forces at the node do not
            if 1 <= dof <= 6:
                slot = dof + 2 if dof >= 4 and self._shares else dof - 1
                load = step["nodal"].setdefault(node, [0.0] * 12)
                load[slot] += value
                # A point force is noted a second time: at a support it
                # goes into the support and not into the member, where a
                # node's share of a load along a member is the member's
                if dof <= 3 and self._points:
                    load[dof + 8] += value
            return (node, dof) not in self._held_rotations
        if self._block == "*DLOAD" and len(parts) >= 6 and parts[1] == "GRAV":
            step["gravity"] = float(parts[2]) * np.array([float(v) for v in parts[3:6]])
        return True


def _weight_on_nodes(
    domain_model: StructuralModel,
    elements_data: Dict[int, Dict],
    node_coords: Dict,
    nodes: Optional[set],
    acceleration: np.ndarray,
) -> Dict[int, np.ndarray]:
    """Self-weight that ``*DLOAD GRAV`` puts on some nodes of the mesh.

    ``nodes`` of None means every node.

    CalculiX works it out on the solids it expands beams and shells into, and
    what reaches a node of the beam or shell is its work-equivalent share:
    the same shares as for any uniform load (measured on a cantilever, to
    four figures).
    """
    owners = getattr(domain_model, "analysis_element_to_member", None) or {}
    weights: Dict[int, np.ndarray] = {}
    per_measure: Dict[str, float] = {}
    for elem_id, elem in elements_data.items():
        if nodes is not None and not any(n in nodes for n in elem.get("nodes", [])):
            continue
        member_id = owners.get(elem_id)
        if member_id not in per_measure:
            member = domain_model.get_member(member_id) if member_id else None
            density = getattr(getattr(member, "material", None), "density", None)
            if getattr(member, "entity_type", None) == "curve":
                size = getattr(getattr(member, "section", None), "area", None)
            else:
                size = getattr(getattr(member, "thickness", None), "value", None)
            per_measure[member_id] = float(density or 0.0) * float(size or 0.0)
        measured = _element_measure_and_shares(elem, node_coords)
        if measured is None or not per_measure[member_id]:
            continue
        measure, shares = measured
        for node, share in zip(elem["nodes"], shares):
            if nodes is None or node in nodes:
                weights[node] = weights.get(node, np.zeros(3)) + (
                    per_measure[member_id] * measure * share * acceleration
                )
    return weights


def write_analysis_steps(
    file: TextIO,
    domain_model: Optional[StructuralModel] = None,
    analysis_type: str = "linear_static",
    short_id_map: Optional[Dict[str, str]] = None,
    element_sets: Optional[Dict[str, List[int]]] = None,
    node_coords: Optional[Dict[int, Tuple[float, float, float]]] = None,
    gravity: bool = False,
    gravity_direction: Optional[List[float]] = None,
    u1_node_masses: Optional[Dict[int, float]] = None,
    u1_element_sets: Optional[set] = None,
    elements_data: Optional[Dict[int, Dict]] = None,
    temperatures: Optional[Dict[Optional[str], Dict[int, Tuple[float, ...]]]] = None,
) -> None:
    """
    Write the analysis steps, and record the loads they put on support nodes.

    See ``_write_analysis_steps`` for the arguments. Afterwards
    ``domain_model.support_node_loads`` holds, for each step in order, the
    load applied directly at each support node, ``{node: [fx, fy, fz, mx,
    my, mz, sx, sy, sz, px, py, pz]}``: the results exporter takes it off
    what the solver reports there, and the moment off what the ends of the
    members give. ``s`` is the node's share of moments per length, which the
    ends of the members include and the solver's forces at the node do not.
    ``p`` is what of the force is point loads: a member's end has none of
    one that its support takes, and has the node's share of a load along
    the member.
    ``domain_model.applied_load_totals`` holds the whole load of each step,
    ``[fx, fy, fz]``, which the reactions have to balance, and
    ``domain_model.applied_load_moments`` its moment about the origin of the
    global axes, ``[mx, my, mz]``: that of the forces where they act and the
    moments applied, which the moments of the reactions have to balance.
    """
    supports = getattr(domain_model, "support_nodes", None)
    held_rotations = set()
    if isinstance(supports, dict):
        held_rotations = {
            (node, dof)
            for record in supports.values()
            for node in record["nodes"]
            for dof in record.get("dofs", ())
            if dof >= 4
        }
    recorder = _StepLoadRecorder(file, held_rotations)
    # Point loads moved to a node, gathered over the steps for one warning
    if domain_model is not None:
        domain_model._moved_point_loads = {}
    try:
        _write_analysis_steps(
            recorder,  # type: ignore[arg-type]
            domain_model,
            analysis_type,
            short_id_map,
            element_sets,
            node_coords,
            gravity,
            gravity_direction,
            u1_node_masses,
            u1_element_sets,
            elements_data,
            temperatures,
        )
    finally:
        moved = getattr(domain_model, "_moved_point_loads", None) or {}
        if domain_model is not None:
            del domain_model._moved_point_loads
    if moved:
        _warn_model(
            domain_model,
            "W-LOD-007",
            f"{len(moved)} point load(s) are further than {_POINT_LOAD_SNAP} m "
            "from any mesh node and are applied at the nearest one, up to "
            f"{max(moved.values()):.2f} m from where the file puts them. The "
            f"first are {', '.join(list(moved)[:5])}.",
            ifc_guids=guids_of(domain_model, moved),
        )
    recorder.finish()
    _record_user_element_loads(domain_model, recorder.steps)
    if not isinstance(supports, dict):
        return
    nodes = {node for record in supports.values() for node in record["nodes"]}
    recorded = []
    totals = []
    moments = []
    for step in recorder.steps:
        everywhere = {node: np.array(force) for node, force in step["nodal"].items()}
        if step["gravity"] is not None and elements_data and node_coords:
            for node, weight in _weight_on_nodes(
                domain_model, elements_data, node_coords, None, step["gravity"]
            ).items():
                everywhere[node] = everywhere.get(node, np.zeros(12)) + np.append(
                    weight, np.zeros(9)
                )
        recorded.append(
            {n: [float(v) for v in f] for n, f in everywhere.items() if n in nodes}
        )
        totals.append(
            [float(v) for v in sum(everywhere.values(), np.zeros(12))[:3]]  # type: ignore
        )
        # About the origin. Without the place of every loaded node there is
        # no such figure, and none is given
        about_origin: Optional[np.ndarray] = np.zeros(3)
        for node, load in everywhere.items():
            if not node_coords or node not in node_coords:
                about_origin = None
                break
            about_origin += (
                np.cross(np.array(node_coords[node], dtype=float), load[:3])
                + load[3:6]
                + load[6:9]
            )
        moments.append(
            None if about_origin is None else [float(v) for v in about_origin]
        )
    domain_model.support_node_loads = recorded
    domain_model.applied_load_totals = totals
    domain_model.applied_load_moments = moments


def _record_user_element_loads(
    domain_model: Optional[StructuralModel], steps: List[Dict[str, Any]]
) -> None:
    """Record what each U1 element gives its nodes of the loads, step by step.

    CalculiX gets the forces of U1 elements wrong, and the results parser
    works out their section forces from their stiffness and displacements
    (``user_element_section_forces``). A U1 element carries no load of its
    own: what acts along it is written as forces on its nodes, and its
    section forces are what the stiffness gives less its share of those.
    ``domain_model.user_element_loads`` has, for each step in order,
    ``{element: [fx, fy, fz, mx, my, mz] at its first node, then at its
    second}``, its self-weight included.
    """
    elements = getattr(domain_model, "user_elements", None)
    if not isinstance(elements, dict) or not elements:
        return
    recorded = []
    for step in steps:
        loads = {element: np.array(v, float) for element, v in step["elements"].items()}
        acceleration = step["user_weight"]
        if acceleration is not None:
            for element, record in elements.items():
                mass = float(record.get("mass_per_length") or 0.0)
                if not mass:
                    continue
                start, end = (np.array(p, dtype=float) for p in record["positions"])
                half = mass * float(np.linalg.norm(end - start)) / 2.0 * acceleration
                share = loads.setdefault(element, np.zeros(12))
                share[0:3] += half
                share[6:9] += half
        recorded.append({e: [float(v) for v in share] for e, share in loads.items()})
    domain_model.user_element_loads = recorded


def _note_user_element_loads(
    file: TextIO,
    load,
    element_set_name: str,
    domain_model: StructuralModel,
    element_sets: Dict[str, List[int]],
    elements_data: Dict[int, Dict],
    node_coords: Dict,
) -> None:
    """Pass on what each U1 element of a set gives its nodes of a load.

    Each element's share is worked out as the load's nodal forces and
    moments on a set of that element alone, so that the sum of them is what
    was written.
    """
    note = getattr(file, "note_element_loads", None)
    elements = getattr(domain_model, "user_elements", None)
    if note is None or not isinstance(elements, dict) or not elements:
        return
    shares: Dict[int, np.ndarray] = {}
    for element in element_sets.get(element_set_name, []):
        if element not in elements:
            continue
        alone = {element_set_name: [element]}
        forces = _load_to_nodal_forces(
            load, element_set_name, domain_model, alone, elements_data, node_coords
        )
        moments = _load_to_nodal_moments(
            load, element_set_name, domain_model, alone, elements_data, node_coords
        )
        values = np.zeros(12)
        for slot, node in zip((0, 6), elements[element]["nodes"]):
            values[slot : slot + 3] += forces.get(node, (0.0, 0.0, 0.0))
            values[slot + 3 : slot + 6] += moments.get(node, (0.0, 0.0, 0.0))
        shares[element] = values
    if shares:
        note(shares)


def _write_analysis_steps(
    file: TextIO,
    domain_model: Optional[StructuralModel] = None,
    analysis_type: str = "linear_static",
    short_id_map: Optional[Dict[str, str]] = None,
    element_sets: Optional[Dict[str, List[int]]] = None,
    node_coords: Optional[Dict[int, Tuple[float, float, float]]] = None,
    gravity: bool = False,
    gravity_direction: Optional[List[float]] = None,
    u1_node_masses: Optional[Dict[int, float]] = None,
    u1_element_sets: Optional[set] = None,
    elements_data: Optional[Dict[int, Dict]] = None,
    temperatures: Optional[Dict[Optional[str], Dict[int, Tuple[float, ...]]]] = None,
) -> None:
    """
    Write analysis step definitions to the CalculiX input file.

    When explicit load cases are present, writes one *STEP per load case plus
    an optional gravity step. Falls back to a single combined step when there
    are no load cases or for buckling analysis.

    Args:
        file (TextIO): The file object to write to.
        domain_model (Optional[StructuralModel]): The structural domain model.
        analysis_type (str): Type of analysis to perform. Default is "linear_static".
        short_id_map (Optional[Dict[str, str]]): Mapping from full IFC GUIDs to short IDs.
        element_sets (Optional[Dict[str, List[int]]]): Available element sets.
        node_coords: Dictionary of node coordinates for load placement.
        gravity (bool): Whether to include gravity load.
        gravity_direction (Optional[List[float]]): Gravity direction vector.
        u1_element_sets: Set of element set names that contain only U1 elements.
            *DLOAD is skipped for these sets because CalculiX treats P-type loads
            on unknown element types as facial loads, which crashes on U1.
        elements_data: Optional dict mapping element_id → element dict (with "nodes"
            key).  When provided, distributed loads on U1 sets are converted to
            work-equivalent *CLOAD nodal forces instead of being dropped.
        temperatures: ``{group id: {node: (T, gradient, gradient)}}``, the
            *TEMPERATURE values of each load group's temperature loads.
    """
    file.write("** Analysis Steps\n")

    # Linear buckling: a single *BUCKLE step carrying the reference loads.
    # CalculiX scales the loads defined *inside* the buckle step; the reported
    # buckling factor multiplies those loads. Loads placed in a preceding
    # *STATIC step are only a fixed preload, and a buckle step without loads of
    # its own returns meaningless factors (ifc_structural_mechanics-ziq).
    # U1 (Timoshenko) beam elements don't support *EL FILE S, E stress output.
    # BEAM_B31 present in element_sets (even if empty) signals that U1 elements exist.
    has_u1_elements = "BEAM_B31" in (element_sets or {})
    has_springs = any(
        "springs" in record
        for record in (getattr(domain_model, "support_nodes", None) or {}).values()
    )

    displacements = support_displacement_values(domain_model)

    if analysis_type == "linear_buckling":
        if displacements:
            moved = [
                d.id
                for g in domain_model.load_groups
                for d in getattr(g, "support_displacements", ())
            ]
            raise AnalysisError(
                f"The model has {len(moved)} support displacement(s) (the first "
                f"is {moved[0]}); a buckling analysis takes none: CalculiX "
                "scales the loads of the buckling step, not what its supports "
                "are given.",
                code="E-LOD-007",
                ifc_guids=guids_of(domain_model, moved),
            )
        if temperatures:
            heated = [
                t.id
                for g in domain_model.load_groups
                for t in getattr(g, "temperature_loads", ())
            ]
            raise AnalysisError(
                f"The model has {len(heated)} temperature load(s) (the first is "
                f"{heated[0]}); a buckling analysis takes none: CalculiX scales "
                "the loads of the buckling step, not its temperatures.",
                code="E-LOD-008",
                ifc_guids=guids_of(domain_model, heated),
            )
        file.write("*STEP\n")
        file.write("*BUCKLE\n")
        file.write("10\n\n")
        file.write("** Reference loads (buckling factor multiplies these)\n")
        loads_written = _write_validated_loads_within_step(
            file,
            domain_model,
            short_id_map,
            element_sets,
            node_coords,
            u1_element_sets=u1_element_sets,
            elements_data=elements_data,
        )
        # All the load cases act at once, and so does the weight in them
        acceleration = sum(
            (_self_weight_acceleration(g) for g in domain_model.load_groups),
            np.zeros(3),
        )
        if gravity:
            acceleration = acceleration + STANDARD_GRAVITY * np.array(
                gravity_direction or [0.0, 0.0, -1.0], dtype=float
            )
        if _write_self_weight(file, acceleration, u1_node_masses, has_u1_elements):
            loads_written = True
        if not loads_written:
            file.write("** CRITICAL WARNING: No loads written to buckle step\n\n")
        file.write("*NODE FILE\n")
        file.write("U\n")
        file.write("*END STEP\n\n")
        return

    # For linear static: use one step per load case if any exist
    load_cases = [
        g for g in domain_model.load_groups if g.is_load_case and g.has_actions
    ]

    if load_cases:
        # One step per load case
        for load_case in load_cases:
            file.write("*STEP\n")
            file.write("*STATIC\n")
            file.write("1.0, 1.0, 1.0e-5, 1.0\n\n")
            _write_load_reset(file)
            file.write(f"** Load Case: {load_case.name}\n")
            loads_written = _write_validated_loads_within_step(
                file,
                domain_model,
                short_id_map,
                element_sets,
                node_coords,
                target_group_id=load_case.id,
                u1_element_sets=u1_element_sets,
                elements_data=elements_data,
            )
            # The weight of the members the case includes
            if load_case.includes_self_weight:
                file.write("** Self-weight (SelfWeightCoefficients)\n")
                loads_written |= _write_self_weight(
                    file,
                    _self_weight_acceleration(load_case),
                    u1_node_masses,
                    has_u1_elements,
                )
            _write_support_displacements(file, displacements, [load_case.id])
            loads_written |= load_case.id in displacements
            _write_temperatures(file, temperatures, [load_case.id])
            loads_written |= load_case.id in (temperatures or {})
            if not loads_written:
                file.write(
                    f"** WARNING: No loads written for load case {load_case.name}\n\n"
                )
            _write_step_output_requests(
                file, has_u1_elements=has_u1_elements, has_springs=has_springs
            )

        # Gravity that was asked for is a load case of its own
        if gravity:
            file.write("*STEP\n")
            file.write("*STATIC\n")
            file.write("1.0, 1.0, 1.0e-5, 1.0\n\n")
            _write_load_reset(file)
            file.write("** Gravity (self-weight)\n")
            _write_self_weight(
                file,
                STANDARD_GRAVITY
                * np.array(gravity_direction or [0.0, 0.0, -1.0], dtype=float),
                u1_node_masses,
                has_u1_elements,
            )
            _write_support_displacements(file, displacements, [])
            _write_temperatures(file, temperatures, [])
            _write_step_output_requests(
                file, has_u1_elements=has_u1_elements, has_springs=has_springs
            )
    else:
        # No explicit load cases — single combined step (backward-compatible)
        file.write("*STEP\n")
        file.write("*STATIC\n")
        file.write("1.0, 1.0, 1.0e-5, 1.0\n\n")
        _write_load_reset(file)
        file.write("** Loads within step\n")
        loads_written = _write_validated_loads_within_step(
            file,
            domain_model,
            short_id_map,
            element_sets,
            node_coords,
            u1_element_sets=u1_element_sets,
            elements_data=elements_data,
        )
        if gravity:
            file.write("** Gravity (self-weight) load\n")
            loads_written |= _write_self_weight(
                file,
                STANDARD_GRAVITY
                * np.array(gravity_direction or [0.0, 0.0, -1.0], dtype=float),
                u1_node_masses,
                has_u1_elements,
            )
        _write_support_displacements(file, displacements, None)
        loads_written |= bool(displacements)
        _write_temperatures(file, temperatures, None)
        loads_written |= bool(temperatures)
        if not loads_written:
            file.write("** CRITICAL WARNING: No loads written to analysis step\n")
            file.write("** Analysis will execute but produce no meaningful results\n\n")
        _write_step_output_requests(
            file, has_u1_elements=has_u1_elements, has_springs=has_springs
        )


# Largest distance from a point support to the mesh node that takes it
SUPPORT_TOLERANCE = 0.1


def find_support_nodes(
    position: List[float],
    node_coords: Dict[int, Tuple[float, float, float]],
    tolerance: float = 0.1,
    coincidence: float = 1e-3,
    member_nodes: Optional[Collection[int]] = None,
) -> List[int]:
    """Find the mesh node(s) that a point support at *position* acts on.

    Returns the node nearest to *position*, provided it lies within
    *tolerance*, together with any node coincident with it (within
    *coincidence*). Beam and shell meshes keep separate nodes at the same
    location, so a support where a column meets a slab restrains both.
    Given *member_nodes*, the nodes of the members the support holds, only
    those of them are kept (``_held_by``): a support of a beam at the corner
    of a slab hinged to it does not clamp the slab's corner too.

    Unlike ``find_nodes_at_position`` this never returns a neighbouring mesh
    node. Taking every node inside the tolerance radius restrained two adjacent
    nodes whenever the element size was at or below the tolerance, which
    shortens the span and turns a pinned support into a clamped one.

    Args:
        position: The support position [x, y, z].
        node_coords: Dictionary of node coordinates.
        tolerance: Largest accepted distance from *position* to the nearest node.
        coincidence: Distance within which other nodes count as the same point.
        member_nodes: The nodes of the members the support holds, if known.

    Returns:
        Node IDs sorted ascending; empty if no node is within *tolerance*.
    """
    if not node_coords:
        return []
    ids = np.fromiter(node_coords.keys(), dtype=np.int64, count=len(node_coords))
    coords = np.array(list(node_coords.values()), dtype=float)
    distances = np.linalg.norm(coords - np.asarray(position, dtype=float), axis=1)
    nearest = int(np.argmin(distances))
    if distances[nearest] > tolerance:
        return []
    coincident = np.linalg.norm(coords - coords[nearest], axis=1) <= coincidence
    return _held_by(ids[coincident], member_nodes)


def _held_by(
    nodes: Iterable[int], member_nodes: Optional[Collection[int]]
) -> List[int]:
    """The *nodes* of the members a support holds, or all if none of them is.

    A support connected to no member, or to members none of whose nodes is
    there (one stopping short of it, the joint taken by a link), keeps every
    node it finds.
    """
    found = sorted(int(i) for i in nodes)
    if not member_nodes:
        return found
    held = [n for n in found if n in member_nodes]
    return held or found


def find_nodes_on_segment(
    start: List[float],
    end: List[float],
    node_coords: Dict[int, Tuple[float, float, float]],
    tolerance: float = 1e-3,
) -> List[int]:
    """Return the nodes lying on the straight segment from *start* to *end*."""
    if not node_coords:
        return []
    ids = np.fromiter(node_coords.keys(), dtype=np.int64, count=len(node_coords))
    coords = np.array(list(node_coords.values()), dtype=float)
    a = np.asarray(start, dtype=float)
    ab = np.asarray(end, dtype=float) - a
    length_sq = float(np.dot(ab, ab))
    if length_sq < 1e-18:
        return find_support_nodes(start, node_coords, tolerance=tolerance)
    t = np.clip((coords - a) @ ab / length_sq, 0.0, 1.0)
    distance = np.linalg.norm(coords - (a + np.outer(t, ab)), axis=1)
    return sorted(int(i) for i in ids[distance <= tolerance])


def find_nodes_in_face(
    face: List[List[float]],
    node_coords: Dict[int, Tuple[float, float, float]],
    tolerance: float = 1e-3,
) -> List[int]:
    """Return the nodes lying on a plane polygon, its outline included."""
    if not node_coords:
        return []
    corners = np.array(face, dtype=float).reshape(-1, 3)
    origin = corners.mean(axis=0)
    normal = np.zeros(3)
    for i in range(len(corners)):
        normal += np.cross(corners[i], corners[(i + 1) % len(corners)])
    normal = normal / np.linalg.norm(normal)
    u = corners[1] - corners[0]
    u = u - np.dot(u, normal) * normal
    u = u / np.linalg.norm(u)
    v = np.cross(normal, u)
    ids = np.fromiter(node_coords.keys(), dtype=np.int64, count=len(node_coords))
    coords = np.array(list(node_coords.values()), dtype=float) - origin
    near = np.abs(coords @ normal) <= tolerance
    points = np.stack([coords @ u, coords @ v], axis=1)
    polygon = np.stack([(corners - origin) @ u, (corners - origin) @ v], axis=1)
    inside = np.zeros(len(points), dtype=bool)
    on_outline = np.zeros(len(points), dtype=bool)
    for i in range(len(polygon)):
        a, b = polygon[i], polygon[(i + 1) % len(polygon)]
        # Crossings of a ray along +u
        straddles = (a[1] > points[:, 1]) != (b[1] > points[:, 1])
        with np.errstate(divide="ignore", invalid="ignore"):
            at = a[0] + (points[:, 1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
        inside ^= straddles & (points[:, 0] < at)
        ab = b - a
        t = np.clip((points - a) @ ab / float(ab @ ab), 0.0, 1.0)
        on_outline |= (
            np.linalg.norm(points - (a + np.outer(t, ab)), axis=1) <= tolerance
        )
    return sorted(int(i) for i in ids[near & (inside | on_outline)])


def find_connection_support_nodes(
    connection: Any,
    node_coords: Dict[int, Tuple[float, float, float]],
    member_nodes: Optional[Dict[str, Collection[int]]] = None,
) -> List[int]:
    """Return the mesh nodes a support connection restrains.

    A line support (``IfcStructuralCurveConnection``) carries its two end
    points in ``connection.edge`` and restrains every node along that edge; a
    surface support (``IfcStructuralSurfaceConnection``) has its outline in
    ``connection.face`` and restrains every node on it. A point support
    restrains the node at its position.

    Beam and shell meshes keep nodes of their own at one point, so a support
    finds the nodes of members it does not hold as well. Given
    *member_nodes*, ``{connection id: nodes of the members it holds}``, it
    keeps only those (``aiz.97``).
    """
    held = (member_nodes or {}).get(getattr(connection, "id", None))
    face = getattr(connection, "face", None)
    if face is not None:
        return _held_by(find_nodes_in_face(face, node_coords), held)
    edge = getattr(connection, "edge", None)
    if edge is not None and len(edge) == 2:
        # No node on the edge is no support; its midpoint is not a substitute
        return _held_by(find_nodes_on_segment(edge[0], edge[1], node_coords), held)
    position = getattr(connection, "position", None)
    if position is not None and len(position) == 3:
        return find_support_nodes(
            position, node_coords, tolerance=SUPPORT_TOLERANCE, member_nodes=held
        )
    return []


# The share of a uniform spring bed each node of an element takes, lumped by
# the diagonal of the element's consistent matrix (HRZ). The integrals of
# the shape functions, which spread a uniform load, give the corners of a
# six-node triangle nothing, and they would rest on no spring. Line nodes in
# CalculiX order: end, middle, end.
_LINE_SHARES = {2: (0.5, 0.5), 3: (1.0 / 6.0, 2.0 / 3.0, 1.0 / 6.0)}
_TRIANGLE_SHARES = {
    3: (1.0 / 3.0,) * 3,
    6: (3.0 / 57.0,) * 3 + (16.0 / 57.0,) * 3,
}
# The edges of a triangle, as positions in its node list, end to end
_TRIANGLE_EDGES = {
    3: ((0, 1), (1, 2), (2, 0)),
    6: ((0, 3, 1), (1, 4, 2), (2, 5, 0)),
}
# How far the length or area the springs of a support cover may be from that
# of its edge or face
_SPRING_COVER_TOLERANCE = 0.01


def spring_node_shares(
    connection: Any,
    nodes: List[int],
    elements: Dict[int, Dict],
    node_coords: Dict[int, Tuple[float, float, float]],
) -> Dict[int, float]:
    """The length or area of a support each of its nodes stands for.

    A spring condition is per point, per length or per area; what a node's
    spring gets is that times its share. At a point the share is 1, on one
    node (that of a curve member where beam and shell nodes meet there, since
    they are tied). Along an edge it is the length of the elements lying on
    it, curve members' if there are any, else the edges of shells; over a
    face it is the area of the shells inside it. Both are lumped as
    ``_LINE_SHARES`` and ``_TRIANGLE_SHARES`` say.

    Args:
        connection: The support.
        nodes: Its nodes (``find_connection_support_nodes``).
        elements: The mesh elements, ``{id: {"type", "nodes"}}``.
        node_coords: Node coordinates.

    Returns:
        ``{node: share}`` in 1, m or m².

    Raises:
        AnalysisError: If the elements found do not cover the edge or the
            face: a spring left off part of it is a softer support.
    """
    on = set(nodes)
    face = getattr(connection, "face", None)
    edge = getattr(connection, "edge", None)
    shares: Dict[int, float] = {}

    def at(node: int) -> np.ndarray:
        return np.array(node_coords[node], dtype=float)

    if face is not None:
        expected = polygon_area(face)
        covered = 0.0
        for elem in elements.values():
            weights = _TRIANGLE_SHARES.get(len(elem["nodes"]))
            if not str(elem.get("type", "")).startswith("S") or weights is None:
                continue
            if not all(n in on for n in elem["nodes"]):
                continue
            a, b, c = (at(n) for n in elem["nodes"][:3])
            area = 0.5 * float(np.linalg.norm(np.cross(b - a, c - a)))
            covered += area
            for node, weight in zip(elem["nodes"], weights):
                shares[node] = shares.get(node, 0.0) + weight * area
        what, unit = "area", "m²"
    elif edge is not None and len(edge) == 2:
        expected = float(
            np.linalg.norm(np.array(edge[1], float) - np.array(edge[0], float))
        )
        curves: Dict[frozenset, tuple] = {}
        shells: Dict[frozenset, tuple] = {}
        for elem in elements.values():
            elem_nodes = elem["nodes"]
            kind = str(elem.get("type", ""))
            if kind.startswith("S"):
                pieces = [
                    tuple(elem_nodes[i] for i in positions)
                    for positions in _TRIANGLE_EDGES.get(len(elem_nodes), ())
                ]
                found = shells
            else:
                pieces = [tuple(elem_nodes)]
                found = curves
            for piece in pieces:
                if len(piece) in _LINE_SHARES and all(n in on for n in piece):
                    # Two shells share an edge that lies inside a surface
                    found.setdefault(frozenset(piece), piece)
        covered = 0.0
        for piece in (curves or shells).values():
            length = float(np.linalg.norm(at(piece[-1]) - at(piece[0])))
            covered += length
            for node, weight in zip(piece, _LINE_SHARES[len(piece)]):
                shares[node] = shares.get(node, 0.0) + weight * length
        what, unit = "length", "m"
    else:
        curve_nodes = {
            n
            for elem in elements.values()
            if not str(elem.get("type", "")).startswith("S")
            for n in elem["nodes"]
        }
        on_curves = [n for n in sorted(nodes) if n in curve_nodes]
        return {(on_curves or sorted(nodes))[0]: 1.0} if nodes else {}

    if abs(covered - expected) > _SPRING_COVER_TOLERANCE * expected:
        raise AnalysisError(
            f"Support {connection.id} cannot be applied: it is elastic, and "
            f"the elements on it cover {covered:.4g} {unit} of its {what} of "
            f"{expected:.4g} {unit}. Check that it lies on its members.",
            code="E-SUP-008",
        )
    return shares


def polygon_area(points) -> float:
    """The area of a plane polygon given by its corners in 3D."""
    corners = np.array(points, dtype=float).reshape(-1, 3)
    total = np.zeros(3)
    for i in range(len(corners)):
        total += np.cross(corners[i], corners[(i + 1) % len(corners)])
    return 0.5 * float(np.linalg.norm(total))


def find_closest_node(
    position: List[float], node_coords: Dict[int, Tuple[float, float, float]]
) -> Optional[int]:
    """
    Find the closest node to a specific position.

    Args:
        position (List[float]): The position [x, y, z] to search near.
        node_coords (Dict[int, Tuple[float, float, float]]): Dictionary of node coordinates.

    Returns:
        Optional[int]: ID of the closest node, or None if no nodes exist.
    """
    if not node_coords:
        return None

    closest_node = None
    min_distance = float("inf")

    # Convert position to numpy array for easier calculations
    pos_array = np.array(position)

    for node_id, coords in node_coords.items():
        # Calculate distance
        dist = np.linalg.norm(pos_array - np.array(coords))

        # Update closest node if this one is closer
        if dist < min_distance:
            min_distance = dist
            closest_node = node_id

    return closest_node


def _nodes_of_curve_members(elements_data: Optional[Dict[int, Dict]]) -> set:
    """The nodes of beam elements: those a moment can be applied to."""
    return {
        node
        for element in (elements_data or {}).values()
        if not str(element.get("type", "")).startswith("S")
        for node in element.get("nodes", [])
    }


def _point_load_lines(
    load,
    node_coords: Optional[Dict[int, Tuple[float, float, float]]],
    domain_model: StructuralModel,
    elements_data: Optional[Dict[int, Dict]],
) -> List[str]:
    """The ``*CLOAD`` data lines of a point load: its force and its moment.

    A moment goes on rotations 4 to 6 of the node. CalculiX turns a beam
    node loaded that way into a knot, a rigid cross-section with a rotation
    of its own, and the moment arrives in the member as it should (measured
    at an end, between elements and at an element's middle node). A node of
    shells alone has no rotation about their normal.

    Raises:
        AnalysisError: For a moment at a node of no curve member, or a load
            in the local axes of an item that has none.
    """
    node_id = _determine_load_node(
        load, node_coords=node_coords, domain_model=domain_model
    )
    force = _get_validated_force_vector(load)
    moment = getattr(load, "moment", None)
    # In LOCAL_COORDS it is in the axes of the item it is assigned to
    force = _in_global_axes(load, force, domain_model)
    if moment is not None:
        moment = _in_global_axes(load, moment, domain_model)
    lines = [
        f"{node_id}, {i + 1}, {component:.6e}\n"
        for i, component in enumerate(force)
        if abs(component) > 1e-10
    ]
    if moment is not None and np.any(np.abs(moment) > 1e-10):
        if elements_data and node_id not in _nodes_of_curve_members(elements_data):
            raise AnalysisError(
                f"Point load {getattr(load, 'id', '?')} applies a moment where "
                "there is no curve member; moments on surface members are not "
                "supported.",
                code="E-LOD-005",
            )
        lines += [
            f"{node_id}, {i + 4}, {float(component):.6e}\n"
            for i, component in enumerate(moment)
            if abs(component) > 1e-10
        ]
    return lines


def _load_to_nodal_moments(
    load,
    element_set_name: str,
    domain_model: StructuralModel,
    element_sets: Dict[str, List[int]],
    elements_data: Dict[int, Dict],
    node_coords: Dict,
) -> Dict[int, List[float]]:
    """The nodal moments of a moment per length along a curve member.

    Each node takes the share of it that it takes of a force per length.

    Raises:
        AnalysisError: If the moment is in the axes of a member that has
            none, or on a surface member.
    """
    moment = getattr(load, "moment", None)
    if moment is None or not np.any(np.abs(moment) > 1e-30):
        return {}
    turned = _to_global_axes(load, moment, domain_model)
    if turned is None:
        raise AnalysisError(
            f"Load {getattr(load, 'id', '?')} applies a moment in the local axes "
            "of a member that has none.",
            code="E-LOD-004",
        )
    nodal = _distributed_load_to_nodal_forces(
        element_set_name, turned, element_sets, elements_data, node_coords
    )
    if set(nodal) - _nodes_of_curve_members(elements_data):
        raise AnalysisError(
            f"Load {getattr(load, 'id', '?')} applies a moment along a surface "
            "member; moments on surface members are not supported.",
            code="E-LOD-005",
        )
    return nodal


def _write_nodal_moments(file: TextIO, moments: Dict[int, List[float]]) -> bool:
    """Write nodal moments as ``*CLOAD`` on rotations 4 to 6."""
    if not moments:
        return False
    file.write(f"{_DISTRIBUTED_MOMENTS} (equivalent nodal moments)\n")
    file.write("*CLOAD\n")
    for node_id, values in sorted(moments.items()):
        for index, value in enumerate(values):
            if abs(value) > 1e-30:
                file.write(f"{node_id}, {index + 4}, {value:.6e}\n")
    file.write("\n")
    return True


def _add_nodal(total: Dict[int, List[float]], part: Dict[int, List[float]]) -> None:
    for node_id, values in part.items():
        entry = total.setdefault(node_id, [0.0, 0.0, 0.0])
        for i in range(3):
            entry[i] += values[i]


def _write_validated_loads_within_step(
    file: TextIO,
    domain_model: StructuralModel,
    short_id_map: Optional[Dict[str, str]] = None,
    element_sets: Optional[Dict[str, List[int]]] = None,
    node_coords: Optional[Dict[int, Tuple[float, float, float]]] = None,
    target_group_id: Optional[str] = None,
    u1_element_sets: Optional[set] = None,
    elements_data: Optional[Dict[int, Dict]] = None,
) -> bool:
    """
    Enhanced load writing with validation and deduplication.

    When ``target_group_id`` is given, only loads whose parent group ID matches
    are written (used for per-load-case steps).

    Args:
        u1_element_sets: Set of MEMBER_* names that contain U1 elements.
            *DLOAD is skipped for these because P-type loads on U1 crash CalculiX.

    Returns:
        bool: True if any loads were successfully written, False otherwise.
    """
    loads_written = False
    total_loads_attempted = 0
    written_load_ids = set()  # Track load IDs to avoid duplicates

    # Process load groups
    for load_group in domain_model.load_groups:
        # If we're writing a specific load case, skip non-matching groups
        if target_group_id is not None and load_group.id != target_group_id:
            continue
        if not load_group.loads:
            continue

        file.write(f"** Load Group: {load_group.name}\n")
        total_loads_attempted += len(load_group.loads)

        # Process point loads (use *CLOAD)
        point_loads = [load for load in load_group.loads if isinstance(load, PointLoad)]
        # Deduplicate: skip loads already written (from another load group)
        point_loads = [load for load in point_loads if load.id not in written_load_ids]
        if point_loads:
            file.write(f"{_POINT_LOADS}\n")
            file.write("*CLOAD\n")
            for load in point_loads:
                written_load_ids.add(load.id)
                for line in _point_load_lines(
                    load, node_coords, domain_model, elements_data
                ):
                    file.write(line)
                    loads_written = True
            file.write("\n")

        # FIXED: Process distributed loads (use *DLOAD with proper element set references)
        distributed_loads = [
            load for load in load_group.loads if not isinstance(load, PointLoad)
        ]
        if distributed_loads:
            # Accumulate equivalent CLOADs for U1 members; written after DLOAD block.
            u1_extra_cloads: Dict[int, List[float]] = {}
            nodal_moments: Dict[int, List[float]] = {}

            for load in distributed_loads:
                # FIXED: Find the appropriate element set for this load
                element_set_name = None

                # Strategy 1: Check if load has surface/member reference
                # Skip "default" or "default_surface" as these are placeholders
                if hasattr(load, "surface_reference") and load.surface_reference:
                    if load.surface_reference not in ("default", "default_surface"):
                        # Use short ID if available
                        if short_id_map and load.surface_reference in short_id_map:
                            element_set_name = (
                                f"MEMBER_{short_id_map[load.surface_reference]}"
                            )
                        else:
                            element_set_name = f"MEMBER_{load.surface_reference}"
                elif hasattr(load, "member_reference") and load.member_reference:
                    if load.member_reference not in ("default", "default_surface"):
                        # Use short ID if available
                        if short_id_map and load.member_reference in short_id_map:
                            element_set_name = (
                                f"MEMBER_{short_id_map[load.member_reference]}"
                            )
                        else:
                            element_set_name = f"MEMBER_{load.member_reference}"
                elif hasattr(load, "applied_to") and load.applied_to:
                    if load.applied_to not in ("default", "default_surface"):
                        # Use short ID if available
                        if short_id_map and load.applied_to in short_id_map:
                            element_set_name = f"MEMBER_{short_id_map[load.applied_to]}"
                        else:
                            element_set_name = f"MEMBER_{load.applied_to}"

                if not element_set_name:
                    raise AnalysisError(
                        f"Load {getattr(load, 'id', '?')} is not assigned to a "
                        "member of the model, so it cannot be applied.",
                        code="E-LOD-003",
                    )
                if not (elements_data and node_coords):
                    raise AnalysisError(
                        "Distributed loads need the mesh to be turned into "
                        "nodal forces, and no mesh was given.",
                        code="E-GEN-001",
                    )

                if element_set_name:
                    # A member another one overlaps has the elements in its
                    # geometry here (UnifiedCalculixWriter._load_element_sets),
                    # and a member with none stops the meshing
                    if element_sets and not element_sets.get(element_set_name):
                        raise AnalysisError(
                            f"Load {getattr(load, 'id', '?')} cannot be "
                            f"applied: its member ({element_set_name}) has no "
                            "elements in the mesh.",
                            code="E-GEN-001",
                        )
                    elif elements_data and node_coords:
                        # Global-direction nodal forces, written after this block
                        partial = _load_to_nodal_forces(
                            load,
                            element_set_name,
                            domain_model,
                            element_sets or {},
                            elements_data,
                            node_coords,
                        )
                        _add_nodal(u1_extra_cloads, partial)
                        _note_user_element_loads(
                            file,
                            load,
                            element_set_name,
                            domain_model,
                            element_sets or {},
                            elements_data,
                            node_coords,
                        )
                        _add_nodal(
                            nodal_moments,
                            _load_to_nodal_moments(
                                load,
                                element_set_name,
                                domain_model,
                                element_sets or {},
                                elements_data,
                                node_coords,
                            ),
                        )

            # Write the distributed loads as equivalent nodal forces
            if u1_extra_cloads:
                file.write("** Distributed loads (equivalent nodal forces)\n")
                file.write("*CLOAD\n")
                for node_id, forces in sorted(u1_extra_cloads.items()):
                    for dof_idx, val in enumerate(forces):
                        if abs(val) > 1e-30:
                            file.write(f"{node_id}, {dof_idx + 1}, {val:.6e}\n")
                file.write("\n")
                loads_written = True
            if _write_nodal_moments(file, nodal_moments):
                loads_written = True

    # Process loads directly on members (same fix applies)
    for member in domain_model.members:
        member_loads = getattr(member, "loads", [])
        if not member_loads:
            continue

        file.write(f"** Loads on member {member.id}\n")
        total_loads_attempted += len(member_loads)

        # Process point loads on members
        point_loads = [load for load in member_loads if isinstance(load, PointLoad)]
        point_loads = [load for load in point_loads if load.id not in written_load_ids]
        if point_loads:
            file.write(f"{_POINT_LOADS}\n")
            file.write("*CLOAD\n")
            for load in point_loads:
                written_load_ids.add(load.id)
                for line in _point_load_lines(
                    load, node_coords, domain_model, elements_data
                ):
                    file.write(line)
                    loads_written = True
            file.write("\n")

        # FIXED: Process distributed loads on members
        distributed_loads = [
            load for load in member_loads if not isinstance(load, PointLoad)
        ]
        if distributed_loads:
            # Use short ID for element set name
            if short_id_map and member.id in short_id_map:
                element_set_name = f"MEMBER_{short_id_map[member.id]}"
            else:
                element_set_name = f"MEMBER_{member.id}"

            if element_sets and not element_sets.get(element_set_name):
                raise AnalysisError(
                    f"The distributed loads on member {member.id} cannot be "
                    "applied: it has no elements in the mesh.",
                    code="E-GEN-001",
                )
            else:
                if elements_data and node_coords:
                    member_cloads: Dict[int, List[float]] = {}
                    member_moments: Dict[int, List[float]] = {}
                    for load in distributed_loads:
                        partial = _load_to_nodal_forces(
                            load,
                            element_set_name,
                            domain_model,
                            element_sets or {},
                            elements_data,
                            node_coords,
                        )
                        _add_nodal(member_cloads, partial)
                        _note_user_element_loads(
                            file,
                            load,
                            element_set_name,
                            domain_model,
                            element_sets or {},
                            elements_data,
                            node_coords,
                        )
                        _add_nodal(
                            member_moments,
                            _load_to_nodal_moments(
                                load,
                                element_set_name,
                                domain_model,
                                element_sets or {},
                                elements_data,
                                node_coords,
                            ),
                        )
                    if member_cloads:
                        file.write("*CLOAD\n")
                        for node_id, forces in sorted(member_cloads.items()):
                            for dof_idx, val in enumerate(forces):
                                if abs(val) > 1e-30:
                                    file.write(f"{node_id}, {dof_idx + 1}, {val:.6e}\n")
                        file.write("\n")
                        loads_written = True
                    if _write_nodal_moments(file, member_moments):
                        loads_written = True
                    continue
                raise AnalysisError(
                    "Distributed loads need the mesh to be turned into nodal "
                    "forces, and no mesh was given.",
                    code="E-GEN-001",
                )

    # Log results
    if total_loads_attempted > 0:
        if loads_written:
            logger.info(
                f"Successfully wrote loads from {total_loads_attempted} load definitions"
            )
        else:
            logger.warning(
                f"Attempted to write {total_loads_attempted} loads but none were successful"
            )
    else:
        logger.info("No loads to write in this step")

    return loads_written


def _determine_load_node(load, node_coords=None, domain_model=None) -> int:
    """Return the mesh node nearest a point load.

    A load that lands more than ``_POINT_LOAD_SNAP`` from its position is
    reported: it is still applied, at the node, but not where the file says.

    Raises:
        AnalysisError: If the load has no position or there is no mesh.
            A load is never sent to an arbitrary node.
    """
    load_id = getattr(load, "id", "?")
    position = getattr(load, "position", None)
    if position is None or not len(position):
        raise AnalysisError(
            f"Point load {load_id} cannot be applied: no position.", code="E-LOD-003"
        )
    closest = find_closest_node(position, node_coords) if node_coords else None
    if closest is None:
        raise AnalysisError(
            f"Point load {load_id} cannot be applied: there are no mesh nodes.",
            code="E-GEN-001",
        )
    distance = float(
        np.linalg.norm(np.array(position, float) - np.array(node_coords[closest]))
    )
    if distance > _POINT_LOAD_SNAP and domain_model is not None:
        moved = getattr(domain_model, "_moved_point_loads", None)
        if isinstance(moved, dict):
            moved[load_id] = distance
        else:
            _warn_model(
                domain_model,
                "W-LOD-007",
                f"Point load {load_id} is applied at the nearest mesh node, "
                f"{distance:.2f} m from its position.",
                ifc_guids=guids_of(domain_model, [load_id]),
            )
    return closest


# Distance a point load may be moved to reach a mesh node without comment
_POINT_LOAD_SNAP = 0.1


def _get_validated_force_vector(load) -> List[float]:
    """Return a load's force vector as three floats.

    Raises:
        AnalysisError: If the load has no usable force vector. A force is
            never made up.
    """
    try:
        force_vector = np.asarray(load.get_force_vector(), dtype=float).ravel()
    except (AttributeError, TypeError, ValueError) as error:
        raise AnalysisError(
            f"Load {getattr(load, 'id', '?')} has no usable force vector: {error}",
            code="E-LOD-006",
        ) from error
    if force_vector.size < 3 or not np.all(np.isfinite(force_vector[:3])):
        raise AnalysisError(
            f"Load {getattr(load, 'id', '?')} has no usable force vector: "
            f"{force_vector.tolist()}",
            code="E-LOD-006",
        )
    return [float(component) for component in force_vector[:3]]
