"""Results of a load combination, from those of its load cases.

In a linear analysis the response to a sum of loads is the sum of the
responses. So a combination needs no solver step of its own: displacements,
stress components, section forces and nodal forces of each load case are
multiplied by the case's factor and added. That holds for these, which are
linear in the load, and for nothing derived from them: a displacement
magnitude, a von Mises stress, the largest value along a member and the
envelope of a member are all worked out again from the sums, by the same code
that works them out for a load case.

``combine_results()`` returns results in the form ``ResultsParser`` gives
them, holding one step named after the combination, so that
``ResultsExporter`` can be run on them unchanged.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..domain.result import DisplacementResult, ReactionForceResult, StressResult
from ..utils.error_handling import ResultProcessingError

STRESS_COMPONENTS = ("sxx", "syy", "szz", "sxy", "syz", "sxz")
_SECTION_FORCES = ("N", "Vf1", "Vf2", "T", "Mf1", "Mf2")
_SECTION_VECTORS = ("force", "moment")


def combine_results(
    parsed_results: Dict[str, Any],
    factors: Dict[str, float],
    name: str,
    support_node_loads: Optional[List[Dict[int, List[float]]]] = None,
    applied_load_totals: Optional[List[List[float]]] = None,
    applied_load_moments: Optional[List[Optional[List[float]]]] = None,
) -> Tuple[
    Dict[str, Any],
    List[Dict[int, List[float]]],
    List[List[float]],
    List[List[float]],
]:
    """Add up the results of load cases, each multiplied by its factor.

    Args:
        parsed_results: What ``ResultsParser.parse_results()`` returned.
        factors: ``{load case name: factor}``. Every name must be a load
            case with results.
        name: The name the combination's results are given.
        support_node_loads: The loads each step puts on support nodes
            (``StructuralModel.support_node_loads``).
        applied_load_totals: The whole load of each step
            (``StructuralModel.applied_load_totals``).
        applied_load_moments: The moment of each step's load about the
            origin (``StructuralModel.applied_load_moments``).

    Returns:
        The combined results, and the three per-step lists with the single
        step of the combination in them (empty when they were not given, or
        a load case has no value).

    Raises:
        ResultProcessingError: If a load case has no results, or the results
            of two cases are not on the same nodes and cross-sections.
    """
    combined: Dict[str, Any] = {
        "displacement": _combine_displacements(parsed_results, factors, name),
        "stress": _combine_stresses(parsed_results, factors, name),
        "strain": [],
        "buckling": [],
        "section_forces": _combine_section_forces(parsed_results, factors, name),
        "reaction": [],
        "support_node_forces": [],
        "support_node_moments": [],
        "spring_node_displacements": [],
    }

    totals = [
        r
        for r in parsed_results.get("reaction", [])
        if getattr(r, "reference_element", None) == "TOTAL"
    ]
    by_case = {r.metadata.get("load_case"): r for r in totals}
    if totals:
        force = np.zeros(3)
        moment = np.zeros(3)
        for case, factor in factors.items():
            if case not in by_case:
                raise ResultProcessingError(
                    f"Load combination {name}: load case {case} has no reactions.",
                    code="E-RES-003",
                )
            force += factor * np.array(by_case[case].get_forces())
            moment += factor * np.array(by_case[case].get_moments())
        total = ReactionForceResult(reference_element="TOTAL", load_case=name)
        total.set_forces([float(v) for v in force])
        total.set_moments([float(v) for v in moment])
        combined["reaction"] = [total]

    steps = parsed_results.get("support_node_forces") or []
    step_of = {step["load_case"]: index for index, step in enumerate(steps)}
    if steps:
        forces: Dict[int, np.ndarray] = {}
        for case, factor in factors.items():
            if case not in step_of:
                raise ResultProcessingError(
                    f"Load combination {name}: load case {case} has no "
                    "forces at the supports.",
                    code="E-RES-003",
                )
            for node, nodal in steps[step_of[case]]["forces"].items():
                forces[node] = forces.get(node, 0.0) + factor * np.array(nodal)
        combined["support_node_forces"] = [
            {
                "load_case": name,
                "forces": {n: [float(v) for v in f] for n, f in forces.items()},
            }
        ]

    springs = parsed_results.get("spring_node_displacements") or []
    spring_step_of = {step["load_case"]: index for index, step in enumerate(springs)}
    if springs:
        moved: Dict[int, np.ndarray] = {}
        for case, factor in factors.items():
            if case not in spring_step_of:
                raise ResultProcessingError(
                    f"Load combination {name}: load case {case} has no "
                    "displacements of the springs of elastic supports.",
                    code="E-RES-003",
                )
            for node, values in springs[spring_step_of[case]]["displacements"].items():
                moved[node] = moved.get(node, 0.0) + factor * np.array(values)
        combined["spring_node_displacements"] = [
            {
                "load_case": name,
                "displacements": {n: [float(v) for v in u] for n, u in moved.items()},
            }
        ]

    # A node that lacks a moment in one case has none in the combination
    moment_steps = {
        step["load_case"]: step["moments"]
        for step in parsed_results.get("support_node_moments") or []
    }
    if factors and all(case in moment_steps for case in factors):
        shared = set.intersection(*(set(moment_steps[case]) for case in factors))
        combined["support_node_moments"] = [
            {
                "load_case": name,
                "moments": {
                    node: [
                        float(v)
                        for v in sum(
                            factor * np.array(moment_steps[case][node])
                            for case, factor in factors.items()
                        )
                    ]
                    for node in shared
                },
            }
        ]

    node_loads: List[Dict[int, List[float]]] = []
    if support_node_loads and step_of:
        summed: Dict[int, np.ndarray] = {}
        for case, factor in factors.items():
            index = step_of[case]
            if index >= len(support_node_loads):
                continue
            for node, load in support_node_loads[index].items():
                summed[node] = summed.get(node, 0.0) + factor * np.array(load)
        node_loads = [{n: [float(v) for v in f] for n, f in summed.items()}]

    load_totals = _combine_step_vectors(applied_load_totals, factors, step_of)
    load_moments = _combine_step_vectors(applied_load_moments, factors, step_of)

    return combined, node_loads, load_totals, load_moments


def _combine_step_vectors(
    per_step: Optional[List[Any]], factors: Dict[str, float], step_of: Dict[str, int]
) -> List[List[float]]:
    """One vector per step, added up; nothing if a case has none."""
    if not per_step or not step_of:
        return []
    whole = np.zeros(3)
    for case, factor in factors.items():
        index = step_of[case]
        if index >= len(per_step) or per_step[index] is None:
            return []
        whole += factor * np.array(per_step[index])
    return [[float(v) for v in whole]]


def _by_case(results: List[Any], factors: Dict[str, float]) -> Dict[str, List[Any]]:
    grouped: Dict[str, List[Any]] = {case: [] for case in factors}
    for result in results:
        case = result.metadata.get("load_case")
        if case in grouped:
            grouped[case].append(result)
    return grouped


def _check_same_points(name: str, kind: str, counts: Dict[str, int], size: int) -> None:
    """Every case has to contribute at every point, or the sum is not one."""
    short = [case for case, count in counts.items() if count != size]
    if short:
        raise ResultProcessingError(
            f"Load combination {name}: the {kind} results of load case "
            f"{short[0]} are not at the same points as those of the other "
            "cases, so they cannot be added.",
            code="E-RES-003",
        )


def _combine_displacements(
    parsed_results: Dict[str, Any], factors: Dict[str, float], name: str
) -> List[DisplacementResult]:
    grouped = _by_case(parsed_results.get("displacement", []), factors)
    # Plain lists: this runs for every node of the model and every case
    sums: Dict[Any, List[float]] = {}
    for case, results in grouped.items():
        if not results:
            raise ResultProcessingError(
                f"Load combination {name}: load case {case} has no displacements.",
                code="E-RES-003",
            )
        factor = factors[case]
        for result in results:
            values = result.values
            total = sums.get(result.reference_element)
            if total is None:
                total = sums[result.reference_element] = [0.0, 0.0, 0.0]
            total[0] += factor * values.get("tx", 0.0)
            total[1] += factor * values.get("ty", 0.0)
            total[2] += factor * values.get("tz", 0.0)
    _check_same_points(
        name, "displacement", {c: len(r) for c, r in grouped.items()}, len(sums)
    )
    combined = []
    for node, translation in sums.items():
        result = DisplacementResult(reference_element=node, load_case=name)
        result.set_translations(translation)
        combined.append(result)
    return combined


def _combine_stresses(
    parsed_results: Dict[str, Any], factors: Dict[str, float], name: str
) -> List[StressResult]:
    grouped = _by_case(parsed_results.get("stress", []), factors)
    if not any(grouped.values()):
        return []
    sums: Dict[Any, List[float]] = {}
    for case, results in grouped.items():
        factor = factors[case]
        for result in results:
            values = result.values
            total = sums.get(result.reference_element)
            if total is None:
                total = sums[result.reference_element] = [0.0] * 6
            try:
                for i, key in enumerate(STRESS_COMPONENTS):
                    total[i] += factor * values[key]
            except KeyError as e:
                raise ResultProcessingError(
                    f"Load combination {name}: a stress of load case {case} "
                    f"has no component {e}; only components can be added.",
                    code="E-RES-003",
                ) from e
    _check_same_points(
        name, "stress", {c: len(r) for c, r in grouped.items()}, len(sums)
    )
    combined = []
    for node, components in sums.items():
        result = StressResult(reference_element=node, load_case=name)
        result.values.update(zip(STRESS_COMPONENTS, components))
        combined.append(result)
    return combined


def _combine_section_forces(
    parsed_results: Dict[str, Any], factors: Dict[str, float], name: str
) -> List[Dict]:
    sums: Dict[tuple, Dict] = {}
    counts = {case: 0 for case in factors}
    for record in parsed_results.get("section_forces", []):
        if not isinstance(record, dict) or record.get("load_case") not in factors:
            continue
        case = record["load_case"]
        factor = factors[case]
        counts[case] += 1
        key = (record.get("element_id"), record.get("position"))
        total = sums.get(key)
        if total is None:
            total = {
                k: v
                for k, v in record.items()
                if k not in _SECTION_FORCES and k not in _SECTION_VECTORS
            }
            total["load_case"] = name
            total.update({k: 0.0 for k in _SECTION_FORCES if k in record})
            total.update({k: np.zeros(3) for k in _SECTION_VECTORS if k in record})
            sums[key] = total
        for k in _SECTION_FORCES:
            if k in record:
                total[k] += factor * record[k]
        for k in _SECTION_VECTORS:
            if k in record:
                total[k] = total[k] + factor * np.array(record[k], dtype=float)
    if sums:
        _check_same_points(name, "section force", counts, len(sums))
    return list(sums.values())
