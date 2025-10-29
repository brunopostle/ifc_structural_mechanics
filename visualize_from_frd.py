#!/usr/bin/env python3
"""
Visualize results directly from FRD file.

This reads both mesh and results from the same FRD file, so node/element IDs
are consistent and no mapping is needed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from ifc_structural_mechanics.visualization import ResultVisualizer
from ifc_structural_mechanics.ifc.extractor import Extractor
from ifc_structural_mechanics.analysis.results_parser import ResultsParser


def main():
    # Configuration
    ifc_file = "examples/analysis-models/ifcFiles/building_01.ifc"
    results_dir = "./results_building_01"
    frd_file = f"{results_dir}/analysis.frd"

    print("=" * 80)
    print("FRD-Based Visualization (Displacement)")
    print("=" * 80)

    # Extract model (for metadata)
    print(f"\n1. Loading model...")
    extractor = Extractor(ifc_file)
    model = extractor.extract_model()

    # Parse results
    print(f"2. Parsing results from FRD...")
    result_files = {
        "results": frd_file,
        "data": f"{results_dir}/analysis.dat",
    }
    parser = ResultsParser(domain_model=model)
    parsed_results = parser.parse_results(result_files)

    print(f"   Displacements: {len(parsed_results.get('displacement', []))}")
    print(f"   Stresses: {len(parsed_results.get('stress', []))}")

    # Create visualizer and load mesh from FRD
    print(f"\n3. Loading mesh from FRD file...")
    viz = ResultVisualizer(model)
    viz.load_mesh_from_frd(frd_file)

    # Apply displacement field (scale=1 for undeformed visualization)
    print(f"\n4. Mapping results to mesh...")
    viz.apply_displacement_field(scale_factor=1.0)

    # Visualize
    print(f"\n5. Creating visualization...")
    print("   Showing displacement magnitude on undeformed mesh")
    print("   Controls:")
    print("   - Left click + drag: Rotate")
    print("   - Right click + drag: Pan")
    print("   - Scroll: Zoom")
    print("   - 'q': Quit")
    print()

    viz.plot_deformed(
        scale_factor=1.0,
        show_undeformed=False,
        field='Displacement',
        cmap='jet',
        window_size=(1400, 900)
    )

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
