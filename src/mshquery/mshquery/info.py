"""Info command - inspect individual nodes and elements."""

from __future__ import annotations

from typing import Any

import meshio


def node_info(mesh: meshio.Mesh, node_id: int) -> dict[str, Any]:
    """Return coordinates for a node (1-based ID)."""
    idx = node_id - 1  # Convert to 0-based
    if idx < 0 or idx >= len(mesh.points):
        return {"error": f"Node {node_id} not found (valid range: 1-{len(mesh.points)})"}
    coords = mesh.points[idx]
    result: dict[str, Any] = {"id": node_id, "x": float(coords[0]), "y": float(coords[1])}
    if len(coords) > 2:
        result["z"] = float(coords[2])
    else:
        result["z"] = 0.0
    return result


def element_info(mesh: meshio.Mesh, element_id: int) -> dict[str, Any]:
    """Return info for an element (1-based ID, sequential across cell blocks)."""
    eid = element_id - 1  # Convert to 0-based
    offset = 0
    for block in mesh.cells:
        count = len(block.data)
        if eid < offset + count:
            local_idx = eid - offset
            connectivity = [int(n) + 1 for n in block.data[local_idx]]  # 1-based
            result: dict[str, Any] = {
                "id": element_id,
                "type": block.type,
                "connectivity": connectivity,
            }
            # Check group membership
            groups = _find_element_groups(mesh, block.type, local_idx)
            if groups:
                result["groups"] = groups
            return result
        offset += count

    return {"error": f"Element {element_id} not found (valid range: 1-{offset})"}


def _find_element_groups(mesh: meshio.Mesh, cell_type: str, local_idx: int) -> list[str]:
    """Find which physical groups contain this element."""
    groups: list[str] = []
    if not mesh.cell_sets:
        return groups

    # cell_sets maps group_name -> list of arrays (one per cell block)
    for group_name, block_arrays in mesh.cell_sets.items():
        for i, block in enumerate(mesh.cells):
            if block.type == cell_type and i < len(block_arrays):
                arr = block_arrays[i]
                if hasattr(arr, '__len__') and local_idx < len(arr) and arr[local_idx]:
                    groups.append(group_name)
                    break

    return groups
