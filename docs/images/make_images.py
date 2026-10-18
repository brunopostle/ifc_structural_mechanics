"""Make the pictures in README.md and docs/ from the example models.

Run from the root of the repository, with PyVista installed
(``pip install -e ".[viz]"``):

    python docs/images/make_images.py               # every picture
    python docs/images/make_images.py portal_01     # those of some models
    python docs/images/make_images.py --work /tmp/images   # keep the analyses

Each model is analysed at the settings given here, which are part of what
the picture shows, and the pictures are written beside this script.
``building_02`` takes about eight minutes and 2 GB of memory for its static
analysis and as long again for its modes.
"""

import argparse
import os
import sys
import tempfile
import time

from ifc_structural_mechanics.api.structural_analysis import analyze_ifc
from ifc_structural_mechanics.visualization.plot import plot

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(HERE, "..", "..", "examples", "analysis-models", "ifcFiles")
SIZE = (1400, 900)

# Analyses: name -> (IFC file, settings of analyze_ifc)
ANALYSES = {
    "beam_01": ("beam_01", {"mesh_size": 0.25}),
    "portal_01": ("portal_01", {"mesh_size": 0.25}),
    "grid_of_beams": ("grid_of_beams", {"mesh_size": 0.25, "gravity": True}),
    "structure_01": ("structure_01", {"mesh_size": 0.25, "gravity": True}),
    "building_01": ("building_01", {"mesh_size": 0.5}),
    "building_01_modal": (
        "building_01",
        {"mesh_size": 0.5, "analysis_type": "modal", "num_modes": 6},
    ),
    "building_02": ("building_02", {"mesh_size": 2.0}),
    "building_02_modal": (
        "building_02",
        {"mesh_size": 2.0, "analysis_type": "modal", "num_modes": 6},
    ),
}

# Pictures: file -> (analysis, options of plot.render)
PICTURES = {
    "building_02_combination.png": (
        "building_02",
        {"combination": "1.4D+1.6L", "title": "building_02.ifc"},
    ),
    "building_02_mode_1.png": (
        "building_02_modal",
        {"mode": 1, "title": "building_02.ifc"},
    ),
    "building_01_live.png": (
        "building_01",
        {"case": "Live", "edges": True, "title": "building_01.ifc"},
    ),
    "building_01_mode_1.png": (
        "building_01_modal",
        {"mode": 1, "title": "building_01.ifc"},
    ),
    "structure_01_displacement.png": (
        "structure_01",
        {"edges": True, "title": "structure_01.ifc"},
    ),
    "portal_01_moments.png": (
        "portal_01",
        {
            "field": "Mf1",
            "reactions": True,
            "loads": True,
            "title": "portal_01.ifc",
        },
    ),
    "portal_01_displacement.png": (
        "portal_01",
        {"loads": True, "title": "portal_01.ifc"},
    ),
    "grid_of_beams_moments.png": (
        "grid_of_beams",
        {"field": "Mf1", "reactions": True, "title": "grid_of_beams.ifc"},
    ),
    "beam_01_shear.png": (
        "beam_01",
        {"field": "Vf1", "reactions": True, "loads": True, "title": "beam_01.ifc"},
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("models", nargs="*", help="Only the pictures of these")
    parser.add_argument("--work", help="Directory for the analyses (kept)")
    args = parser.parse_args()

    wanted = {
        name: (analysis, options)
        for name, (analysis, options) in PICTURES.items()
        if not args.models or ANALYSES[analysis][0] in args.models
    }
    work = args.work or tempfile.mkdtemp(prefix="ifc_images_")
    done = set()
    for name, (analysis, options) in wanted.items():
        directory = os.path.join(work, analysis)
        if analysis not in done and not os.path.exists(
            os.path.join(directory, "results.json")
        ):
            model, settings = ANALYSES[analysis]
            start = time.time()
            result = analyze_ifc(
                ifc_path=os.path.join(MODELS, f"{model}.ifc"),
                output_dir=directory,
                **settings,
            )
            if result["status"] != "success":
                print(f"{analysis}: {result.get('errors')}", file=sys.stderr)
                return 1
            print(f"{analysis}: analysed in {time.time() - start:.0f} s")
        done.add(analysis)
        path = os.path.join(HERE, name)
        plot(directory, screenshot=path, window_size=SIZE, **options)
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
