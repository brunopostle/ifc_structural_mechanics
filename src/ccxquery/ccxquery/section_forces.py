"""Section forces command - beam section forces from .dat files."""

from __future__ import annotations

from typing import Any


def section_forces(
    dat_data: dict[str, Any],
    element_id: int | None = None,
    show_max: bool = False,
) -> dict[str, Any]:
    """Return beam section forces, optionally filtered to one element.

    Args:
        dat_data: Parsed .dat data from ``parse_dat()``.
        element_id: If given, only return records for this element.
        show_max: If True, return only the worst-case (max abs) per component.

    Returns:
        Dict with ``records`` list and optional ``max`` summary.
    """
    records: list[dict[str, Any]] = dat_data.get("section_forces", [])

    if element_id is not None:
        records = [r for r in records if r["element_id"] == element_id]

    if show_max and records:
        components = ["N", "T", "Mf1", "Mf2", "Vf1", "Vf2"]
        maxima = {c: max(abs(r[c]) for r in records) for c in components}
        return {"count": len(records), "max": maxima, "records": records}

    return {"count": len(records), "records": records}
