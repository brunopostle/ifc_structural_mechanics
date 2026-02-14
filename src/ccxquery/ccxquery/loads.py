"""Loads command - extract CLOADs and DLOADs from .inp files."""

from __future__ import annotations

from typing import Any

from .parsers import inp_parser


def loads(sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Return all concentrated and distributed loads."""
    cloads = inp_parser.parse_cloads(sections)
    dloads = inp_parser.parse_dloads(sections)
    return {
        "concentrated_loads": cloads,
        "distributed_loads": dloads,
    }
