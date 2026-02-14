"""Select command - filter nodes and elements by various criteria."""

from __future__ import annotations

from typing import Any

import meshio
import numpy as np


def nodes_at(
    mesh: meshio.Mesh,
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
    tol: float = 1e-6,
) -> list[dict[str, Any]]:
    """Find nodes near a given position."""
    results: list[dict[str, Any]] = []
    for idx in range(len(mesh.points)):
        coords = mesh.points[idx]
        px, py = float(coords[0]), float(coords[1])
        pz = float(coords[2]) if len(coords) > 2 else 0.0

        match = True
        if x is not None and abs(px - x) > tol:
            match = False
        if y is not None and abs(py - y) > tol:
            match = False
        if z is not None and abs(pz - z) > tol:
            match = False

        if match:
            results.append({"id": idx + 1, "x": px, "y": py, "z": pz})

    return results


def elements_with_node(mesh: meshio.Mesh, node_id: int) -> list[dict[str, Any]]:
    """Find elements containing a given node (1-based)."""
    node_idx = node_id - 1  # Convert to 0-based for meshio
    results: list[dict[str, Any]] = []
    eid = 1  # 1-based element counter

    for block in mesh.cells:
        for local_idx in range(len(block.data)):
            if node_idx in block.data[local_idx]:
                connectivity = [int(n) + 1 for n in block.data[local_idx]]
                results.append({
                    "id": eid + local_idx,
                    "type": block.type,
                    "connectivity": connectivity,
                })
        eid += len(block.data)

    return results


def elements_by_type(mesh: meshio.Mesh, cell_type: str) -> list[dict[str, Any]]:
    """Find all elements of a given type."""
    results: list[dict[str, Any]] = []
    eid = 1

    for block in mesh.cells:
        if block.type == cell_type:
            for local_idx in range(len(block.data)):
                connectivity = [int(n) + 1 for n in block.data[local_idx]]
                results.append({
                    "id": eid + local_idx,
                    "type": block.type,
                    "connectivity": connectivity,
                })
        eid += len(block.data)

    return results
