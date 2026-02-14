"""Sections command - extract section definitions from .inp files."""

from __future__ import annotations

from typing import Any

from .parsers import inp_parser


def sections(sections_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return all section definitions (beam, shell)."""
    return inp_parser.parse_sections(sections_data)
