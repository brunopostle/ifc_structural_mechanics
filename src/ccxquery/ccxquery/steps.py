"""Steps command - extract analysis steps from .inp files."""

from __future__ import annotations

from typing import Any

from .parsers import inp_parser


def steps(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return all analysis steps with their content keywords."""
    return inp_parser.parse_steps(sections)
