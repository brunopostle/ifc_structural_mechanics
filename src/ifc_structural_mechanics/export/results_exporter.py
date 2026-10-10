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
        "max_von_mises_Pa": 1.5e6
      },
      "by_load_case": {
        "Dead": {"max_displacement_m": 0.001, "max_von_mises_Pa": 1.5e6}
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
        util_by_lc = self._member_utilisation(sf_by_lc, member)

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

    def _member_displacements(self, node_ids: set) -> Dict[str, Dict[str, float]]:
        """Return per-load-case displacement stats for the given node set."""
        return {
            lc: {"max_displacement_m": value}
            for lc, value in self._member_max("displacement", node_ids).items()
        }

    def _member_stresses(self, node_ids: set) -> Dict[str, Dict[str, float]]:
        """Return per-load-case von Mises stats for the given node set.

        Node IDs that don't appear in ``node_ids`` (e.g. CalculiX-expanded
        beam brick nodes) are silently skipped.
        """
        return {
            lc: {"max_von_mises_Pa": value}
            for lc, value in self._member_max("stress", node_ids).items()
        }

    def _member_section_forces(self, elem_ids: set) -> Dict[str, Dict[str, float]]:
        """Return per-load-case section force envelopes for the given element set.

        Groups beam section force records by load case, filters to this member's
        elements, and returns the worst-case N, My, Mz, T, Vy, Vz per load case.
        """
        by_lc: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for rec in self.parsed_results.get("section_forces", []):
            if not isinstance(rec, dict):
                continue
            if rec.get("element_id") not in elem_ids:
                continue
            lc = rec.get("load_case", "_combined")
            by_lc[lc]["N"].append(abs(rec.get("N", 0.0)))
            by_lc[lc]["T"].append(abs(rec.get("T", 0.0)))
            by_lc[lc]["Mf1"].append(abs(rec.get("Mf1", 0.0)))
            by_lc[lc]["Mf2"].append(abs(rec.get("Mf2", 0.0)))
            by_lc[lc]["Vf1"].append(abs(rec.get("Vf1", 0.0)))
            by_lc[lc]["Vf2"].append(abs(rec.get("Vf2", 0.0)))

        result = {}
        for lc, components in by_lc.items():
            result[lc] = {
                "max_N_N": max(components["N"]) if components["N"] else 0.0,
                "max_T_Nm": max(components["T"]) if components["T"] else 0.0,
                "max_Mf1_Nm": max(components["Mf1"]) if components["Mf1"] else 0.0,
                "max_Mf2_Nm": max(components["Mf2"]) if components["Mf2"] else 0.0,
                "max_Vf1_N": max(components["Vf1"]) if components["Vf1"] else 0.0,
                "max_Vf2_N": max(components["Vf2"]) if components["Vf2"] else 0.0,
            }
        return result

    def _member_utilisation(
        self, sf_by_lc: Dict[str, Dict[str, float]], member
    ) -> Dict[str, Dict[str, float]]:
        """Compute bending utilisation ratio per load case.

        σ_max = |N|/A + |Mf1|/Iy * y_max + |Mf2|/Iz * z_max

        Returns per-load-case dict with ``max_utilisation_ratio`` (dimensionless,
        where 1.0 = yield stress) when section properties are available.
        Yield stress is not known here — callers should normalise against their
        material yield stress externally, or pass it via the ``limits`` dict as
        ``yield_stress_Pa``.  We instead return the raw stress σ_max in Pa as
        ``max_bending_stress_Pa`` so the caller can decide.
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
        except Exception:
            return {}
        if y_max is None or z_max is None:
            return {}

        result = {}
        for lc, sf in sf_by_lc.items():
            n = sf.get("max_N_N", 0.0)
            mf1 = sf.get("max_Mf1_Nm", 0.0)
            mf2 = sf.get("max_Mf2_Nm", 0.0)
            sigma = n / area + mf1 / iy * y_max + mf2 / iz * z_max
            result[lc] = {"max_bending_stress_Pa": sigma}
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
            if envelope.get(key, 0.0) > limit:
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
