# IFC Structural Mechanics

A comprehensive Python library for structural analysis of IFC (Industry Foundation Classes) building models using CalculiX finite element solver.

## Overview

IFC Structural Mechanics provides a complete workflow for performing structural analysis on IFC building models. The library extracts structural information from IFC files, generates finite element meshes using Gmsh, performs structural analysis with CalculiX, and processes results for visualization and further analysis.

### Key Features

- **IFC Model Extraction**: Extract structural members, connections, loads, and properties from IFC files
- **Automated Meshing**: Generate high-quality finite element meshes using Gmsh
- **Structural Analysis**: Perform linear static and linear buckling analysis using CalculiX
- **Result Processing**: Parse and process analysis results with error detection and mapping
- **Interactive Visualization**: 3D visualization of deformed meshes and stress fields using PyVista
- **Equilibrium Validation**: Automatic checking of load/reaction equilibrium
- **Flexible Configuration**: Comprehensive configuration system for analysis, meshing, and system settings
- **Command-Line Interface**: Easy-to-use CLI for batch processing and automation
- **Error Handling**: Robust error detection with mapping back to original IFC entities



## Installation

### Prerequisites

- Python 3.8 or later
- CalculiX (CCX executable)
- Gmsh with Python API
- IfcOpenShell

### Install from Source

```bash
# Clone the repository (including example models submodule)
git clone --recurse-submodules https://github.com/brunopostle/ifc_structural_mechanics.git
cd ifc_structural_mechanics

# Or if you already cloned without submodules:
# git submodule update --init --recursive

# Install in development mode
pip install -e .

# Install development dependencies
pip install -e ".[dev]"

# Install documentation dependencies
pip install -e ".[docs]"

# Install visualization dependencies
pip install -e ".[viz]"
```

## Usage

### Command Line Interface

The easiest way to perform structural analysis is through the command-line interface:

```bash
# Basic analysis (using installed command)
ifc-analysis analyze model.ifc --output ./results

# Or run as a module (useful for development)
python -m ifc_structural_mechanics.cli analyze model.ifc --output ./results

# Specify analysis type and mesh size
ifc-analysis analyze model.ifc --output ./results --analysis-type linear_static --mesh-size 0.2

# Enable verbose output and JSON results
ifc-analysis analyze model.ifc --output ./results --verbose --json-output
```

**Available Options:**
- `--output DIR`: Output directory for analysis results (required)
- `--analysis-type TYPE`: Analysis type: `linear_static` (default) or `linear_buckling`
- `--mesh-size FLOAT`: Element size for mesh generation (default: 0.1)
- `--verbose`: Enable verbose logging output
- `--json-output`: Write results in JSON format

### Python API

For programmatic use, the library provides a clean Python API:

```python
from ifc_structural_mechanics.api.structural_analysis import analyze_ifc

# Perform structural analysis
result = analyze_ifc(
    ifc_path="path/to/model.ifc",
    output_dir="./results",
    analysis_type="linear_static",
    mesh_size=0.1,
    verbose=True
)

# Check results
if result["status"] == "success":
    print("Analysis completed successfully!")
    print(f"Output files: {result['output_files']}")
else:
    print(f"Analysis failed: {result['errors']}")
```

### Advanced Usage

For more control over the analysis process:

```python
from ifc_structural_mechanics.api.structural_analysis import (
    extract_model,
    create_analysis_config,
    create_meshing_config
)
from ifc_structural_mechanics.config import SystemConfig
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    run_complete_analysis_workflow
)

# Extract structural model
model = extract_model("path/to/model.ifc")

# Create custom configurations
analysis_config = create_analysis_config("linear_static")
meshing_config = create_meshing_config(mesh_size=0.05)
system_config = SystemConfig()

# Run unified analysis workflow
inp_file = run_complete_analysis_workflow(
    domain_model=model,
    output_inp_file="./analysis.inp",
    analysis_config=analysis_config,
    meshing_config=meshing_config,
    system_config=system_config
)
```

### Visualization

#### Interactive Command-Line Tool

The easiest way to visualize results is with the interactive CLI tool:

```bash
# Visualize displacement (with auto-scaled deformation)
python visualize_interactive.py \
    examples/analysis-models/ifcFiles/building_01.ifc \
    ./results_building_01 \
    ./results_building_01/mesh_*.msh \
    --field displacement

# Visualize stress distribution
python visualize_interactive.py \
    model.ifc \
    ./results \
    ./results/mesh_*.msh \
    --field stress \
    --scale 10000

# Save screenshot instead of interactive view
python visualize_interactive.py \
    model.ifc \
    ./results \
    ./results/mesh_*.msh \
    --field displacement \
    --screenshot output.png
```

**Options:**
- `--field {displacement,stress}`: Choose what to visualize (default: displacement)
- `--scale FACTOR`: Displacement scale factor (auto-calculated if not specified)
- `--no-undeformed`: Hide undeformed mesh overlay
- `--screenshot FILE`: Save screenshot and exit (non-interactive)
- `--time-step N`: Visualize specific time step (for multi-step analyses)

#### Python API

For programmatic use:

```python
from ifc_structural_mechanics.visualization import ResultVisualizer
from ifc_structural_mechanics.ifc.extractor import Extractor
from ifc_structural_mechanics.analysis.results_parser import ResultsParser

# Extract model and parse results
extractor = Extractor("model.ifc")
model = extractor.extract_model()

parser = ResultsParser(domain_model=model)
results = parser.parse_results({
    "results": "results/analysis.frd",
    "data": "results/analysis.dat"
})

# Create visualization
viz = ResultVisualizer(model)
viz.load_mesh_from_file("results/mesh.msh")

# Auto-calculate scale factor for visibility
displacements = results['displacement']
max_disp = max(d.get_magnitude() for d in displacements)
scale_factor = 0.01 / max_disp  # ~1% of model size

viz.apply_displacement_field(scale_factor=scale_factor)

# Show displacement or stress
viz.plot_deformed(field='Displacement', show_undeformed=True)

# Or show stress
viz.add_stress_field()
viz.plot_deformed(field='Von Mises Stress', show_undeformed=True)

# Or export to HTML
viz.export_to_html("results.html")
```

**Visualization Features:**
- Interactive 3D deformed mesh with rotation, zoom, pan
- Color-coded displacement magnitude visualization
- Von Mises stress distribution with proper element-to-node mapping
- Side-by-side undeformed/deformed mesh comparison
- Auto-scaling for tiny displacements (typical in building structures)
- Export to HTML for sharing
- Save high-resolution screenshots
- Multiple time step/load case support

**Installation:**
```bash
pip install -e ".[viz]"
```

## Configuration

The library uses a comprehensive configuration system with three main configuration classes:

### Analysis Configuration
```python
from ifc_structural_mechanics.config import AnalysisConfig

config = AnalysisConfig()
config.set_analysis_type("linear_static")
config.set_solver_params({"max_iterations": 200})
```

### Meshing Configuration
```python
from ifc_structural_mechanics.config import MeshingConfig

config = MeshingConfig()
config.set_element_size("curve_members", 0.1)
config.set_element_type("surface_members", "2D_linear_triangle")
```

### System Configuration
```python
from ifc_structural_mechanics.config import SystemConfig

config = SystemConfig()
calculix_path = config.get_calculix_path()
gmsh_path = config.get_gmsh_path()
```

## Supported Analysis Types

- **Linear Static**: Standard linear static structural analysis
- **Linear Buckling**: Linear buckling analysis for stability assessment

## Error Handling and Debugging

The library provides comprehensive error handling with mapping back to original IFC entities:

```python
result = analyze_ifc("model.ifc", "./results")

# Check for errors
if result["errors"]:
    for error in result["errors"]:
        print(f"Error: {error['message']}")
        if error.get("domain_id"):
            print(f"Related to entity: {error['entity_type']} {error['domain_id']}")

# Check for warnings
if result["warnings"]:
    for warning in result["warnings"]:
        print(f"Warning: {warning['message']}")
```

## Testing

Run the test suite:

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ifc_structural_mechanics --cov-report=html

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
```

## Development

### Setting Up Development Environment

```bash
# Install in development mode with all dependencies
pip install -e ".[dev,docs]"

# Run code formatting
black src/ tests/
isort src/ tests/

# Run type checking
mypy src/

# Run linting
flake8 src/
```

### Building Documentation

```bash
# Build documentation
mkdocs build

# Serve documentation locally
mkdocs serve
```



## Contributing

We welcome contributions! Please see our contributing guidelines and submit pull requests for any improvements.

## License

This project is licensed under GPLv3 or later - see the LICENSE file for details.

## Disclaimer

The code in this project was primarily written using a large language model (LLM) as a development tool. While the code has been reviewed and tested, users should be aware of this development approach and exercise appropriate caution when using the software for critical applications.

## Acknowledgments

- Built on top of IfcOpenShell for IFC processing
- Uses Gmsh for mesh generation
- Integrates with CalculiX for finite element analysis
- Inspired by the open-source structural analysis community