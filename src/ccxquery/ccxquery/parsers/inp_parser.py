"""Parser for CalculiX .inp input files.

Parses *KEYWORD sections into structured dicts. Comments (**) are ignored.
Keyword lines like ``*ELEMENT, TYPE=B31, ELSET=M1`` are split into keyword
name and parameter dict.
"""

from __future__ import annotations

import re
from typing import Any


def parse_inp(path: str) -> list[dict[str, Any]]:
    """Parse an .inp file into a list of keyword sections.

    Each section is a dict with:
        keyword: str  (e.g. "NODE", "ELEMENT", "BOUNDARY")
        params: dict  (e.g. {"TYPE": "B31", "ELSET": "M1"})
        data: list[str]  (raw data lines below the keyword)
        line: int  (1-based line number of the keyword)
    """
    with open(path, "r") as f:
        lines = f.readlines()

    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for i, raw in enumerate(lines):
        line = raw.rstrip("\n\r")
        stripped = line.lstrip()

        # Skip comments
        if stripped.startswith("**"):
            continue

        # Keyword line
        if stripped.startswith("*") and not stripped.startswith("**"):
            if current is not None:
                sections.append(current)
            keyword, params = _parse_keyword_line(stripped)
            current = {
                "keyword": keyword,
                "params": params,
                "data": [],
                "line": i + 1,
            }
        elif current is not None:
            if stripped:
                current["data"].append(stripped)

    if current is not None:
        sections.append(current)

    return sections


def _parse_keyword_line(line: str) -> tuple[str, dict[str, str]]:
    """Parse a keyword line into (keyword, params).

    Example: ``*ELEMENT, TYPE=B31, ELSET=M1``
    Returns: ("ELEMENT", {"TYPE": "B31", "ELSET": "M1"})
    """
    # Remove leading *
    line = line.lstrip("*")
    parts = [p.strip() for p in line.split(",")]
    keyword = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.strip().upper()] = v.strip()
        elif part.strip():
            params[part.strip().upper()] = ""
    return keyword, params


def get_sections_by_keyword(sections: list[dict[str, Any]], keyword: str) -> list[dict[str, Any]]:
    """Filter sections by keyword name (case-insensitive)."""
    keyword = keyword.upper()
    return [s for s in sections if s["keyword"] == keyword]


def parse_nodes(sections: list[dict[str, Any]]) -> dict[int, tuple[float, float, float]]:
    """Extract node coordinates from parsed sections."""
    nodes: dict[int, tuple[float, float, float]] = {}
    for sec in get_sections_by_keyword(sections, "NODE"):
        for line in sec["data"]:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                nid = int(parts[0])
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                nodes[nid] = (x, y, z)
            elif len(parts) == 3:
                nid = int(parts[0])
                x, y = float(parts[1]), float(parts[2])
                nodes[nid] = (x, y, 0.0)
    return nodes


def parse_elements(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract elements from parsed sections."""
    elements: list[dict[str, Any]] = []
    for sec in get_sections_by_keyword(sections, "ELEMENT"):
        etype = sec["params"].get("TYPE", "unknown")
        elset = sec["params"].get("ELSET", "")
        for line in sec["data"]:
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) >= 2:
                eid = int(parts[0])
                connectivity = [int(p) for p in parts[1:]]
                elements.append({
                    "id": eid,
                    "type": etype,
                    "elset": elset,
                    "connectivity": connectivity,
                })
    return elements


def parse_node_sets(sections: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Extract NSET definitions."""
    nsets: dict[str, list[int]] = {}
    for sec in get_sections_by_keyword(sections, "NSET"):
        name = sec["params"].get("NSET", "unnamed")
        generate = "GENERATE" in sec["params"]
        ids: list[int] = []
        for line in sec["data"]:
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if generate and len(parts) >= 2:
                start, end = int(parts[0]), int(parts[1])
                step = int(parts[2]) if len(parts) >= 3 else 1
                ids.extend(range(start, end + 1, step))
            else:
                ids.extend(int(p) for p in parts)
        nsets[name] = ids
    return nsets


def parse_element_sets(sections: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Extract ELSET definitions."""
    elsets: dict[str, list[int]] = {}
    for sec in get_sections_by_keyword(sections, "ELSET"):
        name = sec["params"].get("ELSET", "unnamed")
        generate = "GENERATE" in sec["params"]
        ids: list[int] = []
        for line in sec["data"]:
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if generate and len(parts) >= 2:
                start, end = int(parts[0]), int(parts[1])
                step = int(parts[2]) if len(parts) >= 3 else 1
                ids.extend(range(start, end + 1, step))
            else:
                ids.extend(int(p) for p in parts)
        elsets[name] = ids
    return elsets


def parse_materials(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract material definitions."""
    materials: list[dict[str, Any]] = []
    current_mat: dict[str, Any] | None = None

    for sec in sections:
        kw = sec["keyword"]
        if kw == "MATERIAL":
            if current_mat is not None:
                materials.append(current_mat)
            current_mat = {"name": sec["params"].get("NAME", "unnamed"), "properties": {}}
        elif current_mat is not None:
            if kw == "ELASTIC":
                if sec["data"]:
                    parts = [p.strip() for p in sec["data"][0].split(",") if p.strip()]
                    props: dict[str, Any] = {}
                    if len(parts) >= 1:
                        props["youngs_modulus"] = float(parts[0])
                    if len(parts) >= 2:
                        props["poissons_ratio"] = float(parts[1])
                    current_mat["properties"]["elastic"] = props
            elif kw == "DENSITY":
                if sec["data"]:
                    parts = [p.strip() for p in sec["data"][0].split(",") if p.strip()]
                    if parts:
                        current_mat["properties"]["density"] = float(parts[0])
            elif kw == "MATERIAL":
                # Next material starts
                pass
            elif kw.startswith("*"):
                # Non-material keyword, end current material
                pass

    if current_mat is not None:
        materials.append(current_mat)
    return materials


def parse_boundary_conditions(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract boundary conditions."""
    bcs: list[dict[str, Any]] = []
    for sec in get_sections_by_keyword(sections, "BOUNDARY"):
        for line in sec["data"]:
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) >= 3:
                bc: dict[str, Any] = {"target": parts[0]}
                bc["first_dof"] = int(parts[1])
                bc["last_dof"] = int(parts[2])
                if len(parts) >= 4:
                    bc["value"] = float(parts[3])
                bcs.append(bc)
            elif len(parts) == 2:
                bc = {"target": parts[0], "first_dof": int(parts[1]), "last_dof": int(parts[1])}
                bcs.append(bc)
    return bcs


def parse_cloads(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract concentrated loads."""
    loads: list[dict[str, Any]] = []
    for sec in get_sections_by_keyword(sections, "CLOAD"):
        for line in sec["data"]:
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) >= 3:
                loads.append({
                    "node": parts[0],
                    "dof": int(parts[1]),
                    "magnitude": float(parts[2]),
                })
    return loads


def parse_dloads(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract distributed loads."""
    loads: list[dict[str, Any]] = []
    for sec in get_sections_by_keyword(sections, "DLOAD"):
        for line in sec["data"]:
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) >= 3:
                loads.append({
                    "element": parts[0],
                    "type": parts[1],
                    "magnitude": float(parts[2]),
                })
    return loads


def parse_steps(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract analysis steps."""
    steps: list[dict[str, Any]] = []
    in_step = False
    current_step: dict[str, Any] | None = None

    for sec in sections:
        kw = sec["keyword"]
        if kw == "STEP":
            in_step = True
            current_step = {"params": sec["params"], "keywords": [], "line": sec["line"]}
        elif kw == "END STEP" or kw == "ENDSTEP":
            if current_step is not None:
                steps.append(current_step)
            in_step = False
            current_step = None
        elif in_step and current_step is not None:
            current_step["keywords"].append(kw)

    if current_step is not None:
        steps.append(current_step)

    return steps


def parse_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract beam/shell section definitions."""
    result: list[dict[str, Any]] = []
    for kw_name in ("BEAM SECTION", "BEAM GENERAL SECTION", "SHELL SECTION"):
        for sec in get_sections_by_keyword(sections, kw_name):
            entry: dict[str, Any] = {
                "type": kw_name.lower().replace(" ", "_"),
                "params": sec["params"],
            }
            if sec["data"]:
                entry["data"] = sec["data"]
            result.append(entry)
    return result
