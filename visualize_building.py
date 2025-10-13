#!/usr/bin/env python3
"""
Visualize building_01 structural analysis results.

This script loads the building model and creates an interactive 3D visualization
of the deformed structure with stress distribution.
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

    # Scale factor for displacement (make tiny deformations visible)
    # Building models typically have very small displacements
    scale_factor = 100000.0  # Amplify displacements 100,000x for visibility

    print("=" * 80)
    print("Building_01 Structural Analysis Visualization")
    print("=" * 80)

    # Extract model
    print(f"\n1. Extracting model from {ifc_file}...")
    extractor = Extractor(ifc_file)
    model = extractor.extract_model()
    print(f"   Model: {len(model.members)} members, {len(model.connections)} connections")
    print(f"   Load groups: {len(model.load_groups)}")

    # Parse results
    print(f"\n2. Parsing results from {results_dir}...")
    result_files = {
        "results": f"{results_dir}/analysis.frd",
        "data": f"{results_dir}/analysis.dat",
    }
    parser = ResultsParser(domain_model=model)
    parsed_results = parser.parse_results(result_files)

    print(f"   Displacements: {len(parsed_results.get('displacement', []))}")
    print(f"   Stresses: {len(parsed_results.get('stress', []))}")
    print(f"   Strains: {len(parsed_results.get('strain', []))}")
    print(f"   Reactions: {len(parsed_results.get('reaction', []))}")

    # Show max displacement
    displacements = parsed_results.get('displacement', [])
    if displacements:
        max_disp = max(d.get_magnitude() for d in displacements)
        print(f"   Max displacement magnitude: {max_disp:.6e}")

    # Check if we have results
    if not displacements:
        print("\n   ERROR: No displacement results found!")
        return 1

    # Create visualizer
    print(f"\n3. Loading mesh from {mesh_file}...")
    viz = ResultVisualizer(model)

    if not Path(mesh_file).exists():
        print(f"   ERROR: Mesh file not found: {mesh_file}")
        print(f"   Available files in {results_dir}:")
        for f in Path(results_dir).glob("*.msh"):
            print(f"     {f}")
        return 1

    viz.load_mesh_from_file(mesh_file)

    # Apply displacements
    print(f"\n4. Applying displacement field (scale factor: {scale_factor:.0f}x)...")
    viz.apply_displacement_field(scale_factor=scale_factor)

    # Add stress field if available
    if parsed_results.get('stress'):
        print("   Adding stress field...")
        viz.add_stress_field()
        field_to_show = 'Von Mises Stress'
    else:
        print("   No stress results available, showing displacement only")
        field_to_show = 'Displacement'

    # Create visualization
    print("\n5. Creating interactive 3D visualization...")
    print("   Controls:")
    print("   - Left click + drag: Rotate view")
    print("   - Right click + drag: Pan")
    print("   - Scroll wheel: Zoom")
    print("   - 'q': Quit")
    print("   - 'r': Reset camera")
    print()

    # Show with appropriate field
    try:
        viz.plot_deformed(
            scale_factor=scale_factor,
            show_undeformed=True,
            field=field_to_show,
            cmap='jet',
            window_size=(1400, 900)
        )
    except Exception as e:
        print(f"   Visualization error: {e}")
        print("   Trying without undeformed mesh...")
        viz.plot_deformed(
            scale_factor=scale_factor,
            show_undeformed=False,
            field=field_to_show,
            cmap='jet',
            window_size=(1400, 900)
        )

    print("\nVisualization complete!")

    # Optional: Export to HTML
    print("\n6. Exporting to HTML...")
    html_file = f"{results_dir}/visualization.html"
    try:
        viz.export_to_html(html_file, scale_factor=scale_factor, field=field_to_show)
        print(f"   Saved interactive visualization to: {html_file}")
        print(f"   Open this file in a web browser to view")
    except Exception as e:
        print(f"   HTML export failed: {e}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
