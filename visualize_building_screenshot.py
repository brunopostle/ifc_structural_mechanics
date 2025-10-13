#!/usr/bin/env python3
"""
Generate screenshot and HTML of building_01 analysis results.

This script creates visualizations without opening the interactive window,
useful for batch processing or running on headless systems.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ifc_structural_mechanics.visualization import ResultVisualizer
from ifc_structural_mechanics.ifc.extractor import Extractor
from ifc_structural_mechanics.analysis.results_parser import ResultsParser


def main():
    # Configuration
    ifc_file = "examples/analysis-models/ifcFiles/building_01.ifc"
    results_dir = "./results_building_01"
    mesh_file = f"{results_dir}/mesh_2Su8kmjQP9QhnGZXq2NLn9.msh"

    output_screenshot = f"{results_dir}/building_deformed.png"
    output_html = f"{results_dir}/building_interactive.html"

    # Scale factor
    scale_factor = 100000.0

    print("=" * 80)
    print("Building_01 Visualization (Screenshot Mode)")
    print("=" * 80)

    # Extract model
    print(f"\n1. Loading model and results...")
    extractor = Extractor(ifc_file)
    model = extractor.extract_model()

    # Parse results
    result_files = {
        "results": f"{results_dir}/analysis.frd",
        "data": f"{results_dir}/analysis.dat",
    }
    parser = ResultsParser(domain_model=model)
    parsed_results = parser.parse_results(result_files)

    displacements = parsed_results.get('displacement', [])
    if displacements:
        max_disp = max(d.get_magnitude() for d in displacements)
        print(f"   Max displacement: {max_disp:.6e}")

    if not displacements:
        print("   ERROR: No displacement results!")
        return 1

    # Create visualizer
    print(f"\n2. Creating visualization...")
    viz = ResultVisualizer(model)
    viz.load_mesh_from_file(mesh_file)
    viz.apply_displacement_field(scale_factor=scale_factor)

    # Add stress if available
    field_to_show = 'Displacement'
    if parsed_results.get('stress'):
        viz.add_stress_field()
        field_to_show = 'Von Mises Stress'

    # Save screenshot
    print(f"\n3. Saving screenshot to: {output_screenshot}")
    try:
        viz.plot_deformed(
            scale_factor=scale_factor,
            show_undeformed=True,
            field=field_to_show,
            screenshot=output_screenshot,
            window_size=(1920, 1080)
        )
        print(f"   ✓ Screenshot saved")
    except Exception as e:
        print(f"   Screenshot failed: {e}")

    # Export to HTML
    print(f"\n4. Exporting interactive HTML to: {output_html}")
    try:
        viz.export_to_html(output_html, scale_factor=scale_factor, field=field_to_show)
        print(f"   ✓ HTML saved")
        print(f"\n   Open {output_html} in a web browser to view interactively")
    except Exception as e:
        print(f"   HTML export failed: {e}")

    print("\n" + "=" * 80)
    print("Visualization complete!")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
