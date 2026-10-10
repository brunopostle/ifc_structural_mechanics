"""JSON results exporter for ifc_structural_mechanics.

Consumes a ``StructuralModel`` (post-analysis, with node/element memberships
registered) and the ``parsed_results`` dict returned by ``ResultsParser``, and
writes a ``results.json`` file keyed to IFC GlobalIds.

Schema (summary level)
----------------------
{
  "schema_version": "1.0",
  "units": {"length": "m", "force": "N", "moment": "N*m",
            "stress": "Pa", "displacement": "m"},
  "model": {"id": "...", "name": "..."},
  "load_cases": ["Dead", "Live"],
  "members": [
    {
      "ifc_guid": "...",
      "id": "...",
      "type": "curve" | "surface",
      "status": "ok" | "warning" | "fail",
      "section_model": "equivalent_rectangle",
      "envelope": {
        "max_displacement_m": 0.001,
        "max_relative_displacement_m": 0.0008,
        "max_von_mises_Pa": 1.5e6,
        "max_normal_stress_Pa": 1.4e6,
        "utilisation_ratio": 0.006,
        "section_forces": {"max_N_N": 0.0, "max_T_Nm": 0.0,
                           "max_Mf1_Nm": 1.0e4, "max_Mf2_Nm": 0.0,
                           "max_Vf1_N": 1.0e4, "max_Vf2_N": 0.0}
      },
      "by_load_case": {
        "Dead": {"max_displacement_m": 0.001, "max_von_mises_Pa": 1.5e6,
                 "max_normal_stress_Pa": 1.4e6, "section_forces": {...}}
      }
    }
  ],
  "global_displacements": {
    "envelope": {"max_displacement_m": 0.001, "max_tx_m": 0.0, ...},
    "by_load_case": {"Dead": {...}}
  },
  "global_reactions": {
    "by_load_case": {"Dead": {"fx_N": 0.0, "fy_N": 0.0, "fz_N": 5000.0,
                              "mx_Nm": 0.0, "my_Nm": 0.0, "mz_Nm": 0.0,
                              "resultant_N": 5000.0}},
    "total": {...}
  }
}

``max_relative_displacement_m`` is how much a member distorts: the largest
difference in displacement between two of its points in any one global
direction, so without what the member moves as a whole.

Curve members carry ``section_forces``: the largest magnitudes over the member
of the axial force N, the torque T, the bending moments Mf1 (stress varying
over the section's depth; strong-axis bending of a section deeper than wide)
and Mf2, and the shear forces Vf1 (along the depth) and Vf2, plus
``max_tension_N`` and ``max_compression_N``. They are integrated from the
solver's stresses over each cross-section.

``section_force_diagrams`` holds the same forces along the member, signed, per
load case: parallel lists ``distance_m`` (from the member's start), ``N_N``,
``Vf1_N``, ``Vf2_N``, ``T_Nm``, ``Mf1_Nm``, ``Mf2_Nm``. A distance listed twice
is a jump, before and after. ``section_axes`` gives the directions they refer
to: ``x`` from the first point of the member's IFC edge to the last, ``1``
the section's first direction (the profile's depth) and ``2 = x cross 1``.
Each force is what the part of the member beyond the cross-section exerts on
the part before it: N is positive in tension, Mf1 is positive when the +1 side
is in tension, Mf2 when the +2 side is, T is right-handed about x.
``max_normal_stress_Pa`` is the largest of |N|/A + |Mf1| y/Iy + |Mf2| z/Iz over
those cross-sections, with the properties of the member's real section;
``utilisation_ratio`` divides it by the material's yield strength when one is
known. ``max_von_mises_Pa`` is the solver's own value and is absent for members
analysed as equivalent rectangles.

``section_model`` is only present on members whose section CalculiX has no
shape for (I, T, L, C) when they were analysed as a rectangle of the same
stiffness. Those members have no ``max_von_mises_Pa``: the stresses in the
result file are the rectangle's.

``global_reactions.total`` is only present when there is a single load case;
each case is analysed on its own, so several cases have no common total.

Per-member displacement and stress are attributed element by element. CalculiX
expands beam and shell elements into solids and reports on the solids' nodes,
which it numbers itself; each solid keeps the number of the element it came
from. So a member's result nodes are the nodes of its elements in the result
file's own connectivity (``element_nodes``). Elements the result file does not
list (U1 user elements) fall back to the member's mesh nodes.
"""

import json
import logging
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ResultsExporter:
    """Export post-analysis results to a GlobalId-keyed JSON file.

    Args:
        domain_model: The ``StructuralModel`` after analysis, with
            ``node_to_member`` and ``analysis_element_to_member`` populated.
        parsed_results: Dict returned by ``ResultsParser.parse_results()``.
            Expected keys: ``"displacement"``, ``"stress"``, ``"reaction"``.
        limits: Optional dict of pass/fail thresholds, e.g.
            ``{"max_von_mises_Pa": 250e6, "max_displacement_m": 0.02}``.
        element_nodes: Node IDs of each element in the result file, from
            ``ResultsParser.element_nodes``. Without it results are attributed
            through the mesh nodes alone, which misses expanded elements.
    """

    SCHEMA_VERSION = "1.0"

    def __init__(
        self,
        domain_model,
        parsed_results: Dict[str, List],
        limits: Optional[Dict[str, float]] = None,
        element_nodes: Optional[Dict[int, List[int]]] = None,
    ):
        self.model = domain_model
        self.parsed_results = parsed_results
        self.limits = limits or {}
        self.element_nodes = element_nodes or {}
        self._node_index_cache: Dict[str, Dict[int, List[Tuple[str, float]]]] = {}
        self._mesh_nodes: Optional[Dict[str, set]] = None
        self._translations: Optional[Dict[int, List[Tuple[str, List[float]]]]] = None
        self._section_force_records: Optional[Dict[int, List[Dict]]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(self, output_path: str) -> Dict[str, Any]:
        """Build the JSON results dict and write it to *output_path*.

        Args:
            output_path: Absolute path for the ``results.json`` file.

        Returns:
            The dict that was written.
        """
        data = self._build()
        with open(output_path, "w") as fh:
            json.dump(data, fh, indent=2)
        logger.info(f"Wrote results JSON: {output_path}")
        return data

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build(self) -> Dict[str, Any]:
        load_cases = self._load_case_names()
        return {
            "schema_version": self.SCHEMA_VERSION,
            "units": {
                "length": "m",
                "force": "N",
                "moment": "N*m",
                "stress": "Pa",
                "displacement": "m",
            },
            "model": {
                "id": self.model.id,
                "name": self.model.name or "",
            },
            "load_cases": load_cases,
            "members": [self._member_entry(m) for m in self.model.members],
            "global_displacements": self._global_displacements(),
            "global_reactions": self._global_reactions(),
        }

    # ------------------------------------------------------------------
    # Load case helpers
    # ------------------------------------------------------------------

    def _load_case_names(self) -> List[str]:
        """Return ordered unique load case names from displacement results."""
        seen: set = set()
        names: List[str] = []
        for r in self.parsed_results.get("displacement", []):
            lc = r.metadata.get("load_case", "")
            if lc and lc not in seen:
                names.append(lc)
                seen.add(lc)
        return names

    # ------------------------------------------------------------------
    # Per-member entry
    # ------------------------------------------------------------------

    def _member_entry(self, member) -> Dict[str, Any]:
        member_id = member.id
        elem_ids: set = set(getattr(member, "analysis_element_ids", []))
        node_ids = self._member_result_nodes(member_id, elem_ids)

        # A member analysed as an equivalent rectangle has that rectangle's
        # stresses in the result file, not its own.
        equivalent = member_id in (
            getattr(self.model, "equivalent_section_members", None) or ()
        )
        disp_by_lc = self._member_displacements(node_ids)
        stress_by_lc = {} if equivalent else self._member_stresses(node_ids)
        sf_by_lc = self._member_section_forces(elem_ids)
        util_by_lc = self._member_utilisation(elem_ids, member)

        # Merge into per-load-case dict
        all_lcs = set(disp_by_lc) | set(stress_by_lc) | set(sf_by_lc)
        by_load_case: Dict[str, Any] = {}
        for lc in sorted(all_lcs):
            entry: Dict[str, Any] = {}
            if lc in disp_by_lc:
                entry.update(disp_by_lc[lc])
            if lc in stress_by_lc:
                entry.update(stress_by_lc[lc])
            if lc in sf_by_lc:
                entry["section_forces"] = sf_by_lc[lc]
            if lc in util_by_lc:
                entry.update(util_by_lc[lc])
            by_load_case[lc] = entry

        # Envelope across all load cases
        envelope = self._envelope(
            {
                lc: {k: v for k, v in d.items() if isinstance(v, float)}
                for lc, d in by_load_case.items()
            }
        )

        if sf_by_lc:
            envelope["section_forces"] = self._envelope(sf_by_lc)

        status = self._status(envelope)

        result: Dict[str, Any] = {
            "ifc_guid": getattr(member, "ifc_guid", None),
            "id": member_id,
            "type": getattr(member, "entity_type", "unknown"),
            "status": status,
        }
        if equivalent:
            result["section_model"] = "equivalent_rectangle"
        if envelope:
            result["envelope"] = envelope
        if by_load_case:
            result["by_load_case"] = by_load_case
        diagrams = self._member_diagrams(elem_ids)
        if diagrams:
            axes = self._member_axes(member, elem_ids)
            if axes:
                result["section_axes"] = axes
            result["section_force_diagrams"] = diagrams
        return result

    def _member_result_nodes(self, member_id: str, elem_ids: set) -> set:
        """Return the result-file nodes that carry this member's results.

        The nodes of the member's elements as the result file lists them. If
        any of its elements is not listed there, the member's mesh nodes are
        added, since such an element is reported on the nodes it was given.
        """
        node_ids: set = set()
        listed = True
        for elem_id in elem_ids:
            nodes = self.element_nodes.get(elem_id)
            if nodes is None:
                listed = False
            else:
                node_ids.update(nodes)
        if not listed or not elem_ids:
            node_ids.update(self._mesh_nodes_by_member().get(member_id, ()))
        return node_ids

    def _mesh_nodes_by_member(self) -> Dict[str, set]:
        """Return ``{member_id: mesh node IDs}``, built once."""
        if self._mesh_nodes is None:
            by_member = getattr(self.model, "member_nodes", None)
            if isinstance(by_member, dict) and by_member:
                self._mesh_nodes = {
                    mid: {int(n) for n in nodes} for mid, nodes in by_member.items()
                }
            else:
                self._mesh_nodes = defaultdict(set)
                for nid, mid in self.model.node_to_member.items():
                    self._mesh_nodes[mid].add(int(nid))
        return self._mesh_nodes

    def _node_index(self, kind: str) -> Dict[int, List[Tuple[str, float]]]:
        """Return ``{node_id: [(load_case, value), ...]}`` for one result kind.

        Built once per kind and cached, so per-member lookups cost the size of
        the member rather than a scan of every result in the model. ``value`` is
        the displacement magnitude for ``"displacement"`` and the von Mises
        stress for ``"stress"``.
        """
        if kind in self._node_index_cache:
            return self._node_index_cache[kind]
        index: Dict[int, List[Tuple[str, float]]] = defaultdict(list)
        for r in self.parsed_results.get(kind, []):
            try:
                nid = int(r.reference_element)
            except (ValueError, TypeError):
                continue
            if kind == "stress":
                try:
                    value = r.get_von_mises_stress()
                except (ValueError, KeyError):
                    continue
            else:
                value = r.get_magnitude()
            index[nid].append((r.metadata.get("load_case", "_combined"), value))
        self._node_index_cache[kind] = index
        return index

    def _member_max(self, kind: str, node_ids: set) -> Dict[str, float]:
        """Return the per-load-case maximum of *kind* over the given nodes."""
        index = self._node_index(kind)
        maxima: Dict[str, float] = {}
        for nid in node_ids:
            for lc, value in index.get(nid, ()):
                if lc not in maxima or value > maxima[lc]:
                    maxima[lc] = value
        return maxima

    def _translation_index(self) -> Dict[int, List[Tuple[str, List[float]]]]:
        """Return ``{node_id: [(load_case, [tx, ty, tz]), ...]}``, built once."""
        if self._translations is None:
            index: Dict[int, List[Tuple[str, List[float]]]] = defaultdict(list)
            for r in self.parsed_results.get("displacement", []):
                try:
                    nid = int(r.reference_element)
                except (ValueError, TypeError):
                    continue
                index[nid].append(
                    (r.metadata.get("load_case", "_combined"), r.get_translations())
                )
            self._translations = index
        return self._translations

    def _member_displacements(self, node_ids: set) -> Dict[str, Dict[str, float]]:
        """Return per-load-case displacement stats for the given node set.

        ``max_displacement_m`` is the largest displacement of any of the
        member's points. ``max_relative_displacement_m`` is how much the
        member distorts: the largest difference between two of its points in
        any one global direction, which leaves out whatever the member moves
        as a whole.
        """
        stats = {
            lc: {"max_displacement_m": value}
            for lc, value in self._member_max("displacement", node_ids).items()
        }
        index = self._translation_index()
        ranges: Dict[str, List[List[float]]] = {}
        for nid in node_ids:
            for lc, translation in index.get(nid, ()):
                low_high = ranges.get(lc)
                if low_high is None:
                    ranges[lc] = [list(translation), list(translation)]
                    continue
                for i in range(3):
                    low_high[0][i] = min(low_high[0][i], translation[i])
                    low_high[1][i] = max(low_high[1][i], translation[i])
        for lc, (low, high) in ranges.items():
            if lc in stats:
                stats[lc]["max_relative_displacement_m"] = max(
                    high[i] - low[i] for i in range(3)
                )
        return stats

    def _member_stresses(self, node_ids: set) -> Dict[str, Dict[str, float]]:
        """Return per-load-case von Mises stats for the given node set.

        Node IDs that don't appear in ``node_ids`` (e.g. CalculiX-expanded
        beam brick nodes) are silently skipped.
        """
        return {
            lc: {"max_von_mises_Pa": value}
            for lc, value in self._member_max("stress", node_ids).items()
        }

    _FORCE_KEYS = (
        ("N", "max_N_N"),
        ("T", "max_T_Nm"),
        ("Mf1", "max_Mf1_Nm"),
        ("Mf2", "max_Mf2_Nm"),
        ("Vf1", "max_Vf1_N"),
        ("Vf2", "max_Vf2_N"),
    )

    def _section_force_index(self) -> Dict[int, List[Dict]]:
        """Return ``{element_id: [section force records]}``, built once."""
        if self._section_force_records is None:
            index: Dict[int, List[Dict]] = defaultdict(list)
            for rec in self.parsed_results.get("section_forces", []):
                if isinstance(rec, dict) and "element_id" in rec:
                    index[rec["element_id"]].append(rec)
            self._section_force_records = index
        return self._section_force_records

    def _member_section_forces(self, elem_ids: set) -> Dict[str, Dict[str, float]]:
        """Return per-load-case section force envelopes for the given element set.

        The largest magnitude of N, T, Mf1, Mf2, Vf1 and Vf2 over every
        cross-section of the member's elements, per load case, and the
        largest tension and compression. The maxima need not occur at the
        same cross-section.
        """
        index = self._section_force_index()
        result: Dict[str, Dict[str, float]] = {}
        for elem_id in elem_ids:
            for rec in index.get(elem_id, ()):
                entry = result.setdefault(
                    rec.get("load_case", "_combined"),
                    {
                        **{name: 0.0 for _, name in self._FORCE_KEYS},
                        "max_tension_N": 0.0,
                        "max_compression_N": 0.0,
                    },
                )
                for key, name in self._FORCE_KEYS:
                    entry[name] = max(entry[name], abs(rec.get(key, 0.0)))
                axial = rec.get("N", 0.0)
                entry["max_tension_N"] = max(entry["max_tension_N"], axial)
                entry["max_compression_N"] = max(entry["max_compression_N"], -axial)
        return result

    _DIAGRAM_KEYS = (
        ("N", "N_N"),
        ("Vf1", "Vf1_N"),
        ("Vf2", "Vf2_N"),
        ("T", "T_Nm"),
        ("Mf1", "Mf1_Nm"),
        ("Mf2", "Mf2_Nm"),
    )

    def _member_diagrams(self, elem_ids: set) -> Dict[str, Dict[str, List[float]]]:
        """Section forces along the member, per load case, with their signs.

        Each diagram is a set of parallel lists ordered by ``distance_m`` from
        the member's start. Two entries at one distance are the values just
        before and just after it, where a force jumps (a point load, a
        support, another member framing in). Where neighbouring elements
        agree, the cross-section they share is listed once.
        """
        index = self._section_force_index()
        by_case: Dict[str, List[Dict]] = defaultdict(list)
        for elem_id in elem_ids:
            for rec in index.get(elem_id, ()):
                if "distance" in rec:
                    by_case[rec.get("load_case", "_combined")].append(rec)

        diagrams: Dict[str, Dict[str, List[float]]] = {}
        for case, records in by_case.items():
            # At a shared cross-section the end of one element comes before
            # the start of the next
            records = [dict(r) for r in records]
            records.sort(key=lambda r: (round(r["distance"], 9), -r["position"]))
            scales = {
                key: max((abs(r.get(key, 0.0)) for r in records), default=0.0)
                for key, _ in self._DIAGRAM_KEYS
            }
            self._restore_jumps(records, scales)
            scale = max(scales.values(), default=0.0)
            kept: List[Dict] = []
            for rec in records:
                previous = kept[-1] if kept else None
                if (
                    previous is not None
                    and abs(rec["distance"] - previous["distance"]) < 1e-9
                    and all(
                        abs(rec.get(key, 0.0) - previous.get(key, 0.0)) <= 1e-6 * scale
                        for key, _ in self._DIAGRAM_KEYS
                    )
                ):
                    continue
                kept.append(rec)
            diagram = {"distance_m": [r["distance"] for r in kept]}
            for key, name in self._DIAGRAM_KEYS:
                diagram[name] = [r.get(key, 0.0) for r in kept]
            diagrams[case] = diagram
        return diagrams

    # A jump smaller than this fraction of a force's largest value along the
    # member is taken to be noise and left averaged.
    _JUMP_FRACTION = 0.02
    # Forces that vary linearly along a member between loads, so that a step
    # out of line with the others is a jump. Bending moments are left out:
    # they are continuous unless a moment is applied.
    _JUMPING_FORCES = ("N", "Vf1", "Vf2", "T")

    def _restore_jumps(self, records: List[Dict], scales: Dict[str, float]) -> None:
        """Put back the jumps that nodal averaging smooths out, in place.

        Two elements in line share the nodes of the cross-section between
        them, and the solver reports one averaged stress there. Under a point
        load the shear is then the mean of its values on the two sides, and a
        diagram shows a ramp where there is a step.

        The middle cross-section of a quadratic element is its own. From one
        middle to the next a force normally changes by the same amount per
        metre all along the member (the distributed load), so the median of
        those slopes is the normal one, and an interface where the change is
        out of line with it by more than ``_JUMP_FRACTION`` has a jump of the
        difference. The averaged value is replaced by one on each side, half
        the jump apart. Needs four quadratic elements in the member; linear
        elements have no middle cross-section and are left as they are.
        """
        middles = sorted(
            (r for r in records if r["position"] == 0.0), key=lambda r: r["distance"]
        )
        if len(middles) < 4:
            return
        ends = {(r["element_id"], r["position"]): r for r in records}
        for key in self._JUMPING_FORCES:
            if scales.get(key, 0.0) <= 0.0:
                continue
            pairs = [
                (a, b, b["distance"] - a["distance"])
                for a, b in zip(middles, middles[1:])
                if b["distance"] - a["distance"] > 1e-12
            ]
            slopes = sorted(
                (b.get(key, 0.0) - a.get(key, 0.0)) / gap for a, b, gap in pairs
            )
            if len(slopes) < 3:
                continue
            normal = slopes[len(slopes) // 2]
            for a, b, gap in pairs:
                left = ends.get((a["element_id"], 1.0))
                right = ends.get((b["element_id"], -1.0))
                if left is None or right is None:
                    continue
                shared = (
                    abs(left["distance"] - right["distance"]) < 1e-9
                    and abs(left.get(key, 0.0) - right.get(key, 0.0))
                    <= 1e-9 * scales[key]
                )
                if not shared:
                    continue  # separate nodes: the values are already one-sided
                jump = b.get(key, 0.0) - a.get(key, 0.0) - normal * gap
                if abs(jump) > self._JUMP_FRACTION * scales[key]:
                    average = left.get(key, 0.0)
                    left[key] = average - jump / 2.0
                    right[key] = average + jump / 2.0

    def _member_axes(self, member, elem_ids: set) -> Optional[Dict[str, List[float]]]:
        """The axes section forces are given in: ``x``, ``1`` and ``2``.

        ``x`` runs from the first point of the member's geometry to the last;
        ``1`` is the section's first direction, as analysed; ``2 = x cross 1``.
        """
        frames = getattr(self.model, "beam_section_frames", None) or {}
        frame = next((frames[e] for e in sorted(elem_ids) if e in frames), None)
        geometry = getattr(member, "geometry", None)
        if frame is None or not isinstance(geometry, (list, tuple)):
            return None
        try:
            x = [float(b) - float(a) for a, b in zip(geometry[0], geometry[-1])]
        except (TypeError, ValueError, IndexError):
            return None
        length = math.sqrt(sum(v * v for v in x))
        if length < 1e-12:
            return None
        x = [v / length for v in x]
        d1 = [float(v) for v in frame[1]]
        dot = sum(a * b for a, b in zip(x, d1))
        d1 = [a - dot * b for a, b in zip(d1, x)]
        norm = math.sqrt(sum(v * v for v in d1))
        if norm < 1e-9:
            return None
        d1 = [v / norm for v in d1]
        d2 = [
            x[1] * d1[2] - x[2] * d1[1],
            x[2] * d1[0] - x[0] * d1[2],
            x[0] * d1[1] - x[1] * d1[0],
        ]
        return {"x": x, "1": d1, "2": d2}

    def _member_utilisation(self, elem_ids: set, member) -> Dict[str, Dict[str, float]]:
        """Largest normal stress in the member's real section, per load case.

        At each cross-section the axial force and the two bending moments are
        combined at the extreme fibres of the section the member really has::

            sigma = |N| / A + |Mf1| / Iy * y_max + |Mf2| / Iz * z_max

        and the largest over the member is ``max_normal_stress_Pa``. This is
        the only stress a member analysed as an equivalent rectangle has.
        Shear and torsion are not in it. When the material has a yield
        strength, ``utilisation_ratio`` is that stress divided by it.
        """
        section = getattr(member, "section", None)
        if section is None:
            return {}
        area = getattr(section, "area", None)
        iy = getattr(section, "moment_of_inertia_y", None)
        iz = getattr(section, "moment_of_inertia_z", None)
        if not area or not iy or not iz:
            return {}
        try:
            y_max, z_max = section.get_extreme_fibre_distances()
        except (AttributeError, KeyError, TypeError):
            return {}
        if y_max is None or z_max is None:
            return {}

        index = self._section_force_index()
        stress: Dict[str, float] = {}
        for elem_id in elem_ids:
            for rec in index.get(elem_id, ()):
                sigma = (
                    abs(rec.get("N", 0.0)) / area
                    + abs(rec.get("Mf1", 0.0)) / iy * y_max
                    + abs(rec.get("Mf2", 0.0)) / iz * z_max
                )
                case = rec.get("load_case", "_combined")
                stress[case] = max(stress.get(case, 0.0), sigma)

        yield_strength = getattr(
            getattr(member, "material", None), "yield_strength", None
        )
        result: Dict[str, Dict[str, float]] = {}
        for case, sigma in stress.items():
            result[case] = {"max_normal_stress_Pa": sigma}
            if yield_strength:
                result[case]["utilisation_ratio"] = sigma / float(yield_strength)
        return result

    @staticmethod
    def _envelope(by_load_case: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """Compute the envelope (max across all load cases) for each metric."""
        combined: Dict[str, List[float]] = defaultdict(list)
        for lc_data in by_load_case.values():
            for key, val in lc_data.items():
                combined[key].append(val)
        return {key: max(vals) for key, vals in combined.items()}

    def _status(self, envelope: Dict[str, float]) -> str:
        """Return 'fail', 'warning', or 'ok' based on user-supplied limits."""
        if not self.limits:
            return "ok"
        for key, limit in self.limits.items():
            value = envelope.get(key, 0.0)
            if isinstance(value, (int, float)) and value > limit:
                return "fail"
        return "ok"

    # ------------------------------------------------------------------
    # Global displacement stats
    # ------------------------------------------------------------------

    def _global_displacements(self) -> Dict[str, Any]:
        disp_results = self.parsed_results.get("displacement", [])
        if not disp_results:
            return {}

        by_lc: Dict[str, List] = defaultdict(list)
        for r in disp_results:
            lc = r.metadata.get("load_case", "_combined")
            by_lc[lc].append(r)

        def _stats(results) -> Optional[Dict[str, float]]:
            mags = [r.get_magnitude() for r in results]
            if not mags:
                return None
            txs = [abs(r.get_translations()[0]) for r in results]
            tys = [abs(r.get_translations()[1]) for r in results]
            tzs = [abs(r.get_translations()[2]) for r in results]
            stats: Dict[str, float] = {"max_displacement_m": max(mags)}
            if any(v > 0 for v in txs):
                stats["max_tx_m"] = max(txs)
            if any(v > 0 for v in tys):
                stats["max_ty_m"] = max(tys)
            if any(v > 0 for v in tzs):
                stats["max_tz_m"] = max(tzs)
            return stats

        by_lc_summary = {
            lc: s
            for lc, results in by_lc.items()
            if lc != "_combined"
            for s in [_stats(results)]
            if s is not None
        }

        envelope = _stats(list(disp_results))
        if envelope is None:
            return {}
        out: Dict[str, Any] = {"envelope": envelope}
        if by_lc_summary:
            out["by_load_case"] = by_lc_summary
        return out

    # ------------------------------------------------------------------
    # Global reactions
    # ------------------------------------------------------------------

    def _global_reactions(self) -> Dict[str, Any]:
        reaction_results = self.parsed_results.get("reaction", [])
        if not reaction_results:
            return {}

        totals = [r for r in reaction_results if r.reference_element == "TOTAL"]
        if not totals:
            return {}

        def _entry(result) -> Dict[str, float]:
            forces = result.get_forces()
            moments = result.get_moments()
            return {
                "fx_N": forces[0],
                "fy_N": forces[1],
                "fz_N": forces[2],
                "mx_Nm": moments[0],
                "my_Nm": moments[1],
                "mz_Nm": moments[2],
                "resultant_N": math.sqrt(sum(f * f for f in forces)),
            }

        by_load_case = {
            r.metadata.get("load_case", f"step_{i + 1}"): _entry(r)
            for i, r in enumerate(totals)
        }
        reactions: Dict[str, Any] = {"by_load_case": by_load_case}
        # One load case: its total is the total. With several there is no
        # single figure, since each case is analysed on its own.
        if len(totals) == 1:
            reactions["total"] = _entry(totals[0])
        return reactions
