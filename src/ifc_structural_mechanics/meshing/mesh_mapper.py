"""Element-to-member mapping strategies for mesh post-processing.

MeshMapper owns the three strategies used to assign mesh elements to their
parent structural members after Gmsh meshing:

  1. Physical-group mapping  — primary, uses Gmsh physical group tags
  2. Spatial fallback        — for members that get no physical-group elements
  3. Naive fallback          — last resort when no physical group data exists

Using a dedicated class separates the mapping logic from INP file generation,
makes each strategy independently testable, and provides a clear data contract:
inputs are read-only mesh and domain data; outputs are element_sets and
defined_element_sets.
"""

import logging
from typing import Callable, Dict, List, Set

import numpy as np

from ..domain.structural_model import StructuralModel

logger = logging.getLogger(__name__)


class MeshMapper:
    """Assigns mesh elements to structural members using three strategies."""

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
        assigned_elements: Set[int] = set()
        mapped = 0
        unmapped = 0

        for elem_id in self._elements:
            ptag = self._element_physical_group.get(elem_id)
            if ptag is not None:
                group_name = self._physical_group_names.get(ptag)
                if group_name:
                    for member_id in group_name.split("||"):
                        member_elements.setdefault(member_id, []).append(elem_id)
                    assigned_elements.add(elem_id)
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
                unmapped_members.append(member)
                continue
            self._register(member, elems)

        if unmapped_members:
            logger.info(
                f"{len(unmapped_members)} members have no physical group elements — "
                f"using spatial fallback"
            )
            self._assign_spatially(unmapped_members, assigned_elements)

        # Second-chance pass: allow sharing for members still without elements.
        still_empty = [
            m
            for m in self._domain_model.members
            if f"MEMBER_{self._get_short_id(m.id)}" not in self.element_sets
        ]
        if still_empty:
            logger.warning(
                f"{len(still_empty)} members still have no elements after spatial "
                f"fallback; attempting shared-element assignment"
            )
            self._assign_spatially(still_empty, assigned_elements, allow_sharing=True)

        total = sum(
            1
            for m in self._domain_model.members
            if f"MEMBER_{self._get_short_id(m.id)}" in self.element_sets
        )
        logger.info(f"Mapped elements to {total} members total")

    # ------------------------------------------------------------------
    # Strategy 2: spatial proximity
    # ------------------------------------------------------------------

    def _assign_spatially(
        self,
        members: List,
        assigned_elements: Set[int],
        allow_sharing: bool = False,
    ) -> None:
        """Assign elements to members by spatial centroid proximity.

        For each unmapped member, compute its geometry centroid, then find
        elements of matching type whose centroids are closest.

        Args:
            members: Members that need element assignment.
            assigned_elements: Elements already assigned.  When allow_sharing
                is False, only elements NOT in this set are considered.
            allow_sharing: When True all elements are candidates (last resort
                for overlapping geometry).
        """
        for member in members:
            geom = member.geometry
            if not geom or not isinstance(geom, list):
                continue
            try:
                pts = np.array(geom)
                centroid = pts.mean(axis=0)
            except Exception:
                continue

            is_surface = member.entity_type == "surface"
            target_types = (
                {"S3", "S4", "S6", "S8", "S9"} if is_surface else {"B31", "B32"}
            )

            best_elems = []
            for elem_id, elem_data in self._elements.items():
                if not allow_sharing and elem_id in assigned_elements:
                    continue
                if elem_data["type"] not in target_types:
                    continue
                try:
                    node_coords = [
                        self._nodes[nid]
                        for nid in elem_data["nodes"]
                        if nid in self._nodes
                    ]
                    if not node_coords:
                        continue
                    elem_centroid = np.mean(node_coords, axis=0)
                    dist = float(np.linalg.norm(elem_centroid - centroid))
                    best_elems.append((dist, elem_id))
                except Exception:
                    continue

            if not best_elems:
                logger.warning(
                    f"No {'candidate' if allow_sharing else 'unassigned'} "
                    f"elements found for member {member.id}"
                )
                continue

            bbox_size = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
            threshold = max(bbox_size * 0.6, 0.5)
            best_elems.sort()

            member_elems: List[int] = []
            for dist, eid in best_elems:
                if dist <= threshold:
                    member_elems.append(eid)
                    if not allow_sharing:
                        assigned_elements.add(eid)

            if allow_sharing and member_elems:
                logger.warning(
                    f"Member {member.id}: sharing {len(member_elems)} elements "
                    f"with another member (overlapping geometry)"
                )

            if member_elems:
                self._register(member, member_elems)
                logger.info(
                    f"Spatially assigned {len(member_elems)} elements to member {member.id}"
                )
            else:
                logger.warning(
                    f"Could not spatially assign elements to member {member.id} "
                    f"(centroid={centroid.tolist()}, bbox_size={bbox_size:.2f}m)"
                )

    # ------------------------------------------------------------------
    # Strategy 3: naive round-robin (last resort)
    # ------------------------------------------------------------------

    def _map_naive(self) -> None:
        """Naive fallback: distribute elements equally among members by type."""
        surface_elements = [
            eid
            for eid, ed in self._elements.items()
            if ed["type"] in {"S3", "S4", "S6", "S8", "S9"}
        ]
        curve_elements = [
            eid for eid, ed in self._elements.items() if ed["type"] in {"B31", "B32"}
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
            logger.warning(f"No {member_type} elements or members to distribute")
            return
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
