"""Sets command - list/show node and element sets from .inp files."""

from __future__ import annotations

from typing import Any

from .parsers import inp_parser


def list_sets(
    sections: list[dict[str, Any]], set_type: str | None = None
) -> list[dict[str, Any]]:
    """List all node/element sets with their sizes.

    Args:
        set_type: "node", "element", or None for both.
    """
    result: list[dict[str, Any]] = []

    if set_type is None or set_type == "node":
        nsets = inp_parser.parse_node_sets(sections)
        for name, ids in sorted(nsets.items()):
            result.append({"name": name, "type": "node", "count": len(ids)})

    if set_type is None or set_type == "element":
        elsets = inp_parser.parse_element_sets(sections)
        for name, ids in sorted(elsets.items()):
            result.append({"name": name, "type": "element", "count": len(ids)})

    return result


def show_set(sections: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """Show contents of a specific set."""
    nsets = inp_parser.parse_node_sets(sections)
    if name in nsets:
        return {
            "name": name,
            "type": "node",
            "count": len(nsets[name]),
            "ids": nsets[name],
        }

    elsets = inp_parser.parse_element_sets(sections)
    if name in elsets:
        return {
            "name": name,
            "type": "element",
            "count": len(elsets[name]),
            "ids": elsets[name],
        }

    return {"error": f"Set '{name}' not found"}
