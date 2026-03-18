"""Node command - query node coordinates from .inp or .frd files."""

from __future__ import annotations

from typing import Any

from .parsers import inp_parser


def node_info(
    node_id: int, nodes: dict[int, tuple[float, float, float]]
) -> dict[str, Any]:
    """Return coordinates for a specific node."""
    if node_id not in nodes:
        return {"error": f"Node {node_id} not found"}
    x, y, z = nodes[node_id]
    return {"id": node_id, "x": x, "y": y, "z": z}


def nodes_at(
    nodes: dict[int, tuple[float, float, float]],
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
    tol: float = 1e-6,
) -> list[dict[str, Any]]:
    """Find nodes near a given position."""
    results: list[dict[str, Any]] = []
    for nid, (nx, ny, nz) in sorted(nodes.items()):
        match = True
        if x is not None and abs(nx - x) > tol:
            match = False
        if y is not None and abs(ny - y) > tol:
            match = False
        if z is not None and abs(nz - z) > tol:
            match = False
        if match:
            results.append({"id": nid, "x": nx, "y": ny, "z": nz})
    return results


def get_nodes_from_inp(
    sections: list[dict[str, Any]],
) -> dict[int, tuple[float, float, float]]:
    """Extract nodes from parsed .inp sections."""
    return inp_parser.parse_nodes(sections)


def get_nodes_from_frd(
    frd_data: dict[str, Any],
) -> dict[int, tuple[float, float, float]]:
    """Extract nodes from parsed .frd data."""
    return frd_data["nodes"]
