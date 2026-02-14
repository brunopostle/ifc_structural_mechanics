"""Boundary conditions command - extract BCs from .inp files."""

from __future__ import annotations

from typing import Any

from .parsers import inp_parser


def bcs(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return all boundary conditions."""
    return inp_parser.parse_boundary_conditions(sections)
