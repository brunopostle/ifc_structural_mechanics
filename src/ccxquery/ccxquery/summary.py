"""Summary command for .inp and .frd files."""

from __future__ import annotations

from typing import Any

from .parsers import inp_parser, frd_parser


def summary_inp(sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Return an overview of an .inp file."""
    nodes = inp_parser.parse_nodes(sections)
    elements = inp_parser.parse_elements(sections)
    materials = inp_parser.parse_materials(sections)
    section_defs = inp_parser.parse_sections(sections)
    bcs = inp_parser.parse_boundary_conditions(sections)
    cloads = inp_parser.parse_cloads(sections)
    dloads = inp_parser.parse_dloads(sections)
    steps = inp_parser.parse_steps(sections)

    # Count element types
    type_counts: dict[str, int] = {}
    for el in elements:
        t = el["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "nodes": len(nodes),
        "elements": len(elements),
        "element_types": type_counts,
        "materials": len(materials),
        "sections": len(section_defs),
        "boundary_conditions": len(bcs),
        "concentrated_loads": len(cloads),
        "distributed_loads": len(dloads),
        "steps": len(steps),
        "keywords": [s["keyword"] for s in sections],
    }


def summary_frd(frd_data: dict[str, Any]) -> dict[str, Any]:
    """Return an overview of an .frd file."""
    nodes = frd_data["nodes"]
    results = frd_data["results"]

    result_info = {}
    for name, block in results.items():
        result_info[name] = {
            "components": block["components"],
            "node_count": len(block["data"]),
        }

    return {
        "nodes": len(nodes),
        "result_blocks": result_info,
    }
