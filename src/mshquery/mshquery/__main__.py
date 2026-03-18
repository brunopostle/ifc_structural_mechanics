"""CLI entry point for mshquery.

Usage:
    mshquery <file.msh> <command> [options]
    python -m mshquery <file.msh> <command> [options]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def format_output(data: Any, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False)
    elif fmt == "text":
        return _format_text(data)
    return json.dumps(data, indent=2, ensure_ascii=False)


def _format_text(data: Any, indent: int = 0) -> str:
    prefix = "  " * indent
    lines: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_format_text(value, indent + 1))
            else:
                lines.append(f"{prefix}{key}: {value}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                lines.append(_format_text(item, indent))
                lines.append("")
            else:
                lines.append(f"{prefix}- {item}")
    else:
        lines.append(f"{prefix}{data}")
    return "\n".join(lines)


def main() -> None:
    # Parent parser for --format flag, shared across all subcommands
    fmt = argparse.ArgumentParser(add_help=False)
    fmt.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        dest="output_format",
        help="Output format (default: json)",
    )

    parser = argparse.ArgumentParser(
        prog="mshquery",
        description="Query Gmsh mesh files (.msh)",
    )
    parser.add_argument("msh_file", help="Path to Gmsh .msh file")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # summary
    subparsers.add_parser(
        "summary",
        help="Mesh overview (nodes, elements, groups, bounding box)",
        parents=[fmt],
    )

    # info node/element
    info_parser = subparsers.add_parser("info", help="Inspect a node or element")
    info_sub = info_parser.add_subparsers(dest="info_type", required=True)
    node_info_p = info_sub.add_parser("node", help="Node coordinates", parents=[fmt])
    node_info_p.add_argument("id", type=int, help="Node ID (1-based)")
    elem_info_p = info_sub.add_parser("element", help="Element details", parents=[fmt])
    elem_info_p.add_argument("id", type=int, help="Element ID (1-based)")

    # nodes
    nodes_parser = subparsers.add_parser("nodes", help="List nodes", parents=[fmt])
    nodes_parser.add_argument(
        "--range", dest="node_range", help="Node ID range, e.g. 1-10"
    )

    # select
    select_parser = subparsers.add_parser("select", help="Filter nodes/elements")
    select_sub = select_parser.add_subparsers(dest="select_type", required=True)

    nodes_at_p = select_sub.add_parser(
        "nodes-at", help="Nodes near a position", parents=[fmt]
    )
    nodes_at_p.add_argument("--x", type=float, default=None, help="X coordinate")
    nodes_at_p.add_argument("--y", type=float, default=None, help="Y coordinate")
    nodes_at_p.add_argument("--z", type=float, default=None, help="Z coordinate")
    nodes_at_p.add_argument(
        "--tol", type=float, default=1e-6, help="Tolerance (default: 1e-6)"
    )

    ewn_p = select_sub.add_parser(
        "elements-with-node", help="Elements containing a node", parents=[fmt]
    )
    ewn_p.add_argument("id", type=int, help="Node ID (1-based)")

    ebt_p = select_sub.add_parser(
        "elements-by-type", help="Elements of a given type", parents=[fmt]
    )
    ebt_p.add_argument("type", help="Element type (e.g. line, triangle)")

    # groups
    subparsers.add_parser(
        "groups", help="Physical groups with entity counts", parents=[fmt]
    )

    args = parser.parse_args()

    if not os.path.isfile(args.msh_file):
        print(f"Error: File not found: {args.msh_file}", file=sys.stderr)
        sys.exit(1)

    try:
        import meshio

        mesh = meshio.read(args.msh_file)
    except Exception as e:
        print(f"Error: Could not read mesh file: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        result = _dispatch(mesh, args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(format_output(result, args.output_format))


def _dispatch(mesh: Any, args: argparse.Namespace) -> Any:
    """Route command to the appropriate handler."""
    cmd = args.command

    if cmd == "summary":
        from . import summary as summary_mod

        return summary_mod.summary(mesh)

    elif cmd == "info":
        from . import info as info_mod

        if args.info_type == "node":
            return info_mod.node_info(mesh, args.id)
        elif args.info_type == "element":
            return info_mod.element_info(mesh, args.id)

    elif cmd == "nodes":
        from . import nodes as nodes_mod

        return nodes_mod.list_nodes(mesh, range_str=getattr(args, "node_range", None))

    elif cmd == "select":
        from . import select as select_mod

        if args.select_type == "nodes-at":
            return select_mod.nodes_at(mesh, x=args.x, y=args.y, z=args.z, tol=args.tol)
        elif args.select_type == "elements-with-node":
            return select_mod.elements_with_node(mesh, args.id)
        elif args.select_type == "elements-by-type":
            return select_mod.elements_by_type(mesh, args.type)

    elif cmd == "groups":
        from . import groups as groups_mod

        return groups_mod.groups(mesh)

    raise ValueError(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
