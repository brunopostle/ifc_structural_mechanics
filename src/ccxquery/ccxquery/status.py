"""Status command - completion/convergence from .dat files."""

from __future__ import annotations

from typing import Any


def status(dat_data: dict[str, Any]) -> dict[str, Any]:
    """Return analysis completion status."""
    return {"status": dat_data["status"]}
