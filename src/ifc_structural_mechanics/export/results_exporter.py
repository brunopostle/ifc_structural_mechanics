"""JSON results exporter for ifc_structural_mechanics.

Consumes a ``StructuralModel`` (post-analysis, with node/element memberships
registered) and the ``parsed_results`` dict returned by ``ResultsParser``, and
writes a ``results.json`` file keyed to IFC GlobalIds.

Schema (summary level)
----------------------
{
  "schema_version": "1.8",
  "units": {"length": "m", "force": "N", "moment": "N*m",
            "stress": "Pa", "displacement": "m"},
  "model": {"id": "...", "name": "..."},
  "analysis_type": "linear_static" | "linear_buckling",
  "load_cases": ["Dead", "Live"],
  "load_combinations": [
    {"name": "ULS", "ifc_guid": "...", "factors": {"Dead": 1.35, "Live": 1.5}}
  ],
  "members": [
    {
      "ifc_guid": "...",
      "id": "...",
      "type": "curve" | "surface",
      "status": "ok" | "warning" | "fail",
      "section_model": "equivalent_rectangle",
      "tied_to_surface_members": ["..."],
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
                              "mx_Nm": 0.0, "my_Nm": -1.25e4, "mz_Nm": 0.0,
                              "resultant_N": 5000.0,
                              "forces": "solver" | "supports",
                              "applied_load_N": [0.0, 0.0, -5000.0],
                              "imbalance_N": 0.0,
                              "applied_moment_Nm": [0.0, 1.25e4, 0.0],
                              "moment_imbalance_Nm": 0.0}},
    "total": {...}
  },
  "supports": [
    {
      "ifc_guid": "...",
      "id": "...",
      "type": "point" | "line",
      "position_m": [0.0, 0.0, 0.0],
      "restrained": ["tx", "ty", "tz", "ry"],
      "forces": "solver" | "member_end_forces" | "unreliable",
      "moments": "solver" | "member_end_forces" | "none_restrained"
                 | "not_computed",
      "by_load_case": {
        "Dead": {"fx_N": 0.0, "fy_N": 0.0, "fz_N": 5000.0,
                 "mx_Nm": 0.0, "my_Nm": -1.0e4, "mz_Nm": 0.0,
                 "resultant_N": 5000.0}
      },
      "axes": {"x": [...], "y": [...], "z": [...]},
      "by_load_case_in_axes": {"Dead": {"fx_N": ..., ..., "mz_Nm": ...}}
    }
  ]
}

``analysis_type`` (schema 1.4) says what was run. A buckling analysis has one
set of results, named in ``load_cases``: the model under all of its loads
together, every load case and its self-weight. It has no reactions or
stresses. ``buckling`` is then present:

  "buckling": {"reference_load_case": "Reference loads",
               "modes": [{"mode": 1, "factor": 12.3}, ...]}

Each ``factor`` is what those loads have to be multiplied by for the model to
buckle in that mode, lowest first. The mode shapes are in the solver's result
file and not here: they are scaled to a largest value of one, so they are not
displacements.

``load_combinations`` (schema 1.2) lists the load combinations of the file,
each with the factor of every load case in it. A combination's results are
those of its load cases, each multiplied by its factor and added: the solver
runs the load cases only, and the analysis has to be linear static. What is
added is what is linear in the load (displacement vectors, stress components,
section forces at each cross-section, forces at support nodes); magnitudes,
von Mises stress, the largest values along a member and its section force
diagram are then worked out from the sums, exactly as for a load case. They
are found beside each ``by_load_case``, under the combination's name:

- ``members[]``: ``by_load_combination``, ``combination_envelope`` (the
  largest of each value over the combinations; ``envelope`` remains that of
  the load cases) and ``section_force_diagrams_by_combination``. ``status``
  fails if either envelope is over a limit.
- ``global_displacements`` and ``global_reactions``: ``by_load_combination``.
- ``supports[]``: ``by_load_combination`` and, where the support has axes of
  its own, ``by_load_combination_in_axes``.

A load case that has no loads was not solved and adds nothing; a combination
that includes one names it in ``cases_without_loads``, and one made only of
such cases is listed without results. Two combinations of one name have the
GlobalId added to the name of the second. Combinations that cannot be formed
(no load case, or something in them that is not a load case) are not listed;
the analysis warns about them. A load case includes the weight of the members
when the file says so (``SelfWeightCoefficients``). Self-weight asked for with
``--gravity`` is a load case of its own, ``Gravity``, which no combination of
the file includes.

``global_reactions`` entries also carry (schema 1.1) ``applied_load_N``, the
whole load of the case as written to the solver ``[fx, fy, fz]``, and
``imbalance_N``, the size of what is left when it is added to the reaction.
It should be nothing. CalculiX 2.21 and earlier misreport the force along a
member at a support that holds the member's rotation, and the analysis warns
when that happens. ``forces`` (schema 1.8) says where the entry's forces come
from: ``solver``, its own total, or ``supports``, those of ``supports`` added
up, when the solver's total does not balance the loads, some supports' forces
had to be taken from member ends and none is ``unreliable``. If one is, the
total is the solver's and does not balance.

The moments of a ``global_reactions`` entry (schema 1.7) are those of the
reactions about the origin of the global axes: for each support of
``supports``, its moments and the moment of its force at ``position_m``,
added up. The solver has no such figure, and until 1.7 these keys were
always zero. They are absent when a support has no moments (``moments`` is
``not_computed``) or the model's supports are not known. Note that they are
made of the forces ``supports`` gives, which are not the solver's where it
got them wrong (``forces``). ``applied_moment_Nm`` is the moment about the same point of
the loads as written to the solver, forces where they act and moments
applied, ``[mx, my, mz]``, and ``moment_imbalance_Nm`` the size of what is
left when it is added to the reactions' moment. It should be nothing next to
either: a restraint the analysis added to hold the model (see the warnings)
is in neither ``supports`` nor here, and what it takes shows up as this.

``supports`` (schema 1.1) has the reaction at each support: what the support
exerts on the structure, at ``position_m``, in global axes. ``restrained``
lists the global directions the support holds (t for translation, r for
rotation). A skew support holds directions that are not global ones, which
are not in that list: ``restrained_in_axes`` (schema 1.3) has what it holds
along its own ``axes``. The forces are the solver's, summed over the
support's nodes. For a line support ``position_m`` is the middle of its edge.

The solver gives a beam or shell node no moment, so the moments come from
elsewhere, and ``moments`` says where:

- ``none_restrained``: the support holds no rotation; the moments are those
  of its nodal forces about ``position_m`` (zero for a point support).
- ``solver`` (schema 1.6): the support holds a rotation. The solver expands
  beams and shells into solids and gives the force on each of their nodes;
  the moments are those of the forces on the nodes the support's own were
  expanded into, about ``position_m``, less the moments applied at the
  support itself. They are in equilibrium with the loads as the forces are,
  for a member end, a clamped slab edge and a support a member runs on past
  alike. For a line support they include what its forces do about the middle
  of its edge.
- ``member_end_forces``: the solver's forces at the support are wrong (see
  ``forces``) or cannot be attributed to its nodes (a user element), and
  every member it connects is a curve member ending there. The moments are
  the section forces at those member ends, moved to ``position_m``, about the
  restrained axes. They are integrated from stresses and are good to about
  1 %.
- ``not_computed``: neither can be had: the solver's forces are wrong or not
  attributable, and the support joins a surface member, a member that runs on
  past it, one tied to a surface member along its length, or one without
  section forces. The moment keys are absent, not
  zero.

``forces`` says where the forces come from. ``solver`` is the normal case.
CalculiX 2.21 and earlier misreport the force at a support that holds a
rotation. Where the solver's force at such a support is more than 3 % from
the force at the ends of its members, or the reactions of the load case do
not balance its loads, the support has ``member_end_forces`` (good to about
1 %), and its moments come from there as well, less any point load applied
at the support itself, which the member has none of. The solver is wrong at
member ends only, so if the supports then balance the loads to 1 % the others
are as the solver has them. If they do not, a support that holds a rotation
and has no member ends to go by (see ``moments``) has ``unreliable``: the
solver's figures are given, may be wrong, and it has no moments. The analysis
warns in both cases.

``axes``, ``restrained_in_axes`` and ``by_load_case_in_axes`` are present when
the support has axes of its own (a ``ConditionCoordinateSystem``, or the edge
of a line support); the last gives the same reactions along them.

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

``tied_to_surface_members`` is only present on curve members that were tied
along their length to the surface members they lie in (a beam under a slab, a
column in a wall), and lists those. Force passes between the two at every
node, so the member's section forces are its share only. Where that happens
at a point (the end of a wall) they change abruptly from one cross-section to
the next and their largest values, the envelope with them, depend on the mesh
size.

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

import numpy as np

from ..analysis.plausibility import BALANCE_LIMIT, BALANCE_NOISE_N
from ..analysis.superposition import combine_results
from ..utils.error_handling import ResultProcessingError

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
        load_combinations: The ``LoadCombination`` objects to give results
            for, by adding up their load cases. Only for a linear analysis
            with a step per load case.
        analysis_type: ``"linear_static"`` or ``"linear_buckling"``.
    """

    SCHEMA_VERSION = "1.8"

    def __init__(
        self,
        domain_model,
        parsed_results: Dict[str, List],
        limits: Optional[Dict[str, float]] = None,
        element_nodes: Optional[Dict[int, List[int]]] = None,
        load_combinations: Optional[List] = None,
        analysis_type: str = "linear_static",
    ):
        self.model = domain_model
        self.analysis_type = analysis_type
        self.parsed_results = parsed_results
        self.limits = limits or {}
        self.element_nodes = element_nodes or {}
        self._elements_at_node: Optional[Dict[int, List[int]]] = None
        self.load_combinations = list(load_combinations or [])
        # What each solver step put on the structure, in step order
        self._support_node_loads = getattr(domain_model, "support_node_loads", None)
        self._applied_load_totals = getattr(domain_model, "applied_load_totals", None)
        self._applied_load_moments = getattr(domain_model, "applied_load_moments", None)
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
        supports = self._supports()
        data = {
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
            "analysis_type": self.analysis_type,
            "load_cases": load_cases,
            "members": [self._member_entry(m) for m in self.model.members],
            "global_displacements": self._global_displacements(),
            "global_reactions": self._global_reactions(supports),
            "supports": supports,
        }
        if self.analysis_type == "linear_buckling":
            data["buckling"] = self._buckling(load_cases)
        self._add_load_combinations(data)
        return data

    def _buckling(self, load_cases: List[str]) -> Dict[str, Any]:
        """Return the buckling factors, lowest first."""
        factors = self.parsed_results.get("buckling") or []
        if not factors:
            raise ResultProcessingError(
                "The buckling analysis ran but the solver reported no "
                "buckling factors."
            )
        return {
            "reference_load_case": load_cases[0] if load_cases else None,
            "modes": [
                {"mode": int(mode), "factor": float(factor)}
                for mode, factor in sorted(factors)
            ],
        }

    # ------------------------------------------------------------------
    # Load combinations
    # ------------------------------------------------------------------

    def _add_load_combinations(self, data: Dict[str, Any]) -> None:
        """Add the results of each load combination to *data*.

        A combination's results are those of its load cases, each multiplied
        by its factor and added (``analysis/superposition.py``); everything
        that is not linear in the load is then worked out from the sums by
        this class, run on them as it is run on a load case. One combination
        is held at a time.
        """
        if not self.load_combinations:
            return
        solved = set(data["load_cases"])
        listed: List[Dict[str, Any]] = []
        names: set = set()
        for combination in self.load_combinations:
            name = combination.name
            if name in names:
                # Two combinations of one name: tell them apart
                name = f"{name} ({combination.id})"
            names.add(name)
            factors: Dict[str, float] = {}
            without_loads: List[str] = []
            for group_id, factor in combination.load_groups.items():
                group = self.model.get_load_group(group_id)
                case = group.name if group is not None else group_id
                factors[case] = factors.get(case, 0.0) + float(factor)
                if case not in solved:
                    without_loads.append(case)
            entry: Dict[str, Any] = {
                "name": name,
                "ifc_guid": combination.id,
                "factors": factors,
            }
            if without_loads:
                entry["cases_without_loads"] = without_loads
            listed.append(entry)
            active = {c: f for c, f in factors.items() if c in solved}
            if active:
                self._add_one_combination(data, name, active)
        data["load_combinations"] = listed

        for member in data["members"]:
            by_combination = member.get("by_load_combination")
            if not by_combination:
                continue
            envelope = self._envelope(
                {
                    name: {k: v for k, v in d.items() if isinstance(v, float)}
                    for name, d in by_combination.items()
                }
            )
            forces = {
                name: d["section_forces"]
                for name, d in by_combination.items()
                if "section_forces" in d
            }
            if forces:
                envelope["section_forces"] = self._envelope(forces)
            member["combination_envelope"] = envelope
            if self._status(envelope) == "fail":
                member["status"] = "fail"

    def _add_one_combination(
        self, data: Dict[str, Any], name: str, factors: Dict[str, float]
    ) -> None:
        combined, node_loads, load_totals, load_moments = combine_results(
            self.parsed_results,
            factors,
            name,
            self._support_node_loads,
            self._applied_load_totals,
            self._applied_load_moments,
        )
        part = ResultsExporter(
            self.model, combined, limits=self.limits, element_nodes=self.element_nodes
        )
        part._support_node_loads = node_loads
        part._applied_load_totals = load_totals
        part._applied_load_moments = load_moments
        part._mesh_nodes = self._mesh_nodes
        result = part._build()

        for member, combined_member in zip(data["members"], result["members"]):
            values = combined_member.get("by_load_case", {}).get(name)
            if values is not None:
                member.setdefault("by_load_combination", {})[name] = values
            diagram = combined_member.get("section_force_diagrams", {}).get(name)
            if diagram is not None:
                member.setdefault("section_force_diagrams_by_combination", {})[
                    name
                ] = diagram

        for block in ("global_displacements", "global_reactions"):
            values = result.get(block, {}).get("by_load_case", {}).get(name)
            if values is not None:
                data[block].setdefault("by_load_combination", {})[name] = values

        for support, combined_support in zip(data["supports"], result["supports"]):
            for key in ("by_load_case", "by_load_case_in_axes"):
                values = combined_support.get(key, {}).get(name)
                if values is not None:
                    target = key.replace("load_case", "load_combination")
                    support.setdefault(target, {})[name] = values
            # A reaction the solver got wrong in a load case is wrong in the
            # combination; one it only gets wrong added up is as unusable
            if combined_support["forces"] != "solver" and support["forces"] == "solver":
                support["forces"] = combined_support["forces"]
            if combined_support["moments"] != support["moments"] == "solver":
                support["moments"] = combined_support["moments"]

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
        diagrams = self._member_diagrams(elem_ids)
        sf_by_lc = self._member_section_forces(elem_ids, diagrams)
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
        tied_to = getattr(member, "tied_to_surface_members", None)
        if tied_to:
            result["tied_to_surface_members"] = list(tied_to)
        if envelope:
            result["envelope"] = envelope
        if by_load_case:
            result["by_load_case"] = by_load_case
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

    def _member_section_forces(
        self, elem_ids: set, diagrams: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, Dict[str, float]]:
        """Return per-load-case section force envelopes for the given element set.

        The largest magnitude of N, T, Mf1, Mf2, Vf1 and Vf2 over every
        cross-section of the member's elements, per load case, and the
        largest tension and compression. The maxima need not occur at the
        same cross-section. Where a load case has a diagram in ``diagrams``
        the values are its own: where a force jumps it has the value on each
        side, and the cross-sections have their mean (an applied moment of
        1000 N·m in the middle of a beam is 500 on each side and nothing in
        the mean; next to a point load the mean can be the larger).
        """
        index = self._section_force_index()
        result: Dict[str, Dict[str, float]] = {}
        for elem_id in elem_ids:
            for rec in index.get(elem_id, ()):
                if rec.get("load_case", "_combined") in (diagrams or {}):
                    continue
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
        names = dict(self._DIAGRAM_KEYS)
        for case, diagram in (diagrams or {}).items():
            entry = result.setdefault(
                case,
                {
                    **{name: 0.0 for _, name in self._FORCE_KEYS},
                    "max_tension_N": 0.0,
                    "max_compression_N": 0.0,
                },
            )
            for key, name in self._FORCE_KEYS:
                values = diagram.get(names.get(key, ""), ())
                entry[name] = max([entry[name]] + [abs(v) for v in values])
            for axial in diagram.get("N_N", ()):
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
            self._restore_jumps(records, scales, self._ends_shared(elem_ids))
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
    # out of line with the others is a jump.
    _JUMPING_FORCES = ("N", "Vf1", "Vf2", "T")
    # A bending moment changes by its shear force per metre, so a change that
    # the shear does not account for is a jump: an applied moment.
    _MOMENTS_AND_SHEARS = (("Mf1", "Vf1"), ("Mf2", "Vf2"))

    def _ends_shared(self, elem_ids: set) -> set:
        """Elements of a member that share nodes with an element of another.

        Members in line that are joined rigidly are expanded into solids that
        share the nodes of the cross-section between them, as two elements of
        one member do, and the solver's stress there is the mean of the two.
        (Members at an angle meet in a knot and keep their own nodes.)
        """
        if self._elements_at_node is None:
            at_node: Dict[int, List[int]] = defaultdict(list)
            for element, nodes in self.element_nodes.items():
                for node in nodes:
                    at_node[node].append(element)
            self._elements_at_node = at_node
        return {
            element
            for element in elem_ids
            for node in self.element_nodes.get(element, ())
            if any(other not in elem_ids for other in self._elements_at_node[node])
        }

    def _restore_jumps(
        self,
        records: List[Dict],
        scales: Dict[str, float],
        shared_ends: Optional[set] = None,
    ) -> None:
        """Put back the jumps that nodal averaging smooths out, in place.

        Two elements in line share the nodes of the cross-section between
        them, and the solver reports one averaged stress there. Under a point
        load the shear is then the mean of its values on the two sides, and a
        diagram shows a ramp where there is a step; under an applied moment
        the bending moment is, and the diagram passes through nothing where
        it should reach half the moment on each side.

        The middle cross-section of a quadratic element is its own, and a
        force there is the mean of the element's own values at its two ends,
        less what the load does to it by varying along the element. Where the
        solver's value at an end is the mean with a neighbour's, the middle
        is out by a quarter of the jump there, which ``_jumps_between()``
        looks for. Nothing is assumed of the load along the member: the
        slopes between middles were once compared with their median, which
        put a step at every element end under a load that varied or stopped
        part of the way (``aiz.84``).

        A bending moment changes by its shear force per metre, which the
        middles on either side give, so a change the shear does not account
        for is a jump. The averaged value is replaced by one on each side,
        half the jump apart, when the jump is more than ``_JUMP_FRACTION`` of
        the force's largest value. Two quadratic elements are enough; linear
        elements have no middle cross-section and are left as they are.

        The end of a member that runs on into another in line
        (``shared_ends``: the elements that share nodes with another
        member's) is averaged with that member, which is not in ``records``.
        It is treated as one more cross-section with a jump to find.
        """
        middles = sorted(
            (r for r in records if r["position"] == 0.0), key=lambda r: r["distance"]
        )
        if len(middles) < 2:
            return
        ends = {(r["element_id"], r["position"]): r for r in records}
        pairs = [
            (a, b, b["distance"] - a["distance"])
            for a, b in zip(middles, middles[1:])
            if b["distance"] - a["distance"] > 1e-12
        ]

        def interface(a: Dict, b: Dict, key: str):
            """The records of the cross-section two elements share, if they do."""
            left = ends.get((a["element_id"], 1.0))
            right = ends.get((b["element_id"], -1.0))
            if left is None or right is None:
                return None
            shared = (
                abs(left["distance"] - right["distance"]) < 1e-9
                and abs(left.get(key, 0.0) - right.get(key, 0.0)) <= 1e-9 * scales[key]
            )
            # Separate nodes: the values are already one-sided
            return (left, right) if shared else None

        def set_apart(left: Dict, right: Dict, key: str, jump: float) -> None:
            if abs(jump) > self._JUMP_FRACTION * scales[key]:
                average = left.get(key, 0.0)
                left[key] = average - jump / 2.0
                right[key] = average + jump / 2.0

        # The outermost cross-sections, where they are shared with a member
        # that runs on: (record, its element's own middle)
        outer = []
        outer_start = outer_end = None
        for middle, position in ((middles[0], -1.0), (middles[-1], 1.0)):
            record = ends.get((middle["element_id"], position))
            if record is not None and middle["element_id"] in (shared_ends or ()):
                outer.append((record, middle))
                if position < 0.0:
                    outer_start = record
                else:
                    outer_end = record

        for key in self._JUMPING_FORCES:
            if scales.get(key, 0.0) <= 0.0:
                continue
            # What the middle of each element has over the mean of its ends
            excess: List[Optional[float]] = []
            lengths: List[float] = []
            for middle in middles:
                first = ends.get((middle["element_id"], -1.0))
                last = ends.get((middle["element_id"], 1.0))
                length = (
                    0.0
                    if first is None or last is None
                    else last["distance"] - first["distance"]
                )
                lengths.append(length)
                if first is None or last is None or length <= 1e-12:
                    excess.append(None)
                else:
                    excess.append(
                        middle.get(key, 0.0)
                        - 0.5 * (first.get(key, 0.0) + last.get(key, 0.0))
                    )
            between = [interface(a, b, key) for a, b in zip(middles, middles[1:])]
            jumps = self._jumps_between(
                excess,
                lengths,
                outer_start is not None,
                outer_end is not None,
                self._JUMP_FRACTION * scales[key],
            )
            for n, found in enumerate(between):
                if found and jumps.get(n):
                    set_apart(*found, key, jumps[n])
            for record, n, side in (
                (outer_start, -1, 1.0),
                (outer_end, len(between), -1.0),
            ):
                # Half of the jump is this member's side of it
                if record is not None and (
                    abs(jumps.get(n, 0.0)) > 2.0 * self._JUMP_FRACTION * scales[key]
                ):
                    record[key] = record.get(key, 0.0) + side * jumps[n] / 2.0

        for moment, shear in self._MOMENTS_AND_SHEARS:
            if scales.get(moment, 0.0) <= 0.0:
                continue
            # Whether the moment rises or falls with a positive shear: as
            # most stretches have it, since one with a jump in it says
            # nothing
            changes = sorted(
                (b.get(moment, 0.0) - a.get(moment, 0.0))
                * (a.get(shear, 0.0) + b.get(shear, 0.0))
                for a, b, _ in pairs
            )
            sign = -1.0 if changes and changes[len(changes) // 2] < 0.0 else 1.0
            for a, b, gap in pairs:
                found = interface(a, b, moment)
                if not found:
                    continue
                # The shear on each side, as restored above, with its middle
                left, right = found
                at = left["distance"]
                sheared = (
                    sign
                    * 0.5
                    * (
                        (a.get(shear, 0.0) + left.get(shear, 0.0))
                        * (at - a["distance"])
                        + (right.get(shear, 0.0) + b.get(shear, 0.0))
                        * (b["distance"] - at)
                    )
                )
                jump = b.get(moment, 0.0) - a.get(moment, 0.0) - sheared
                set_apart(*found, moment, jump)
            for record, middle in outer:
                reach = record["distance"] - middle["distance"]
                mean_shear = 0.5 * (middle.get(shear, 0.0) + record.get(shear, 0.0))
                value = middle.get(moment, 0.0) + sign * mean_shear * reach
                if abs(value - record.get(moment, 0.0)) > (
                    self._JUMP_FRACTION * scales[moment]
                ):
                    record[moment] = value

    # How many cross-sections say what is usual for the one in their middle
    _JUMP_WINDOW = 7

    @classmethod
    def _jumps_between(
        cls,
        excess: List[Optional[float]],
        lengths: List[float],
        start_shared: bool,
        end_shared: bool,
        tolerance: float,
    ) -> Dict[int, float]:
        """The jumps of a force at the cross-sections between elements.

        ``excess[e]`` is what the force at the middle of element ``e`` has
        over the mean of the solver's values at its ends, and ``lengths[e]``
        its length. With ``J[n]`` the jump between elements ``n`` and
        ``n + 1`` (the value after less the value before), an element's own
        ends are the solver's values with half a jump taken off or put on,
        and::

            4 excess[e] = J[e - 1] - J[e] + (what the load does in e)

        The load's part is half the change of the load per metre times the
        square of the element's length: nothing under a uniform load or
        none, whether it covers the member or not, and in proportion to the
        squares of the lengths where the load varies linearly. Added up from
        the start of the member, the left sides are then on a straight line
        against the sum of those squares, except at a cross-section with a
        jump, which is off the line by the jump.

        The line is looked for among the ``_JUMP_WINDOW`` cross-sections
        around each one, so that it follows a load that curves: the one
        through two of them that has the most of them within half of
        ``tolerance``, fitted to those. When that is not more than half of
        them the line says nothing, and no jump is given: a member tied to a
        slab at every node has a force coming in at each of them, the middle
        ones as well.

        A member with fewer than four elements has too few for that: the
        line then goes through its two ends, where they have no jump to
        find, and is level through one. The end of a member that runs on
        into another (``start_shared``, ``end_shared``) is a cross-section
        ``-1`` or ``len(excess) - 1`` with a jump of its own.

        Returns the jump at every cross-section, small or not; none where a
        value is missing.
        """
        count = len(excess)
        if count < 2 or any(value is None for value in excess):
            return {}
        # At cross-section n - 1, for n from 0: the sum so far and where it
        # is plotted
        sums, places = [0.0], [0.0]
        for value, length in zip(excess, lengths):
            sums.append(sums[-1] + 4.0 * value)
            places.append(places[-1] + length**2)

        usual: List[float] = []
        if count >= 4:
            usual = cls._lines_most_are_on(places, sums, 0.5 * tolerance)
        elif not start_shared and not end_shared:
            usual = [sums[-1] * place / places[-1] for place in places]
        elif not start_shared:
            usual = [0.0] * (count + 1)
        elif not end_shared:
            usual = [sums[-1]] * (count + 1)
        else:
            return {}
        return {n - 1: usual[n] - sums[n] for n in range(count + 1)}

    @classmethod
    def _lines_most_are_on(
        cls, xs: List[float], ys: List[float], band: float
    ) -> List[float]:
        """For each point, the line most of the points around it are on.

        Each point has the ``_JUMP_WINDOW`` points around it (those at an
        end, the first or last that many). Of the lines through two of them,
        the one with the most of them within ``band`` is kept, the closest
        one of several, and fitted to those by least squares. Returns its
        value at each point, or the point's own value where the line has no
        more than half of the points on it.
        """
        x, y = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
        width = min(cls._JUMP_WINDOW, len(x))
        first = np.clip(np.arange(len(x)) - width // 2, 0, len(x) - width)
        window = first[:, None] + np.arange(width)[None, :]
        wx, wy = x[window], y[window]
        one, other = np.triu_indices(width, 1)
        slope = (wy[:, other] - wy[:, one]) / (wx[:, other] - wx[:, one])
        # Windows, lines, points
        off = np.abs(
            wy[:, None, :]
            - wy[:, one, None]
            - slope[:, :, None] * (wx[:, None, :] - wx[:, one, None])
        )
        on = off <= band
        # The number on the line first, how close they are second
        score = on.sum(axis=2) - (off * on).sum(axis=2) / (band * width + 1e-300)
        best = np.argmax(score, axis=1)
        rows = np.arange(len(x))
        weight = on[rows, best, :].astype(float)
        number = weight.sum(axis=1)
        mean_x = (weight * wx).sum(axis=1) / number
        mean_y = (weight * wy).sum(axis=1) / number
        spread = (weight * (wx - mean_x[:, None]) ** 2).sum(axis=1)
        fitted = (weight * (wx - mean_x[:, None]) * (wy - mean_y[:, None])).sum(
            axis=1
        ) / np.where(spread > 0.0, spread, 1.0)
        value = mean_y + fitted * (x - mean_x)
        return [float(v) for v in np.where(2 * number > width, value, y)]

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
            if not results:
                return None
            largest = 0.0
            along = [0.0, 0.0, 0.0]
            for r in results:
                tx, ty, tz = r.get_translations()
                largest = max(largest, tx * tx + ty * ty + tz * tz)
                along[0] = max(along[0], abs(tx))
                along[1] = max(along[1], abs(ty))
                along[2] = max(along[2], abs(tz))
            stats: Dict[str, float] = {"max_displacement_m": math.sqrt(largest)}
            for key, value in zip(("max_tx_m", "max_ty_m", "max_tz_m"), along):
                if value > 0:
                    stats[key] = value
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
    # Reactions at each support
    # ------------------------------------------------------------------

    # A support further than this inside a member's length is not at its end:
    # the member runs on past it, and its end forces are not the support's
    _END_TOLERANCE = 1e-3

    def _supports(self) -> List[Dict[str, Any]]:
        """The reaction at every support, per load case.

        Forces are the solver's, summed over the nodes the support restrains.
        A node two supports share is counted for the first of them.
        """
        recorded = getattr(self.model, "support_nodes", None) or {}
        steps = self.parsed_results.get("support_node_forces") or []
        if not isinstance(recorded, dict) or not recorded or not steps:
            return []

        def entries(trusted: bool) -> List[Dict[str, Any]]:
            found = []
            taken: set = set()
            for connection in self.model.connections:
                record = recorded.get(connection.id)
                if not record:
                    continue
                nodes = {n: xyz for n, xyz in record["nodes"].items() if n not in taken}
                taken.update(nodes)
                found.append(
                    self._support_entry(connection, record, nodes, steps, trusted)
                )
            return found

        # Where the solver's reactions do not balance the loads, those at
        # member ends that hold a rotation are replaced. If the whole then
        # balances, the solver was right at the other supports
        supports = entries(trusted=True)
        if all(
            self._reactions_balance(index)
            or self._supports_balance(supports, index, step["load_case"])
            for index, step in enumerate(steps)
        ):
            return supports
        return entries(trusted=False)

    # The forces at the ends of members are good to about 1 %; with some of
    # the supports' forces taken from there, the whole balances the loads
    # this closely or the solver's figure at another support is wrong too
    _REPLACED_BALANCE_LIMIT = 0.01

    def _supports_balance(
        self, supports: List[Dict[str, Any]], step_index: int, case: str
    ) -> bool:
        """Whether the supports' forces balance the loads of one step."""
        loads = self._applied_load_totals
        if not isinstance(loads, list) or step_index >= len(loads):
            return False
        load = np.array(loads[step_index], dtype=float)
        whole = self._force_of_supports(supports, case)
        if whole is None:
            return False
        size = max(float(np.linalg.norm(load)), float(np.linalg.norm(whole)))
        return float(np.linalg.norm(whole + load)) <= max(
            BALANCE_NOISE_N, self._REPLACED_BALANCE_LIMIT * size
        )

    @staticmethod
    def _force_of_supports(
        supports: List[Dict[str, Any]], case: str
    ) -> Optional[np.ndarray]:
        """The forces of all the supports in one load case, added up."""
        whole = np.zeros(3)
        for support in supports:
            values = support.get("by_load_case", {}).get(case)
            if values is None:
                return None
            whole += [values["fx_N"], values["fy_N"], values["fz_N"]]
        return whole

    def _support_entry(
        self,
        connection,
        record: Dict,
        nodes: Dict[int, tuple],
        steps: List[Dict],
        trusted: bool = True,
    ) -> Dict[str, Any]:
        """One support's reactions.

        ``trusted`` says the solver's forces are right at a support that has
        no member end to check them against, in a load case its reactions do
        not balance: see ``_supports``.
        """
        edge = getattr(connection, "edge", None)
        if edge is not None and len(edge) == 2:
            kind = "line"
            position = (np.array(edge[0], float) + np.array(edge[1], float)) / 2.0
        else:
            kind = "point"
            position = np.array(connection.position, dtype=float)
        # What the support holds, as projections onto those directions
        hold = self._projection(record, "translations", 1)
        turn = self._projection(record, "rotations", 4)
        held_rotations = bool(turn.any())

        entry: Dict[str, Any] = {
            "ifc_guid": getattr(connection, "ifc_guid", None),
            "id": connection.id,
            "type": kind,
            "position_m": [float(v) for v in position],
            "restrained": self._held_names(hold, turn, np.eye(3)),
        }
        entry["forces"] = "solver"
        ends = self._member_ends_at(connection, position) if held_rotations else {}
        balanced = all(self._reactions_balance(index) for index in range(len(steps)))
        # The solver is known to go wrong at member ends that hold a
        # rotation; a support with those is not taken on trust
        balanced = balanced or (trusted and not ends)

        # Per load case: the solver's force, the moment of its nodal forces,
        # and what the ends of the members give for both
        solved: List[Tuple[np.ndarray, Optional[np.ndarray]]] = []
        at_ends: List[Optional[Tuple[np.ndarray, np.ndarray]]] = []
        # The solver's forces are not to be trusted at this support
        mistaken = not balanced
        for index, step in enumerate(steps):
            applied = self._loads_on_support_nodes(index)
            applied_moments = self._moments_on_support_nodes(index)
            pushed = self._point_forces_on_support_nodes(index)
            couples = self._support_node_moments(index, nodes) if balanced else None
            force = np.zeros(3)
            moment = np.zeros(3)
            for node, xyz in nodes.items():
                # The solver gives the force inside the structure at the
                # node; the reaction is that less the load applied there
                nodal = np.array(step["forces"].get(node, (0.0, 0.0, 0.0)))
                nodal = nodal - np.array(applied.get(node, (0.0, 0.0, 0.0)))
                force += nodal
                moment += np.cross(np.array(xyz) - position, nodal)
            nodal_moment: Optional[np.ndarray] = moment
            if held_rotations:
                # A node that takes a moment has it in the forces on the
                # nodes it was expanded into, with every moment applied there
                nodal_moment = None
                if couples is not None:
                    nodal_moment = moment + sum(couples.values(), np.zeros(3))
                    for node in nodes:
                        nodal_moment -= self._all_moments_on_support_node(index, node)
            solved.append((force, nodal_moment))
            if not held_rotations or ends is None:
                at_ends.append(None)
                continue
            end_force = np.zeros(3)
            end_moment = np.zeros(3)
            for sign, records in ends.values():
                rec = records.get(step["load_case"])
                if rec is None:
                    continue
                arm = np.array(rec["centre"]) - position
                end_force += sign * np.array(rec["force"])
                end_moment += sign * (
                    np.array(rec["moment"]) + np.cross(arm, np.array(rec["force"]))
                )
            # The support takes that, less a point force or a moment
            # applied at its own node, and only resists what it holds
            for node in nodes:
                end_force -= np.array(pushed.get(node, (0.0, 0.0, 0.0)))
                end_moment -= np.array(applied_moments.get(node, (0.0, 0.0, 0.0)))
            held_force = hold @ end_force
            at_ends.append((held_force, turn @ end_moment))
            apart = float(np.linalg.norm(force - held_force))
            size = max(np.linalg.norm(force), np.linalg.norm(held_force))
            if apart > max(BALANCE_NOISE_N, self._SOLVER_FORCE_TOLERANCE * size):
                mistaken = True

        from_solver = not mistaken and all(m is not None for _, m in solved)
        if not held_rotations:
            entry["moments"] = "none_restrained"
        elif from_solver:
            entry["moments"] = "solver"
        elif ends is not None:
            entry["moments"] = "member_end_forces"
        else:
            entry["moments"] = "not_computed"

        by_load_case: Dict[str, Dict[str, float]] = {}
        for index, step in enumerate(steps):
            force, nodal_moment = solved[index]
            moment = nodal_moment if entry["moments"] != "member_end_forces" else None
            ended = at_ends[index]
            if ended is not None:
                held_force, end_moment = ended
                if moment is None:
                    moment = end_moment
                apart = float(np.linalg.norm(force - held_force))
                size = max(np.linalg.norm(force), np.linalg.norm(held_force))
                if not self._reactions_balance(index) or apart > max(
                    BALANCE_NOISE_N, self._SOLVER_FORCE_TOLERANCE * size
                ):
                    # The solver's force here is wrong (see
                    # ``_reactions_balance``); the member ends' is not
                    force = held_force
                    entry["forces"] = "member_end_forces"
            values = {
                "fx_N": float(force[0]),
                "fy_N": float(force[1]),
                "fz_N": float(force[2]),
            }
            if entry["moments"] != "not_computed" and moment is not None:
                values.update(
                    mx_Nm=float(moment[0]),
                    my_Nm=float(moment[1]),
                    mz_Nm=float(moment[2]),
                )
            values["resultant_N"] = float(np.linalg.norm(force))
            by_load_case[step["load_case"]] = values
        entry["by_load_case"] = by_load_case
        if held_rotations and entry["forces"] == "solver" and not balanced:
            entry["forces"] = "unreliable"

        axes = getattr(connection, "local_axes", None)
        if axes is not None:
            rotation = np.array(axes, dtype=float)
            entry["axes"] = {
                name: [float(v) for v in row] for name, row in zip("xyz", rotation)
            }
            entry["restrained_in_axes"] = self._held_names(hold, turn, rotation)
            entry["by_load_case_in_axes"] = {
                case: self._in_axes(values, rotation)
                for case, values in by_load_case.items()
            }
        return entry

    @staticmethod
    def _projection(record: Dict, key: str, first_dof: int) -> np.ndarray:
        """The projection onto the directions a support holds.

        ``record[key]`` has them as rows; a record without it holds the
        global directions of its ``dofs``.
        """
        if key in record:
            rows = np.array(record[key], dtype=float).reshape(-1, 3)
        else:
            rows = np.eye(3)[
                [d - first_dof for d in record["dofs"] if 0 <= d - first_dof < 3]
            ]
        if rows.shape[0] == 0:
            return np.zeros((3, 3))
        _, singular, vh = np.linalg.svd(rows, full_matrices=False)
        basis = vh[singular > 1e-9]
        return basis.T @ basis

    @staticmethod
    def _held_names(hold: np.ndarray, turn: np.ndarray, axes: np.ndarray) -> List[str]:
        """Which of three axes a support holds outright, as tx .. rz."""
        return [
            kind + name
            for kind, projection in (("t", hold), ("r", turn))
            for name, axis in zip("xyz", axes)
            if float(axis @ projection @ axis) > 1.0 - 1e-6
        ]

    # The force at a support that holds a rotation is also known from the
    # ends of its members, to about 1 %. Further apart than this, the
    # solver's figure is taken to be wrong.
    _SOLVER_FORCE_TOLERANCE = 0.03

    def _reactions_balance(self, step_index: int) -> bool:
        """Whether the solver's reactions balance the loads of one step.

        They have to. CalculiX 2.21 and earlier misreport the force at a
        support that holds a member's rotation: the same input gives the same
        displacements as 2.23, and reactions that are wrong by anything up to
        the size of the load. The errors of two supports can cancel, so each
        such support is also checked against the ends of its members.
        """
        totals = [
            r
            for r in self.parsed_results.get("reaction", [])
            if getattr(r, "reference_element", None) == "TOTAL"
        ]
        loads = self._applied_load_totals
        if (
            not isinstance(loads, list)
            or step_index >= len(loads)
            or step_index >= len(totals)
        ):
            return True
        applied = self._loads_on_support_nodes(step_index).values()
        load = loads[step_index]
        reaction = [
            value - sum(node_load[axis] for node_load in applied)
            for axis, value in enumerate(totals[step_index].get_forces())
        ]
        imbalance = math.sqrt(sum((r + a) ** 2 for r, a in zip(reaction, load)))
        size = max(
            math.sqrt(sum(v * v for v in load)),
            math.sqrt(sum(v * v for v in reaction)),
        )
        return imbalance <= max(BALANCE_NOISE_N, BALANCE_LIMIT * size)

    def _loads_on_support_nodes(self, step_index: int) -> Dict[int, List[float]]:
        """Forces applied directly at support nodes in one step, by node."""
        recorded = self._support_node_loads
        if not isinstance(recorded, list) or step_index >= len(recorded):
            return {}
        return {node: list(load[:3]) for node, load in recorded[step_index].items()}

    def _moments_on_support_nodes(self, step_index: int) -> Dict[int, List[float]]:
        """Moments applied directly at support nodes in one step, by node."""
        recorded = self._support_node_loads
        if not isinstance(recorded, list) or step_index >= len(recorded):
            return {}
        return {
            node: list(load[3:6])
            for node, load in recorded[step_index].items()
            if len(load) >= 6
        }

    def _support_node_moments(
        self, step_index: int, nodes: Dict[int, tuple]
    ) -> Optional[Dict[int, np.ndarray]]:
        """The moment the solver's forces give at each of a support's nodes.

        About the node itself, from the forces on the nodes it was expanded
        into (``ResultsParser.parse_support_node_moments``). None unless
        every node has one.
        """
        steps = self.parsed_results.get("support_node_moments") or []
        if step_index >= len(steps):
            return None
        moments = steps[step_index]["moments"]
        if not nodes or any(node not in moments for node in nodes):
            return None
        return {node: np.array(moments[node], dtype=float) for node in nodes}

    def _all_moments_on_support_node(self, step_index: int, node: int) -> np.ndarray:
        """Every moment applied at a support node in one step.

        Point moments and the node's share of moments per length: the forces
        on the node's expanded nodes have neither where the support holds the
        rotation, and both where it does not.
        """
        recorded = self._support_node_loads
        if not isinstance(recorded, list) or step_index >= len(recorded):
            return np.zeros(3)
        load = list(recorded[step_index].get(node, ()))
        load += [0.0] * (9 - len(load))
        return np.array(load[3:6]) + np.array(load[6:9])

    def _point_forces_on_support_nodes(self, step_index: int) -> Dict[int, List[float]]:
        """Point forces applied directly at support nodes in one step.

        Without a node's share of the loads along its members: the section
        forces at the end of a member have those, and have nothing of a
        point load that the support takes.
        """
        recorded = self._support_node_loads
        if not isinstance(recorded, list) or step_index >= len(recorded):
            return {}
        return {
            node: list(load[9:12])
            for node, load in recorded[step_index].items()
            if len(load) >= 12
        }

    @staticmethod
    def _in_axes(values: Dict[str, float], rotation: np.ndarray) -> Dict[str, float]:
        """The components of a reaction along three given axes."""
        turned: Dict[str, float] = {}
        for keys in (("fx_N", "fy_N", "fz_N"), ("mx_Nm", "my_Nm", "mz_Nm")):
            if keys[0] not in values:
                continue
            vector = rotation @ np.array([values[key] for key in keys])
            turned.update({key: float(v) for key, v in zip(keys, vector)})
        return turned

    def _member_ends_at(self, connection, position: np.ndarray) -> Optional[Dict]:
        """The member ends a support holds, for its reaction moments.

        Returns ``{member_id: (sign, {load_case: record})}`` with the section
        force record of the end cross-section nearest the support and the sign
        that turns it into what the support exerts on the member: the record
        is what the part beyond the cross-section exerts on the part before,
        so +1 at a member's far end and -1 at its start.

        None when the moments cannot be had this way: the support connects no
        member, a member that is not a curve member, has no section forces
        or is tied to a surface member, or one that runs on past the support.
        """
        member_ids = list(getattr(connection, "connected_members", None) or [])
        if not member_ids:
            return None
        index = self._section_force_index()
        ends: Dict[str, tuple] = {}
        for member_id in member_ids:
            member = self.model.get_member(member_id)
            if member is None or getattr(member, "entity_type", None) != "curve":
                return None
            # Tied to a surface along its length, a member has its share of
            # the force only, and the surface brings the rest to the support
            if getattr(member, "tied_to_surface_members", None):
                return None
            by_case: Dict[str, List[Dict]] = defaultdict(list)
            for elem_id in getattr(member, "analysis_element_ids", []):
                for rec in index.get(elem_id, ()):
                    if "distance" in rec and "moment" in rec:
                        by_case[rec.get("load_case", "_combined")].append(rec)
            if not by_case:
                return None
            geometry = getattr(member, "geometry", None)
            try:
                start = np.array(geometry[0], dtype=float)
                along = np.array(geometry[-1], dtype=float) - start
                along = along / np.linalg.norm(along)
            except (TypeError, ValueError, IndexError):
                return None
            # Where the support is along the member; an end zone or an
            # eccentricity moves it sideways or beyond an end, never inside
            station = float(np.dot(position - start, along))
            sign = None
            chosen: Dict[str, Dict] = {}
            for case, records in by_case.items():
                first = min(records, key=lambda r: r["distance"])
                last = max(records, key=lambda r: r["distance"])
                if (
                    first["distance"] + self._END_TOLERANCE
                    < station
                    < last["distance"] - self._END_TOLERANCE
                ):
                    return None
                at_start = abs(station - first["distance"]) <= abs(
                    station - last["distance"]
                )
                sign = -1.0 if at_start else 1.0
                chosen[case] = first if at_start else last
            ends[member_id] = (sign, chosen)
        return ends

    # ------------------------------------------------------------------
    # Global reactions
    # ------------------------------------------------------------------

    def _global_reactions(
        self, supports: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """The whole reaction of each load case.

        Args:
            supports: What ``_supports()`` returned, when it has been called
                already.
        """
        reaction_results = self.parsed_results.get("reaction", [])
        if not reaction_results:
            return {}

        totals = [r for r in reaction_results if r.reference_element == "TOTAL"]
        if not totals:
            return {}
        if supports is None:
            supports = self._supports()

        def _entry(index: int, case: str) -> Dict[str, Any]:
            # The solver's total is of the forces inside the structure at
            # the support nodes: a load applied at one of them in a
            # restrained direction is missing from it, and has to be taken
            # off to get the reaction (see ``_StepLoadRecorder``)
            applied = self._loads_on_support_nodes(index).values()
            forces = [
                value - sum(load[axis] for load in applied)
                for axis, value in enumerate(totals[index].get_forces())
            ]
            # Where the solver's total does not balance the loads and the
            # supports it had wrong could all be replaced, the total is that
            # of the supports. One that balances is kept: the errors of two
            # supports can cancel, and it is then exact where theirs is not
            source = "solver"
            kinds = {support["forces"] for support in supports}
            if (
                "member_end_forces" in kinds
                and "unreliable" not in kinds
                and not self._reactions_balance(index)
            ):
                whole = self._force_of_supports(supports, case)
                if whole is not None and self._supports_balance(supports, index, case):
                    forces = [float(v) for v in whole]
                    source = "supports"
            entry: Dict[str, Any] = {
                "forces": source,
                "fx_N": forces[0],
                "fy_N": forces[1],
                "fz_N": forces[2],
            }
            moment = self._moment_about_origin(supports, case)
            if moment is not None:
                entry.update(
                    mx_Nm=float(moment[0]),
                    my_Nm=float(moment[1]),
                    mz_Nm=float(moment[2]),
                )
            entry["resultant_N"] = math.sqrt(sum(f * f for f in forces))
            loads = self._applied_load_totals
            if isinstance(loads, list) and index < len(loads):
                load = loads[index]
                entry["applied_load_N"] = [float(v) for v in load]
                entry["imbalance_N"] = math.sqrt(
                    sum((f + a) ** 2 for f, a in zip(forces, load))
                )
            turning = self._applied_load_moments
            if (
                moment is not None
                and isinstance(turning, list)
                and index < len(turning)
                and turning[index] is not None
            ):
                entry["applied_moment_Nm"] = [float(v) for v in turning[index]]
                entry["moment_imbalance_Nm"] = float(
                    np.linalg.norm(moment + np.array(turning[index], dtype=float))
                )
            return entry

        names = [
            r.metadata.get("load_case", f"step_{i + 1}") for i, r in enumerate(totals)
        ]
        by_load_case = {name: _entry(i, name) for i, name in enumerate(names)}
        reactions: Dict[str, Any] = {"by_load_case": by_load_case}
        # One load case: its total is the total. With several there is no
        # single figure, since each case is analysed on its own.
        if len(totals) == 1:
            reactions["total"] = _entry(0, names[0])
        return reactions

    @staticmethod
    def _moment_about_origin(
        supports: List[Dict[str, Any]], case: str
    ) -> Optional[np.ndarray]:
        """The moment of the reactions of one load case about the origin.

        Each support's moment, and that of its force at the support's
        position. None when a support has no moment, or there is no support
        to add up: the solver has no figure of its own for this.
        """
        if not supports:
            return None
        moment = np.zeros(3)
        for support in supports:
            values = support.get("by_load_case", {}).get(case)
            if values is None or "mx_Nm" not in values:
                return None
            force = [values["fx_N"], values["fy_N"], values["fz_N"]]
            moment += np.cross(np.array(support["position_m"], dtype=float), force)
            moment += [values["mx_Nm"], values["my_Nm"], values["mz_Nm"]]
        return moment
