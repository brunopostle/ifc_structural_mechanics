"""Summary command for .msh files."""

from __future__ import annotations

from typing import Any

import meshio


def summary(mesh: meshio.Mesh) -> dict[str, Any]:
    """Return an overview of the mesh file."""
    points = mesh.points
    node_count = len(points)

    # Element counts by type
    type_counts: dict[str, int] = {}
    total_elements = 0
    for block in mesh.cells:
        cell_type = block.type
        count = len(block.data)
        type_counts[cell_type] = type_counts.get(cell_type, 0) + count
        total_elements += count

    # Bounding box
    if node_count > 0:
        bbox = {
            "min": {
                "x": float(points[:, 0].min()),
                "y": float(points[:, 1].min()),
                "z": float(points[:, 2].min()) if points.shape[1] > 2 else 0.0,
            },
            "max": {
                "x": float(points[:, 0].max()),
                "y": float(points[:, 1].max()),
                "z": float(points[:, 2].max()) if points.shape[1] > 2 else 0.0,
            },
        }
    else:
        bbox = None

    # Physical groups
    groups: list[dict[str, Any]] = []
    if mesh.field_data:
        for name, (tag, dim) in mesh.field_data.items():
            groups.append({"name": name, "tag": int(tag), "dimension": int(dim)})

    result: dict[str, Any] = {
        "nodes": node_count,
        "elements": total_elements,
        "element_types": type_counts,
        "bounding_box": bbox,
    }
    if groups:
        result["physical_groups"] = groups

    return result
