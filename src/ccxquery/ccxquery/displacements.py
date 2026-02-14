"""Displacements command - displacement results from .frd files."""

from __future__ import annotations

import math
from typing import Any

from .parsers import frd_parser


def displacements(
    frd_data: dict[str, Any],
    node_id: int | None = None,
    show_max: bool = False,
    show_min: bool = False,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Query displacement results.

    Args:
        node_id: Return displacements for a specific node.
        show_max: Return the node with maximum displacement magnitude.
        show_min: Return the node with minimum displacement magnitude.
    """
    data = frd_parser.get_displacements(frd_data)
    if data is None:
        return {"error": "No displacement results found in file"}

    # Get components from the result block
    for name in ("DISP", "DISPLACEMENT", "DISPLACEMENTS"):
        if name in frd_data["results"]:
            components = frd_data["results"][name].get("components", ["D1", "D2", "D3"])
            break
    else:
        components = ["D1", "D2", "D3"]

    if node_id is not None:
        if node_id not in data:
            return {"error": f"Node {node_id} not found in displacement results"}
        values = data[node_id]
        magnitude = math.sqrt(sum(v * v for v in values[:3])) if len(values) >= 3 else 0.0
        return _format_disp_entry(node_id, values, components, magnitude)

    if show_max or show_min:
        best_nid = None
        best_mag = -1.0 if show_max else float("inf")
        for nid, values in data.items():
            mag = math.sqrt(sum(v * v for v in values[:3])) if len(values) >= 3 else 0.0
            if show_max and mag > best_mag:
                best_mag = mag
                best_nid = nid
            elif show_min and mag < best_mag:
                best_mag = mag
                best_nid = nid
        if best_nid is not None:
            values = data[best_nid]
            return _format_disp_entry(best_nid, values, components, best_mag)
        return {"error": "No displacement data"}

    # Return all displacements
    results: list[dict[str, Any]] = []
    for nid in sorted(data.keys()):
        values = data[nid]
        mag = math.sqrt(sum(v * v for v in values[:3])) if len(values) >= 3 else 0.0
        results.append(_format_disp_entry(nid, values, components, mag))
    return results


def _format_disp_entry(
    nid: int, values: list[float], components: list[str], magnitude: float
) -> dict[str, Any]:
    """Format a single displacement entry."""
    entry: dict[str, Any] = {"node": nid}
    for i, comp in enumerate(components):
        if i < len(values):
            entry[comp] = values[i]
    entry["magnitude"] = magnitude
    return entry
