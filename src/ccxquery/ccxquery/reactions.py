"""Reactions command - reaction forces from .dat files."""

from __future__ import annotations

from typing import Any


def reactions(dat_data: dict[str, Any]) -> dict[str, Any]:
    """Return reaction forces (per-node and totals)."""
    return {
        "reactions": dat_data["reactions"],
        "totals": dat_data["totals"],
    }
