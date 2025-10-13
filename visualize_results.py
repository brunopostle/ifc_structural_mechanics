#!/usr/bin/env python3
"""
Example script to visualize structural analysis results.

This script loads a mesh file and analysis results, then creates an
interactive 3D visualization of the deformed structure.
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
    ifc_file = "examples/analysis-models/ifcFiles/beam_01.ifc"
    results_dir = "./results"
    mesh_file = f"{results_dir}/mesh_16GlpLAhr6UgLoZdff86vk.msh"

    # Scale factor for displacement (make deformations visible)
    scale_factor = 1000.0  # Amplify displacements 1000x for visibility

    print("=" * 80)
    print("Structural Analysis Results Visualization")
    print("=" * 80)

    # Extract model
    print(f"\n1. Extracting model from {ifc_file}...")
    extractor = Extractor(ifc_file)
    model = extractor.extract_model()
    print(f"   Model: {len(model.members)} members, {len(model.connections)} connections")

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

    # Check if we have results
    if not parsed_results.get('displacement'):
        print("\n   ERROR: No displacement results found!")
        return 1

    # Create visualizer
    print(f"\n3. Loading mesh from {mesh_file}...")
    viz = ResultVisualizer(model)

    if not Path(mesh_file).exists():
        print(f"   ERROR: Mesh file not found: {mesh_file}")
        return 1

    viz.load_mesh_from_file(mesh_file)

    # Apply displacements
    print(f"\n4. Applying displacement field (scale factor: {scale_factor}x)...")
    viz.apply_displacement_field(scale_factor=scale_factor)

    # Add stress field if available
    if parsed_results.get('stress'):
        print("   Adding stress field...")
        viz.add_stress_field()

    # Create visualization
    print("\n5. Creating interactive 3D visualization...")
    print("   - Use mouse to rotate view")
    print("   - Scroll to zoom")
    print("   - Close window when done")
    print()

    # Show displacement field
    viz.plot_deformed(
        scale_factor=scale_factor,
        show_undeformed=True,
        field='Displacement',
        cmap='jet'
    )

    print("\nVisualization complete!")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
