"""Stresses command - stress results from .frd files."""

from __future__ import annotations

import math
from typing import Any

from .parsers import frd_parser


def stresses(
    frd_data: dict[str, Any],
    node_id: int | None = None,
    show_max: bool = False,
    show_min: bool = False,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Query stress results."""
    data = frd_parser.get_stresses(frd_data)
    if data is None:
        return {"error": "No stress results found in file"}

    for name in ("STRESS", "STRESSES"):
        if name in frd_data["results"]:
            components = frd_data["results"][name].get(
                "components", ["SXX", "SYY", "SZZ", "SXY", "SYZ", "SZX"]
            )
            break
    else:
        components = ["SXX", "SYY", "SZZ", "SXY", "SYZ", "SZX"]

    if node_id is not None:
        if node_id not in data:
            return {"error": f"Node {node_id} not found in stress results"}
        values = data[node_id]
        von_mises = _von_mises(values) if len(values) >= 6 else None
        return _format_stress_entry(node_id, values, components, von_mises)

    if show_max or show_min:
        best_nid = None
        best_vm = -1.0 if show_max else float("inf")
        for nid, values in data.items():
            vm = _von_mises(values) if len(values) >= 6 else 0.0
            if show_max and vm > best_vm:
                best_vm = vm
                best_nid = nid
            elif show_min and vm < best_vm:
                best_vm = vm
                best_nid = nid
        if best_nid is not None:
            values = data[best_nid]
            vm = _von_mises(values) if len(values) >= 6 else None
            return _format_stress_entry(best_nid, values, components, vm)
        return {"error": "No stress data"}

    results: list[dict[str, Any]] = []
    for nid in sorted(data.keys()):
        values = data[nid]
        vm = _von_mises(values) if len(values) >= 6 else None
        results.append(_format_stress_entry(nid, values, components, vm))
    return results


def _format_stress_entry(
    nid: int, values: list[float], components: list[str], von_mises: float | None
) -> dict[str, Any]:
    entry: dict[str, Any] = {"node": nid}
    for i, comp in enumerate(components):
        if i < len(values):
            entry[comp] = values[i]
    if von_mises is not None:
        entry["von_mises"] = von_mises
    return entry


def _von_mises(values: list[float]) -> float:
    """Calculate von Mises stress from 6 components [sxx, syy, szz, sxy, syz, szx]."""
    if len(values) < 6:
        return 0.0
    sxx, syy, szz, sxy, syz, szx = values[:6]
    vm = math.sqrt(
        0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
        + 3.0 * (sxy**2 + syz**2 + szx**2)
    )
    return vm
