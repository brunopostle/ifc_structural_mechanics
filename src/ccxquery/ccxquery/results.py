"""Results command - list available result blocks from .frd files."""

from __future__ import annotations

from typing import Any


def results(frd_data: dict[str, Any]) -> list[dict[str, Any]]:
    """List available result blocks with their components."""
    blocks: list[dict[str, Any]] = []
    for name, block in frd_data["results"].items():
        blocks.append(
            {
                "name": name,
                "components": block["components"],
                "node_count": len(block["data"]),
            }
        )
    return blocks
