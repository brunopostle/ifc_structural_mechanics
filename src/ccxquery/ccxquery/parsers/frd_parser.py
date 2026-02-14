"""Parser for CalculiX .frd result files.

FRD is a fixed-format ASCII file with node coordinates and result blocks.
Node block starts with ``2C`` header, result blocks start with ``-4 NAME``.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

# Proven regex for concatenated scientific notation values in FRD files.
# Handles values that run together without spaces.
VALUE_RE = re.compile(r"[+-]?(?:\d+\.\d+(?:[EeDd][+-]?\d+)?|\d+[EeDd][+-]?\d+)")


def parse_frd(path: str) -> dict[str, Any]:
    """Parse an .frd file into structured data.

    Returns a dict with:
        nodes: dict[int, tuple[float, float, float]]
        results: dict[str, dict]  (block_name -> {components, data})
    """
    with open(path, "r") as f:
        lines = f.readlines()

    nodes = _parse_node_block(lines)
    results = _parse_result_blocks(lines)

    return {"nodes": nodes, "results": results}


def _parse_node_block(lines: list[str]) -> dict[int, tuple[float, float, float]]:
    """Parse the node coordinate block (between 2C header and -3 marker)."""
    nodes: dict[int, tuple[float, float, float]] = {}
    in_block = False

    for line in lines:
        if line.strip().startswith("2C"):
            in_block = True
            continue
        if in_block:
            if line.strip().startswith("-3"):
                break
            if line.strip().startswith("-1"):
                node_id, coords = _parse_node_line(line)
                if node_id is not None:
                    nodes[node_id] = coords

    return nodes


def _parse_node_line(line: str) -> tuple[int | None, tuple[float, float, float]]:
    """Parse a single node line from the node block.

    Format: ``-1 <node_id> <x><y><z>``
    Values may run together in scientific notation.
    """
    try:
        # Node ID is in fixed columns after -1
        # Typical format: "-1         1  0.00000E+00  0.00000E+00  0.00000E+00"
        # But sometimes values run together
        stripped = line.strip()
        if not stripped.startswith("-1"):
            return None, (0.0, 0.0, 0.0)

        # Remove the -1 prefix
        rest = stripped[2:].strip()

        # Try fixed-width first: node_id is first token, then 3 values
        parts = rest.split()
        if len(parts) >= 4:
            nid = int(parts[0])
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            return nid, (x, y, z)

        # Fall back to regex for concatenated values
        # Node ID is the first integer
        nid_match = re.match(r"\s*(\d+)", rest)
        if not nid_match:
            return None, (0.0, 0.0, 0.0)
        nid = int(nid_match.group(1))
        coord_str = rest[nid_match.end():]
        values = VALUE_RE.findall(coord_str)
        if len(values) >= 3:
            coords = [float(v.replace("D", "E").replace("d", "e")) for v in values[:3]]
            return nid, (coords[0], coords[1], coords[2])

        return None, (0.0, 0.0, 0.0)
    except (ValueError, IndexError):
        return None, (0.0, 0.0, 0.0)


def _parse_result_blocks(lines: list[str]) -> dict[str, dict[str, Any]]:
    """Parse all result blocks (-4 NAME sections)."""
    results: dict[str, dict[str, Any]] = {}
    i = 0

    while i < len(lines):
        line = lines[i].rstrip()

        # Result block header: starts with " -4  NAME"
        if line.lstrip().startswith("-4") and not line.lstrip().startswith("-4 -4"):
            block_name, components, i = _parse_result_header(lines, i)
            if block_name:
                data, i = _parse_result_data(lines, i)
                results[block_name] = {
                    "components": components,
                    "data": data,
                }
                continue
        i += 1

    return results


def _parse_result_header(lines: list[str], start: int) -> tuple[str, list[str], int]:
    """Parse a result block header to get block name and component names.

    Returns (block_name, components, next_line_index).
    """
    header_line = lines[start].strip()
    # Extract block name: "-4  DISP" or "-4  STRESS"
    parts = header_line.split()
    if len(parts) < 2:
        return "", [], start + 1

    block_name = parts[1]
    components: list[str] = []
    i = start + 1

    # Parse component definition lines (start with -5)
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("-5"):
            # Component name line
            comp_parts = line.split()
            if len(comp_parts) >= 2:
                components.append(comp_parts[1])
            i += 1
        else:
            break

    return block_name, components, i


def _parse_result_data(lines: list[str], start: int) -> tuple[dict[int, list[float]], int]:
    """Parse result data lines until -3 marker.

    Returns (node_id -> values, next_line_index).
    """
    data: dict[int, list[float]] = {}
    i = start

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("-3"):
            return data, i + 1
        if line.startswith("-1"):
            nid, values = _parse_result_line(line)
            if nid is not None:
                data[nid] = values
        i += 1

    return data, i


def _parse_result_line(line: str) -> tuple[int | None, list[float]]:
    """Parse a single result data line.

    Format: ``-1 <node_id> <v1><v2><v3>...``
    """
    try:
        stripped = line.strip()
        if not stripped.startswith("-1"):
            return None, []

        rest = stripped[2:].strip()
        parts = rest.split()

        if len(parts) >= 2:
            nid = int(parts[0])
            # Try splitting remaining as separate values
            value_str = " ".join(parts[1:])
            raw_values = VALUE_RE.findall(value_str)
            if raw_values:
                values = [float(v.replace("D", "E").replace("d", "e")) for v in raw_values]
                return nid, values

            # Try the whole rest as concatenated
            raw_values = VALUE_RE.findall(rest[len(parts[0]):])
            if raw_values:
                values = [float(v.replace("D", "E").replace("d", "e")) for v in raw_values]
                return nid, values

        return None, []
    except (ValueError, IndexError):
        return None, []


def get_node_coords(frd_data: dict[str, Any]) -> dict[int, tuple[float, float, float]]:
    """Get node coordinates from parsed FRD data."""
    return frd_data["nodes"]


def get_result_blocks(frd_data: dict[str, Any]) -> list[str]:
    """Get list of available result block names."""
    return list(frd_data["results"].keys())


def get_displacements(frd_data: dict[str, Any]) -> dict[int, list[float]] | None:
    """Get displacement results if available."""
    for name in ("DISP", "DISPLACEMENT", "DISPLACEMENTS"):
        if name in frd_data["results"]:
            return frd_data["results"][name]["data"]
    return None


def get_stresses(frd_data: dict[str, Any]) -> dict[int, list[float]] | None:
    """Get stress results if available."""
    for name in ("STRESS", "STRESSES"):
        if name in frd_data["results"]:
            return frd_data["results"][name]["data"]
    return None
