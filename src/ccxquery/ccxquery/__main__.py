"""CLI entry point for ccxquery.

Usage:
    ccxquery <file> <command> [options]
    python -m ccxquery <file> <command> [options]
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


def _detect_file_type(path: str) -> str:
    """Detect file type from extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".inp":
        return "inp"
    elif ext == ".frd":
        return "frd"
    elif ext == ".dat":
        return "dat"
    else:
        return "unknown"


def _resolve_sibling(path: str, ext: str) -> str | None:
    """Find a sibling file with the given extension."""
    base = os.path.splitext(path)[0]
    candidate = base + ext
    if os.path.isfile(candidate):
        return candidate
    return None


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
        prog="ccxquery",
        description="Query CalculiX input and output files (.inp, .frd, .dat)",
    )
    parser.add_argument("file", help="Path to CalculiX file (.inp, .frd, or .dat)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # summary
    subparsers.add_parser("summary", help="File overview (nodes, elements, results)", parents=[fmt])

    # sets
    sets_parser = subparsers.add_parser("sets", help="List node/element sets", parents=[fmt])
    sets_parser.add_argument("--type", choices=["node", "element"], dest="set_type", help="Filter by set type")

    # set <name>
    set_parser = subparsers.add_parser("set", help="Show contents of a specific set", parents=[fmt])
    set_parser.add_argument("name", help="Set name")

    # materials
    subparsers.add_parser("materials", help="Material definitions", parents=[fmt])

    # sections
    subparsers.add_parser("sections", help="Section definitions (beam/shell)", parents=[fmt])

    # bcs
    subparsers.add_parser("bcs", help="Boundary conditions", parents=[fmt])

    # loads
    subparsers.add_parser("loads", help="Concentrated and distributed loads", parents=[fmt])

    # steps
    subparsers.add_parser("steps", help="Analysis steps", parents=[fmt])

    # node <id>
    node_parser = subparsers.add_parser("node", help="Node coordinates", parents=[fmt])
    node_parser.add_argument("node_id", type=int, help="Node ID")

    # nodes-at
    nodes_at_parser = subparsers.add_parser("nodes-at", help="Find nodes near a position", parents=[fmt])
    nodes_at_parser.add_argument("--x", type=float, default=None, help="X coordinate")
    nodes_at_parser.add_argument("--y", type=float, default=None, help="Y coordinate")
    nodes_at_parser.add_argument("--z", type=float, default=None, help="Z coordinate")
    nodes_at_parser.add_argument("--tol", type=float, default=1e-6, help="Tolerance (default: 1e-6)")

    # results
    subparsers.add_parser("results", help="Available result blocks from .frd", parents=[fmt])

    # displacements
    disp_parser = subparsers.add_parser("displacements", help="Displacement results from .frd", parents=[fmt])
    disp_parser.add_argument("--node", type=int, default=None, help="Specific node ID")
    disp_parser.add_argument("--max", action="store_true", dest="show_max", help="Show max displacement")
    disp_parser.add_argument("--min", action="store_true", dest="show_min", help="Show min displacement")

    # stresses
    stress_parser = subparsers.add_parser("stresses", help="Stress results from .frd", parents=[fmt])
    stress_parser.add_argument("--node", type=int, default=None, help="Specific node ID")
    stress_parser.add_argument("--max", action="store_true", dest="show_max", help="Show max stress")
    stress_parser.add_argument("--min", action="store_true", dest="show_min", help="Show min stress")

    # reactions
    subparsers.add_parser("reactions", help="Reaction forces from .dat", parents=[fmt])

    # status
    subparsers.add_parser("status", help="Analysis completion status from .dat", parents=[fmt])

    args = parser.parse_args()

    # Validate file exists
    if not os.path.isfile(args.file):
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    file_type = _detect_file_type(args.file)

    try:
        result = _dispatch(args, file_type)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(format_output(result, args.output_format))


def _dispatch(args: argparse.Namespace, file_type: str) -> Any:
    """Route command to the appropriate handler."""
    cmd = args.command

    # Commands that need .inp data
    if cmd in ("summary", "sets", "set", "materials", "sections", "bcs", "loads", "steps"):
        if file_type == "inp":
            inp_path = args.file
        else:
            inp_path = _resolve_sibling(args.file, ".inp")
            if inp_path is None and file_type != "frd":
                raise FileNotFoundError(f"No .inp file found for {args.file}")

        if cmd == "summary":
            if file_type == "frd":
                from .parsers import frd_parser
                from . import summary as summary_mod
                frd_data = frd_parser.parse_frd(args.file)
                return summary_mod.summary_frd(frd_data)
            elif file_type == "inp" or inp_path:
                from .parsers import inp_parser
                from . import summary as summary_mod
                sections = inp_parser.parse_inp(inp_path or args.file)
                return summary_mod.summary_inp(sections)
            else:
                raise ValueError(f"Cannot produce summary for {file_type} file")

        # All other .inp commands
        from .parsers import inp_parser
        sections = inp_parser.parse_inp(inp_path or args.file)

        if cmd == "sets":
            from . import sets as sets_mod
            return sets_mod.list_sets(sections, getattr(args, "set_type", None))
        elif cmd == "set":
            from . import sets as sets_mod
            return sets_mod.show_set(sections, args.name)
        elif cmd == "materials":
            from . import materials as mat_mod
            return mat_mod.materials(sections)
        elif cmd == "sections":
            from . import sections as sec_mod
            return sec_mod.sections(sections)
        elif cmd == "bcs":
            from . import bcs as bcs_mod
            return bcs_mod.bcs(sections)
        elif cmd == "loads":
            from . import loads as loads_mod
            return loads_mod.loads(sections)
        elif cmd == "steps":
            from . import steps as steps_mod
            return steps_mod.steps(sections)

    # Commands that need node data (from .inp or .frd)
    elif cmd in ("node", "nodes-at"):
        from . import node as node_mod

        if file_type == "frd":
            from .parsers import frd_parser
            frd_data = frd_parser.parse_frd(args.file)
            nodes = node_mod.get_nodes_from_frd(frd_data)
        elif file_type == "inp":
            from .parsers import inp_parser
            sections = inp_parser.parse_inp(args.file)
            nodes = node_mod.get_nodes_from_inp(sections)
        else:
            # Try to find .inp or .frd sibling
            frd_path = _resolve_sibling(args.file, ".frd")
            inp_path = _resolve_sibling(args.file, ".inp")
            if frd_path:
                from .parsers import frd_parser
                frd_data = frd_parser.parse_frd(frd_path)
                nodes = node_mod.get_nodes_from_frd(frd_data)
            elif inp_path:
                from .parsers import inp_parser
                sections = inp_parser.parse_inp(inp_path)
                nodes = node_mod.get_nodes_from_inp(sections)
            else:
                raise FileNotFoundError(f"No .inp or .frd file found for {args.file}")

        if cmd == "node":
            return node_mod.node_info(args.node_id, nodes)
        elif cmd == "nodes-at":
            return node_mod.nodes_at(nodes, x=args.x, y=args.y, z=args.z, tol=args.tol)

    # Commands that need .frd data
    elif cmd in ("results", "displacements", "stresses"):
        if file_type == "frd":
            frd_path = args.file
        else:
            frd_path = _resolve_sibling(args.file, ".frd")
            if frd_path is None:
                raise FileNotFoundError(f"No .frd file found for {args.file}")

        from .parsers import frd_parser
        frd_data = frd_parser.parse_frd(frd_path)

        if cmd == "results":
            from . import results as results_mod
            return results_mod.results(frd_data)
        elif cmd == "displacements":
            from . import displacements as disp_mod
            return disp_mod.displacements(frd_data, node_id=args.node, show_max=args.show_max, show_min=args.show_min)
        elif cmd == "stresses":
            from . import stresses as stress_mod
            return stress_mod.stresses(frd_data, node_id=args.node, show_max=args.show_max, show_min=args.show_min)

    # Commands that need .dat data
    elif cmd in ("reactions", "status"):
        if file_type == "dat":
            dat_path = args.file
        else:
            dat_path = _resolve_sibling(args.file, ".dat")
            if dat_path is None:
                raise FileNotFoundError(f"No .dat file found for {args.file}")

        from .parsers import dat_parser
        dat_data = dat_parser.parse_dat(dat_path)

        if cmd == "reactions":
            from . import reactions as react_mod
            return react_mod.reactions(dat_data)
        elif cmd == "status":
            from . import status as status_mod
            return status_mod.status(dat_data)

    raise ValueError(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
