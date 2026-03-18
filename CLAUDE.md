# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IFC Structural Mechanics is a Python library for structural analysis of IFC (Industry Foundation Classes) building models using the CalculiX finite element solver. The library extracts structural information from IFC files, generates finite element meshes using Gmsh, and performs structural analysis.

## Common Commands

### Development Setup
```bash
# Install in development mode with all dependencies
pip install -e ".[dev]"

# Install visualization dependencies (optional)
pip install -e ".[viz]"
```

### Testing
```bash
# Run all tests
pytest

# Skip slow end-to-end tests (building_01a etc.)
pytest -m "not slow"

# Run with coverage
pytest --cov=ifc_structural_mechanics --cov-report=html

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
pytest tests/validation/

# Run a single test file
pytest tests/unit/ifc/test_entity_identifier.py

# Run a single test
pytest tests/unit/ifc/test_entity_identifier.py::TestClassName::test_method_name
```

### Code Quality
```bash
# Format code
black src/ tests/
isort src/ tests/

# Linting (flake8 config in .flake8: max-line-length=88, extend-ignore=E203,E501)
flake8 src/ tests/

# Fast linting + unused import detection
ruff check src/ tests/

# Type checking
mypy src/
```

### Running Analysis
```bash
# Basic analysis using CLI (installed command)
ifc-analysis analyze model.ifc --output ./results

# Or run as a module (useful for development)
python -m ifc_structural_mechanics.cli analyze model.ifc --output ./results

# Specify analysis type and mesh size
ifc-analysis analyze model.ifc --output ./results --analysis-type linear_static --mesh-size 0.2

# Enable verbose output and JSON results
ifc-analysis analyze model.ifc --output ./results --verbose --json-output
```

### Visualization
```bash
# Visualize displacement results (auto-scales)
python visualize.py building_01a

# Visualize stress results
python visualize.py slab_01 --field stress

# Save screenshot (non-interactive)
python visualize.py building_01a --screenshot result.png

# Custom scale factor
python visualize.py portal_01 --scale 500
```

## Architecture Overview

### Core Data Flow
The analysis follows a unified pipeline with embedded traceability:
1. **IFC Extraction** → 2. **Domain Model** → 3. **Gmsh Meshing** → 4. **Unified CalculiX Writer** → 5. **CalculiX Analysis** → 6. **Results Parsing**

This is implemented as: `IFC File → Extractor → StructuralModel → Gmsh → UnifiedCalculixWriter → CalculiX Input File`

**Traceability Chain**: Each entity maintains its lineage for error propagation:
- IFC GlobalId → Domain Entity (`ifc_guid`) → Mesh Entity IDs (`mesh_entity_ids`) → Analysis Element IDs (`analysis_element_ids`)
- Errors from CalculiX can be traced back to the originating IFC entity via `StructuralModel.trace_error_to_ifc()`

### Key Architectural Components

#### 1. Domain Model (`src/ifc_structural_mechanics/domain/`)
The core structural representation independent of IFC or FEA formats:
- `StructuralModel`: Container for all structural elements, connections, loads, and results. **Maintains reverse lookup indices for error traceability** (`analysis_element_to_member`, `mesh_entity_to_member`, etc.)
- `StructuralMember`: Base class with `CurveMember` (beams, columns) and `SurfaceMember` (slabs, walls) subclasses. **Each member carries traceability fields**: `ifc_guid`, `mesh_entity_ids`, `analysis_element_ids`
- `StructuralConnection`: Various connection types (point, rigid, hinge, spring). **Each connection carries traceability fields**: `ifc_guid`, `mesh_entity_ids`, `analysis_element_ids`
- `Load`: Load definitions and load groups/combinations
- `Property`: Material and section properties

#### 2. IFC Extraction (`src/ifc_structural_mechanics/ifc/`)
Extracts structural information from IFC files:
- `Extractor`: Main coordinator that orchestrates extraction using specialized extractors
- `MembersExtractor`: Extracts curve and surface structural members
- `ConnectionsExtractor`: Extracts structural connections with stiffness properties
- `LoadsExtractor`: Extracts loads, load groups, and load combinations
- `PropertiesExtractor`: Extracts material and section properties
- `entity_identifier.py`: Utilities for identifying and classifying IFC structural entities
- `geometry/`: Handles geometric extraction for curves, surfaces, and topology

#### 3. Converters (`src/ifc_structural_mechanics/converters/`)
Stateless utility functions for type conversions:
- `calculix_types.py`: Pure functions for element type mapping (Gmsh → CalculiX), error parsing, etc.

**Note**: The old `mapping/` module has been removed. Traceability is now embedded directly in domain entities via their `ifc_guid`, `mesh_entity_ids`, and `analysis_element_ids` fields. The `StructuralModel` maintains reverse lookup indices for error propagation.

#### 4. Meshing (`src/ifc_structural_mechanics/meshing/`)
Generates finite element meshes:
- `unified_calculix_writer.py`: **THE UNIFIED SOLUTION** - Single tool for writing CalculiX input files. This replaces dual systems and eliminates element writing conflicts. **Registers analysis element IDs** in domain model via `StructuralModel.register_analysis_elements()`
- `gmsh_runner.py`: Executes Gmsh to generate meshes. Outputs `.msh` mesh files (not `.geo` script files).
- `gmsh_geometry.py`: Creates Gmsh geometry from domain model using **conforming meshes via shared topology**. Uses a shared point registry and `gmsh.model.occ.fragment()` so connected members share mesh nodes automatically. **Registers mesh entity IDs** in domain model via `StructuralModel.register_mesh_entities()`
- `gmsh_utils.py`: Gmsh utility functions

**Conforming Mesh Pipeline** (`gmsh_geometry.py` `convert_model()`):
1. Create all geometry with shared points (no per-member synchronize)
2. Call `fragment()` separately for curves and surfaces (separate point registries to avoid CalculiX KNOT generation when beam and shell elements share nodes)
3. Single `synchronize()` call
4. Remap entity tags after fragmentation
5. Apply mesh sizes (minimum size for shared points)
6. Create Gmsh physical groups — each member's geometry entities get a numbered physical group named by member ID, so mesh elements inherit their parent member identity

**Element-to-Member Mapping** (`unified_calculix_writer.py`):
- Uses `cell_data['gmsh:physical']` from meshio to correctly assign mesh elements to their parent structural members via `_map_elements_via_physical_groups()`
- Falls back to spatial centroid matching for members whose geometry was merged during fragment (overlapping members)
- **Important**: The old naive `_distribute_elements_to_members()` (round-robin assignment) is kept only as a last-resort fallback — it produces incorrect spatial mapping for multi-member models

**Note**: The workflow uses Gmsh's `.msh` mesh format exclusively. `.geo` geometry script files are not used in production as they may have XAO dependencies in newer Gmsh versions.

#### 5. Analysis (`src/ifc_structural_mechanics/analysis/`)
Runs CalculiX and processes results:
- `calculix_runner.py`: Executes CalculiX solver
- `results_parser.py`: Parses CalculiX result files (`.frd`, `.dat`). Uses `_parse_frd_data_line()` for fixed-width FRD column parsing (node ID in chars 3-12, values in 12-char columns). Handles values that run together without spaces.
- `output_parser.py`: Parses CalculiX output for errors/warnings and convergence
- `file_writers.py`: Utilities for writing various analysis files
- `boundary_condition_handling.py`: Handles boundary conditions and analysis steps

#### 5a. Visualization (`src/ifc_structural_mechanics/visualization/`)
Interactive 3D result visualization using PyVista:
- `result_visualizer.py`: `ResultVisualizer` class that loads mesh from FRD+INP files, maps displacement/stress results to mesh nodes via coordinate-based KDTree matching, and renders with PyVista. Displacement field displayed in mm.

#### 6. Configuration (`src/ifc_structural_mechanics/config/`)
Configuration system with three main classes:
- `AnalysisConfig`: Analysis type (linear_static, linear_buckling), solver parameters
- `MeshingConfig`: Element sizes, element types per member type
- `SystemConfig`: Paths to external tools (CalculiX, Gmsh)

#### 7. API (`src/ifc_structural_mechanics/api/`)
Public-facing API for users:
- `structural_analysis.py`: Main entry point with `run_enhanced_analysis()` (preferred) and `analyze_ifc()` functions
- `structural_model.py`: Model extraction API

#### 8. CLI (`src/ifc_structural_mechanics/cli/`)
Command-line interface:
- `commands.py`: Click-based CLI implementation

### Critical Architectural Principles

1. **Unified CalculiX Writing**: The `UnifiedCalculixWriter` is the ONLY system that writes elements to CalculiX input files. Never create parallel element writing systems.

2. **Domain Model as Hub**: All conversions flow through the domain model. IFC → Domain → Gmsh → CalculiX. The domain model is the single source of truth.

3. **Embedded Traceability**:
   - Each domain entity (`StructuralMember`, `StructuralConnection`) carries its own traceability fields: `ifc_guid`, `mesh_entity_ids`, `analysis_element_ids`
   - `StructuralModel` maintains reverse lookup indices for O(1) error mapping
   - No separate mapping files or mapper objects - traceability is part of the domain model itself
   - Use `StructuralModel.register_mesh_entities()` and `StructuralModel.register_analysis_elements()` to record relationships
   - Use `StructuralModel.trace_error_to_ifc()` to map CalculiX errors back to IFC GUIDs

4. **Separation of Concerns**:
   - IFC module: Only knows about IFC and domain models
   - Meshing module: Only knows about domain models and FEA formats
   - Converters module: Stateless type conversion utilities

5. **Error Handling**: Custom exceptions in `utils/error_handling.py` (`StructuralAnalysisError`, `ModelExtractionError`, `MeshingError`, `AnalysisError`) maintain context through the pipeline.

## Common Development Patterns

### Adding a New Member Type
1. Extend `StructuralMember` in `domain/structural_member.py` - make sure to pass `ifc_guid` to parent `__init__`
2. Add extraction logic in `ifc/members_extractor.py` - extract and pass `ifc_guid` from IFC entity
3. Update `entity_identifier.py` to recognize the type
4. Add geometry conversion in `gmsh_geometry.py` - call `register_mesh_entities()` after creating Gmsh entities
5. Update `UnifiedCalculixWriter` element type mappings if needed - call `register_analysis_elements()` after distributing elements

### Adding a New Analysis Type
1. Add analysis type definition in `config/analysis_config.py` (`ANALYSIS_TYPES`)
2. Update `analysis/boundary_condition_handling.py` for analysis step writing
3. Update CLI choices in `cli/commands.py`
4. Add tests in `tests/unit/config/test_analysis_config.py`

### Adding a New Load Type
1. Extend `Load` class in `domain/load.py`
2. Add extraction in `ifc/loads_extractor.py`
3. Update boundary condition writing in `analysis/boundary_condition_handling.py`

## Testing Strategy

- **Unit tests** (`tests/unit/`): Test individual classes/functions in isolation with mocks
- **Integration tests** (`tests/integration/`): Test workflows across multiple modules with real IFC files
  - `test_ifc_to_geo.py`: Tests IFC → Gmsh mesh conversion, outputs `.msh` files for inspection
  - `test_building_analysis.py`, `test_physical_group_mapping.py`, etc.: Regression tests for mesh connectivity fixes
- **Validation tests** (`tests/validation/`): Numerical accuracy tests against analytical solutions
  - Tier 1: Direct CalculiX input/output tests
  - Tier 2: Full pipeline tests (IFC → results)
- **Test data**: Located in `tests/test_data/`
- **Fixtures**: Common test fixtures in `tests/conftest.py`
- **Slow tests**: End-to-end building model tests are marked `@pytest.mark.slow`. Skip with `-m "not slow"`.

### Note on Gmsh File Formats
- **`.msh` format (preferred)**: Mesh files used in the production workflow. Fully supported, no external dependencies.
- **`.geo` format**: Gmsh geometry scripts. Modern Gmsh versions may create `.geo_unrolled` files with XAO references that require OpenCASCADE support for reading. Use `.msh` format for testing and inspection instead.

## Dependencies

### External Tools (must be installed separately)
- CalculiX (CCX executable) - finite element solver
- Gmsh (with Python API) - mesh generation
- IfcOpenShell - IFC file parsing

### Python Packages
Core: numpy, scipy, ifcopenshell, gmsh, meshio, click, pyyaml, pandas
Visualization: pyvista (optional, for result visualization)
Dev: pytest, pytest-cov, black, isort, flake8, ruff, mypy

## Key File Locations

- Entry point script: `src/ifc_structural_mechanics/cli/__init__.py`
- Main API: `src/ifc_structural_mechanics/api/structural_analysis.py`
- Unified workflow: `src/ifc_structural_mechanics/meshing/unified_calculix_writer.py`
- Configuration: `src/ifc_structural_mechanics/config/`
- Traceability: `src/ifc_structural_mechanics/domain/structural_model.py` (see `register_*` and `trace_error_to_ifc` methods)
- Type converters: `src/ifc_structural_mechanics/converters/calculix_types.py`
- Result visualization: `src/ifc_structural_mechanics/visualization/result_visualizer.py`
- Visualization CLI: `visualize.py` (general-purpose: any model, displacement/stress, screenshot/interactive)
- FRD-only visualization: `visualize_from_frd.py` (reads mesh+results directly from FRD, no IFC needed)
- Test utilities: `tests/conftest.py`

## Code Style

- Line length: 88 characters (Black default)
- Python versions: 3.8, 3.9, 3.10
- Type hints: Required for public APIs (enforced by mypy)
- Docstrings: Required for all public classes and functions (Google style)
- Import order: isort with Black profile
- Linting: flake8 config in `.flake8` (max-line-length=88, extend-ignore=E203,E501); ruff for additional checks
- All four tools must pass cleanly: `black`, `isort`, `flake8`, `ruff`

## Working with IFC Files

IFC entities commonly encountered:
- `IfcStructuralAnalysisModel`: Top-level structural model container
- `IfcStructuralCurveMember`: Beams, columns, braces (1D elements)
- `IfcStructuralSurfaceMember`: Slabs, walls, shells (2D elements)
- `IfcStructuralPointConnection`: Point supports/connections
- `IfcStructuralCurveConnection`: Line supports
- `IfcStructuralSurfaceConnection`: Surface supports
- `IfcStructuralLoadGroup`: Groups loads by load case
- `IfcStructuralLoadCase`: Specific load cases

Use `entity_identifier.py` functions to classify IFC entities rather than direct `is_a()` checks.

## Debugging Tools for LLM Agents

Two CLI query tools are provided so that an LLM agent can inspect analysis files without parsing raw binary or fixed-width formats directly.

### `ccxquery` — Query CalculiX files (`.inp`, `.frd`, `.dat`)

```bash
# Overview of a CalculiX input or result file
python -m ccxquery analysis.inp summary
python -m ccxquery analysis.frd summary

# Inspect mesh: node/element sets, materials, sections, boundary conditions, loads
python -m ccxquery analysis.inp sets
python -m ccxquery analysis.inp materials
python -m ccxquery analysis.inp sections
python -m ccxquery analysis.inp bcs
python -m ccxquery analysis.inp loads

# Inspect results
python -m ccxquery analysis.frd results
python -m ccxquery analysis.frd displacements
python -m ccxquery analysis.frd stresses
python -m ccxquery analysis.dat reactions

# Find a specific node
python -m ccxquery analysis.frd node 42
python -m ccxquery analysis.inp nodes-at 1.0 2.5 0.0

# Check if analysis completed successfully
python -m ccxquery analysis.dat status
```

### `mshquery` — Query Gmsh mesh files (`.msh`)

```bash
# Overview: node/element counts, physical groups, bounding box
python -m mshquery mesh.msh summary

# Physical groups (member ID → element count mapping)
python -m mshquery mesh.msh groups

# Inspect a specific node or element
python -m mshquery mesh.msh info 42

# Filter nodes/elements
python -m mshquery mesh.msh select --near 1.0 2.5 0.0 --radius 0.5
```

Both tools are located in `src/ccxquery/` and `src/mshquery/` and have their own `pyproject.toml`. They share no code with the main library — their FRD/DAT parsing is an independent implementation.

## Temporary Files

The system uses `utils/temp_dir.py` for managing temporary files during analysis. Temporary files are automatically cleaned up unless `set_keep_temp_files(True)` is called (useful for debugging).

## Known Limitations

- **Load cases**: Only a subset of IFC load cases may be written to the INP. Models with multiple `IfcStructuralLoadCase` (e.g., Dead, Live, Wind, Earthquake) may only get some cases applied. Each load case should ideally map to a separate `*STEP`.
- **Connection geometry**: Structural connections are resolved by geometric proximity (0.5 m tolerance in `_find_connection_nodes_at_location()`) rather than using the `IfcRelConnectsStructuralMember` relationship topology from the IFC file. This can cause incorrect connectivity for closely spaced but unconnected members.
- **Overlapping members**: Members with identical geometry (e.g., a short beam inside a longer beam) may lose their physical group during `fragment()`. These are logged as warnings and their loads/sections are skipped.
- **FRD/DAT parsing duplication**: `results_parser.py` and `ccxquery/parsers/` independently implement the same FRD/DAT parsing logic. `ccxquery` is intentionally standalone (a debugging tool for LLM agents), so this duplication is by design.
- **Linear buckling**: The `linear_buckling` analysis type exists in the CLI but has not been validated against known solutions.
