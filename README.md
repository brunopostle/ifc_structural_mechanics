# IFC Structural Mechanics

A Python library for structural analysis of IFC (Industry Foundation Classes) building models using the CalculiX finite element solver.

> **Development Status**: This is early-stage, experimental software. It has been tested against a small set of example models and produces plausible results, but has known limitations described below. It is not suitable for production use without independent verification of results.

See [VISION.md](VISION.md) for the project roadmap and intended architecture.
See [docs/validation_report.md](docs/validation_report.md) for numerical accuracy benchmarks.

## Overview

IFC Structural Mechanics provides a workflow for performing structural analysis on IFC building models. The library extracts structural information from IFC files, generates finite element meshes using Gmsh, performs structural analysis with CalculiX, and provides tools for visualizing results.

### Capabilities

- **IFC Model Extraction**: Extract structural members (beams, columns, slabs, walls), connections, loads, and material/section properties from IFC files using `IfcStructuralAnalysisModel`
- **Automated Meshing**: Generate finite element meshes using Gmsh with conforming topology (shared nodes at member intersections). Elements are quadratic by default: three-node beams (B32R) and six-node triangular shells (S6)
- **Structural Analysis**: Linear static and linear buckling analysis using CalculiX (CCX)
- **Multiple Load Cases**: Each `IfcStructuralLoadCase` maps to a separate CalculiX `*STEP`; results are tagged with the load case name
- **Beam Sections**: Rectangular, circular, hollow circular (PIPE), and hollow rectangular (BOX/RHS) cross-sections map to native CalculiX beam sections; I, T, L (angle), and C (channel) profiles are analysed via CalculiX U1 (Timoshenko) elements using a computed general section (`A`, `Iy`, `Iz`, shear factor). Sections are oriented by `IfcStructuralCurveMember.Axis`, with the profile depth along the member's local z
- **Supports and Releases**: Support conditions are read in the connection's own axes (a line support's `drx` is rotation about its edge). Rotational releases from `IfcRelConnectsStructuralMember.AppliedCondition` become pinned member ends, hinged edges between a slab and a wall, a support that leaves the released rotations free, or a hinge about one or two axes; an eccentric member end is hinged where it ends, on a rigid lever arm
- **Result Visualization**: 3D visualization of deformed meshes and stress fields using PyVista; filter by load case with `--step`

### Known Limitations

Open bugs and planned work are tracked in the project's `bd` (beads) issue
database; `bd list --status=open` shows the current list. The points below are
the ones a user needs to know before trusting a result.

- **Large models are only partly verified.** `structure_01` (slab, wall and two
  columns) is within 2% of an independent Code_Aster result. `building_02`
  solves but has no reference, and `building_01` does not solve (singular
  stiffness matrix).
- **Large models are slow and still mesh-sensitive.** `building_02` takes about
  200 s and 1.8 GB at a 2 m mesh, and needs more than 5 GB at 1 m. Its
  deflections still move 15-35% between a 4 m and a 2 m mesh. `--element-order 1`
  switches to linear elements, which are faster but several times too stiff in
  slab bending at these mesh sizes.
- **End releases on I, T, L and C members are analysed as full pins** (all
  three rotations released), with a warning. For other sections a release about
  one or two axes is modelled as given.
- **Skew supports are not modelled.** A support that restrains only some
  directions, in axes that are not parallel to the global ones, is analysed as
  if its axes were global, with a warning.
- **I, T, L and C sections only work when every beam in the model has one.**
  These profiles are analysed with CalculiX U1 (Timoshenko) elements and a
  general section (`A`, `Iy`, `Iz`, shear factor). Stock CalculiX crashes when a
  U1 element shares a model with any other beam or shell element. A patched
  build runs, but transfers no moment between a U1 beam and a native beam at a
  shared node, so the joint behaves as a pin. Rectangular, circular, pipe and box
  sections use native beam sections and do not have this problem.
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
| `--element-order [1\|2]` | `2`: quadratic elements (B32R, S6). `1`: linear (B31, S3), faster but needs a much finer mesh for slabs | `2` |
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
| `beam_01` | 4 m beam fixed at both ends, 20 kN at midspan | No | 0.34 mm (0.35 mm at a 0.05 m mesh) | 20.0 kN | 0.35 mm by hand | Verified |
| `cantilever_01` | 3 m cantilever, 0.2 × 0.4 m section, self-weight | **Yes** | 0.28 mm | 17.3 N of 18.4 N at this mesh | 0.277 mm Code_Aster, 0.281 mm by hand | Verified |
| `structure_01` | Slab hinged on a wall, two columns, self-weight | **Yes** | 0.429 mm (0.433 mm at 0.5 m) | 651 N of 660 N | 0.427 mm Code_Aster | Verified, within 2% |
| `slab_01` | Slab clamped along two edges, self-weight | **Yes** | 0.173 mm (0.181 mm at 0.5 m) | 220 N of 230 N | 0.181 mm by hand | Verified; the Code_Aster file is for other supports |
| `grid_of_beams` | Secondary beams hinged onto two main beams, self-weight | **Yes** | 0.372 mm (0.373 mm at 0.5 m) | 266 N of 273 N | 0.396 mm Code_Aster, 0.367 mm without its spurious arm weight | Verified, within 2% |
| `portal_01` | Portal frame of I-sections, distributed load | No | 3.8 mm (4.1 mm at 0.25 m) | 85.4 kN | none | Runs; unchecked |
| `building_02` | Multi-storey building, two load cases | No | 462 mm (Live), 457 mm (Extra_dead) at a 2 m mesh | 29.4 MN | none | Runs; unchecked, mesh-sensitive |
| `building_01` | Multi-storey building, lateral loads | No | — | — | none | Fails: singular stiffness matrix |

Values are from the default 1.0 m mesh (2 m for `building_02`, which does not
fit in 5 GB of memory at 1 m) with CalculiX 2.23 and quadratic elements,
measured on 2026-10-10. The Code_Aster references are the IfcOpenShell IFC2CA
results shipped in `examples/analysis-models/models/`. The reported reaction
leaves out the share of a distributed load that lands on the restrained nodes
themselves, so it approaches the true weight as the mesh is refined.

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
