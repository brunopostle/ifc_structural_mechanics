# IFC Structural Mechanics

Structural analysis for IFC that provides finite element analysis capabilities using CalculiX.

## Overview

IFC Structural mechanics provides structural analysis capabilities by leveraging existing IFC structural models and integrating with the open-source CalculiX finite element solver. The implementation provides a headless workflow for processing structural models, analyzing them using CalculiX, and storing results in a format compatible with both IFC and visualization tools like ParaView.

### Key Features

- Process structural analysis models from IFC files
- Transform IFC structural elements into CalculiX input format
- Execute CalculiX analysis as a subprocess
- Import analysis results back into the IFC model
- Store results in formats compatible with visualization tools

## Installation

### Prerequisites

- Python 3.8 or later
- CalculiX (CCX executable)
- Gmsh with Python API
- IfcOpenShell

### Install from Source

```bash
# Clone the repository
git clone https://github.com/brunopostle/ifc_structural_mechanics.git
cd ifc_structural_mechanics

# Install in development mode
pip install -e .

# Install development dependencies
pip install -e ".[dev]"
```

## Usage

Basic usage example:

```python
from ifc_structural_mechanics.api.structural_analysis import (
    load_ifc_model,
    run_analysis,
    export_results
)

# Load IFC model into domain model
model = load_ifc_model("path/to/model.ifc")

# Run analysis
results = run_analysis(
    model,
    analysis_type="linear_static",
    meshing_params={"element_size": 0.1}
)

# Export results to IFC and ParaView
export_results(
    results,
    ifc_output="path/to/results.ifc",
    paraview_output="path/to/results.vtk"
)
```

See the `examples/` directory for more detailed examples.

## Documentation

For complete documentation, visit [our documentation site](https://brunopostle.github.io/ifc_structural_mechanics).

## Development

### Setting Up Development Environment

```bash
# Install development dependencies
pip install -e ".[dev]"

# Install documentation dependencies
pip install -e ".[docs]"
```

### Running Tests

```bash
# Run all tests
pytest

# Run tests with coverage report
pytest --cov=ifc_structural_mechanics --cov-report=html
```

### Building Documentation

```bash
# Build documentation
mkdocs build

# Serve documentation locally
mkdocs serve
```

## License

This project is licensed under GPLv3 - see the LICENSE file for details.
