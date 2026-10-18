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

# Skip slow end-to-end tests (building_02)
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

# Linear elements (B31, S3) instead of the default quadratic ones (B32R, S6)
ifc-analysis analyze model.ifc --output ./results --element-order 1

# Only the connections in the IFC file (no implied beam-to-slab ties)
ifc-analysis analyze model.ifc --output ./results --strict-connections

# CalculiX U1 elements for I/T/L/C/round/hollow sections (models of those only)
ifc-analysis analyze model.ifc --output ./results --open-sections user-element

# Natural frequencies and mode shapes (mass from the materials only)
ifc-analysis analyze model.ifc --output ./results --analysis-type modal --modes 12

# Enable verbose output and JSON results
ifc-analysis analyze model.ifc --output ./results --verbose --json-output
```

### Visualization
```bash
# Visualize displacement results (auto-scales)
python visualize.py building_02

# Visualize stress results
python visualize.py slab_01 --field stress

# Save screenshot (non-interactive)
python visualize.py building_02 --screenshot result.png

# Custom scale factor
python visualize.py portal_01 --scale 500

# A mode shape of a modal or buckling analysis
python visualize.py beam_01 --mode 2
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
- `entity_identifier.py`: Utilities for identifying and classifying IFC structural entities

#### 3. Converters (`src/ifc_structural_mechanics/converters/`)
Stateless functions that turn domain properties into what the solver needs:
- `section_profiles.py`: equivalent rectangles for sections that are not solid rectangles (see Beam Section Orientation)

**Note**: The old `mapping/` module has been removed. Traceability is now embedded directly in domain entities via their `ifc_guid`, `mesh_entity_ids`, and `analysis_element_ids` fields. The `StructuralModel` maintains reverse lookup indices for error propagation.

#### 4. Meshing (`src/ifc_structural_mechanics/meshing/`)
Generates finite element meshes:
- `unified_calculix_writer.py`: **THE UNIFIED SOLUTION** - Single tool for writing CalculiX input files. This replaces dual systems and eliminates element writing conflicts. **Registers analysis element IDs** in domain model via `StructuralModel.register_analysis_elements()`
- `gmsh_runner.py`: Executes Gmsh to generate meshes. Outputs `.msh` mesh files (not `.geo` script files).
- `gmsh_geometry.py`: Creates Gmsh geometry from domain model using **conforming meshes via shared topology**. Uses a shared point registry and `gmsh.model.occ.fragment()` so connected members share mesh nodes automatically. **Registers mesh entity IDs** in domain model via `StructuralModel.register_mesh_entities()`
- `mesh_mapper.py`: Assigns mesh elements to members from the physical groups

**Conforming Mesh Pipeline** (`gmsh_geometry.py` `convert_model()`):
1. Create all geometry with shared points (no per-member synchronize)
2. Call `fragment()` separately for curves and surfaces, so beams share nodes with beams and shells with shells. Support points on beam interiors and connection points landing on a slab are passed as fragment tools so the mesh has a node there, and so are line connections joining a beam and a slab, which are meshed node for node with the beam. Beam and shell nodes are joined later, in the writer (see Connections)
3. Single `synchronize()` call
4. Remap entity tags after fragmentation
5. Apply mesh sizes (minimum size for shared points)
6. Create Gmsh physical groups — each member's geometry entities get a numbered physical group named by member ID, so mesh elements inherit their parent member identity

**Element order**: the mesh is second order by default (`MeshingConfig.get_element_order()`,
`--element-order`), giving `B32R` beams and `S6` shells. Linear `S3` shells are several
times too stiff in bending at practical mesh sizes; do not go back to them to save time
without saying so in the results. Two things follow from the middle nodes:

- Gmsh lists a three-node line as (start, end, middle); CalculiX wants (start, middle,
  end). `_process_mesh()` reorders them. Six-node triangles need no change.
- U1 is a two-node element, so `_split_quadratic_u1_elements()` turns each three-node
  line of a U1 member into two elements.

**Element-to-Member Mapping** (`unified_calculix_writer.py`):
- Uses `cell_data['gmsh:physical']` from meshio to correctly assign mesh elements to their parent structural members via `_map_elements_via_physical_groups()`
- **Members that overlap** (a short beam lying inside a longer one, a landing in a floor slab; `building_01` has both) share geometry entities after `fragment()`, over the whole of both or a part. `_create_physical_groups()` groups entities by the set of members they belong to and names the group `A||B`; `MeshMapper` gives the elements to each, and `_resolve_overlapping_element_sets()` keeps them for the first in the file, with a warning. `_geometry_element_sets` remembers what lies in each member's geometry: `_find_connection_nodes_at_location()` goes by it, so a member with no elements of its own is still joined where it ends
- **A member is never given elements by how near they are** (`aiz.87`). A fallback once gave an overlapped member every element within a ball around its middle: in `building_01` that took the last element of four beams framing in beside it, and their ends were left out of their joints without a word. A member with no elements in the mesh raises `MeshingError`, and so does a curve member with no node at one of its connections (`_check_members_reach_their_connections()`)
- **Important**: a mesh with no physical groups can only be attributed when the model has one member of each kind; with more, `MeshMapper` raises `MeshingError`. The old round-robin assignment dealt elements out wherever they were; do not bring it back

**Note**: The workflow uses Gmsh's `.msh` mesh format exclusively. `.geo` geometry script files are not used in production as they may have XAO dependencies in newer Gmsh versions.

#### 5. Analysis (`src/ifc_structural_mechanics/analysis/`)
Runs CalculiX and processes results:
- `calculix_runner.py`: Executes CalculiX solver
- `results_parser.py`: Parses CalculiX result files (`.frd`, `.dat`). `parse_element_nodes()` reads the FRD element block: CalculiX reports on the nodes of the solids it expands beams and shells into, numbered by the solver, and each solid keeps the number of the input element it came from. `ResultsExporter` attributes results to a member through those (member → `analysis_element_ids` → FRD nodes), never through mesh node numbers, except for elements the FRD does not list (U1). Uses `_parse_frd_data_line()` for fixed-width FRD column parsing (node ID in chars 3-12, values in 12-char columns). Handles values that run together without spaces.
- `output_parser.py`: Reads what CalculiX printed (`CalculixRunner.solver_output`): `check_convergence()` for whether it finished, `solver_warnings()` for its `*WARNING` blocks, each kind once with a count, which go into `result["warnings"]`. A warning caused by something the writer does on purpose is to be removed at the source (the rigid links have `*DENSITY 0.` for that), not filtered here
- `boundary_condition_handling.py`: Handles boundary conditions and analysis steps
- `superposition.py`: Results of a load combination from those of its load cases (see Load steps)
- `plane_structure.py`: Recognises plane trusses and frames and what holds them in their plane (see Connections)

#### 5a. Visualization (`src/ifc_structural_mechanics/visualization/`)
Interactive 3D result visualization using PyVista:
- `result_visualizer.py`: `ResultVisualizer` class that loads mesh from FRD+INP files, maps displacement/stress results to mesh nodes via coordinate-based KDTree matching, and renders with PyVista. Displacement field displayed in mm.

#### 6. Configuration (`src/ifc_structural_mechanics/config/`)
Configuration system with three main classes:
- `AnalysisConfig`: Analysis type (linear_static, linear_buckling, modal), solver parameters (`num_modes` for modal)
- `MeshingConfig`: Element sizes, element types per member type
- `SystemConfig`: Paths to external tools (CalculiX, Gmsh)

#### 7. API (`src/ifc_structural_mechanics/api/`)
Public-facing API for users:
- `structural_analysis.py`: Main entry point, `analyze_ifc()`. `results.json` (schema, versioning and changelog in `docs/results_schema.md`, example in `docs/examples/beam_01_results.json`) is the contract with other tools: bump `SCHEMA_VERSION` and add to the changelog when it changes, and regenerate the example. It returns `status: "failed"` with the error in `result["errors"]` for meshing, solver and result-reading failures, and raises `ModelExtractionError` for a file it cannot read

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

6. **Nothing is made up, and nothing is dropped quietly** (`aiz.12`, 2026-10-11). The risk in this tool is a wrong answer that looks right, so:
   - **Never substitute a default for something the file should give** (material, section, thickness, position, load value, load target). Raise the stage's error, with a message that names the entity and says what is missing. `MembersExtractor._create_member()`, `ConnectionsExtractor._create_domain_connection()` and `LoadsExtractor._create_domain_loads()` wrap every failure as "Member/Connection/Load <GlobalId> cannot be analysed. <reason>".
   - **Never leave an entity out and carry on.** A model with a member, support or load missing is another structure.
   - **`except Exception` may only re-raise as a typed error.** Put `except <TypedError>: raise` in front of it so an inner message is not wrapped twice. The only exceptions are cleanup (`gmsh.finalize()`, temp files, `__del__`). Results that cannot be read or exported fail the analysis (`ResultProcessingError`).
   - **An approximation the user did not ask for is a warning in the results**, not a log line: `_warn_user()` in the writer, `_warn_model()` in the load writer, `self.warnings` in the extractors (`Extractor._pass_on_warnings()` moves them to `model.analysis_warnings`). One warning for the whole model with a count and the first few ids, never one per member.
   - **Every warning and error has a code** (`94g.12`), `W-<stage>-<nnn>`, registered in `utils/messages.py` with a title and an explanation of what it means and what to do; `docs/messages.md` is generated from it and `tests/unit/utils/test_messages.py` fails if it is stale or a code is unregistered or unused. The call sites pass the code first (`_warn_user("W-SUP-001", ...)`, `_warn_model(model, "W-LOD-007", ...)`, `warning(code, ...)` in the extractors) and `ifc_guids=` with every entity concerned. Stages are grouped so related warnings sit together, numbered most likely first; a new kind takes the next number of its stage, and a code is never renumbered or reused: one no longer given stays registered with `retired=True` (its explanation says what replaced it), and the test fails if it is used. Errors have codes too, `E-<stage>-<nnn>`, in the same registry: every `raise` of a typed error passes `code=` (a wrapper passes on `code=error.code`), the code shows in `str(error)` and in `result["errors"]`, and the test fails on a raise without one. An error about particular entities passes `ifc_guids=` as well (the extractor wrappers add their entity's GlobalId to the inner error's), which goes into `result["errors"]`. A warning that says an entity was left out or something was assumed in its place is an error instead: a joint that joins nothing, a load in axes the item does not have. Regenerate the docs with `python -m ifc_structural_mechanics.utils.messages > docs/messages.md`.
   - **Mocks that say yes to everything hide this.** `mock.is_a.return_value = "IfcX"` makes `is_a("IfcEdge")` true, and a bare `MagicMock` has every attribute. Prefer real `ifcopenshell` entities (see `tests/unit/ifc/test_extraction_fails_loudly.py`), or give the mock a truthful `is_a` and a `spec`.
   - Do not add code paths that detect a test environment. `LoadsExtractor` once returned invented loads when its file was a mock.

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
  - Tier 1: Direct CalculiX input/output tests (hand-written `.inp`)
  - Tier 2: `test_pipeline_benchmarks.py` — full pipeline (IFC → results) against closed-form beam and plate theory and the Code_Aster references. Add a case here whenever a change touches sections, orientation, supports, joints, shells or loads
- **Test data**: Located in `tests/test_data/`
- **Fixtures**: Common test fixtures in `tests/conftest.py`
- **Slow tests**: End-to-end `building_02` tests are marked `@pytest.mark.slow` and share one analysis through the session fixture `building_02_run` in `tests/conftest.py` (about 6 minutes in total with its three load cases and 17 load combinations, and 2.3 GB of memory). Skip with `-m "not slow"`.

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
Dev: pytest, pytest-cov, black, isort, flake8, ruff (pinned), mypy

## Key File Locations

- Entry point script: `src/ifc_structural_mechanics/cli/__init__.py`
- Main API: `src/ifc_structural_mechanics/api/structural_analysis.py`
- Unified workflow: `src/ifc_structural_mechanics/meshing/unified_calculix_writer.py`
- Configuration: `src/ifc_structural_mechanics/config/`
- Traceability: `src/ifc_structural_mechanics/domain/structural_model.py` (see `register_*` and `trace_error_to_ifc` methods)
- Equivalent sections: `src/ifc_structural_mechanics/converters/section_profiles.py`
- Result visualization: `src/ifc_structural_mechanics/visualization/result_visualizer.py`
- Visualization CLI: `visualize.py` (general-purpose: any model, displacement/stress, screenshot/interactive)
- FRD-only visualization: `visualize_from_frd.py` (reads mesh+results directly from FRD, no IFC needed)
- Test utilities: `tests/conftest.py`
- Warning and error codes: `src/ifc_structural_mechanics/utils/messages.py` (list in `docs/messages.md`)

## Code Style

- Line length: 88 characters (Black default)
- Python versions: 3.9, 3.10, 3.11 (the CI matrix)
- Type hints: Required for public APIs. mypy is configured but not run in CI
- Docstrings: Required for all public classes and functions (Google style)
- Import order: isort with Black profile
- Linting: flake8 config in `.flake8` (max-line-length=88, extend-ignore=E203,E501); ruff rules are set in `pyproject.toml` (`E`, `F`, `W`; isort owns import order)
- All four tools must pass cleanly: `black`, `isort`, `flake8`, `ruff`. CI pins their versions in `.github/workflows/ci.yml`; use the same ones

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

**Everything an item gives is in the axes of its `ObjectPlacement`**: the points of its
representation, a member's `Axis`, a connection's `ConditionCoordinateSystem`, and the
forces of a load in `GLOBAL_COORDS`. `get_item_transformation(item, length_scale)`
returns the whole chain of placements with its offset in metres; apply it with
`transform_vectors()` to coordinates that are already in metres. No example model has a
placement away from the origin, so nothing but `tests/unit/ifc/test_object_placement.py`
and `TestPlacedModel` will tell you if a new extraction path forgets it (`aiz.57`: members
once added the offset in the file's unit, and supports and loads ignored it).

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

Open bugs and proposed work are tracked in beads (`bd list --status=open`), not
here. This section only records the constraints that shape day-to-day work.

- **Stock CalculiX is the target** (decision 2026-10-09). The local `ccx` may be
  a patched Copr build; CI runs Ubuntu's package (2.21) on three Python
  versions and conda-forge's 2.23 in a job of its own
  (`test-calculix-2-23`). Do not rely on the gen3delem patch in `patches/`.
- **Reactions are the solver's nodal forces less the loads applied at the
  support nodes** (`94g.1`). CalculiX's `RF` is the force inside the
  structure at a node: a load applied there in a restrained direction is
  missing from it and one in a free direction appears in it (measured).
  `write_analysis_steps()` records what each step puts on support nodes
  (`_StepLoadRecorder` reads the `*CLOAD` lines as they are written;
  `_weight_on_nodes()` gives the share of `*DLOAD GRAV`), and
  `ResultsExporter` takes it off. Reactions then equal the applied loads to
  six figures at any mesh size; `global_reactions` carries `applied_load_N`
  and `imbalance_N`.
- **The moments in `global_reactions` are added up from `supports`**
  (`94g.10`): each support's moments and its force at its position, about
  the origin of the global axes. The solver has no total moment, and the
  keys were zero in every model until schema 1.7. They are absent when a
  support has no moments. `write_analysis_steps()` records the moment of
  each step's loads about the origin (`StructuralModel.applied_load_moments`:
  every nodal force where it acts, and every moment applied), which is
  beside them as `applied_moment_Nm` with `moment_imbalance_Nm`. Measured:
  the two cancel to six figures or better in all eight example models
  (`building_01` `Dead`: 194 162 872 against 194 162 905 N·m), and on
  CalculiX 2.21 to 5 in 100 000 in `beam_01` and `portal_01`, where the
  forces come from the member ends.
- **CalculiX gives a node no reaction moment; its forces on the expanded
  nodes have it** (`94g.8`). `*NODE FILE` asks for `RF`, which puts the
  force on every node of the expanded solids in the FRD. The writer records
  every element at each support node, links and arms included
  (`_record_support_node_elements()`: the forces between the elements at a
  node only cancel when all are added); `parse_support_node_moments()` takes
  an expanded node for the node of its element it is nearest to and gives
  the moment of those forces about each support node; `_support_entry()`
  adds the lever arms of the nodal forces and takes off every moment
  applied at the node, shares of a moment per length too
  (`support_node_loads` has values 7 to 9 per node for that). Measured: a
  cantilever root, a slab clamped along one edge and a bar clamped along
  its span give statics to five figures at any mesh size, where member ends
  gave 0.1%. In a statically indeterminate model they are the mesh's own
  answer: `beam_01`'s fixing moment is 0.4% above beam theory at 0.5 m and
  0.1% at 0.1 m, and the moment at that end of the member's diagram agrees
  with it to 1 in 100 000 (`aiz.89`, below). CalculiX 2.21 has these forces wrong at a clamped member end
  only (the same as 2.23 on the slab edges, the wall foot and the grid),
  with the printed force wrong by as much, so the check on the forces
  covers the moments.
  `supports[].moments` is `"solver"` then. The section forces at the ends
  of the members (`_member_ends_at()`) remain the check on the solver's
  forces and the source (`"member_end_forces"`) where it got them wrong, or
  a node has a user element; `"not_computed"`, with the keys absent, only
  where neither can be had. A node whose expanded forces do not add up to
  the force printed for it gets no moment (the tolerance allows for six
  figures of a couple through a slab's thickness, which at a coarse mesh
  is far larger than the node's force).
- **CalculiX 2.21, Ubuntu 24.04's, misreports `RF` at a support that holds
  a rotation** (2.23 is right, stock as well as the Copr build;
  displacements are identical). The errors of two
  supports can cancel, so `ResultsExporter` checks each such support against
  its member ends (3%) and the whole against the applied load, replaces what
  it can (`forces: "member_end_forces"`), and
  `plausibility.balance_warnings()` says so. 2.21 is wrong at clamped member
  ends only (measured: slab edges, a wall foot and supports a member runs on
  past are as 2.23 has them), so when the supports balance the loads to 1%
  with those replaced, the others keep the solver's forces and moments and
  the total in `global_reactions` is that of the supports where the solver's
  own does not balance (`forces: "supports"`; `_supports()` builds them
  twice for that). A solver's total that balances is kept: in `beam_01` the
  errors of the two supports cancel and it is exact. Only if
  they still do not balance are the others `"unreliable"` and the total the
  solver's (`94g.7`). Measured on 2.21: `portal_01`'s own total is 11%
  short and the supports' is off by 5 in 100 000; `structure_01`'s wall
  foot was unreliable and is not. **A point force on a support node is not
  in the member's end**: `support_node_loads` has it a second time (values
  10 to 12, from the `** Point loads` line the load writer puts before
  them) and `_support_entry()` takes it off the member end's force before
  comparing. Without that a load on a clamped node made the solver look
  wrong on any version and the reaction came out short by the load. **A
  member tied to a surface along its length is no check on its support**
  (`_member_ends_at()` returns None for it): its end has its share of the
  force only. Two cantilevers under a slab had 58.5 N each for 49.7, as
  `member_end_forces` with a warning, on 2.23; on 2.21 such a root is now
  `"unreliable"`, which it is. Tests of the solver's own
  reactions at clamped supports call `_needs_solver_reactions()` and are
  skipped on 2.21; the 2.23 job in CI fails if any of them is skipped. To run the suite against 2.21 locally: a container from
  `ubuntu:24.04` with `calculix-ccx`, and a `ccx` script first in `PATH`
  that runs `podman run --rm -v "$PWD":/w:Z -w /w <image> ccx "$@"`.
- **Only the solid rectangle is written as a CalculiX section**, with one
  shear modulus lowered to correct its torsion. Every other
  profile is an equivalent rectangle (see Beam Section Orientation). Do not
  go back to CalculiX's CIRC, PIPE or BOX: a PIPE cantilever measured 83% too
  flexible with the weight of a solid bar, and B31 rejects PIPE and BOX.
- **U1 beams are opt-in** (`--open-sections user-element`) and only correct in
  all-U1 models. On stock CalculiX a U1 element next to any other 1D/2D
  element crashes in gen3delem
  (`CalculixRunner._raise_if_known_gen3delem_user_element_bug()` reports it);
  on a patched build a U1 beam and a native beam sharing a node transfer no
  moment (`aiz.14`), and a U1 member at a connection is tied in translation
  only. So the writer refuses a U1 member joined to native beams or shells,
  by a shared node or a connection, unless the file releases every rotation
  of one of the two (`_check_user_elements_join_their_own_kind()`, an
  `AnalysisError`). CalculiX gets the nodal forces of U1 wrong
  (`resultsmech_u1.f` adds both end forces with one sign and recovers them
  with `1/(1 - phi)`: a root printed -1500 N, or 728 N, for +1500), and its
  printed section forces with them. At support nodes where only U1 elements
  meet, `ResultsParser._correct_user_element_forces()` replaces force and
  moment with the elements' stiffness times the displacements
  (`analysis/user_element_forces.py`, the matrix of `e_c3d_u1.f` as it is,
  which is not the textbook Timoshenko beam) and corrects the printed total
  (`aiz.19`). Good to about 1e-4: the FRD has six figures, and the shear of a
  short element is a small difference of its displacements. Measured the
  same on 2.21 and 2.23. Statics decides at run time: if ours do not balance
  the loads and the solver's do, CalculiX has changed U1 and its forces are
  kept, with a warning to update the matrix; if both balance, a warning says
  the solver has put it right; if neither, a U1 warning says so.
  **Section forces of U1 members** (`bgz`) come from the same matrix:
  `ResultsParser.compute_user_element_section_forces()` takes each
  element's stiffness times its displacements, less its share of the loads
  along it (`StructuralModel.user_element_loads`, recorded per step by the
  load writer: `_note_user_element_loads()` works out each element's share
  on a set of that element alone, and the self-weight is half of each
  element's at either end), and gives records at both ends and no middle,
  which `_restore_jumps()` leaves as they are. A U1 element carries no load
  of its own, so these are the forces of statics at every node of a
  determinate member, at any mesh. The six figures of the FRD limit them
  towards a free end, where the forces are small differences of large
  displacements: measured on the I cantilever about its weak axis, shear
  out by 0.7% of the root's at a 0.25 m mesh and 5% at 0.05 m, moments by
  3e-4 to 1e-3; about the strong axis 0.1% and 0.5%.
- **Equivalent-rectangle members have no `max_von_mises_Pa`** (the solver's
  stresses are the rectangle's); `results.json` marks them with
  `section_model`. Their stress is `max_normal_stress_Pa`, from the section
  forces and the real section.
- **Beam section forces are integrated by us** (`analysis/section_forces.py`),
  never requested from CalculiX: it only writes them in 2D output mode
  (`OUTPUT=2D` + `SECTION FORCES`), which averages shell stress through the
  thickness. At each cross-section of an expanded element that has nodes, the
  nodal stresses are interpolated and integrated in the axes the writer
  recorded for the element (`StructuralModel.beam_section_frames`), turned
  to point the way the member does (first point of its geometry to the last)
  so signs are the same along a member. `results.json` has the envelope and
  the signed diagram.
- **`analysis/plausibility.py` warns about results too large to believe**:
  a member distorting by more than 1/100 of its size
  (`max_relative_displacement_m`, which leaves out rigid movement), or any
  displacement over 5% of the model's size. `building_02` with
  `--strict-connections` is the case it was written for. A warning here
  means look at connections and supports before anything else.
- **Nodal stresses are averaged between elements that share nodes**, so a
  force that jumps at a cross-section (shear under a point load, bending
  moment under an applied moment) comes out as the mean of the two sides.
  `ResultsExporter._restore_jumps()` puts the step back from the elements'
  own middle cross-sections. A force at the middle of a quadratic element is
  the mean of the element's own two ends, less what the load does by varying
  along it, so a middle that is not the mean of the solver's two end values
  says the jumps at the ends differ, by four times as much. `_jumps_between()`
  adds those up along the member; a cross-section with a jump is off the line
  that most of the seven around it are on (`_lines_most_are_on()`), and where
  no line has more than half of them no jump is given (a member tied to a
  slab at every node). Two elements are enough. **Nothing is assumed of the
  load**: the slopes between middles were once compared with their median,
  which put a step of 5 to 14% at every element end under a load that varied
  or covered part of the member (`aiz.84`). Do not go back to slopes between
  middles. Tried and dropped on the way: solving for the jumps from pairs of
  neighbours (one element with senseless values, and `building_01` has them,
  grew into steps of ten times the force along the whole member) and a
  repeated-median fit (it missed the steps where cross beams frame into
  `grid_of_beams`, three jumps in seven cross-sections). A bending moment
  changes by its shear per metre, so what the shear on each side does not
  account for is its jump. At a knot (members at an angle) the nodes are
  separate and the values are already one-sided. Members in line that are
  joined rigidly share nodes as two elements of one member do
  (`_ends_shared()`), and their end cross-section is one more with a jump to
  find, of which the member has its half; its moment gets the value the
  member's own last middle leads to. The envelope in `results.json` is
  taken from these diagrams, never from the raw cross-sections: beside a
  jump the mean can be larger than either side's own value.
- **A moment curved along an element is put right** (`aiz.89`,
  `_correct_curvature()`). An expanded B32R has two integration points
  along it and its nodal stress is the straight line through them, so
  where a load along the element makes the moment a parabola the ends read
  `M'' h²/12` too large and the middle `M'' h²/24` too small (46 N·m at
  `beam_01`'s fixed ends at a 0.5 m mesh). The shear is a straight line and
  right, and `M''` is its change along the element: nothing is assumed of
  the load. It is done after the shear jumps are restored (a point load
  would otherwise count as half a load along the element), with one value
  at a shared cross-section so that a jump in the moment is still found.
  The diagrams, the envelope, `max_normal_stress_Pa` and the member ends a
  support is checked against all read the corrected records
  (`_member_records()`). Measured: `cantilever_01`'s diagram is
  w (L - x)²/2 to 1 in 100 000 at a 0.5 m mesh, where it was 0.5% out.
- **Section forces of a member tied to a surface along its length are its share
  only** (`aiz.86`), and `results.json` marks it with
  `tied_to_surface_members`. A tie brings force in at every node, middle nodes
  included. Under a load spread along the member the diagram is smooth
  (`TestSlabBearingOnBeams`, measured). Where force passes at a point it is
  not: a column of `building_01` standing in a masonry wall has -3457, -871,
  +1717 kN in its first element at a 0.5 m mesh and -4145, -834, +2574 kN at
  0.25 m. The size is real (its `Dead` case is 48.5 MN), the values at the
  ends of that element grow as the mesh is refined, and `_restore_jumps()`
  has nothing to go by there. The tie warning says so; nothing is smoothed.
- **`building_01` solves**; its reactions match the applied loads (282.0 and
  13.5 kN) and its self-weight is dominated by a 202 t/m³ `Masonry` material
  in the file. `building_02` solves, its reactions match the applied loads and its
  deflections are plausible (26 mm under Live at a 2 m mesh), but it has no
  reference, and a 1 m mesh needs more than 5 GB of memory (`aiz.37`).
  Never run it finer than 2 m on the development machine. Measured
  2026-10-17: at 2 m `ccx` alone needs 60 s and 2.08 GB (SPOOLES, the only
  direct solver of stock builds); `SOLVER=ITERATIVE CHOLESKY` does not
  converge on expanded shells, and S8R quads instead of S6 save 17% of
  memory on a plate. Measured 2026-10-18 on a machine with 6.7 GB and as
  much zram: at 1 m the whole run takes 24 min, `ccx` about 5 to 5.5 GB,
  reactions balance to 1e-7, and the largest displacements are 2 to 6%
  above those at 2 m (Dead 17.81 against 16.81 mm, Live 26.64 against
  26.06). A 2 m mesh is good enough for development.
- **Member results are read on the faces of expanded elements.** A member's
  largest displacement in `results.json` includes what its rotation adds at
  the faces: a few percent on a slender member, more on a deep one.
  `global_displacements` leaves out the nodes of links and arms, elements of
  no member (`ResultsExporter._link_nodes()`, `aiz.92`): their faces are up
  to 0.25 m from their axis, and one set `structure_01`'s largest Y
  displacement 57% above the structure's own and `building_01`'s `Dead`
  0.6% above it.
- **`slab_01.rmed` is not a reference for `slab_01.ifc`** (`aiz.36`): it was
  computed with one edge hinged; the IFC file as shipped clamps both. The
  Code_Aster runs also give their rigid eccentricity arms weight (16 N each in
  `grid_of_beams`, whose reference maximum is 0.029 mm too high for it).
- **Self-weight is what the file says it is** (`aiz.71`, decision
  2026-10-12). `IfcStructuralLoadCase.SelfWeightCoefficients` are the shares
  of the members' weight a case includes along global x, y and z
  (`LoadGroup.self_weight_coefficients`, `includes_self_weight`); the case's
  step gets `*DLOAD GRAV` scaled and turned by them
  (`_write_self_weight()`, with `STANDARD_GRAVITY` = 9.81 m/s², which IFC
  does not give). A case with nothing else is still a case: select load
  cases with `LoadGroup.has_actions`, never with `.loads`. `Dead` has
  `(0, 0, -1)` in `beam_01`, `building_01` and `building_02`. A buckling
  step has the weight of every case, as it has every load.
- **`--gravity` is for files with no load case** (`cantilever_01`,
  `slab_01`, `structure_01`, `grid_of_beams`, which have no loads otherwise,
  and whose Code_Aster references are self-weight runs). It adds a case of
  its own, `Gravity`, that no combination includes, and warns when a case of
  the file already has self-weight. Do not make it change the file's cases.
- **Benchmarks on `beam_01` variants take the weight out** (`_beam_01()` in
  `test_pipeline_benchmarks.py`) so that one load is checked against its
  closed form; those that run the file as shipped include it.
- **Buckling factors** come from a single `*BUCKLE` step that contains the
  loads. CalculiX scales only loads defined inside that step; a preceding
  `*STATIC` step is a fixed preload. Validated for one Euler column only.
  The result file has the displacements under those loads first (the same
  as a static run, measured) and then a shape per mode scaled to a largest
  value of one. `ResultsParser._set_mode_shapes_apart()` moves the shapes to
  `parsed_results["mode_shapes"]`; they are not displacements and must never
  be listed as load cases (`aiz.73`). `results.json` has the one case
  `Reference loads` and `buckling.modes` with the factors.
- **Modal analysis** (`lon`, `--analysis-type modal`, `--modes`, default 10)
  is one `*FREQUENCY` step and no load. Its mass is the materials' density
  alone (a material without one stops it, `E-MAT-003`): IFC cannot say
  which loads are mass, so none is, and `W-LOD-011` says so when the file
  has load cases. Links, arms and springs have no mass; knots for point
  loads are not made and the plane hold is not applied (modes out of the
  plane are real). U1 members are refused (`E-SEC-006`): CalculiX gives
  them no mass. `ResultsParser.parse_frequencies()` reads the frequencies,
  participation factors and effective masses (rotations about the global
  origin) from the .dat, the same on 2.21 and 2.23; every displacement set
  in the .frd is a shape, mass-normalised, and goes to `mode_shapes` as
  `Mode <n>` (buckling shapes are named so too). A mode below 0.01 Hz or
  with a negative eigenvalue is `mechanism` (`W-CHK-003`): CalculiX solves
  a mechanism and gives such modes rather than stopping. Measured
  (`TestModalAnalysis`): an equivalent rectangle has the real section's mass
  and rotary inertia, rho (Iy + Iz), and its bending modes are Timoshenko's
  with kappa 1 on the real shear areas to 1e-3; axial modes are exact;
  torsion of a solid rectangle is 0.8% low, of an open section 5.4 times too
  high (30 times too stiff). `cantilever_01`'s first four vertical modes
  are Timoshenko's with 5/6 to 1e-6 (they were 0.16 to 2.8% above before
  its shear modulus was put right, `aiz.101`); sideways they follow the
  width modulus written, 17% above 5/6 G, to 1e-3. `slab_01` held in translation on four
  edges is 1.4 to 1.7% below Mindlin's hard simply supported plate, as its
  static deflection is 2.6 to 3.3% above Navier's.
- **FRD/DAT parsing is duplicated on purpose** between `results_parser.py` and
  `ccxquery/parsers/`; `ccxquery` is a standalone debugging tool.

## Beam Section Orientation

CalculiX's `*BEAM SECTION` second data line is the direction of the section's
local 1 axis. The first dimension (`RECT a`, `BOX a`) is measured along it, and
for `SECTION=GENERAL` the first inertia `I11` resists loads acting along it.

IFC maps the profile's Y dimension (depth) onto the member's local z, which
`IfcStructuralCurveMember.Axis` defines. So the writer always gives CalculiX the
**IFC local z** (`member.local_axis[2]`, via `_get_beam_normal()`), with
**depth-first dimensions** and **`I11 = Iy`**. In the domain model
`moment_of_inertia_y` is the strong-axis value for a section deeper than wide.
A member has no `local_axis` when the file gives no usable `Axis` (IFC2X3 has
no such attribute; one along the member is no use). Its section is then placed
by `_default_section_direction()`, depth as near vertical as the member
allows and along global X for a vertical member, and one warning lists the
members for which that matters (`_section_has_a_direction()`: not a circle,
a round tube or a square) (`pfk`).
`tests/validation/test_pipeline_benchmarks.py` checks both axes.

**Equivalent rectangles.** A section that is not a solid rectangle is written
as `RECT a, b` with a material of its own (`MAT_EQ_<member>`):
`converters/section_profiles.equivalent_rectangle()` gives
`a = sqrt(12 Iy / A)`, `b = sqrt(12 Iz / A)` and a factor `A / (a b)` that
scales the elastic modulus and the density, so EA, both EI and the weight per
length are exact. The material is orthotropic (`*ELASTIC, TYPE=ENGINEERING
CONSTANTS` with an `*ORIENTATION` along the member): `G12` and `G13` are set
so that `G12 a b = G A_shear,y` and `G13 a b = G A_shear,z`. Note the absence
of 5/6. That is calibrated, not derived: with these strongly orthotropic
materials the I-section benchmarks come out right with 1.0 and 12 to 18% short
in shear with 5/6. An isotropic rectangle with a Poisson's ratio behaves as
5/6 (a simply supported 0.3 m square matched to 0.01% with nu = 0.3); with
the nu = 0 that beams have it shears with its whole area as well (`aiz.101`).

**Torsion.** CalculiX puts one solid element across a beam's section, which
can only warp as `x2 x3`, so an `a` x `b` beam twists with
`4PQ/(P+Q)`, `P = G12 a b³/12`, `Q = G13 b a³/12`
(`expanded_rectangle_torsion_stiffness()`; measured to three figures). Two
shear moduli cannot match two shear areas and a torsion constant, so
`equivalent_shear_moduli()` picks by section type:

- Open sections keep their shear stiffness; torsion is far too stiff (I
  section 30 times). Nothing can be done about this with a rectangle.
- `TORSION_MATCHED_SECTIONS` (circular, hollow circular, hollow rectangular)
  get both moduli scaled by one number so that torsion is exact; their shear
  stiffness is then too high by that number (bar 1.1, box 1.4, thin tube
  1.9). They need `torsional_constant` on the section, else shear is matched.
- A solid rectangle gets 5/6 of the material's shear modulus along its
  depth, since it too shears with its whole area (`aiz.101`), and the one
  across its width is set so that torsion is exact
  (`rectangle_shear_moduli()`, `aiz.53`); left alone a square is 18.5% too
  stiff in torsion and 20% in shear. It is written with a material of its
  own (`MAT_RT_<member>`) and an `*ORIENTATION`, real modulus and density,
  so its stresses stay meaningful. The width modulus comes out near 5/6 of
  the material's: 3% above for a square, 4% for 1:2, 17% for 2:1 (deep).
  Deeper than about 2.1:1 it would need more than the material's own
  modulus and soon more than any, so it is held at G and the depth modulus
  raised until torsion is exact: shear along the depth is then 4% stiff at
  3:1, 9% at 5:1 and 14% at 10:1 (`W-SEC-001` gives the figures).
  Measured: `cantilever_01` under its weight is Timoshenko's to 1e-6 at a
  0.5, 0.25 and 0.1 m mesh (it was 0.29% stiff at all three with the
  material's modulus), and 0.06% stiff on its side.

`TestTorsion` checks all of these by reading the twist from the solver's nodes.
Do not measure torsion from a tip deflection: it is read on element faces,
where the rotation of the member adds to it.

A new section type only needs `A`, `Iy`, `Iz` and the two shear areas in
`domain/property.py`, plus an extraction handler (and `torsional_constant`
with an entry in `TORSION_MATCHED_SECTIONS` if it is closed). In the extractors, test hollow IFC profiles before solid
ones: `IfcCircleHollowProfileDef.is_a("IfcCircleProfileDef")` is true. A
channel is `IfcUShapeProfileDef`. A profile with no handler raises
`ModelExtractionError`; never fall back to a default section.

**Area loads follow the member's outline.** Where one surface member lies
inside another (a landing on a floor slab), fragmenting gives each element to
one of them. `_load_element_sets()` applies an area load to every shell
element within the loaded member's outline, whoever owns it, and a load on a
curve member to the elements in its geometry (`_geometry_element_sets`): a
beam lying inside another once had its loads left out with a warning.

## Boundary Condition Handling

`IfcBoundaryNodeCondition` uses three value types for each stiffness component:
- `IfcBoolean(True)` — rigid/fixed (treated as 1e20 N/m or N·m/rad)
- `IfcBoolean(False)` — free/released (treated as 0.0)
- Numeric measure — spring stiffness in project units

The helper `_ifc_stiffness_to_float()` in `entity_identifier.py` handles this;
`get_connection_input()` scales a number by the powers of length its kind has
(N/m and N·m/rad at a point, per metre along an edge, N/m per m² over a face). After extraction, `get_constrained_dofs(connection)` in `boundary_condition_handling.py` translates per-DOF stiffness values to the list of CalculiX DOF numbers to fix (threshold 1e12). This correctly handles pinned supports (`T,T,T,F,F,F` → DOF 1-3) and fully fixed supports (`T,T,T,T,T,T` → DOF 1-6).

**The six values are in the connection's own axes, not the global ones.** A point
connection uses its `ConditionCoordinateSystem`; a curve connection has x along its
edge, with `Axis` giving local z. The extractor stores them as
`connection.local_axes` and `get_constrained_dofs()` permutes the flags into global
DOF numbers, so `drx` of a line support along global Y is DOF 5, rotation about the
edge.

**Skew supports** (`aiz.35`): axes that are not parallel to the global ones, with a
condition that treats its translations or its rotations differently (a roller on an
incline, a line support along a diagonal wall that holds rotation about its edge).
`support_restraint()` gives what any support holds as direction rows in global
coordinates; `get_constrained_dofs()` returns only those that are global DOFs, so ask
`support_restraint()` (or `share_in_span()`) when the question is what a support holds.
What is skew is written by `write_boundary_conditions()` from `support_equations()`:

- A translation is an `*EQUATION` between the node's own global translations. The
  reaction arrives as the solver's force at the node, as for a `*BOUNDARY` (measured,
  with and without a load on the node).
- A rotation is held with a stiff arm (`rotation_arm()`, built by
  `_build_support_arms()`): a B31 link from the node along an axis the support leaves
  free, its tip tied in the directions that stop the held rotations and no other. The
  tip is a support node (in `ALL_BC_NODES` and `support_nodes`), since part of the
  reaction arrives there; it is not in `BC_<id>`. When any rotation of a support is
  skew, all of them go through the arm and none is a `*BOUNDARY`.
- **Do not use `*TRANSFORM` for this.** It works, rotations of beam nodes included
  (measured), but it changes the meaning of every `*CLOAD` and `*EQUATION` term on the
  node, and distributed loads, joints, bearings and the load recorder all write those.
- **A node of shells alone has no rotation about their normal**, and an arm fixed to
  it swings about that axis freely: `slab_01` turned 30 degrees came out with the
  right deflection and in-plane displacements of 800 km. `_drilling_axis()` finds
  such nodes and `rotation_arm()` holds the tip against it too.
- Arm tips and hinge tips are in `self._helper_nodes`. Supports and loads look for
  their node in `_structure_nodes()`, which leaves them out; use it, not
  `dict(self.nodes)`, for anything placed by position.
- The first term of every such equation is in `_collect_boundary_condition_dofs()`
  with the restrained DOFs, so no joint equation makes it depend on something else
  as well; the plane hold skips it for the same reason.
- No arms in a model with U1 members (no link elements next to U1): a skew rotation
  there stops the analysis with an `AnalysisError`.

**Elastic supports** (`aiz.94`): a stiffness that is neither zero nor rigid is
a spring (`support_springs()`; it was once taken as free without a word). Measured
on 2.23, and what the design rests on:

- `SPRING1` on DOF 1-3 of a beam or shell node works; on DOF 4-6 it is accepted
  and does nothing.
- A spring at the tip of a stiff arm holds the node's translation as well. So
  `_build_support_springs()` puts each spring on a node of its own whose first
  translation an `*EQUATION` makes what it resists: the node's translation along
  the spring, or for a rotation the arm tip's movement across the arm over its
  length. The spring node is held in DOF 2-3 (the solver crashes without a word
  otherwise). Rotational springs on a node of shells alone: the arm lies in their
  plane and its tip is held against turning about the normal relative to the
  node; one about the normal holds nothing and is left out with a warning.
- `RF` is wrong at a node an equation leans on (a line bearing's tie gave
  -7994 N where the spring took +1006 N), and at a spring node it is the spring's
  force along global x whatever its direction. So the reaction of a spring is its
  stiffness times its node's displacement (`SPRING_NODES`, printed every step,
  `ResultsParser.parse_spring_displacements()`, combined by superposition).
  `ResultsExporter._elastic_correction()` takes the spring nodes' `RF` and the
  equations' push on support nodes (`_spring_push_on_node()`) off the solver's
  total and adds the springs.
- A line or surface spring is shared out by `spring_node_shares()`: HRZ-lumped
  (a six-node triangle's corners 3/57, middles 16/57 of its area; a quadratic
  edge 1/6, 2/3, 1/6), since the shape functions' integrals give a six-node
  triangle's corners nothing. The elements found must cover the edge or face to
  1%, else `AnalysisError`.

**Surface supports** (`aiz.96`, `IfcStructuralSurfaceConnection`) keep their
outline in `connection.face`; their axes are those of the `Position` of the
face's `IfcPlane` (z across it), and a condition that differs by direction on a
face with no plane raises. `GmshGeometry._surface_support_pieces()` intersects
the outline with each surface member and the pieces fragment the members, so
the mesh follows it. The support holds every node on the face
(`find_nodes_in_face()`). An `IfcBoundaryFaceCondition` has translations only:
inside a rigidly held area a slab's normals still turn, against transverse
shear alone, over about sqrt(D / kappa G t), which at the edge of the area adds
M l / D of rotation (measured: half of `slab_01` held, the free half 15% over
q L^4 / 8 D, as that predicts). `TestElasticSupports` and `TestSurfaceSupports`
check them against closed forms.

`results.json` lists what a support holds along global axes in `restrained` and along
its own in `restrained_in_axes`. `TestSkewSupports` has the incline and a clamp about a
skew axis against statics; `TestPlacedModel.test_turned_off_the_global_axes` runs
`slab_01` and `structure_01` turned 30 degrees about Z against the files as shipped.

**Support displacements** (`aiz.58`): a point action whose applied load is an
`IfcStructuralLoadSingleDisplacement`, assigned to a point connection with an
`AppliedCondition`, moves that support (settlement, a support turned). It is a
`SupportDisplacement` in `LoadGroup.support_displacements`, never among
`loads`, which everything else reads as forces; rotations follow the file's
`PLANEANGLEUNIT`. The steps give it as `*BOUNDARY` values on the support's set
(`_write_support_displacements()`). Measured on 2.21 and 2.23: a value
written in a step stays in force in the later ones, so every DOF any case
moves is written in every step, zero where the step moves none; `*BOUNDARY,
OP=NEW` breaks the model, do not use it. A nonzero rotation on a clamped
beam node works. Only a direction the support holds rigidly as a global DOF
can be moved (`support_displacement_values()`): one it leaves free would add
a restraint, and springs and skew directions (equations) are not done; each
raises `E-LOD-007`, as do one on a member and one in a buckling analysis.
Reactions balance each other (`applied_load_N` is zero), and
`supports[].prescribed_displacements` says what moved. `TestSupportDisplacements`
has a settled middle support and a turned end of a fixed beam against
Timoshenko's closed forms (0.1%), a second case, and a combination.

**Temperature loads** (`aiz.98`): a curve or planar action whose applied load
is an `IfcStructuralLoadTemperature` changes the temperature of the whole
member it is assigned to (CONST only; another distribution, or one on a point
action, raises `E-LOD-008`). It is a `TemperatureLoad` in
`LoadGroup.temperature_loads`, never among `loads`, in K
(`THERMODYNAMICTEMPERATUREUNIT`: a difference, so 5/9 per °F, and the
material's `ThermalExpansionCoefficient` per file unit is divided by the
same). `DeltaTY` and `DeltaTZ` are differences between the outer fibres on
either side of local y and z: across a curve member's real section
(`Section.get_depths()`: width along y, depth along z), across a surface
member's thickness (z only; its normal is that of its face's plane,
`SurfaceMember.normal`). No coefficient, no axes or depth for a difference,
a U1 member or a buckling analysis raises `E-LOD-008`. Measured on 2.21 and
2.23, and what the writer rests on:

- `*TEMPERATURE` takes the change, then gradients in K/m: on a beam node
  along the element's tangent times its section's 1 axis, then along the 1
  axis; on a shell node along the element's normal. The curvature is alpha
  times the gradient whatever the rectangle, so an equivalent one is
  exact. Both turn over with the element's node order, so
  `_prepare_temperature_loads()` turns the elements of a member with a
  difference to run with its x or normal, and `_temperature_fields()` gives
  each node its values from the section axes recorded per element.
- Beam materials (`MAT_RT_`, `MAT_EQ_`, 1 axis along the member) expand
  along the member only (`TYPE=ORTHO`): isotropic expansion is held by any
  knot that holds the section, and a free cantilever under a gradient had
  E alpha dT of stress at its root. Shells expand isotropically.
- A node has one temperature. Where members with different changes meet
  (one heated, one not but with a coefficient), the node takes the mean
  (`W-LOD-010`): two elements see part of the other's change, and a
  restrained run keeps its whole expansion (exact for B32R).
- Every node of a member that expands is written in every step, zero where
  the step heats nothing (temperatures stay in force), after
  `*INITIAL CONDITIONS, TYPE=TEMPERATURE` of zero. A free cantilevered slab
  is no closed form (its clamped edge holds the curvature across); the
  benchmark is a slab on three corners, a sphere.

`plane_structure.py` takes a difference as bending along its gradient.
`TestTemperatureLoads` has a free and a clamped bar, cantilevers, a fixed
beam, a beam bowing out of its plane, the slab, a second case and a node
shared with a cold member against closed forms.

**Member-side releases** (`IfcRelConnectsStructuralMember.AppliedCondition`) are in
the axes of that relation (`connection.release_axes_by_member`; the member's own axes
when the relation has no `ConditionCoordinateSystem`). `released_rotation_axes()`
returns them as directions, and `get_released_rotations()` as global DOFs (None for a
partial release in skew axes: use the directions). A support holding a single member
leaves the released rotations free, whatever their axes: a fully fixed support under a
column released in both bending rotations is written as DOF 1-3 plus torsion. A
surface member is hinged along an edge when it is released about the direction of
the edge, whichever way the edge runs.

Support nodes: `find_support_nodes()` returns the single mesh node nearest the
connection position (within 0.1 m) plus any node coincident with it (beam and
shell meshes keep separate nodes at one point). It never returns a neighbouring
node; doing so fixed two adjacent nodes on fine meshes. Of coincident nodes a
support keeps those of the members it holds (`aiz.97`,
`UnifiedCalculixWriter._support_member_nodes()`, edges and faces too): a
support of a beam at the corner of a slab hinged to it once clamped the
slab's corner, and the slab came out 15% stiff. With none of its members'
nodes there (one stopping short of it) it keeps them all. Point loads go to the
single nearest node.

## Connections

CalculiX expands beam and shell elements into solids, so their nodes have **no
rotational degrees of freedom**. This drives everything about joints:

- `*EQUATION` on DOF 4-6 between two beam/shell nodes is accepted and does
  nothing. `*RIGID BODY` and `*MPC BEAM` on such nodes are rejected. Never use
  them to make a joint rigid.
- **The only rigid joint is a shared node**, where CalculiX builds a knot.
  `UnifiedCalculixWriter._merge_rigid_connection_nodes()` merges the coincident
  nodes of every unreleased member at a connection.
- **Members that stop short of the joint** (rigid end zones: a column ending at
  the beam soffit) are bridged with a stiff B31 link, written by
  `_write_rigid_links()`. Links are not in `self.elements` or `EALL`. Where no
  member reaches the connection (`building_02` has two, with 115 links for
  its 117 eccentric ends) the nearest member end is the joint and the others
  are linked to it: the connection itself has no node (`aiz.88`).
- **A point force on a beam node is put on a knot** (`aiz.76`, `aiz.91`,
  `_knot_point_loaded_nodes()`). On a beam node that is not a knot CalculiX
  puts a force on the four corners of the expanded cross-section, a quarter
  each (`gen3dforc.f`), and dents them more the finer the mesh: a column
  under a load on its top shortened 6.6% more than PL/EA at a 0.1 m mesh,
  and an I section (its equivalent rectangle) under a load at midspan sagged
  1.2% more than Timoshenko's beam at 0.25 m and 3.1% at 0.05 m. A short
  thin link at right angles, its tip free, makes the node a knot: the column
  is right to 0.03% and the I section to 3e-6 at any mesh. The knot links
  are in `_knot_links`, not `_rigid_links`.
- **Beams have no Poisson's ratio** (`aiz.91`, `_BEAM_POISSON`): their
  materials (`MAT_RT_`, `MAT_EQ_`) are written with nu = 0, their shear
  moduli as before. Beam theory has no use for it, and in an expanded beam
  it makes the section contract as it bends, which a knot (clamped end,
  joint at an angle, link, arm, point load) stops: a cantilever was 1.2,
  0.75 and 0.5% stiff at a 0.5, 0.25 and 0.1 m mesh with nu = 0.2 and is
  exact at all three without (once its shear modulus was put right,
  `aiz.101`); a beam with a knot at every node was 24% stiff
  with nu = 0.3. Knots cost a beam nothing now. Shells keep theirs: a shell
  node that is a knot has its thickness held, which stiffens the slab there
  (a cantilevered slab clamped through knots along a line: 3% of its own
  deflection at a 0.25 m mesh, nu = 0.3).
- **Never tie the two ends of a rigid link in translation as well.** They are
  apart, so equal translations plus a rigid link means no rotation, which clamps
  the joint. `_write_point_connection()` skips nodes in the same
  `_rigid_link_groups()` group.
- **Released members** get their own node (split off if the mesh shared it)
  and DOF 1-3 equations: a ball joint. A rotation that is *not* released is
  taken away again by `_build_release_hinges()`: two stiff arms, one on the
  member end and one on the joint, side by side along a released axis, with
  their tips tied in the directions across the arm. U1 members (opt-in) are
  excluded: no link elements next to U1 on stock CalculiX, so they stay full
  pins, with a warning.
- **An eccentric member end is hinged where it ends.** A rigid link carries
  the joint out to that point first, so the reaction keeps its lever arm.
- **A joint can sit along a member's span.** Every connection position inside
  a curve member is seeded with a mesh node (`_seed_support_points()`), and
  `_find_connection_nodes_at_location()` targets the point of the member
  nearest the connection, not its nearest end.
- **Hinged edges between surfaces**: surfaces sharing an edge share its nodes
  after `fragment()`, which is a rigid joint. A surface member released about
  that edge gets copies of the edge nodes (`_release_hinged_edges()`), tied to
  the originals in DOF 1-3 (`_write_edge_hinges()`); a row of ball joints along
  a line is a hinge about it.
- **A curve member lying in a surface member bears on it along its length**,
  connected in the IFC or not (`_build_line_bearings()`). Example models
  connect a slab at its corners only; without this the edge beams carry
  nothing and the slab spans corner to corner (`building_02` gave 462 mm).
  Each beam node the shell mesh does not share is tied in DOF 1-3 to the
  triangle it falls in, with that element's shape functions. It is a hinge
  line, and one warning reports how many members were tied. Not tied: nodes
  on a rigid link, nodes in any earlier equation, and ties that would lean
  on a restrained shell node (CalculiX reports that force at the tied node,
  so it goes missing from the reactions). A member needs two nodes in the
  surface, so a column passing through a slab is left alone.
  `--strict-connections` (`AnalysisConfig.get_strict_connections()`) leaves
  the ties out and the warning then says what was left unconnected.
- **`*EQUATION` data lines take at most four terms.** Use `_write_equation()`.
- **A curve member meeting a surface member at one point** (a column ending
  on a slab or passing through it) is pinned to it there by the same code,
  unless a connection of the file already joins them at that point.
  `_seed_crossings()` in the geometry stage puts a node there in both meshes.
- **A line connection of the file joining a beam and a slab joins them all
  along it** (`aiz.51`, `_line_joints()`), under strict connections too.
  It was once taken for a point at its midpoint: a knot there, or one rigid
  link from a downstand beam, and the slab hung from it. The geometry stage
  meshes the line into the slab and the beam with the same nodes along it
  (`_seed_line_joints()`, `_conform_line_joints()`: the beam is split at the
  line's ends and at the image of every point on either, and each pair of
  pieces is transfinite with one count). Rigid (neither member released
  about the line): the nodes are merged, or joined by a rigid link where the
  beam is eccentric (a downstand beam; `IfcRelConnectsWithEccentricity` is
  taken from the geometry, as at points), in `_merge_rigid_connection_nodes()`.
  Released: each beam node is tied in DOF 1-3 to the slab node at its foot,
  through a link where eccentric (`_build_line_joints()`). **Not with arms
  or equations**: tying a slab's middle surface reaches neither its normals
  nor its rotation, and a slab clamped that way to a beam held against
  twisting came out 40% too flexible in its own share. A line connection
  joining two curve members raises `AnalysisError`. `TestSlabJoinedToBeamsAlongALine`
  has a strip between stiff beams against q B^4 / 384 D and 5 q B^4 / 384 D
  (0.5% and 0.14% at a 0.25 m mesh). A surface member hinged about such a
  line is a hinge with the beam only: `_release_hinged_edges()` takes the
  surface members of a connection alone.
- **A member nothing stops spinning about its own axis is held**
  (`_hold_spinning_members()`): rotation about its axis is restrained at one
  of its supports, with a warning. Ball supports at both ends of a beam are
  the usual cause. A member is held by a support that restrains that
  rotation or by a member across it that it joins without a torsional
  release. Members in line turn together and hold nothing for each other:
  they are one run, held once (`aiz.72`), at a support at an end of the run
  if it has one, else at a joint inside it (measured to 0.1%: only the
  torsion of members in line is restrained there). Along a global axis the
  hold is a `*BOUNDARY` on that rotation, outside the support's set. Along
  any other (a rafter, a brace) the support is given the rotation to hold
  (`connection.torsion_hold_axes`, `aiz.74`): `support_restraint()` returns
  it with what the file says, so the arm, the equations and the reactions
  are those of a skew support, and `_build_support_arms()` runs after this
  step for that reason. Only reported: runs with no support of their own,
  and skew ones on line supports or in a model with U1 members.
- **A plane truss or frame that can leave its plane is held in it**
  (`_hold_plane_structure()`, `94g.3`). `analysis/plane_structure.py`:
  `plane_normal()` recognises one (curve members only, in a plane parallel to
  two global axes, loads, the self-weight of load cases and gravity in it,
  section axes in and across it; a
  straight run takes the plane of its loads) and `out_of_plane_freedoms()`
  counts what nothing restrains, with members and joints as rigid bodies tied
  by the file's connections and supports. If any, every node gets the
  translation across the plane restrained (a `*BOUNDARY` of its own, not in
  `ALL_BC_NODES`, so not in the reactions), `spinning_members()` says where
  to hold what can still spin, and one warning reports it. Linear static
  only: buckling out of the plane must stay possible. A plane model that
  stands up (`beam_01`, `portal_01`) is untouched. **Never restrain a
  rotation at a node inside a member in bending**: CalculiX's rotational
  restraint of a beam node is approximate, and doing so moved a portal's
  moments by 3% and made them unequal. Hold rotations only at a pinned end
  or at a support, as `_hold_spinning_members()` does.
- **Curve members that touch share a node, connection or not** (`aiz.80`).
  `fragment()` gives a beam ending on the span of another, or two that
  cross, one node there, and a shared node is a rigid joint. Where no
  connection of the file joins the two
  (`_curve_members_joined_by_the_mesh()`), one warning counts the places
  (`building_02` has 334: its secondary beams and some columns end on girders
  and have connections of their own that join nothing else), and
  `_hold_spinning_members()` counts the joint as one: those beams were once
  reported as free to spin. Rigid is the decision (2026-10-12): analysis
  programs join members that meet, and the IFC specification, which joins
  members through connection objects alone, says nothing of members that
  only touch. Do not make these joints pins, and do not take them apart
  under `--strict-connections`. `plane_structure.py` still goes by the
  file's connections alone (`aiz.81`).
- **A connection is a support only if it has an `AppliedCondition`**
  (`stiffness_properties` in the domain model). Without one it restrains
  nothing, however many members it joins and whatever its type.
- **What a connection holds says nothing about how members are joined to
  it** (`aiz.78`). Members meeting at a pinned support with no release of
  their own (`IfcRelConnectsStructuralMember.AppliedCondition`) are joined
  rigidly: a beam runs on over the support. `analyze_connection_type()` once
  called a support with a free rotation a "hinge", and the writer released
  every member there. The writer's "hinge" type is now only for a
  `HingeConnection` built by hand.
- **Supports are never invented or dropped** (`aiz.59`).
  `write_boundary_conditions()` raises `AnalysisError` for a model with no
  support and for a support with no mesh node within 0.1 m; a line support
  with no node on its edge is not moved to its midpoint. It once fixed every
  node at y = 0 when it found no support. A hand-built test model needs a
  real support: `tests/helpers.fixed_support()`.
- **The solver runs the input file as written, once.** `CalculixRunner` does
  not edit it, swap it for another file in the directory, or retry; it
  collects only the result files named after the input.
- **Gmsh is used through its Python API only.** The geometry lives there, so
  the executable cannot mesh it; `GmshRunner` has no executable mode.
- **Line supports** (`IfcStructuralCurveConnection`) keep their end points in
  `connection.edge` and restrain every node on the segment
  (`find_connection_support_nodes()`).
- Writer warnings go through `_warn_user()` to `domain_model.analysis_warnings`
  and from there into `result["warnings"]`.

**Distributed loads** are never written as `*DLOAD`. `P2` on a beam and `P` on a
shell act along the element's own axes, which cannot express a load given in
global directions (they once sent every vertical line load sideways).
`_distributed_load_to_nodal_forces()` turns a line or area load into
work-equivalent nodal forces and they are written as `*CLOAD`. A load with
`coordinate_system == "local"` (IFC `GlobalOrLocal`) is rotated with the
member's `local_axis` first. Check any change to loads by summing the applied
load by hand and comparing it with `global_reactions.by_load_case`
(`applied_load_N` there is what was written to the solver, not a check on it).

**A line load may vary along its member or act on part of it** (`aiz.58`). An
`IfcStructuralCurveAction` of type LINEAR or POLYGONAL has an
`IfcStructuralLoadConfiguration`: values with their `Locations` along the member, the
first and last being where the load starts and ends. They become `LineLoad.samples`
(distance from the member's start in metres, force per length);
`_varying_line_load_to_nodal_forces()` integrates them over each element, and
`_seed_load_points()` puts a mesh node at every sample. `portal_01` is loaded on half
of its beam this way and was once analysed with twice its load, because the locations
were not read. `ProjectedOrTrue` is applied in the extractor (`_per_true_length()`).
The other distributions (`aiz.58`):

- **SINUS and PARABOLA** have one value, the largest, at the middle of the member, and
  none at its ends. They are `LineLoad.half_wave` (a key of `HALF_WAVES` in
  `domain/load.py`) and `LineLoad.peak`; `magnitude` is the mean value, as it is for a
  load with samples. `_half_wave_load_to_nodal_forces()` integrates them with a
  five-point Gauss rule.
- **DISCRETE** is a configuration of `IfcStructuralLoadSingleForce` with a location
  each. `_create_domain_loads()` returns a list for that reason: one `PointLoad` per
  force, with id `<GlobalId>#<n>` and `action_id` the GlobalId (the check for loads in
  no load case goes by it). In LOCAL_COORDS they keep `coordinate_system = "local"`
  and `member_reference`, and `_point_load_lines()` turns them with the member's axes.
- **A point load on the span of a curve member gets a mesh node**
  (`_seed_load_points()`), whatever it came from. It once went to the nearest node,
  silently if that was within 0.1 m.
- EQUIDISTANT and USERDEFINED actions, the varying actions of IFC2X3 and a warping
  moment raise `ModelExtractionError`; never read one as a constant load.
- **A point action in LOCAL_COORDS is in the axes of the item it is assigned to**
  (`aiz.85`): a member's, or a connection's `local_axes` (the
  `ConditionCoordinateSystem` of a point connection, the global axes when it has
  none). `_point_load()` sets `coordinate_system` and puts the item's GlobalId in
  `member_reference`, a connection's as well; `_to_global_axes()` turns force and
  moment. Assigned to no item, or to a surface connection, it raises.

**Applied moments** (`aiz.58`) are `Load.moment`: N·m on a `PointLoad`, N·m per
metre on a `LineLoad` with one value (a moment that varies along its member raises).
They are written as `*CLOAD` on rotations 4 to 6. CalculiX makes a beam node loaded
that way a knot, and the moment arrives in the member (measured on hand-written input
at a member's end, between elements and at a middle node, on 2.21 and 2.23). This is
not the `*EQUATION` on DOF 4-6 that does nothing (see Connections). Things to keep:

- A moment per length is shared out to the nodes as a force is. A couple along a beam
  then leaves a saw tooth in the moment diagram of half of what one element carries.
- A moment on a rotation that a support holds by `*BOUNDARY` goes straight into the
  support. `_StepLoadRecorder` notes it and does not pass it on to the file: the
  solver would warn for each one ("zero coefficient on the dependent side", "no MPC is
  generated for the mean rotation").
- `support_node_loads` has six values per node. A support's moment is its member
  ends' less the point moments applied at its own nodes
  (`_moments_on_support_nodes()`), not the nodal shares of a moment per length, which
  the section forces at the end of the member include already (measured: taking them
  off gave 2020.8 N·m for 2000).
- A moment at a node of no curve member raises `AnalysisError`: shells alone have no
  rotation about their normal.
- `plane_normal()` takes a moment about the normal as a load in the plane.
- A load case of moments alone has no force for the reactions to be compared with;
  `BALANCE_NOISE_N` (1 mN) stops rounding from being reported as an imbalance.

**Load steps**: CalculiX keeps loads active from step to step. Every static step
starts with `*CLOAD, OP=NEW` / `*DLOAD, OP=NEW` (`_write_load_reset()`), otherwise
each load case would include all the earlier ones.

**Load combinations are added up, not solved** (`94g.2`).
`LoadsExtractor.extract_load_combinations()` reads each `LOAD_COMBINATION`
group with the factor of every load case in it (`Factor` of an
`IfcRelAssignsToGroupByFactor`, 1 for a plain relation, times the group's
`Coefficient`). The solver runs the load cases only;
`analysis/superposition.combine_results()` multiplies and adds what is linear
in the load (displacement vectors, the six stress components, section force
records, nodal forces at supports, and what each step applied), and
`ResultsExporter._add_one_combination()` runs the exporter itself on that
sum, so magnitudes, von Mises stress, maxima, diagrams, envelopes and support
reactions are worked out by the code that does it for a load case. Never add
maxima or envelopes. One combination is held in memory at a time
(`building_02` has 16). Results go beside each `by_load_case` as
`by_load_combination`; `envelope` stays that of the load cases. Buckling has
no combinations (a warning says so). A load case with neither loads nor
self-weight has no step and adds nothing (`cases_without_loads`). `TestLoadCombinations` checks a
combination against hand values and against one case holding the factored
loads.

**Reference results**: `examples/analysis-models/models/<name>/<name>.rmed` are
Code_Aster results for the same IFC files under self-weight (HDF5; read
`CHA/Bld_DISP` with h5py, six components per node stored component by
component). Use them to check any change to joints, supports or shells.
Compare the displacement field at several points and the reactions, not only
the largest displacement: `structure_01` once matched its reference maximum to
11% with a slab that was too stiff and a wall that was leaning over.

`portal_01.ifc` holds results of its own (`IfcStructuralPointReaction` and
`IfcStructuralCurveReaction` in an `IfcStructuralResultGroup`, in lbf and inches):
reactions, and member end forces. `_portal_reactions_in_the_file()` reads them. They
were computed with a shear area of about 0.79 of the section, where this library
takes the web of an I section, so thrust and moments differ by 2 to 6%; the vertical
reactions agree to 0.02%. Its displacements are in some other unit and are not used.


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:46cd31e7 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
