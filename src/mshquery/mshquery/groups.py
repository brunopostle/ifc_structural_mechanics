"""Groups command - list physical groups with entity counts."""

from __future__ import annotations

from typing import Any

import meshio


def groups(mesh: meshio.Mesh) -> list[dict[str, Any]]:
    """List all physical groups with their entity counts."""
    results: list[dict[str, Any]] = []

    if mesh.field_data:
        for name, (tag, dim) in sorted(mesh.field_data.items()):
            count = _count_group_entities(mesh, name)
            results.append({
                "name": name,
                "tag": int(tag),
                "dimension": int(dim),
                "count": count,
            })

    return results


def _count_group_entities(mesh: meshio.Mesh, group_name: str) -> int:
    """Count entities in a physical group."""
    if not mesh.cell_sets or group_name not in mesh.cell_sets:
        return 0

    count = 0
    for arr in mesh.cell_sets[group_name]:
        if hasattr(arr, '__len__'):
            count += int(sum(1 for x in arr if x))
    return count
