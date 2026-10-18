"""The files of an analysis, read for drawing.

An output directory of ``analyze_ifc()`` holds what a picture needs:

- ``analysis.inp``, the mesh as written: beams and shells, the elements of
  each member (a ``** Member <id>`` comment names each member's set), the
  nodes of each support (``BC_<id>``) and the nodal forces of each step;
- ``analysis.frd``, the solver's results, on the solids CalculiX expands the
  beams and shells into. Each solid keeps the number of the element it came
  from, and each of its nodes belongs to the node of that element it is
  nearest to, so a beam or shell node has the result nodes of its
  cross-section or thickness: its displacement is their mean, its stress
  the largest of theirs;
- ``results.json``, the load cases, combinations and modes by name, the
  section force diagrams, the supports and their reactions.

Nothing here needs PyVista: cells are given as VTK cell type numbers.
"""

import json
import os
import re
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..analysis.results_parser import ResultsParser, _parse_frd_data_line

# VTK cell types
VTK_LINE = 3
VTK_TRIANGLE = 5
VTK_QUADRATIC_EDGE = 21
VTK_QUADRATIC_TRIANGLE = 22
SURFACE_CELLS = (VTK_TRIANGLE, VTK_QUADRATIC_TRIANGLE)

# CalculiX element types and the VTK cells drawn for them, with the order of
# their nodes in the VTK cell. CalculiX lists a three-node beam as (start,
# middle, end) and VTK wants (start, end, middle); a six-node triangle is the
# same in both. A spring has one node and nothing to draw.
CALCULIX_CELLS = {
    "B31": (VTK_LINE, (0, 1)),
    "U1": (VTK_LINE, (0, 1)),
    "B32R": (VTK_QUADRATIC_EDGE, (0, 2, 1)),
    "S3": (VTK_TRIANGLE, (0, 1, 2)),
    "S6": (VTK_QUADRATIC_TRIANGLE, (0, 1, 2, 3, 4, 5)),
}
NOT_DRAWN = {"SPRING1"}

_MEMBER_COMMENT = re.compile(r"^\*\*\s*Member\s+(\S+)\s*$")


class InputMesh:
    """The nodes, elements, sets and nodal loads of a CalculiX input file.

    Attributes:
        node_ids: Node numbers, ascending.
        points: Their coordinates, one row each, in the same order.
        elements: ``{element number: (VTK cell type, node numbers)}`` with
            the nodes in VTK's order.
        member_elements: ``{member id: [element numbers]}``, from the sets
            the writer names after each member.
        node_sets: ``{set name: [node numbers]}``.
        step_loads: Per step, ``{node number: force}``: the forces of
            ``*CLOAD`` on the translations, in N, added up per node.
    """

    def __init__(self, inp_file: str):
        nodes: Dict[int, List[float]] = {}
        self.elements: Dict[int, Tuple[int, List[int]]] = {}
        self.member_elements: Dict[str, List[int]] = {}
        self.node_sets: Dict[str, List[int]] = {}
        self.step_loads: List[Dict[int, np.ndarray]] = []
        element_sets: Dict[str, List[int]] = {}

        keyword = None
        options: Dict[str, str] = {}
        member = None
        current_set: Optional[List[int]] = None
        pending: List[str] = []
        with open(inp_file) as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("**"):
                    found = _MEMBER_COMMENT.match(line)
                    if found:
                        member = found.group(1)
                    continue
                if line.startswith("*"):
                    parts = [part.strip() for part in line.split(",")]
                    keyword = parts[0].upper()
                    options = {
                        key.strip().upper(): value.strip()
                        for key, _, value in (part.partition("=") for part in parts[1:])
                    }
                    current_set = None
                    if keyword == "*ELSET":
                        name = options.get("ELSET", "")
                        current_set = element_sets.setdefault(name, [])
                        if member is not None:
                            self.member_elements[member] = current_set
                        member = None
                    elif keyword == "*NSET":
                        name = options.get("NSET", "")
                        current_set = self.node_sets.setdefault(name, [])
                    elif keyword == "*STEP":
                        self.step_loads.append({})
                    continue
                values = [v.strip() for v in line.split(",") if v.strip()]
                if keyword == "*NODE":
                    nodes[int(values[0])] = [float(v) for v in values[1:4]]
                elif keyword == "*ELEMENT":
                    pending.extend(values)
                    if line.endswith(","):
                        continue
                    self._add_element(options.get("TYPE", "").upper(), pending)
                    pending = []
                elif current_set is not None:
                    current_set.extend(int(v) for v in values if v.isdigit())
                elif keyword == "*CLOAD" and self.step_loads:
                    self._add_load(values)

        self.node_ids = np.array(sorted(nodes), dtype=int)
        self.points = np.array([nodes[n] for n in self.node_ids], dtype=float).reshape(
            -1, 3
        )
        self._index = {int(n): i for i, n in enumerate(self.node_ids)}

    def _add_element(self, element_type: str, values: List[str]) -> None:
        numbers = [int(v) for v in values]
        if element_type in NOT_DRAWN:
            return
        if element_type not in CALCULIX_CELLS:
            raise ValueError(f"Element type {element_type} cannot be drawn")
        cell_type, order = CALCULIX_CELLS[element_type]
        self.elements[numbers[0]] = (cell_type, [numbers[1:][k] for k in order])

    def _add_load(self, values: List[str]) -> None:
        dof = int(values[1])
        if dof > 3:
            return
        targets = (
            [int(values[0])]
            if values[0].isdigit()
            else self.node_sets.get(values[0], [])
        )
        loads = self.step_loads[-1]
        for node in targets:
            force = loads.setdefault(node, np.zeros(3))
            force[dof - 1] += float(values[2])

    def index(self, node: int) -> int:
        """The row of a node number in ``points``."""
        return self._index[node]

    def indices(self, nodes) -> np.ndarray:
        """The rows of several node numbers."""
        return np.array([self._index[n] for n in nodes], dtype=int)


class ResultFile:
    """The node coordinates, elements and result blocks of an FRD file.

    The file is scanned once; a block's values are read when asked for.
    """

    def __init__(self, frd_file: str):
        self.path = frd_file
        self.coordinates: Dict[int, np.ndarray] = {}
        # (name, offset of its first line) of every result block, in order
        self.blocks: List[Tuple[str, int]] = []
        in_nodes = False
        offset = 0
        with open(frd_file, "rb") as fh:
            for raw in fh:
                start = offset
                offset += len(raw)
                if raw.startswith(b"    2C"):
                    in_nodes = True
                elif in_nodes:
                    if raw.startswith(b" -1"):
                        _, values = _parse_frd_data_line(raw.decode())
                        self.coordinates[int(raw[3:13])] = np.array(values[:3])
                    elif raw.startswith(b" -3"):
                        in_nodes = False
                elif raw.startswith(b" -4"):
                    self.blocks.append((raw[5:13].decode().strip(), start))
        self.element_nodes = ResultsParser().parse_element_nodes(frd_file)

    def offsets(self, name: str) -> List[int]:
        """Where each block of this name starts, in order."""
        return [offset for block, offset in self.blocks if block == name]

    def read(self, offset: int) -> Dict[int, np.ndarray]:
        """The values of the block at ``offset``, by node number."""
        values: Dict[int, np.ndarray] = {}
        with open(self.path, "rb") as fh:
            fh.seek(offset)
            fh.readline()
            for raw in fh:
                if raw.startswith(b" -3"):
                    break
                if raw.startswith(b" -1"):
                    node, numbers = _parse_frd_data_line(raw.decode())
                    values[int(node)] = np.array(numbers, dtype=float)
        return values


def von_mises(components: np.ndarray) -> np.ndarray:
    """Von Mises stress of rows of (xx, yy, zz, xy, yz, zx)."""
    sxx, syy, szz, sxy, syz, szx = components.T
    return np.sqrt(
        0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
        + 3.0 * (sxy**2 + syz**2 + szx**2)
    )


class AnalysisOutput:
    """An output directory of ``analyze_ifc()``, read for drawing.

    Args:
        directory: Holds ``analysis.inp``, ``analysis.frd`` and
            ``results.json``.

    Raises:
        FileNotFoundError: If one of them is missing.
    """

    def __init__(self, directory: str):
        self.directory = directory
        paths = {
            name: os.path.join(directory, name)
            for name in ("analysis.inp", "analysis.frd", "results.json")
        }
        for name, path in paths.items():
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"{path} not found: not the output directory of an analysis"
                )
        with open(paths["results.json"]) as fh:
            self.results = json.load(fh)
        self.mesh = InputMesh(paths["analysis.inp"])
        self.frd = ResultFile(paths["analysis.frd"])
        self._pairs = self._attribute_result_nodes()

    # ------------------------------------------------------------------
    # What there is to draw
    # ------------------------------------------------------------------

    @property
    def analysis_type(self) -> str:
        return self.results.get("analysis_type", "linear_static")

    @property
    def load_cases(self) -> List[str]:
        return list(self.results.get("load_cases", []))

    @property
    def load_combinations(self) -> Dict[str, Dict[str, float]]:
        return {
            combination["name"]: combination["factors"]
            for combination in self.results.get("load_combinations", [])
        }

    @property
    def modes(self) -> List[dict]:
        """The modes of a modal analysis or the buckling factors of a
        buckling one, as ``results.json`` has them."""
        if self.analysis_type == "modal":
            return list(self.results.get("modal", {}).get("modes", []))
        if self.analysis_type == "linear_buckling":
            return list(self.results.get("buckling", {}).get("modes", []))
        return []

    def members(self, kind: Optional[str] = None) -> List[dict]:
        """The members of ``results.json`` that have elements in the mesh."""
        return [
            member
            for member in self.results.get("members", [])
            if member["id"] in self.mesh.member_elements
            and (kind is None or member.get("type") == kind)
        ]

    def member_cells(self) -> Dict[str, List[Tuple[int, List[int]]]]:
        """``{member id: [(VTK cell type, node rows)]}``."""
        cells = {}
        for member_id, elements in self.mesh.member_elements.items():
            cells[member_id] = [
                (
                    self.mesh.elements[e][0],
                    list(self.mesh.indices(self.mesh.elements[e][1])),
                )
                for e in elements
                if e in self.mesh.elements
            ]
        return cells

    def support_nodes(self) -> Dict[str, np.ndarray]:
        """``{support id: node rows}``, from the writer's ``BC_<id>`` sets."""
        found = {}
        for support in self.results.get("supports", []):
            nodes = self.mesh.node_sets.get(f"BC_{support['id']}")
            if nodes:
                found[support["id"]] = self.mesh.indices(nodes)
        return found

    def member_start(self, member: dict) -> Optional[np.ndarray]:
        """Where a curve member's section force diagrams start.

        Their distances run from the first point of the member's edge along
        ``section_axes["x"]``: the node of its elements least far along it.
        """
        axis = member.get("section_axes", {}).get("x")
        elements = self.mesh.member_elements.get(member["id"], [])
        nodes = {
            n
            for e in elements
            if e in self.mesh.elements
            for n in self.mesh.elements[e][1]
        }
        if axis is None or not nodes:
            return None
        points = self.mesh.points[self.mesh.indices(sorted(nodes))]
        return points[int(np.argmin(points @ np.array(axis, dtype=float)))]

    # ------------------------------------------------------------------
    # Fields on the input nodes
    # ------------------------------------------------------------------

    def _attribute_result_nodes(self) -> Tuple[np.ndarray, np.ndarray]:
        """Pairs (input node row, result node number) covering every node.

        A node of an element the result file does not list (U1) keeps its
        own number.
        """
        rows: List[int] = []
        result_nodes: List[int] = []
        covered = set()
        for element, (_, own) in self.mesh.elements.items():
            expanded = self.frd.element_nodes.get(element)
            if not expanded:
                continue
            own_points = self.mesh.points[self.mesh.indices(own)]
            found = [n for n in expanded if n in self.frd.coordinates]
            if not found:
                continue
            points = np.array([self.frd.coordinates[n] for n in found])
            distance = np.linalg.norm(
                points[:, None, :] - own_points[None, :, :], axis=2
            )
            for result_node, nearest in zip(found, np.argmin(distance, axis=1)):
                key = (own[nearest], result_node)
                if key not in covered:
                    covered.add(key)
                    rows.append(self.mesh.index(own[nearest]))
                    result_nodes.append(result_node)
        mapped = set(rows)
        for row, node in enumerate(self.mesh.node_ids):
            if row not in mapped and int(node) in self.frd.coordinates:
                rows.append(row)
                result_nodes.append(int(node))
        return np.array(rows, dtype=int), np.array(result_nodes, dtype=int)

    def _block_index(self, case: Optional[str], mode: Optional[int]) -> int:
        """Which displacement or stress block a case or mode is."""
        if mode is not None:
            if self.analysis_type not in ("modal", "linear_buckling"):
                raise ValueError(f"No mode {mode}: a {self.analysis_type} analysis")
            count = len(self.frd.offsets("DISP"))
            # A buckling analysis has the displacements under its loads first
            first = 1 if self.analysis_type == "linear_buckling" else 0
            if not 1 <= mode <= count - first:
                raise ValueError(f"No mode {mode}: the analysis has {count - first}")
            return first + mode - 1
        if case not in self.load_cases:
            raise ValueError(f"No load case {case!r}: {self.load_cases or 'none'}")
        return self.load_cases.index(case)

    def _factors(
        self, case: Optional[str], combination: Optional[str]
    ) -> Dict[str, float]:
        if combination is not None:
            if combination not in self.load_combinations:
                raise ValueError(
                    f"No load combination {combination!r}: "
                    f"{list(self.load_combinations) or 'none'}"
                )
            return self.load_combinations[combination]
        return {case: 1.0}

    def _on_nodes(self, name: str, index: int, width: int) -> np.ndarray:
        """A block's values on the result nodes paired with input nodes."""
        offsets = self.frd.offsets(name)
        if index >= len(offsets):
            raise ValueError(f"The result file has no {name} block {index + 1}")
        block = self.frd.read(offsets[index])
        empty = np.zeros(width)
        return np.array(
            [block.get(int(n), empty)[:width] for n in self._pairs[1]]
        ).reshape(-1, width)

    def displacement(
        self,
        case: Optional[str] = None,
        combination: Optional[str] = None,
        mode: Optional[int] = None,
    ) -> np.ndarray:
        """Displacement of every input node, one row each, in m.

        The mean over a node's cross-section is the movement of its axis. A
        combination is its load cases' displacements times their factors.
        """
        rows, _ = self._pairs
        values = np.zeros((len(rows), 3))
        if mode is not None:
            values = self._on_nodes("DISP", self._block_index(None, mode), 3)
        else:
            for name, factor in self._factors(case, combination).items():
                values = values + factor * self._on_nodes(
                    "DISP", self._block_index(name, None), 3
                )
        total = np.zeros((len(self.mesh.node_ids), 3))
        count = np.zeros(len(self.mesh.node_ids))
        np.add.at(total, rows, values)
        np.add.at(count, rows, 1.0)
        return total / np.maximum(count, 1.0)[:, None]

    def von_mises(
        self, case: Optional[str] = None, combination: Optional[str] = None
    ) -> np.ndarray:
        """The largest von Mises stress over each input node's result nodes,
        in Pa. A combination adds the stress components first."""
        rows, _ = self._pairs
        components = np.zeros((len(rows), 6))
        for name, factor in self._factors(case, combination).items():
            components = components + factor * self._on_nodes(
                "STRESS", self._block_index(name, None), 6
            )
        largest = np.zeros(len(self.mesh.node_ids))
        np.maximum.at(largest, rows, von_mises(components))
        return largest

    def applied_loads(
        self, case: Optional[str] = None, combination: Optional[str] = None
    ) -> Dict[int, np.ndarray]:
        """``{node row: force in N}`` written to the solver for a case, or
        the sum of a combination's; self-weight is not among them."""
        loads: Dict[int, np.ndarray] = {}
        for name, factor in self._factors(case, combination).items():
            step = self._block_index(name, None)
            if step >= len(self.mesh.step_loads):
                continue
            for node, force in self.mesh.step_loads[step].items():
                row = self.mesh.index(node)
                loads[row] = loads.get(row, np.zeros(3)) + factor * force
        return loads

    def self_weight(self, case: Optional[str], combination: Optional[str]) -> bool:
        """Whether a case, or a case of a combination, includes self-weight:
        a ``GRAV`` load in its step."""
        names = self._factors(case, combination)
        return any(name in self._steps_with_weight() for name in names)

    def _steps_with_weight(self) -> set:
        if not hasattr(self, "_weighted"):
            weighted = set()
            step = -1
            with open(os.path.join(self.directory, "analysis.inp")) as fh:
                for line in fh:
                    if line.upper().startswith("*STEP"):
                        step += 1
                    elif ", GRAV," in line.upper() and 0 <= step < len(self.load_cases):
                        weighted.add(self.load_cases[step])
            self._weighted = weighted
        return self._weighted
