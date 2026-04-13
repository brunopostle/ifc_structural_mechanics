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
    "total": {"fx_N": 0.0, "fy_N": 0.0, "fz_N": 5000.0,
              "mx_Nm": 0.0, "my_Nm": 0.0, "mz_Nm": 0.0}
  }
}

Per-member displacement is mapped via ``StructuralModel.node_to_member`` which is
populated by the meshing pipeline.  Per-member stress follows the same mapping;
for B31 beam elements CalculiX internally expands to C3D8I bricks whose nodes
are not in the original mesh, so beam stress results often contain only global
values — this is a known limitation noted in the output.
"""

import json
import logging
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional

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
    """

    SCHEMA_VERSION = "1.0"

    def __init__(
        self,
        domain_model,
        parsed_results: Dict[str, List],
        limits: Optional[Dict[str, float]] = None,
    ):
        self.model = domain_model
        self.parsed_results = parsed_results
        self.limits = limits or {}

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
        node_ids: set = {
            int(nid) for nid, mid in self.model.node_to_member.items() if mid == member_id
        }
        elem_ids: set = set(getattr(member, "analysis_element_ids", []))

        disp_by_lc = self._member_displacements(node_ids)
        stress_by_lc = self._member_stresses(node_ids)
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
        if envelope:
            result["envelope"] = envelope
        if by_load_case:
            result["by_load_case"] = by_load_case
        return result

    def _member_displacements(self, node_ids: set) -> Dict[str, Dict[str, float]]:
        """Return per-load-case displacement stats for the given node set."""
        by_lc: Dict[str, List[float]] = defaultdict(list)
        for r in self.parsed_results.get("displacement", []):
            try:
                nid = int(r.reference_element)
            except (ValueError, TypeError):
                continue
            if nid not in node_ids:
                continue
            mag = r.get_magnitude()
            lc = r.metadata.get("load_case", "_combined")
            by_lc[lc].append(mag)

        return {
            lc: {"max_displacement_m": max(mags)} for lc, mags in by_lc.items() if mags
        }

    def _member_stresses(self, node_ids: set) -> Dict[str, Dict[str, float]]:
        """Return per-load-case von Mises stats for the given node set.

        Node IDs that don't appear in ``node_ids`` (e.g. CalculiX-expanded
        beam brick nodes) are silently skipped.
        """
        by_lc: Dict[str, List[float]] = defaultdict(list)
        for r in self.parsed_results.get("stress", []):
            try:
                nid = int(r.reference_element)
            except (ValueError, TypeError):
                continue
            if nid not in node_ids:
                continue
            try:
                vm = r.get_von_mises_stress()
            except (ValueError, KeyError):
                continue
            lc = r.metadata.get("load_case", "_combined")
            by_lc[lc].append(vm)

        return {
            lc: {"max_von_mises_Pa": max(values)}
            for lc, values in by_lc.items()
            if values
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

        total = next(
            (r for r in reaction_results if r.reference_element == "TOTAL"), None
        )
        if not total:
            return {}

        forces = total.get_forces()
        moments = total.get_moments()
        return {
            "total": {
                "fx_N": forces[0],
                "fy_N": forces[1],
                "fz_N": forces[2],
                "mx_Nm": moments[0],
                "my_Nm": moments[1],
                "mz_Nm": moments[2],
                "resultant_N": math.sqrt(sum(f * f for f in forces)),
            }
        }
