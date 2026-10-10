# IFC Structural Mechanics

A Python library for structural analysis of IFC (Industry Foundation Classes) building models using the CalculiX finite element solver.

> **Development Status**: This is early-stage, experimental software. It has been tested against a small set of example models and produces plausible results, but has known limitations described below. It is not suitable for production use without independent verification of results.

See [VISION.md](VISION.md) for the project roadmap and intended architecture.
See [docs/validation_report.md](docs/validation_report.md) for numerical accuracy benchmarks.

## Overview

IFC Structural Mechanics provides a workflow for performing structural analysis on IFC building models. The library extracts structural information from IFC files, generates finite element meshes using Gmsh, performs structural analysis with CalculiX, and provides tools for visualizing results.

### Capabilities

- **IFC Model Extraction**: Extract structural members (beams, columns, slabs, walls), connections, loads, and material/section properties from IFC files using `IfcStructuralAnalysisModel`
- **Automated Meshing**: Generate finite element meshes using Gmsh with conforming topology (shared nodes at member intersections)
- **Structural Analysis**: Linear static and linear buckling analysis using CalculiX (CCX)
- **Multiple Load Cases**: Each `IfcStructuralLoadCase` maps to a separate CalculiX `*STEP`; results are tagged with the load case name
- **Beam Sections**: Rectangular, circular, hollow circular (PIPE), and hollow rectangular (BOX/RHS) cross-sections map to native CalculiX B31 sections; I, T, L (angle), and C (channel) profiles are analysed via CalculiX U1 (Timoshenko) elements using a computed general section (`A`, `Iy`, `Iz`, shear factor). Sections are oriented by `IfcStructuralCurveMember.Axis`, with the profile depth along the member's local z
- **Connection End-Releases**: Rotational releases read from `IfcRelConnectsStructuralMember.AppliedCondition` and modelled as pinned connections
- **Result Visualization**: 3D visualization of deformed meshes and stress fields using PyVista; filter by load case with `--step`

### Known Limitations

Open bugs and planned work are tracked in the project's `bd` (beads) issue
database; `bd list --status=open` shows the current list. The points below are
the ones a user needs to know before trusting a result.

- **Multi-member models are only partly verified.** `structure_01` (slab, wall
  and two columns) is within 12% of an independent Code_Aster result.
  `building_02` solves with plausible magnitudes but has no reference, and
  `building_01` does not solve (singular stiffness matrix).
- **Slab results depend on mesh size.** Shells are linear triangles, which
  converge slowly: `structure_01` moves from 0.38 to 0.56 mm between a 1.0 m and
  a 0.25 m mesh. Check convergence before relying on a slab deflection.
- **Hinged slab edges are not modelled.** A slab sharing an edge with a wall is
  rigidly joined to it, and a line support ignores a release on the member
  side. `slab_01` is 2-3 times too stiff for this reason.
- **A single-axis end release is analysed as a full pin** (all three rotations
  released), with a warning.
- **I, T, L and C sections only work when every beam in the model has one.**
  These profiles are analysed with CalculiX U1 (Timoshenko) elements and a
  general section (`A`, `Iy`, `Iz`, shear factor). Stock CalculiX crashes when a
  U1 element shares a model with any other beam or shell element. A patched
  build runs, but transfers no moment between a U1 beam and a native beam at a
  shared node, so the joint behaves as a pin. Rectangular, circular, pipe and box
  sections use native B31 sections and do not have this problem.
- **Open-section approximations.** The general section has no product of inertia
  and no offset. `IfcAsymmetricIShapeProfileDef` has its flanges averaged, and
  L (angle) sections are analysed about their leg-parallel axes rather than
  their rotated principal axes.
- **No beam section forces or utilisation ratios yet.** `results.json` reports
  displacements, von Mises stress and total reactions. Per-member axial force,
  shear and moment are not available.
- **Reactions are a single total**, not one per load case.
- **Self-weight needs `--gravity`.** Models without an `IfcStructuralLoadCase`
  (`cantilever_01`, `slab_01`, `structure_01`, `grid_of_beams`) have no loads
  otherwise and return zero displacement.
- **Linear buckling** is validated for one Euler column only.
- **Members without an IFC `Axis`** are given a default section orientation,
  which for a non-square section may not be the one intended.

## Installation

### Prerequisites

Install these separately before installing this library:

- **Python 3.9 or later** (CI tests 3.9, 3.10 and 3.11)
- **CalculiX** (`ccx` executable) — finite element solver. The unmodified distribution package is the supported target
- **Gmsh with Python API** — mesh generation (`pip install gmsh`)
- **IfcOpenShell** — IFC file parsing (`pip install ifcopenshell`)

### Install from Source

```bash
# Clone the repository (including example models submodule)
git clone --recurse-submodules https://github.com/brunopostle/ifc_structural_mechanics.git
cd ifc_structural_mechanics

# Or if you already cloned without submodules:
# git submodule update --init --recursive

# Install in development mode
pip install -e .

# Install with development dependencies
pip install -e ".[dev]"

# Install visualization dependencies (PyVista — optional)
pip install -e ".[viz]"
```

## Usage

### Command Line Interface

```bash
# Basic analysis
ifc-analysis analyze model.ifc --output ./results

# Specify mesh size (in metres, default: 1.0)
ifc-analysis analyze model.ifc --output ./results --mesh-size 0.5

# Include self-weight gravity loads
ifc-analysis analyze model.ifc --output ./results --gravity

# Enable verbose output
ifc-analysis analyze model.ifc --output ./results --verbose

# Output results as JSON
ifc-analysis analyze model.ifc --output ./results --json-output
```

**Available Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--output DIR` | Output directory for analysis results (required) | — |
| `--analysis-type TYPE` | `linear_static` or `linear_buckling` | `linear_static` |
| `--mesh-size FLOAT` | Element size for mesh generation (metres) | `1.0` |
| `--gravity` | Include self-weight gravity loads | off |
| `--verbose` | Enable verbose logging | off |
| `--json-output` | Write results in JSON format | off |
| `--enhanced/--no-enhanced` | Use enhanced boundary condition handling | on |
| `--map-entities/--no-map-entities` | Map errors back to IFC entities | on |

### Python API

```python
from ifc_structural_mechanics.api.structural_analysis import run_enhanced_analysis

result = run_enhanced_analysis(
    ifc_path="path/to/model.ifc",
    output_dir="./results",
    analysis_type="linear_static",
    mesh_size=0.5,
    verbose=True,
    gravity=False,
)

if result["status"] == "success":
    print(f"Output files: {result['output_files']}")
else:
    print(f"Errors: {result['errors']}")
```

### Visualization

Results can be visualized using the `visualize.py` script. This requires PyVista (`pip install -e ".[viz]"`). Results must be in the `_analysis_output/<model_name>/` directory (the default output location when running the CLI).

```bash
# Visualize displacement (interactive, auto-scaled)
python visualize.py slab_01

# Visualize stress distribution
python visualize.py structure_01 --field stress

# Save screenshot (non-interactive)
python visualize.py portal_01 --screenshot result.png

# Custom displacement scale factor
python visualize.py beam_01 --scale 500

# Use a different output directory
python visualize.py mymodel --output-dir /path/to/results

# Export to interactive HTML
python visualize.py slab_01 --html slab_results.html
```

**Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--field {displacement,stress}` | Field to visualize | `displacement` |
| `--scale FACTOR` | Displacement scale factor | auto |
| `--step NAME` | Filter results to a specific load case / step name | all steps |
| `--screenshot FILE` | Save screenshot and exit | — |
| `--html FILE` | Export interactive HTML | — |
| `--output-dir DIR` | Override results directory | `_analysis_output/<model>` |
| `--no-undeformed` | Hide undeformed wireframe overlay | off |
| `--cmap COLORMAP` | Matplotlib colormap name | `jet` |

The script expects:
- IFC file at `examples/analysis-models/ifcFiles/<model_name>.ifc`
- Analysis results at `_analysis_output/<model_name>/analysis.frd` and `analysis.inp`

## Example Models

The repository includes example IFC structural models (as a git submodule in `examples/analysis-models/`):

| Model | Description | `--gravity` | Max displacement | Vertical reaction | Reference | Status |
|-------|-------------|-------------|------------------|-------------------|-----------|--------|
| `beam_01` | 4 m beam fixed at both ends, 20 kN at midspan | No | 0.26 mm (0.35 mm at a 0.05 m mesh) | 20.0 kN | 0.35 mm by hand | Verified |
| `cantilever_01` | 3 m cantilever, 0.2 × 0.4 m section, self-weight | **Yes** | 0.28 mm | 15 N of 18.4 N at this mesh | 0.277 mm Code_Aster, 0.281 mm by hand | Verified |
| `structure_01` | Slab on a wall and two columns, self-weight | **Yes** | 0.38 mm (0.47 mm at 0.5 m) | 632 N | 0.427 mm Code_Aster | Within 12% |
| `slab_01` | Slab on two line supports, self-weight | **Yes** | 0.06 mm (0.14 mm at 0.25 m) | 198 N | 0.376 mm Code_Aster | Too stiff: edge releases not modelled |
| `grid_of_beams` | Grid of beams, self-weight | **Yes** | 0.49 mm | 244 N | 0.396 mm Code_Aster | Does not converge with refinement |
| `portal_01` | Portal frame of I-sections, distributed load | No | 3.1 mm | 85.4 kN | none | Runs; unchecked |
| `building_02` | Multi-storey building, two load cases | No | 99 mm (Live), 252 mm (Extra_dead) | 29.4 MN | none | Runs; unchecked, mesh-sensitive |
| `building_01` | Multi-storey building, lateral loads | No | — | — | none | Fails: singular stiffness matrix |

Values are from the default 1.0 m mesh with CalculiX 2.23, measured on
2026-10-10. The Code_Aster references are the IfcOpenShell IFC2CA results
shipped in `examples/analysis-models/models/`. A coarse mesh under-predicts
deflection; use `--mesh-size` to refine.

To run an example:

```bash
# Model with explicit load cases — no --gravity needed
ifc-analysis analyze examples/analysis-models/ifcFiles/portal_01.ifc \
    --output _analysis_output/portal_01
python visualize.py portal_01

# Model with self-weight only — requires --gravity
ifc-analysis analyze examples/analysis-models/ifcFiles/slab_01.ifc \
    --output _analysis_output/slab_01 --gravity --mesh-size 0.5
python visualize.py slab_01
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ifc_structural_mechanics --cov-report=html

# Skip slow end-to-end tests
pytest -m "not slow"

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
pytest tests/validation/
```

## Development

```bash
# Install in development mode with all dependencies
pip install -e ".[dev]"

# Format code
black src/ tests/
isort src/ tests/

# Linting (all four must pass; CI pins the versions)
flake8 src/ tests/
ruff check src/ tests/

# Type checking (configured, not enforced in CI)
mypy src/
```

## Architecture

The analysis pipeline:

1. **IFC Extraction** — reads `IfcStructuralAnalysisModel` and related entities
2. **Domain Model** — language-neutral representation of members, connections, loads, sections
3. **Gmsh Meshing** — conforming finite element mesh (shared nodes at intersections)
4. **CalculiX Input** — writes `.inp` file with elements, boundary conditions, loads
5. **CalculiX Analysis** — runs `ccx` solver
6. **Results Parsing** — reads `.frd` and `.dat` output files

Each structural entity carries traceability fields (`ifc_guid`, `mesh_entity_ids`, `analysis_element_ids`) so that solver errors can be mapped back to the originating IFC entity.

## License

GPLv3 or later — see the LICENSE file for details.

## Disclaimer

The code in this project was primarily written using a large language model (LLM) as a development tool. While the code has been reviewed and tested against example models, users should exercise appropriate caution and independently verify results before using for any engineering purpose.

## Acknowledgments

- [IfcOpenShell](https://ifcopenshell.org/) for IFC processing
- [Gmsh](https://gmsh.info/) for mesh generation
- [CalculiX](http://www.calculix.de/) for finite element analysis
- [PyVista](https://pyvista.org/) for visualization
