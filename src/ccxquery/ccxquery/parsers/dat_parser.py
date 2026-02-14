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
        status: "completed" | "no_convergence" | "divergence" | "unknown"
    """
    with open(path, "r") as f:
        content = f.read()

    return {
        "reactions": _parse_reactions(content),
        "totals": _parse_totals(content),
        "status": _parse_status(content),
    }


def _parse_reactions(content: str) -> list[dict[str, Any]]:
    """Parse per-node reaction forces."""
    reactions: list[dict[str, Any]] = []
    lines = content.split("\n")
    in_forces = False

    for line in lines:
        stripped = line.strip()

        # Detect reaction force header
        if "forces" in stripped.lower() and "node" in stripped.lower():
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
