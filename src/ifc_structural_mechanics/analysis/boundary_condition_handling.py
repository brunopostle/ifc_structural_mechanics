"""
Enhanced boundary condition handling for the IFC Structural Mechanics Analysis package.

This module improves the boundary condition and load handling in the conversion process
from IFC structural models to CalculiX.
"""

import logging
from typing import Any, Dict, List, Optional, TextIO, Tuple

import numpy as np

from ..domain.load import PointLoad
from ..domain.structural_model import StructuralModel
from ..utils.error_handling import AnalysisError

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


def support_is_skew(connection) -> bool:
    """True when a support condition cannot be written in global axes.

    That is the case when the connection's axes are rotated away from the
    global ones and the condition treats its three translations, or its three
    rotations, differently. A condition that fixes or frees all three alike is
    the same in any axes.
    """
    fixed = _local_fixity(connection)
    local_axes = getattr(connection, "local_axes", None)
    if fixed is None or _global_axis_of_each_local_axis(local_axes) is not None:
        return False
    return len(set(fixed[:3])) > 1 or len(set(fixed[3:])) > 1


def get_released_rotations(connection, member_id: str) -> Optional[List[int]]:
    """Return the global rotation DOFs (4-6) a member is released in at a connection.

    The release comes from the member side of the connection
    (``IfcRelConnectsStructuralMember.AppliedCondition``) and is stored in the
    axes of that relation; this turns it into global DOF numbers.

    Returns:
        The released DOFs, empty when the member has no release, or None when
        a partial release is given in skew axes and has no global equivalent.
    """
    released = (getattr(connection, "released_dofs_by_member", None) or {}).get(
        member_id
    )
    if not released:
        return []
    if {4, 5, 6}.issubset(released):
        return [4, 5, 6]
    axes = (getattr(connection, "release_axes_by_member", None) or {}).get(member_id)
    global_axis = _global_axis_of_each_local_axis(axes)
    if global_axis is None:
        return None
    return sorted(global_axis[dof - 4] + 4 for dof in released if dof in (4, 5, 6))


def get_constrained_dofs(connection) -> List[int]:
    """
    Return the CalculiX DOF numbers that should be constrained for a connection.

    Reads per-DOF stiffness from the connection's stiffness_properties dict when
    available (keys dx/dy/dz/drx/dry/drz).  A DOF is constrained when its
    stiffness >= _RIGID_STIFFNESS_THRESHOLD.  A connection with no stiffness
    properties restrains nothing, whatever its type.

    The stiffness keys are in the connection's own axes (``local_axes``); the
    DOF numbers returned are global:

        1=UX  2=UY  3=UZ  4=ROTX  5=ROTY  6=ROTZ

    A line support along global Y with ``drx`` fixed therefore restrains DOF 5,
    rotation about the edge. Axes that are a permutation of the global ones are
    mapped exactly. A skew support (see ``support_is_skew``) is written as if
    its axes were global, and ``write_boundary_conditions`` warns about it.

    A support that holds a single member cannot restrain a rotation that the
    member is released in (``get_released_rotations``), so those DOFs are left
    out: a fully fixed support under a column with both bending rotations
    released is a pin that still resists torsion.
    """
    fixed = _local_fixity(connection)

    if fixed is not None:
        global_axis = _global_axis_of_each_local_axis(
            getattr(connection, "local_axes", None)
        ) or [0, 1, 2]
        dofs = set()
        for local, is_fixed in enumerate(fixed):
            if is_fixed:
                dofs.add(3 * (local // 3) + global_axis[local % 3] + 1)
        members = list(getattr(connection, "connected_members", []))
        if len(members) == 1:
            dofs -= set(get_released_rotations(connection, members[0]) or [])
        return sorted(dofs)

    # No support condition, so no support: IFC expresses a support through
    # the connection's AppliedCondition, which is where the stiffness comes
    # from. A connection without one only joins its members.
    return []


def write_boundary_conditions(
    file: TextIO,
    domain_model: StructuralModel,
    node_sets: Dict[str, List[int]],
    element_sets: Dict[str, List[int]],
    node_coords: Dict[int, Tuple[float, float, float]],
) -> None:
    """
    Write the supports of the model to the CalculiX input file.

    Every connection that restrains something becomes a node set and a
    ``*BOUNDARY`` card. The nodes of all supports are collected in
    ``ALL_BC_NODES``, which the steps use to print the reactions.

    Args:
        file (TextIO): The file object to write to.
        domain_model (StructuralModel): The structural domain model.
        node_sets (Dict[str, List[int]]): Dictionary of node sets.
        element_sets (Dict[str, List[int]]): Dictionary of element sets.
        node_coords (Dict[int, Tuple[float, float, float]]): Dictionary of node coordinates.

    Raises:
        AnalysisError: If a support has no mesh node to act on, or the model
            has no support at all. Neither is replaced by a guess: this
            function used to fix every node at y = 0 when it found no support.
    """
    file.write("** Boundary Conditions\n")

    all_bc_nodes = set()
    unattached = []
    # What each support restrains, for the reactions in the results
    domain_model.support_nodes = {}

    for connection in domain_model.connections:
        connection_id = connection.id
        set_name = f"BC_{connection_id}"

        dofs_to_fix = get_constrained_dofs(connection)

        # A connection that restrains nothing only joins members
        if not dofs_to_fix:
            continue

        if support_is_skew(connection):
            _warn_model(
                domain_model,
                f"Support {connection_id} restrains only some directions, in "
                "axes that are not parallel to the global ones. Skew supports "
                "are not modelled: it is analysed as if its axes were global.",
            )

        bc_nodes = find_connection_support_nodes(connection, node_coords)
        if not bc_nodes and not getattr(connection, "connected_members", None):
            # It holds no member and lies on none: it supports nothing
            unattached.append(str(connection_id))
            continue
        if not bc_nodes:
            raise AnalysisError(
                f"Support {connection_id} cannot be applied: the mesh has no "
                f"node within {SUPPORT_TOLERANCE} m of its position "
                f"{[round(float(c), 4) for c in connection.position]}. Check "
                "that it lies on a member."
            )

        node_sets[set_name] = bc_nodes
        all_bc_nodes.update(bc_nodes)
        domain_model.support_nodes[connection_id] = {
            "nodes": {
                int(node): tuple(float(c) for c in node_coords[node])
                for node in bc_nodes
            },
            "dofs": list(dofs_to_fix),
        }

        file.write(f"*NSET, NSET={set_name}\n")
        for i in range(0, len(bc_nodes), 8):
            file.write(", ".join(map(str, bc_nodes[i : i + 8])) + "\n")

        # One line per contiguous range of degrees of freedom
        file.write("*BOUNDARY\n")
        first = prev = dofs_to_fix[0]
        for dof in dofs_to_fix[1:]:
            if dof != prev + 1:
                file.write(f"{set_name}, {first}, {prev}\n")
                first = dof
            prev = dof
        file.write(f"{set_name}, {first}, {prev}\n\n")

    if unattached:
        _warn_model(
            domain_model,
            f"{len(unattached)} support(s) are connected to no member and lie "
            "on none; they support nothing and are left out: "
            + ", ".join(unattached[:5])
            + (", ..." if len(unattached) > 5 else ""),
        )

    if not all_bc_nodes:
        raise AnalysisError(
            "The model has no supports: no connection has an AppliedCondition "
            "that restrains anything. It cannot be analysed."
        )

    file.write("** Combined set of all nodes with boundary conditions\n")
    file.write("*NSET, NSET=ALL_BC_NODES\n")
    bc_nodes_list = sorted(all_bc_nodes)
    for i in range(0, len(bc_nodes_list), 8):
        file.write(", ".join(map(str, bc_nodes_list[i : i + 8])) + "\n")
    file.write("\n")
    node_sets["ALL_BC_NODES"] = bc_nodes_list


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


def _global_force_vector(load, domain_model: StructuralModel) -> Optional[np.ndarray]:
    """Return a distributed load's force vector in global axes.

    A load given in the member's own axes (``coordinate_system == "local"``,
    from IFC ``GlobalOrLocal``) is rotated with the member's ``local_axis``.
    Returns None when that is needed and the member has no axes.
    """
    vector = np.array(_get_validated_force_vector(load), dtype=float)
    if getattr(load, "coordinate_system", "global") != "local":
        return vector
    member_id = getattr(load, "member_reference", None) or getattr(
        load, "surface_reference", None
    )
    member = domain_model.get_member(member_id) if member_id else None
    axes = getattr(member, "local_axis", None)
    try:
        axes = np.array(axes, dtype=float)
    except (TypeError, ValueError):
        return None
    if axes.shape != (3, 3):
        return None
    return axes.T.dot(vector)


def _warn_model(domain_model: StructuralModel, message: str) -> None:
    """Log a warning and record it on the model for ``result["warnings"]``."""
    logger.warning(message)
    if not hasattr(domain_model, "analysis_warnings"):
        domain_model.analysis_warnings = []
    domain_model.analysis_warnings.append(
        {
            "message": message,
            "severity": "warning",
            "entity_type": None,
            "ccx_id": None,
            "domain_id": None,
        }
    )


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
    """
    file.write("*NODE FILE\n")
    file.write("U\n")
    # The force on each support node, and their total
    file.write("*NODE PRINT, NSET=ALL_BC_NODES, TOTALS=YES\n")
    file.write("RF\n")
    if not has_u1_elements:
        file.write("*EL FILE\n")
        file.write("S, E\n")
    file.write("*END STEP\n\n")


class _StepLoadRecorder:
    """Passes what is written on to the input file and notes each step's loads.

    CalculiX reports the force inside the structure at a support node, not
    the reaction: a load applied at that node in a restrained direction is
    missing from it, and one in a free direction appears in it. The loads on
    support nodes are needed to put that right, and reading them off what is
    written covers every path that writes one.
    """

    def __init__(self, file: TextIO):
        self._file = file
        self._pending = ""
        self._block = ""
        # One per step: {"nodal": {node: [fx, fy, fz]}, "gravity": vector}
        self.steps: List[Dict[str, Any]] = []

    def write(self, text: str) -> int:
        self._pending += text
        *lines, self._pending = self._pending.split("\n")
        for line in lines:
            self._note(line.strip())
        return self._file.write(text)

    def _note(self, line: str) -> None:
        if not line or line.startswith("**"):
            return
        if line.startswith("*"):
            self._block = line.split(",")[0].strip().upper()
            if self._block == "*STEP":
                self.steps.append({"nodal": {}, "gravity": None})
            return
        if not self.steps:
            return
        step = self.steps[-1]
        parts = [part.strip() for part in line.split(",")]
        if self._block == "*CLOAD":
            node, dof, value = int(parts[0]), int(parts[1]), float(parts[2])
            if 1 <= dof <= 3:
                step["nodal"].setdefault(node, [0.0, 0.0, 0.0])[dof - 1] += value
        elif self._block == "*DLOAD" and len(parts) >= 6 and parts[1] == "GRAV":
            step["gravity"] = float(parts[2]) * np.array([float(v) for v in parts[3:6]])


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
) -> None:
    """
    Write the analysis steps, and record the loads they put on support nodes.

    See ``_write_analysis_steps`` for the arguments. Afterwards
    ``domain_model.support_node_loads`` holds, for each step in order, the
    load applied directly at each support node, ``{node: [fx, fy, fz]}``:
    the results exporter takes it off what the solver reports there.
    ``domain_model.applied_load_totals`` holds the whole load of each step,
    ``[fx, fy, fz]``, which the reactions have to balance.
    """
    recorder = _StepLoadRecorder(file)
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
    )
    supports = getattr(domain_model, "support_nodes", None)
    if not isinstance(supports, dict):
        return
    nodes = {node for record in supports.values() for node in record["nodes"]}
    recorded = []
    totals = []
    for step in recorder.steps:
        everywhere = {node: np.array(force) for node, force in step["nodal"].items()}
        if step["gravity"] is not None and elements_data and node_coords:
            for node, weight in _weight_on_nodes(
                domain_model, elements_data, node_coords, None, step["gravity"]
            ).items():
                everywhere[node] = everywhere.get(node, np.zeros(3)) + weight
        recorded.append(
            {n: [float(v) for v in f] for n, f in everywhere.items() if n in nodes}
        )
        totals.append(
            [float(v) for v in sum(everywhere.values(), np.zeros(3))]  # type: ignore
        )
    domain_model.support_node_loads = recorded
    domain_model.applied_load_totals = totals


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

    if analysis_type == "linear_buckling":
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
            if not loads_written:
                file.write(
                    f"** WARNING: No loads written for load case {load_case.name}\n\n"
                )
            _write_step_output_requests(file, has_u1_elements=has_u1_elements)

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
            _write_step_output_requests(file, has_u1_elements=has_u1_elements)
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
        if not loads_written:
            file.write("** CRITICAL WARNING: No loads written to analysis step\n")
            file.write("** Analysis will execute but produce no meaningful results\n\n")
        _write_step_output_requests(file, has_u1_elements=has_u1_elements)


# Largest distance from a point support to the mesh node that takes it
SUPPORT_TOLERANCE = 0.1


def find_support_nodes(
    position: List[float],
    node_coords: Dict[int, Tuple[float, float, float]],
    tolerance: float = 0.1,
    coincidence: float = 1e-3,
) -> List[int]:
    """Find the mesh node(s) that a point support at *position* acts on.

    Returns the node nearest to *position*, provided it lies within
    *tolerance*, together with any node coincident with it (within
    *coincidence*). Beam and shell meshes keep separate nodes at the same
    location, so a support where a column meets a slab restrains both.

    Unlike ``find_nodes_at_position`` this never returns a neighbouring mesh
    node. Taking every node inside the tolerance radius restrained two adjacent
    nodes whenever the element size was at or below the tolerance, which
    shortens the span and turns a pinned support into a clamped one.

    Args:
        position: The support position [x, y, z].
        node_coords: Dictionary of node coordinates.
        tolerance: Largest accepted distance from *position* to the nearest node.
        coincidence: Distance within which other nodes count as the same point.

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
    return sorted(int(i) for i in ids[coincident])


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


def find_connection_support_nodes(
    connection: Any, node_coords: Dict[int, Tuple[float, float, float]]
) -> List[int]:
    """Return the mesh nodes a support connection restrains.

    A line support (``IfcStructuralCurveConnection``) carries its two end
    points in ``connection.edge`` and restrains every node along that edge. A
    point support restrains the node at its position.
    """
    edge = getattr(connection, "edge", None)
    if edge is not None and len(edge) == 2:
        # No node on the edge is no support; its midpoint is not a substitute
        return find_nodes_on_segment(edge[0], edge[1], node_coords)
    position = getattr(connection, "position", None)
    if position is not None and len(position) == 3:
        return find_support_nodes(position, node_coords, tolerance=SUPPORT_TOLERANCE)
    return []


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
            file.write("*CLOAD\n")
            for load in point_loads:
                written_load_ids.add(load.id)

                # Position-based node determination
                node_id = _determine_load_node(
                    load, node_coords=node_coords, domain_model=domain_model
                )

                # Enhanced force vector validation
                force_vector = _get_validated_force_vector(load)

                # Write load components
                for i, component in enumerate(force_vector):
                    if abs(component) > 1e-10:  # Only write significant forces
                        file.write(f"{node_id}, {i+1}, {component:.6e}\n")
                        loads_written = True
            file.write("\n")

        # FIXED: Process distributed loads (use *DLOAD with proper element set references)
        distributed_loads = [
            load for load in load_group.loads if not isinstance(load, PointLoad)
        ]
        if distributed_loads:
            # Accumulate equivalent CLOADs for U1 members; written after DLOAD block.
            u1_extra_cloads: Dict[int, List[float]] = {}

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
                        "member of the model, so it cannot be applied."
                    )
                if not (elements_data and node_coords):
                    raise AnalysisError(
                        "Distributed loads need the mesh to be turned into "
                        "nodal forces, and no mesh was given."
                    )

                if element_set_name:
                    # Check if this element set actually exists and is
                    # non-empty (may be empty if the member was merged during
                    # fragment, or lost all its elements to an overlapping
                    # member during overlap resolution) — an empty set has no
                    # corresponding *ELSET card in the file.
                    if element_sets and not element_sets.get(element_set_name):
                        _warn_model(
                            domain_model,
                            f"Load {getattr(load, 'id', 'unknown')} is not "
                            f"applied: its member ({element_set_name}) has no "
                            "elements, having lost its geometry to a member "
                            "it overlaps.",
                        )
                    elif elements_data and node_coords:
                        # Global-direction nodal forces, written after this block
                        vector = _global_force_vector(load, domain_model)
                        if vector is None:
                            _warn_model(
                                domain_model,
                                f"Load {getattr(load, 'id', '?')} is given in the "
                                "local axes of a member that has none; it is "
                                "applied in global axes.",
                            )
                            vector = _get_validated_force_vector(load)
                        partial = _distributed_load_to_nodal_forces(
                            element_set_name,
                            vector,
                            element_sets or {},
                            elements_data,
                            node_coords,
                        )
                        for nid, fvec in partial.items():
                            entry = u1_extra_cloads.setdefault(nid, [0.0, 0.0, 0.0])
                            entry[0] += fvec[0]
                            entry[1] += fvec[1]
                            entry[2] += fvec[2]

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
            file.write("*CLOAD\n")
            for load in point_loads:
                written_load_ids.add(load.id)
                node_id = _determine_load_node(
                    load, node_coords=node_coords, domain_model=domain_model
                )
                force_vector = _get_validated_force_vector(load)

                for i, component in enumerate(force_vector):
                    if abs(component) > 1e-10:
                        file.write(f"{node_id}, {i+1}, {component:.6e}\n")
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

            # Skip if element set doesn't exist or is empty (member merged
            # during fragment, or lost all elements during overlap resolution)
            if element_sets and not element_sets.get(element_set_name):
                _warn_model(
                    domain_model,
                    f"The distributed loads on member {member.id} are not "
                    "applied: it has no elements, having lost its geometry to "
                    "a member it overlaps.",
                )
            else:
                if elements_data and node_coords:
                    member_cloads: Dict[int, List[float]] = {}
                    for load in distributed_loads:
                        vector = _global_force_vector(load, domain_model)
                        if vector is None:
                            vector = _get_validated_force_vector(load)
                        partial = _distributed_load_to_nodal_forces(
                            element_set_name,
                            vector,
                            element_sets or {},
                            elements_data,
                            node_coords,
                        )
                        for nid, fvec in partial.items():
                            entry = member_cloads.setdefault(nid, [0.0, 0.0, 0.0])
                            for i in range(3):
                                entry[i] += fvec[i]
                    if member_cloads:
                        file.write("*CLOAD\n")
                        for node_id, forces in sorted(member_cloads.items()):
                            for dof_idx, val in enumerate(forces):
                                if abs(val) > 1e-30:
                                    file.write(f"{node_id}, {dof_idx + 1}, {val:.6e}\n")
                        file.write("\n")
                        loads_written = True
                    continue
                raise AnalysisError(
                    "Distributed loads need the mesh to be turned into nodal "
                    "forces, and no mesh was given."
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
        logger.warning("No loads found in domain model")

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
        raise AnalysisError(f"Point load {load_id} cannot be applied: no position.")
    closest = find_closest_node(position, node_coords) if node_coords else None
    if closest is None:
        raise AnalysisError(
            f"Point load {load_id} cannot be applied: there are no mesh nodes."
        )
    distance = float(
        np.linalg.norm(np.array(position, float) - np.array(node_coords[closest]))
    )
    if distance > _POINT_LOAD_SNAP and domain_model is not None:
        _warn_model(
            domain_model,
            f"Point load {load_id} is applied at the nearest mesh node, "
            f"{distance:.2f} m from its position.",
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
            f"Load {getattr(load, 'id', '?')} has no usable force vector: {error}"
        ) from error
    if force_vector.size < 3 or not np.all(np.isfinite(force_vector[:3])):
        raise AnalysisError(
            f"Load {getattr(load, 'id', '?')} has no usable force vector: "
            f"{force_vector.tolist()}"
        )
    return [float(component) for component in force_vector[:3]]
