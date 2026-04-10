# IFC Structural Mechanics

A Python library for structural analysis of IFC (Industry Foundation Classes) building models using the CalculiX finite element solver.

> **Development Status**: This is early-stage, experimental software. It has been tested against a small set of example models and produces plausible results, but has known limitations described below. It is not suitable for production use without independent verification of results.

## Overview

IFC Structural Mechanics provides a workflow for performing structural analysis on IFC building models. The library extracts structural information from IFC files, generates finite element meshes using Gmsh, performs structural analysis with CalculiX, and provides tools for visualizing results.

### Capabilities

- **IFC Model Extraction**: Extract structural members (beams, columns, slabs, walls), connections, loads, and material/section properties from IFC files using `IfcStructuralAnalysisModel`
- **Automated Meshing**: Generate finite element meshes using Gmsh with conforming topology (shared nodes at member intersections)
- **Structural Analysis**: Linear static and linear buckling analysis using CalculiX (CCX)
- **Multiple Load Cases**: Each `IfcStructuralLoadCase` maps to a separate CalculiX `*STEP`; results are tagged with the load case name
- **Beam Sections**: Rectangular, circular, hollow circular (PIPE), and hollow rectangular (BOX/RHS) cross-sections extracted directly from IFC profile definitions
- **Connection End-Releases**: Rotational releases read from `IfcRelConnectsStructuralMember.AppliedCondition` and modelled as pinned connections
- **Result Visualization**: 3D visualization of deformed meshes and stress fields using PyVista; filter by load case with `--step`

### Known Limitations

This software is under active development. The following limitations are known:

- **Connection geometry**: Structural connections between members are resolved by geometric proximity (0.5 m tolerance) rather than using the `IfcRelConnectsStructuralMember` relationship topology defined in the IFC file. This can cause incorrect connectivity for closely spaced but unconnected members.
- **Overlapping members**: Members with identical or overlapping geometry may lose their physical group assignment during mesh fragmentation. Their sections will be skipped with a warning; a fallback assigns the nearest elements by spatial proximity (shared ownership).
- **Linear buckling**: The `linear_buckling` analysis type produces two CalculiX steps (static pre-stress + perturbation buckle) and parses eigenvalue multipliers from the `.dat` file, but results have not been validated against published benchmarks.
- **Section types**: Only rectangular, circular, pipe (hollow circle), and box (hollow rectangle) cross-sections are supported for CalculiX B31 beam elements. I-sections are approximated as equivalent rectangles preserving area and second moment of area.
- **Partial end-releases**: Connection end-releases read from `IfcRelConnectsStructuralMember.AppliedCondition` are modelled as full pins (all three rotational DOFs released). Partial releases — where only one member or one rotation axis is released — are not yet supported.

## Installation

### Prerequisites

Install these separately before installing this library:

- **Python 3.8 or later**
- **CalculiX** (`ccx` executable) — finite element solver
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
python visualize.py building_01a --field stress

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

| Model | Description | Status |
|-------|-------------|--------|
| `beam_01` | Simply supported beam, point load | Working |
| `cantilever_01` | Cantilever beam, gravity | Working |
| `portal_01` | Portal frame, distributed load | Working |
| `grid_of_beams` | Grid of beams, gravity | Working (near-zero reactions if no density in IFC) |
| `slab_01` | Flat slab, gravity | Working |
| `structure_01` | Mixed structure, gravity | Working |
| `building_01` | Multi-storey building, planar forces | Working |
| `building_02` | Larger multi-storey building | Working |

To run an example:

```bash
ifc-analysis analyze examples/analysis-models/ifcFiles/slab_01.ifc \
    --output _analysis_output/slab_01 --mesh-size 0.5
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

# Type checking
mypy src/

# Linting
flake8 src/
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
