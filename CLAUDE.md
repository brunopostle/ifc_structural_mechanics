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

# /tmp is a 2.9 GB tmpfs that Claude sessions and pytest fill; when a run fails
# with EDQUOT ("Disk quota exceeded"), keep the run's temporary files on disk
T=$HOME/.cache/ism-test-tmp; mkdir -p $T
TMPDIR=$T pytest -m "not slow" --basetemp=$T/pt; rm -rf $T
```
pytest-xdist is not installed: no `-n`. The non-slow suite takes about 4 minutes.

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

### Checking members against the building
```bash
# Members against the building elements they idealise (IfcRelAssignsToProduct);
# reports W-BLD codes, does not analyse, exits 1 when there are findings
ifc-analysis check model.ifc [--tolerance 0.05] [--json-output]
```

### Visualization
```bash
# Deformed shape of the first load case (needs the viz extra)
ifc-analysis plot ./results

# Stress, a combination, mesh edges
ifc-analysis plot ./results --field von-mises --combination ULS --edges

# Section force diagram with loads and reactions, to a PNG
ifc-analysis plot ./results --field Mf1 --loads --reactions --screenshot moments.png

# A mode shape of a modal or buckling analysis
ifc-analysis plot ./results --mode 2

# The pictures of README.md and docs/ (building_02 takes about 12 minutes)
python docs/images/make_images.py [model ...] [--work DIR]
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
- `idealisation.py`: `ifc-analysis check` (`94g.33`): each member against the
  building element an `IfcRelAssignsToProduct` links it to, either way round
  (`ifcopenshell.api.structural.assign_product` and homemaker-addon make the
  member the `RelatingProduct`). Position is tested at points well inside the
  member (quarter points; points inside a face, against the body's thickness band
  and outline hull, so a window is an area difference, not a misplacement), never
  at ends, which run on to axes. The load-bearing layers are those with `Category`
  'LoadBearing', else those of the member's material, else none (`W-BLD-009`):
  homemaker's walls are 0.20 of 0.33 m with plaster. Its query functions
  (`element_member_pairs()`, `reference_points()`) are candidates for an
  `ifcopenshell.util.structural` (`94g.34.16`)

#### 3. Converters (`src/ifc_structural_mechanics/converters/`)
Stateless functions that turn domain properties into what the solver needs:
- `section_profiles.py`: equivalent rectangles for sections that are not solid rectangles (see `docs/design/sections.md`)

**Note**: The old `mapping/` module has been removed. Traceability is now embedded directly in domain entities via their `ifc_guid`, `mesh_entity_ids`, and `analysis_element_ids` fields. The `StructuralModel` maintains reverse lookup indices for error propagation.

#### 4. Meshing (`src/ifc_structural_mechanics/meshing/`)
Generates finite element meshes:
- `unified_calculix_writer.py`: **THE UNIFIED SOLUTION** - Single tool for writing CalculiX input files. This replaces dual systems and eliminates element writing conflicts. **Registers analysis element IDs** in domain model via `StructuralModel.register_analysis_elements()`
- `gmsh_runner.py`: Executes Gmsh to generate meshes. Outputs `.msh` mesh files (not `.geo` script files).
- `gmsh_geometry.py`: Creates Gmsh geometry from domain model using **conforming meshes via shared topology**. Uses a shared point registry and `gmsh.model.occ.fragment()` so connected members share mesh nodes automatically. **Registers mesh entity IDs** in domain model via `StructuralModel.register_mesh_entities()`
- `mesh_mapper.py`: Assigns mesh elements to members from the physical groups

**Conforming Mesh Pipeline** (`gmsh_geometry.py` `convert_model()`):
1. Create all geometry with shared points (no per-member synchronize)
2. Call `fragment()` separately for curves and surfaces, so beams share nodes with beams and shells with shells. Support points on beam interiors and connection points landing on a slab are passed as fragment tools so the mesh has a node there, and so are line connections joining a beam and a slab, which are meshed node for node with the beam. Beam and shell nodes are joined later, in the writer (see `docs/design/connections.md`)
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
- `superposition.py`: Results of a load combination from those of its load cases (see `docs/design/connections.md`)
- `plane_structure.py`: Recognises plane trusses and frames and what holds them in their plane (see `docs/design/connections.md`)

#### 5a. Visualization (`src/ifc_structural_mechanics/visualization/`)
Pictures of an output directory (`ifc-analysis plot`, vi9):
- `output_files.py`: `AnalysisOutput` reads `analysis.inp` (the mesh as written; a `** Member <id>` comment the writer puts before each member's set gives its id; `BC_<id>` node sets; `*CLOAD` per step), `analysis.frd` and `results.json`. No PyVista. Each node of an expanded solid belongs to the node of its own input element it is nearest to (the rule of `parse_support_node_moments()`); a node's displacement is the mean over its cross-section, its stress the largest. **Never match nodes by distance alone**: a 0.15 m tolerance once left 4 of `beam_01`'s 10 nodes undeformed (`aiz.102`). Combinations are their cases times their factors; load case n is the n-th `DISP` block, mode n of a buckling analysis the (n+1)-th.
- `plot.py`: `render()` and `plot()` with PyVista: deformed shapes (viridis), section force diagrams from `results.json` along `section_axes` (moments on the tension side, diverging colours), supports, reactions, loads, mode shapes. Quadratic cells are split into linear ones through all their nodes. Draw many things as one mesh: a mesh per member took 39 s on `building_02`.
- `docs/images/make_images.py` makes the pictures of README.md and docs/ from the example models; run it again when a change shows in them.

#### 6. Configuration (`src/ifc_structural_mechanics/config/`)
Configuration system with three main classes:
- `AnalysisConfig`: Analysis type (linear_static, linear_buckling, modal), solver parameters (`num_modes` for modal)
- `MeshingConfig`: Element sizes, element types per member type
- `SystemConfig`: Paths to external tools (CalculiX, Gmsh)

#### 7. API (`src/ifc_structural_mechanics/api/`)
Public-facing API for users:
- `structural_analysis.py`: Main entry point, `analyze_ifc()`. `results.json` (schema, versioning and changelog in `docs/results_schema.md`, example in `docs/examples/beam_01_results.json`) is the contract with other tools: bump `SCHEMA_VERSION` and add to the changelog when it changes, change the JSON Schema `export/results_schema.json` with it (an autouse fixture in `tests/conftest.py` validates every results.json a test writes, and it rejects keys it does not describe), and regenerate the example. It returns `status: "failed"` with the error in `result["errors"]` for meshing, solver and result-reading failures, and raises `ModelExtractionError` for a file it cannot read

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
- **Slow tests**: A failing one fails CI. End-to-end `building_02` tests are marked `@pytest.mark.slow` and share one analysis through the session fixture `building_02_run` in `tests/conftest.py` (about 15 minutes in total with its three load cases and 17 load combinations, and 3.1 GB of memory). Skip with `-m "not slow"`. **They are CI's to run** (decision 2026-10-31): most development machines do not have the memory, so run `pytest -m "not slow"` locally, commit to `main` and push without a branch or a local slow run, and look at CI's result on that commit. A release is tagged only on a commit whose CI run passed.

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
Visualization: pyvista (optional, `viz` extra; `ifc-analysis plot`). CI runs `tests/unit/visualization` under Xvfb in the Python 3.10 job and fails if a picture test is skipped
Dev: pytest, pytest-cov, black, isort, flake8, ruff (pinned), mypy

## Key File Locations

- Entry point script: `src/ifc_structural_mechanics/cli/__init__.py`
- Main API: `src/ifc_structural_mechanics/api/structural_analysis.py`
- Unified workflow: `src/ifc_structural_mechanics/meshing/unified_calculix_writer.py`
- Configuration: `src/ifc_structural_mechanics/config/`
- Traceability: `src/ifc_structural_mechanics/domain/structural_model.py` (see `register_*` and `trace_error_to_ifc` methods)
- Equivalent sections: `src/ifc_structural_mechanics/converters/section_profiles.py`
- Pictures: `src/ifc_structural_mechanics/visualization/` (`ifc-analysis plot`); documentation images: `docs/images/make_images.py`
- Test utilities: `tests/conftest.py`
- Warning and error codes: `src/ifc_structural_mechanics/utils/messages.py` (list in `docs/messages.md`)

## Code Style

- Line length: 88 characters (Black default)
- Python versions: 3.10, 3.11 (the CI matrix; 3.9 dropped at its end of life)
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

Units and placements: see `docs/design/ifc_units_and_placement.md`.

## Debugging Tools for LLM Agents

`python -m ccxquery <file.inp|.frd|.dat> <command>` (summary, sets, materials,
sections, bcs, loads, results, displacements, stresses, reactions, status,
`node <id>`, `nodes-at x y z`) and `python -m mshquery <file.msh> <command>`
(summary, groups, `info <id>`, `select --near x y z --radius r`) inspect
CalculiX and Gmsh files. They live in `src/ccxquery/` and `src/mshquery/`, have
their own `pyproject.toml`, and share no code with the library: their FRD/DAT
parsing is an independent implementation, on purpose.

## Temporary Files

The system uses `utils/temp_dir.py` for managing temporary files during analysis. Temporary files are automatically cleaned up unless `set_keep_temp_files(True)` is called (useful for debugging).

## Design notes

The detail of how CalculiX behaves, what was measured, and why the writer does
what it does is in `docs/design/`. **Read the file for an area before changing
it**: each entry records measurements and decisions not to be undone without new
ones.

- `docs/design/known_limitations.md`: stock CalculiX 2.21 and 2.23, reactions and
  support moments, U1 elements, section forces and jumps, plausibility,
  `building_01`/`building_02` sizes and memory, self-weight and `--gravity`,
  buckling and modal analysis.
- `docs/design/sections.md`: beam section orientation, equivalent rectangles,
  torsion, profile outlines, eccentric members, openings, plain `IfcFace`, area
  loads.
- `docs/design/supports.md`: boundary conditions, skew supports and arms,
  equations on shell nodes and knots, elastic and surface supports, support
  displacements, temperature loads, member-side releases, support nodes.
- `docs/design/connections.md`: joints (shared nodes, links, knots, releases,
  hinged edges, line bearings, line joints, spinning members, plane structures,
  mechanisms), distributed and point loads, moments, load steps, combinations,
  reference results.
- `docs/design/ifc_units_and_placement.md`: units declared and undeclared, object
  placements.

Rules that cut across them:

- Expanded beam and shell nodes have no rotational DOFs: `*EQUATION` on DOF 4-6
  does nothing, `*RIGID BODY` and `*MPC BEAM` are rejected, and the only rigid
  joint is a shared node. Do not use `*TRANSFORM`, `*DLOAD` for distributed
  loads, `OFFSET1`/`OFFSET2`, or CalculiX's CIRC, PIPE and BOX sections.
- Stock CalculiX is the target (2.21 in CI on Ubuntu, 2.23 in its own job); do
  not rely on `patches/`.
- Never run `building_02` finer than 2 m on the development machine.
- After touching joints, supports, shells or loads, check against
  `tests/validation/test_pipeline_benchmarks.py` and the Code_Aster references,
  and compare `moment_imbalance_Nm` as well as `imbalance_N`.
- Supports are never invented or dropped; a hand-built test model needs
  `tests/helpers.fixed_support()`.
- In the writer, place things by position with `_structure_nodes()`, not
  `dict(self.nodes)`; write equations with `_write_equation()` (four terms a
  line); change a section force with `_shift()`.

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
