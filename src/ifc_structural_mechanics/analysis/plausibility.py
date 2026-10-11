"""Warnings for results too large to be believed.

A model that is barely held, or held nowhere near where its author thinks,
still solves: CalculiX returns numbers, the status is "success", and the
displacements are metres or kilometres. These checks look at the exported
results and say so. They are not serviceability checks; the limits are set
far above what a working structure does.
"""

import math
from typing import Any, Dict, List, Optional, Sequence

# A member that distorts by more than this fraction of its own size.
MEMBER_LIMIT = 1.0 / 100.0
# A displacement larger than this fraction of the size of the whole model.
MODEL_LIMIT = 0.05


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


def _warning(message: str, domain_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "message": message,
        "severity": "warning",
        "entity_type": None,
        "ccx_id": None,
        "domain_id": domain_id,
    }


def _length(value: float) -> str:
    """A length in the unit that reads best."""
    if value >= 1000.0:
        return f"{value / 1000.0:.3g} km"
    if value >= 1.0:
        return f"{value:.3g} m"
    return f"{value * 1000.0:.3g} mm"


def plausibility_warnings(
    results: Dict[str, Any], domain_model
) -> List[Dict[str, Any]]:
    """Return a warning for each load case whose results are not believable.

    Two checks, per load case:

    * the largest displacement against the size of the model (``MODEL_LIMIT``):
      beyond it the model is probably a mechanism;
    * each member's distortion, the largest difference in displacement between
      its own points, against its own size (``MEMBER_LIMIT``): beyond it the
      member is probably not connected or supported as intended. The worst
      member is named and the others counted.

    Args:
        results: The dict written to ``results.json``.
        domain_model: The analysed ``StructuralModel``, for member geometry.

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

    warnings: List[Dict[str, Any]] = []
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
                _warning(
                    f"Load case {case}: the largest displacement is "
                    f"{_length(largest)}{name}, in a model {_length(model_size)} "
                    "across. The model is probably a mechanism: check the "
                    "supports and the connections between members.",
                    where["id"] if where else None,
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
                _warning(
                    f"Load case {case}: member {member_id} distorts by "
                    f"{_length(relative)} over its {_length(size)} ({fraction}), "
                    f"more than 1/{1 / MEMBER_LIMIT:.0f}. It is probably not "
                    f"connected or supported as intended.{others}",
                    member_id,
                )
            )
    return warnings
