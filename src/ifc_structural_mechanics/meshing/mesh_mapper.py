"""Element-to-member mapping strategies for mesh post-processing.

MeshMapper owns the two strategies used to assign mesh elements to their
parent structural members after Gmsh meshing:

  1. Physical-group mapping  — primary, uses Gmsh physical group tags
  2. Naive fallback          — for a mesh with no physical group data, which
     can only be attributed when there is one member of each kind

A member is never given elements by how near they are: members that overlap
are named together in their physical group, and a member the mesh has nothing
for stops the analysis.

Using a dedicated class separates the mapping logic from INP file generation,
makes each strategy independently testable, and provides a clear data contract:
inputs are read-only mesh and domain data; outputs are element_sets and
defined_element_sets.
"""

import logging
from typing import Callable, Dict, List, Set

import numpy as np

from ..domain.structural_model import StructuralModel
from ..utils.error_handling import MeshingError

logger = logging.getLogger(__name__)

# CalculiX element types written for curve members and for surface members
BEAM_ELEMENT_TYPES = frozenset({"B31", "B32", "B32R"})
SHELL_ELEMENT_TYPES = frozenset({"S3", "S4", "S6", "S8", "S9"})


class MeshMapper:
    """Assigns mesh elements to structural members by their physical groups."""

    def __init__(
        self,
        elements: Dict[int, Dict],
        nodes: Dict[int, np.ndarray],
        domain_model: StructuralModel,
        element_physical_group: Dict[int, int],
        physical_group_names: Dict[int, str],
        get_short_id: Callable[[str], str],
    ) -> None:
        self._elements = elements
        self._nodes = nodes
        self._domain_model = domain_model
        self._element_physical_group = element_physical_group
        self._physical_group_names = physical_group_names
        self._get_short_id = get_short_id

        self.element_sets: Dict[str, List[int]] = {}
        self.defined_element_sets: Set[str] = set()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def map(self) -> None:
        """Run the highest-quality available mapping strategy.

        Populates self.element_sets and self.defined_element_sets in-place.
        """
        if self._element_physical_group and self._physical_group_names:
            logger.info("Mapping elements to domain members...")
            self._map_via_physical_groups()
        else:
            logger.warning(
                "No physical group data — falling back to naive element distribution"
            )
            self._map_naive()

    # ------------------------------------------------------------------
    # Strategy 1: physical group tags
    # ------------------------------------------------------------------

    def _map_via_physical_groups(self) -> None:
        """Map elements to members using Gmsh physical group tags.

        Each element's physical group tag identifies which member it belongs
        to.  The physical group name is the member ID.  For exact-overlap
        members the name is "A||B||C" — all named members receive the elements.
        Members with no physical-group elements fall back to spatial assignment.
        """
        member_elements: Dict[str, List[int]] = {}
        mapped = 0
        unmapped = 0

        for elem_id in self._elements:
            ptag = self._element_physical_group.get(elem_id)
            if ptag is not None:
                group_name = self._physical_group_names.get(ptag)
                if group_name:
                    for member_id in group_name.split("||"):
                        member_elements.setdefault(member_id, []).append(elem_id)
                    mapped += 1
                    continue
            unmapped += 1

        logger.info(
            f"Physical group mapping: {mapped} elements mapped, {unmapped} unmapped"
        )

        unmapped_members = []
        for member in self._domain_model.members:
            elems = member_elements.get(member.id, [])
            if not elems:
                unmapped_members.append(member.id)
                continue
            self._register(member, elems)

        if unmapped_members:
            raise MeshingError(
                f"{len(unmapped_members)} member(s) have no elements in the "
                "mesh, so the model cannot be analysed as given. The first are "
                f"{', '.join(unmapped_members[:5])}.",
                code="E-MSH-002",
            )

        logger.info(f"Mapped elements to {len(self.element_sets)} members total")

    # ------------------------------------------------------------------
    # Strategy 2: a mesh with no physical groups
    # ------------------------------------------------------------------

    def _map_naive(self) -> None:
        """Naive fallback: distribute elements equally among members by type."""
        surface_elements = [
            eid
            for eid, ed in self._elements.items()
            if ed["type"] in SHELL_ELEMENT_TYPES
        ]
        curve_elements = [
            eid
            for eid, ed in self._elements.items()
            if ed["type"] in BEAM_ELEMENT_TYPES
        ]
        surface_members = [
            m for m in self._domain_model.members if m.entity_type == "surface"
        ]
        curve_members = [
            m for m in self._domain_model.members if m.entity_type == "curve"
        ]
        self._distribute(surface_elements, surface_members, "surface")
        self._distribute(curve_elements, curve_members, "curve")

    def _distribute(self, elements: List[int], members: List, member_type: str) -> None:
        """Distribute elements equally among members (naive round-robin)."""
        if not elements or not members:
            return
        if len(members) > 1:
            raise MeshingError(
                f"The mesh carries no physical groups, so its {len(elements)} "
                f"{member_type} elements cannot be attributed to the "
                f"{len(members)} {member_type} members.",
                code="E-MSH-003",
            )
        per = len(elements) // len(members)
        rem = len(elements) % len(members)
        start = 0
        for i, member in enumerate(members):
            count = per + (1 if i < rem else 0)
            self._register(member, elements[start : start + count])
            logger.info(
                f"Assigned {count} {member_type} elements to member {member.id}"
            )
            start += count

    # ------------------------------------------------------------------
    # Shared helper
    # ------------------------------------------------------------------

    def _register(self, member, elems: List[int]) -> None:
        """Record element assignment in element_sets and domain model."""
        short_id = self._get_short_id(member.id)
        member_set = f"MEMBER_{short_id}"
        self.element_sets[member_set] = elems
        self.defined_element_sets.add(member_set)
        self._domain_model.register_analysis_elements(
            member.id, elems, entity_type="member"
        )
