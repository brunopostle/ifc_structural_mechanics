"""Warnings for results too large to be believed.

A model that is barely held, or held nowhere near where its author thinks,
still solves: CalculiX returns numbers, the status is "success", and the
displacements are metres or kilometres. These checks look at the exported
results and say so. They are not serviceability checks; the limits are set
far above what a working structure does.
"""

import math
import re
from typing import Any, Dict, List, Optional, Sequence

from ..utils.messages import guids_of, warning

# A member that distorts by more than this fraction of its own size.
MEMBER_LIMIT = 1.0 / 100.0
# A displacement larger than this fraction of the size of the whole model.
MODEL_LIMIT = 0.05
# Reactions that miss the applied load by more than this fraction of it.
BALANCE_LIMIT = 1.0e-3
# An imbalance smaller than this is rounding whatever the loads are: a load
# case of applied moments alone has no force to compare it with.
BALANCE_NOISE_N = 1.0e-3


def _points(geometry: Any) -> List[Sequence[float]]:
    """Corner points of a member's geometry, whatever form it is stored in."""
    if isinstance(geometry, dict):
        boundaries = geometry.get("boundaries") or []
        geometry = boundaries[0] if boundaries else []
    points = []
    for point in geometry or []:
        try:
            points.append([float(point[0]), float(point[1]), float(point[2])])
        except (TypeError, ValueError, IndexError):
            continue
    return points


def _extent(points: List[Sequence[float]]) -> Optional[float]:
    """Diagonal of the box around a set of points; None for fewer than two."""
    if len(points) < 2:
        return None
    return math.sqrt(
        sum(
            (max(p[i] for p in points) - min(p[i] for p in points)) ** 2
            for i in range(3)
        )
    )


def _length(value: float) -> str:
    """A length in the unit that reads best."""
    if value >= 1000.0:
        return f"{value / 1000.0:.3g} km"
    if value >= 1.0:
        return f"{value:.3g} m"
    return f"{value * 1000.0:.3g} mm"


def _has_the_rotation_fault(solver_version: Optional[str]) -> bool:
    """Whether a version of CalculiX can misreport reactions at clamped ends.

    2.21 does and 2.23 does not. A version that cannot be read may.
    """
    numbers = re.match(r"(\d+)\.(\d+)", solver_version or "")
    return not numbers or (int(numbers[1]), int(numbers[2])) < (2, 23)


def balance_warnings(
    results: Dict[str, Any],
    user_elements: bool = False,
    solver_version: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return one warning if the reactions are not to be trusted.

    Statics requires the reactions to balance the loads, so a difference
    means something is wrong. There is one known cause that leaves the
    displacements right: CalculiX 2.21 and earlier misreport the force at a
    support that holds a rotation. Measured: the same input gives the same
    displacements in 2.21 and 2.23, and reactions that are right only in 2.23.
    The errors of two supports can cancel, so the exporter also checks each
    such support against the ends of its members and marks the ones it had to
    replace. The warning names that cause only where the check found such a
    support on a version that has the fault, and otherwise says there is no
    explanation (``uda``: it once blamed 2.21 while running on 2.23, for
    forces that had gone missing through a hinge's equations).

    Args:
        results: The dict written to ``results.json``.
        user_elements: The model has U1 elements, whose reactions are worked
            out from their stiffness and not taken from the solver.
        solver_version: The version of CalculiX that ran, if known.

    Returns:
        A list with one warning, or an empty list.
    """
    unbalanced = []
    cases = results.get("global_reactions", {}).get("by_load_case", {})
    for case, reaction in cases.items():
        load = reaction.get("applied_load_N")
        imbalance = reaction.get("imbalance_N")
        if load is None or imbalance is None:
            continue
        size = math.sqrt(sum(v * v for v in load))
        if imbalance > max(
            BALANCE_NOISE_N,
            BALANCE_LIMIT * max(size, reaction.get("resultant_N", 0.0)),
        ):
            unbalanced.append((case, imbalance, size))
    supports = results.get("supports", [])
    replaced = sum(1 for s in supports if s.get("forces") == "member_end_forces")
    unreliable = sum(1 for s in supports if s.get("forces") == "unreliable")
    if not unbalanced and not replaced and not unreliable:
        return []
    explained = user_elements or (
        (replaced or unreliable) and _has_the_rotation_fault(solver_version)
    )
    message = (
        "The reactions the solver reported are wrong."
        if explained
        else "The reactions are not to be trusted."
    )
    if unbalanced:
        listed = ", ".join(
            f"{case} (off by {imbalance:.4g} N of {size:.4g} N)"
            for case, imbalance, size in unbalanced[:5]
        )
        more = f", and {len(unbalanced) - 5} more" if len(unbalanced) > 5 else ""
        message += (
            f" They do not balance the applied loads in {len(unbalanced)} load "
            f"case(s): {listed}{more}; do not rely on the total reactions."
        )
    if replaced:
        message += (
            f" At {replaced} support(s) that hold a rotation the forces are "
            "taken from the ends of the members instead, good to about 1 %."
        )
        if any(r.get("forces") == "supports" for r in cases.values()):
            message += (
                " Where the solver's total did not balance the applied "
                "loads, the total given is that of the supports."
            )
    if unreliable:
        message += (
            f" At {unreliable} support(s) that hold a rotation there is "
            "nothing to take them from, and the figures given are wrong."
        )
    if user_elements:
        message += (
            " The forces at the supports of U1 elements are worked out from "
            "the U1 stiffness of CalculiX 2.23, because the solver's are "
            "wrong; this version of CalculiX may have a different U1 element."
        )
    elif explained:
        message += (
            " CalculiX 2.21 and earlier misreport the force at a support that "
            "holds a rotation; 2.23 does not."
        )
    if explained:
        message += " Displacements and member forces are not affected."
    else:
        message += (
            " No known fault of the solver explains this, so the displacements "
            "and member forces may be wrong as well. Please report it with the "
            "input file."
        )
    concerned = [
        s["ifc_guid"]
        for s in supports
        if s.get("forces") in ("member_end_forces", "unreliable") and s.get("ifc_guid")
    ]
    return [warning("W-RES-001", message, ifc_guids=concerned)]


def _has_user_elements(domain_model) -> bool:
    """Whether the input writer recorded U1 elements in the model."""
    recorded = getattr(domain_model, "user_elements", None)
    return isinstance(recorded, dict) and bool(recorded)


def _mechanism_mode_warnings(results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A warning for the modes of a modal analysis that are mechanisms."""
    modes = (results.get("modal") or {}).get("modes") or []
    loose = [m["mode"] for m in modes if m.get("mechanism")]
    if not loose:
        return []
    return [
        warning(
            "W-CHK-003",
            f"{len(loose)} of the {len(modes)} modes found have no stiffness "
            f"(mode {', '.join(str(n) for n in loose[:5])}"
            + (" ..." if len(loose) > 5 else "")
            + "): the model can move that way without straining. Check the "
            "supports and the connections between members.",
        )
    ]


def plausibility_warnings(
    results: Dict[str, Any], domain_model, solver_version: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return a warning for each load case whose results are not believable.

    Two checks, per load case, and in a modal analysis one on the modes:

    * the largest displacement against the size of the model (``MODEL_LIMIT``):
      beyond it the model is probably a mechanism;
    * each member's distortion, the largest difference in displacement between
      its own points, against its own size (``MEMBER_LIMIT``): beyond it the
      member is probably not connected or supported as intended. The worst
      member is named and the others counted;
    * modes with no frequency to speak of, which are mechanisms.

    Args:
        results: The dict written to ``results.json``.
        domain_model: The analysed ``StructuralModel``, for member geometry.
        solver_version: The version of CalculiX that ran, if known.

    Returns:
        Warning dicts in the form used by ``result["warnings"]``.
    """
    sizes: Dict[str, float] = {}
    everything: List[Sequence[float]] = []
    for member in getattr(domain_model, "members", []):
        points = _points(getattr(member, "geometry", None))
        everything.extend(points)
        extent = _extent(points)
        if extent:
            sizes[member.id] = extent
    model_size = _extent(everything)

    warnings: List[Dict[str, Any]] = balance_warnings(
        results, _has_user_elements(domain_model), solver_version
    )
    warnings.extend(_mechanism_mode_warnings(results))
    members = results.get("members", [])
    by_case = results.get("global_displacements", {}).get("by_load_case", {})
    for case in results.get("load_cases", []) or list(by_case):
        largest = by_case.get(case, {}).get("max_displacement_m")
        if model_size and largest and largest > MODEL_LIMIT * model_size:
            where = max(
                members,
                key=lambda m: m.get("by_load_case", {})
                .get(case, {})
                .get("max_displacement_m", 0.0),
                default=None,
            )
            name = f", at member {where['id']}" if where else ""
            warnings.append(
                warning(
                    "W-CHK-002",
                    f"Load case {case}: the largest displacement is "
                    f"{_length(largest)}{name}, in a model {_length(model_size)} "
                    "across. The model is probably a mechanism: check the "
                    "supports and the connections between members.",
                    domain_id=where["id"] if where else None,
                    ifc_guids=guids_of(domain_model, [where["id"]]) if where else (),
                )
            )

        distorted = []
        for member in members:
            size = sizes.get(member.get("id"))
            relative = (
                member.get("by_load_case", {})
                .get(case, {})
                .get("max_relative_displacement_m")
            )
            if size and relative and relative > MEMBER_LIMIT * size:
                distorted.append((relative / size, relative, size, member["id"]))
        if distorted:
            distorted.sort(reverse=True)
            ratio, relative, size, member_id = distorted[0]
            fraction = f"1/{1 / ratio:.0f}" if ratio < 0.5 else "more than half of it"
            others = (
                f" {len(distorted) - 1} other member(s) exceed the same limit."
                if len(distorted) > 1
                else ""
            )
            warnings.append(
                warning(
                    "W-CHK-001",
                    f"Load case {case}: member {member_id} distorts by "
                    f"{_length(relative)} over its {_length(size)} ({fraction}), "
                    f"more than 1/{1 / MEMBER_LIMIT:.0f}. It is probably not "
                    f"connected or supported as intended.{others}",
                    domain_id=member_id,
                    ifc_guids=guids_of(domain_model, [d[3] for d in distorted]),
                )
            )
    return warnings
