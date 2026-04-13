"""Parser for CalculiX .dat output files.

Parses reaction forces, total forces, and completion/convergence status.
"""

from __future__ import annotations

import re
from typing import Any


def parse_dat(path: str) -> dict[str, Any]:
    """Parse a .dat file into structured data.

    Returns a dict with:
        reactions: list of {node, fx, fy, fz}
        totals: {fx, fy, fz} or None
        section_forces: list of {element_id, int_pt, N, T, Mf1, Mf2, Vf1, Vf2, step}
        status: "completed" | "no_convergence" | "divergence" | "unknown"
    """
    with open(path, "r") as f:
        content = f.read()

    return {
        "reactions": _parse_reactions(content),
        "totals": _parse_totals(content),
        "section_forces": _parse_section_forces(content),
        "status": _parse_status(content),
    }


def _parse_reactions(content: str) -> list[dict[str, Any]]:
    """Parse per-node reaction forces."""
    reactions: list[dict[str, Any]] = []
    lines = content.split("\n")
    in_forces = False

    for line in lines:
        stripped = line.strip()

        # Detect reaction force header: "forces (fx,fy,fz) for set ..."
        # but NOT "total force" lines
        if (
            "forces" in stripped.lower()
            and "total" not in stripped.lower()
            and "(fx,fy,fz)" in stripped.lower()
        ):
            in_forces = True
            continue

        if "total force" in stripped.lower():
            in_forces = False
            continue

        if in_forces and stripped:
            parts = stripped.split()
            try:
                if len(parts) >= 4:
                    node = int(parts[0])
                    fx, fy, fz = float(parts[1]), float(parts[2]), float(parts[3])
                    reactions.append({"node": node, "fx": fx, "fy": fy, "fz": fz})
            except (ValueError, IndexError):
                continue

    return reactions


def _parse_totals(content: str) -> dict[str, float] | None:
    """Parse total force line.

    CalculiX format:
        total force (fx,fy,fz) for set <NAME> and time  0.1000000E+01
        <blank line>
                5.000000E+03  1.000000E+03  5.000000E+02
    """
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if "total force" in line.lower():
            # Check if values are on the same line after the header text
            # Extract any floats from this line (skip Fortran-formatted time values in header)
            nums = _extract_floats(line)
            # The header itself contains a time value like 0.1000000E+01, so need 3+ extra
            if len(nums) >= 4:
                # Last 3 are the force values (first is the time)
                return {"fx": nums[-3], "fy": nums[-2], "fz": nums[-1]}

            # Look at next non-blank lines (values may be on next line or after blank)
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                if not candidate:
                    continue
                nums = _extract_floats(candidate)
                if len(nums) >= 3:
                    return {"fx": nums[0], "fy": nums[1], "fz": nums[2]}
                break  # Stop at first non-blank non-matching line

    return None


def _extract_floats(line: str) -> list[float]:
    """Extract all floating point numbers from a line."""
    pattern = re.compile(r"[+-]?\d+\.?\d*(?:[eE][+-]?\d+)?")
    return [float(m) for m in pattern.findall(line)]


def _parse_section_forces(content: str) -> list[dict[str, Any]]:
    """Parse beam section forces from a DAT file.

    CalculiX format::

        beam section forces and moments

         element no.  integ. pt. no.     N          T         Mf1        Mf2        Vf1        Vf2
              1           1       1.234E+03  0.000E+00  ...

    Returns list of dicts with keys: element_id, int_pt, N, T, Mf1, Mf2, Vf1, Vf2, step.
    """
    results: list[dict[str, Any]] = []
    lines = content.split("\n")
    step = 0
    in_block = False
    past_header = False

    for line in lines:
        stripped = line.strip()

        # Track steps
        if stripped.lower().startswith("s t e p") or stripped.lower().startswith("step"):
            parts = stripped.split()
            for p in parts:
                try:
                    step = int(p)
                    break
                except ValueError:
                    continue

        # Detect section force block
        if "beam section forces" in stripped.lower():
            in_block = True
            past_header = False
            continue

        if not in_block:
            continue

        # Skip the column header line
        if not past_header:
            if "element no" in stripped.lower() or "integ" in stripped.lower():
                past_header = True
            continue

        # Blank line or new section ends the block
        if not stripped:
            in_block = False
            past_header = False
            continue

        parts = stripped.split()
        try:
            elem_id = int(parts[0])
            int_pt = int(parts[1])
            floats = [float(p) for p in parts[2:]]
        except (ValueError, IndexError):
            in_block = False
            past_header = False
            continue

        results.append(
            {
                "element_id": elem_id,
                "int_pt": int_pt,
                "N": floats[0] if len(floats) > 0 else 0.0,
                "T": floats[1] if len(floats) > 1 else 0.0,
                "Mf1": floats[2] if len(floats) > 2 else 0.0,
                "Mf2": floats[3] if len(floats) > 3 else 0.0,
                "Vf1": floats[4] if len(floats) > 4 else 0.0,
                "Vf2": floats[5] if len(floats) > 5 else 0.0,
                "step": step,
            }
        )

    return results


def _parse_status(content: str) -> str:
    """Determine analysis completion status."""
    content_lower = content.lower()

    if "job finished" in content_lower:
        return "completed"
    if "best solution" in content_lower and "no convergence" in content_lower:
        return "no_convergence"
    if "diverge" in content_lower:
        return "divergence"
    if "*error" in content_lower or "error" in content_lower:
        return "error"

    # If we have force/displacement output but no explicit status,
    # the analysis likely completed (CalculiX only writes results on success)
    if "total force" in content_lower or "step" in content_lower:
        return "completed"

    return "unknown"
