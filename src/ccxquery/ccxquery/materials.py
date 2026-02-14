"""Materials command - extract material definitions from .inp files."""

from __future__ import annotations

from typing import Any

from .parsers import inp_parser


def materials(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return all material definitions."""
    return inp_parser.parse_materials(sections)
