#!/usr/bin/env python3
"""
Visualize structural analysis results for any model.

Usage:
    python visualize.py <model_name> [options]

Examples:
    python visualize.py slab_01
    python visualize.py portal_01 --scale 500
    python visualize.py building_02 --field stress --screenshot result.png
    python visualize.py beam_01 --html beam_result.html
    python visualize.py structure_01 --output-dir /path/to/results

Models are looked up in _analysis_output/<model_name>/ by default,
with IFC files from examples/analysis-models/ifcFiles/<model_name>.ifc.
"""

import argparse
import sys
from pathlib import Path

from ifc_structural_mechanics.visualization import ResultVisualizer
from ifc_structural_mechanics.ifc.extractor import Extractor
from ifc_structural_mechanics.analysis.results_parser import ResultsParser


DEFAULT_OUTPUT_DIR = Path("_analysis_output")
DEFAULT_IFC_DIR = Path("examples/analysis-models/ifcFiles")


def find_files(model_name, output_dir=None):
    """Locate IFC, INP, and result files for a model."""
    out = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR / model_name
    ifc = DEFAULT_IFC_DIR / f"{model_name}.ifc"

    if not out.exists():
        sys.exit(f"Output directory not found: {out}\nRun the analysis first.")
    if not ifc.exists():
        sys.exit(f"IFC file not found: {ifc}")

    # Find INP file
    inp_file = out / "analysis.inp"
    if not inp_file.exists():
        sys.exit(f"No analysis.inp found in {out}")

    # Find FRD result file
    frd_file = None
    for f in [out / "analysis.frd", out / "calculix_output.results"]:
        if f.exists():
            frd_file = f
            break
    if not frd_file:
        sys.exit(f"No .frd result file found in {out}")

    # Find DAT file
    dat_file = None
    for f in [out / "analysis.dat", out / "calculix_output.data"]:
        if f.exists():
            dat_file = f
            break

    return ifc, inp_file, frd_file, dat_file


def auto_scale(displacements):
    """Pick a scale factor that makes max displacement visible."""
    if not displacements:
        return 1.0
    max_disp = max(
        (sum(c ** 2 for c in r.get_translations()) ** 0.5)
        for r in displacements
    )
    if max_disp < 1e-12:
        return 1.0
    return min(max(0.1 / max_disp, 1.0), 10000.0)


def main():
    parser = argparse.ArgumentParser(
        description="Visualize structural analysis results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("model", help="Model name (e.g. slab_01, portal_01, building_02)")
    parser.add_argument("--output-dir", "-d", help="Override output directory path")
    parser.add_argument(
        "--scale", "-s", type=float, default=None,
        help="Displacement scale factor (default: auto)",
    )
    parser.add_argument(
        "--field", "-f", default="displacement",
        choices=["displacement", "stress"],
        help="Field to visualize (default: displacement)",
    )
    parser.add_argument("--cmap", "-c", default="jet", help="Colormap (default: jet)")
    parser.add_argument("--screenshot", help="Save screenshot to file instead of interactive view")
    parser.add_argument("--html", help="Export interactive HTML to file")
    parser.add_argument("--no-undeformed", action="store_true", help="Hide undeformed wireframe")
    parser.add_argument(
        "--step", default=None,
        help="Load case / step name to visualize (default: all steps combined)",
    )

    args = parser.parse_args()

    # Find files
    ifc_path, inp_file, frd_file, dat_file = find_files(args.model, args.output_dir)

    print(f"Model:   {args.model}")
    print(f"IFC:     {ifc_path}")
    print(f"INP:     {inp_file}")
    print(f"Results: {frd_file}")
    print()

    # Extract model
    print("Extracting model...")
    model = Extractor(str(ifc_path)).extract_model()
    print(f"  {len(model.members)} members, {len(model.connections)} connections")

    # Parse results
    print("Parsing results...")
    result_files = {"results": str(frd_file)}
    if dat_file:
        result_files["data"] = str(dat_file)
    parsed = ResultsParser(domain_model=model).parse_results(result_files)

    n_disp = len(parsed.get("displacement", []))
    n_stress = len(parsed.get("stress", []))
    print(f"  {n_disp} displacement results, {n_stress} stress results")

    # Filter by step/load-case name if requested
    if args.step:
        filtered = [
            r for r in parsed.get("displacement", [])
            if r.get_metadata("load_case") == args.step
        ]
        if not filtered:
            available = sorted(set(
                r.get_metadata("load_case") for r in parsed.get("displacement", [])
                if r.get_metadata("load_case")
            ))
            sys.exit(
                f"No results for step '{args.step}'. "
                f"Available: {available or ['(no load case tags)']}"
            )
        parsed["displacement"] = filtered
        n_disp = len(filtered)
        print(f"  Filtered to {n_disp} results for step '{args.step}'")

    if n_disp == 0:
        sys.exit("No displacement results found — nothing to visualize.")

    # Load mesh via FRD+INP (handles CalculiX node renumbering)
    print("Loading mesh and building node mapping...")
    viz = ResultVisualizer(model)
    viz.load_mesh_from_frd(str(frd_file), str(inp_file))
    mapped = len(getattr(viz, '_inp_node_to_frd_node', {}))
    print(f"  {viz.mesh.n_points} mesh nodes, {mapped} mapped to FRD results")

    # Determine scale factor
    from ifc_structural_mechanics.domain.result import DisplacementResult
    disp_results = [r for r in model.results if isinstance(r, DisplacementResult)]
    scale = args.scale if args.scale is not None else auto_scale(disp_results)
    print(f"  Scale factor: {scale:.1f}x")

    # Apply displacement field
    print("Applying displacements...")
    viz.apply_displacement_field(scale_factor=scale)

    # Apply stress field if requested and available
    field_name = "Displacement (mm)"
    if args.field == "stress":
        if n_stress > 0:
            print("Applying stress field...")
            viz.add_stress_field()
            field_name = "Von Mises Stress"
        else:
            print("No stress results available, falling back to displacement.")

    # Output
    if args.html:
        print(f"Exporting to {args.html}...")
        viz.export_to_html(args.html, scale_factor=scale, field=field_name, cmap=args.cmap)
        print(f"Done — open {args.html} in a browser.")
    elif args.screenshot:
        print(f"Saving screenshot to {args.screenshot}...")
        viz.plot_deformed(
            scale_factor=scale,
            show_undeformed=not args.no_undeformed,
            field=field_name,
            cmap=args.cmap,
            screenshot=args.screenshot,
        )
        print("Done.")
    else:
        print("Opening interactive viewer...")
        print("  Mouse: rotate | Scroll: zoom | Shift+mouse: pan | Q: quit")
        viz.plot_deformed(
            scale_factor=scale,
            show_undeformed=not args.no_undeformed,
            field=field_name,
            cmap=args.cmap,
        )


if __name__ == "__main__":
    main()
