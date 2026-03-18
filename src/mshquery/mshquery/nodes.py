"""Nodes command - list nodes with optional range filter."""

from __future__ import annotations

from typing import Any

import meshio


def list_nodes(mesh: meshio.Mesh, range_str: str | None = None) -> list[dict[str, Any]]:
    """List nodes, optionally filtered by ID range.

    Args:
        range_str: "N-M" range string (1-based, inclusive).
    """
    start = 1
    end = len(mesh.points)

    if range_str:
        parts = range_str.split("-")
        if len(parts) == 2:
            start = int(parts[0])
            end = int(parts[1])
        elif len(parts) == 1:
            start = end = int(parts[0])

    start = max(1, start)
    end = min(len(mesh.points), end)

    results: list[dict[str, Any]] = []
    for nid in range(start, end + 1):
        idx = nid - 1
        coords = mesh.points[idx]
        entry: dict[str, Any] = {
            "id": nid,
            "x": float(coords[0]),
            "y": float(coords[1]),
        }
        entry["z"] = float(coords[2]) if len(coords) > 2 else 0.0
        results.append(entry)

    return results
