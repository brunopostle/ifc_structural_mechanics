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
2. Call `fragment()` separately for curves and surfaces, so beams share nodes with beams and shells with shells. Support points on beam interiors and connection points landing on a slab are passed as fragment tools so the mesh has a node there. Beam and shell nodes are joined later, in the writer (see Connections)
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
- Falls back to spatial centroid matching for members whose geometry was merged during fragment (overlapping members)
- **Important**: a mesh with no physical groups can only be attributed when the model has one member of each kind; with more, `MeshMapper` raises `MeshingError`. The old round-robin assignment dealt elements out wherever they were; do not bring it back

**Note**: The workflow uses Gmsh's `.msh` mesh format exclusively. `.geo` geometry script files are not used in production as they may have XAO dependencies in newer Gmsh versions.

#### 5. Analysis (`src/ifc_structural_mechanics/analysis/`)
Runs CalculiX and processes results:
- `calculix_runner.py`: Executes CalculiX solver
- `results_parser.py`: Parses CalculiX result files (`.frd`, `.dat`). `parse_element_nodes()` reads the FRD element block: CalculiX reports on the nodes of the solids it expands beams and shells into, numbered by the solver, and each solid keeps the number of the input element it came from. `ResultsExporter` attributes results to a member through those (member → `analysis_element_ids` → FRD nodes), never through mesh node numbers, except for elements the FRD does not list (U1). Uses `_parse_frd_data_line()` for fixed-width FRD column parsing (node ID in chars 3-12, values in 12-char columns). Handles values that run together without spaces.
- `output_parser.py`: Parses CalculiX output for errors/warnings and convergence
- `boundary_condition_handling.py`: Handles boundary conditions and analysis steps
- `superposition.py`: Results of a load combination from those of its load cases (see Load steps)
- `plane_structure.py`: Recognises plane trusses and frames and what holds them in their plane (see Connections)

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
- `structural_analysis.py`: Main entry point, `analyze_ifc()`. `results.json` (schema in the docstring of `export/results_exporter.py`) is the contract with other tools: bump `SCHEMA_VERSION` when it changes. It returns `status: "failed"` with the error in `result["errors"]` for meshing, solver and result-reading failures, and raises `ModelExtractionError` for a file it cannot read

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
   - **Never substitute a default for something the file should give** (material, section, thickness, position, load value, load target). Raise the stage's error, with a message that names the entity and says what is missing. `MembersExtractor._create_member()`, `ConnectionsExtractor._create_domain_connection()` and `LoadsExtractor._create_domain_load()` wrap every failure as "Member/Connection/Load <GlobalId> cannot be analysed. <reason>".
   - **Never leave an entity out and carry on.** A model with a member, support or load missing is another structure.
   - **`except Exception` may only re-raise as a typed error.** Put `except <TypedError>: raise` in front of it so an inner message is not wrapped twice. The only exceptions are cleanup (`gmsh.finalize()`, temp files, `__del__`). Results that cannot be read or exported fail the analysis (`ResultProcessingError`).
   - **An approximation the user did not ask for is a warning in the results**, not a log line: `_warn_user()` in the writer, `_warn_model()` in the load writer, `self.warnings` in the extractors (`Extractor._pass_on_warnings()` moves them to `model.analysis_warnings`). One warning for the whole model with a count and the first few ids, never one per member.
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
- **Slow tests**: End-to-end `building_02` tests are marked `@pytest.mark.slow` and share one analysis through the session fixture `building_02_run` in `tests/conftest.py` (about 6 minutes in total with its 17 load combinations, and 2.2 GB of memory). Skip with `-m "not slow"`.

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
- **CalculiX gives no reaction moments.** `supports[].moments` in
  `results.json` are the section forces at the ends of the curve members a
  support holds (`_member_ends_at()`), moved to its position; absent, not
  zero, where a member runs on past the support or a surface is clamped.
- **CalculiX 2.21, Ubuntu 24.04's, misreports `RF` at a support that holds
  a rotation** (2.23 is right, stock as well as the Copr build;
  displacements are identical). The errors of two
  supports can cancel, so `ResultsExporter` checks each such support against
  its member ends (3%) and the whole against the applied load, replaces what
  it can (`forces: "member_end_forces"`), marks the rest `"unreliable"`, and
  `plausibility.balance_warnings()` says so. Tests of the solver's own
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
  moment (`aiz.14`). U1 reactions have the wrong sign (`aiz.19`).
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
  force that jumps at a cross-section (shear under a point load) comes out as
  the mean of the two sides. `ResultsExporter._restore_jumps()` puts the step
  back for N, V and T from the elements' own middle cross-sections; it needs
  four quadratic elements in the member. At a joint the nodes are separate
  and the values are already one-sided.
- **`building_01` solves**; its reactions match the applied loads (282.0 and
  13.5 kN) and its self-weight is dominated by a 202 t/m³ `Masonry` material
  in the file. `building_02` solves, its reactions match the applied loads and its
  deflections are plausible (26 mm under Live at a 2 m mesh), but it has no
  reference, and a 1 m mesh needs more than 5 GB of memory (`aiz.37`).
  Never run it finer than 2 m on the development machine.
- **Member results are read on the faces of expanded elements.** A member's
  largest displacement in `results.json` includes what its rotation adds at
  the faces: a few percent on a slender member, more on a deep one.
- **Skew supports are not modelled** (`aiz.35`): a support that restrains only
  some directions in axes not parallel to the global ones is written in global
  axes, with a warning. The same goes for a partial release in skew axes.
- **`slab_01.rmed` is not a reference for `slab_01.ifc`** (`aiz.36`): it was
  computed with one edge hinged; the IFC file as shipped clamps both. The
  Code_Aster runs also give their rigid eccentricity arms weight (16 N each in
  `grid_of_beams`, whose reference maximum is 0.029 mm too high for it).
- **Self-weight needs `--gravity`.** Models without an `IfcStructuralLoadCase`
  (`cantilever_01`, `slab_01`, `structure_01`, `grid_of_beams`) have no loads
  otherwise.
- **`SelfWeightCoefficients` of a load case is read and not applied**
  (`LoadGroup.self_weight_coefficients`; `aiz.71`). `Dead` has
  `(0, 0, -1)` in `beam_01`, `building_01` and `building_02`, where it has no
  other load, so it has no step and every combination is without it. The
  extractor warns. `--gravity` adds a separate `Gravity` case that no
  combination includes. Applying the coefficients will change the `Dead`
  results of those three models and most `beam_01` benchmarks.
- **Buckling factors** come from a single `*BUCKLE` step that contains the
  loads. CalculiX scales only loads defined inside that step; a preceding
  `*STATIC` step is a fixed preload. Validated for one Euler column only.
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
A purely geometric default is used only when a member has no `local_axis`.
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
in shear with 5/6. An ordinary isotropic rectangle does behave as 5/6 (a
simply supported 0.3 m square matches to 0.01%).

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
- A solid rectangle keeps the modulus of its depth and has the one of its
  width lowered until torsion is exact (`rectangle_shear_moduli()`,
  `aiz.53`); left alone a square is 18.5% too stiff. It is written with a
  material of its own (`MAT_RT_<member>`) and an `*ORIENTATION`, real modulus
  and density, so its stresses stay meaningful. Shear across the width is
  27% soft for a square and 45% for 1:2; bending and shear along the depth
  do not move (measured to four figures). These mildly orthotropic rectangles
  still follow 5/6 in shear, unlike the equivalent ones.

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
element within the loaded member's outline, whoever owns it.

## Boundary Condition Handling

`IfcBoundaryNodeCondition` uses three value types for each stiffness component:
- `IfcBoolean(True)` — rigid/fixed (treated as 1e20 N/m or N·m/rad)
- `IfcBoolean(False)` — free/released (treated as 0.0)
- Numeric measure — spring stiffness in project units

The helper `_ifc_stiffness_to_float()` in `entity_identifier.py` handles this. After extraction, `get_constrained_dofs(connection)` in `boundary_condition_handling.py` translates per-DOF stiffness values to the list of CalculiX DOF numbers to fix (threshold 1e12). This correctly handles pinned supports (`T,T,T,F,F,F` → DOF 1-3) and fully fixed supports (`T,T,T,T,T,T` → DOF 1-6).

**The six values are in the connection's own axes, not the global ones.** A point
connection uses its `ConditionCoordinateSystem`; a curve connection has x along its
edge, with `Axis` giving local z. The extractor stores them as
`connection.local_axes` and `get_constrained_dofs()` permutes the flags into global
DOF numbers, so `drx` of a line support along global Y is DOF 5, rotation about the
edge. Only axes parallel to the global ones are handled (see Known Limitations).

**Member-side releases** (`IfcRelConnectsStructuralMember.AppliedCondition`) are in
the axes of that relation (`connection.release_axes_by_member`; the member's own axes
when the relation has no `ConditionCoordinateSystem`). `get_released_rotations()`
returns them as global DOFs. A support holding a single member leaves the released
rotations free: a fully fixed support under a column released in both bending
rotations is written as DOF 1-3 plus torsion.

Support nodes: `find_support_nodes()` returns the single mesh node nearest the
connection position (within 0.1 m) plus any node coincident with it (beam and
shell meshes keep separate nodes at one point). It never returns a neighbouring
node; doing so fixed two adjacent nodes on fine meshes. Point loads go to the
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
  `_write_rigid_links()`. Links are not in `self.elements` or `EALL`.
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
  A line connection of the file joining a beam and a slab is tied the same
  way, with no warning and under strict connections too.
- **A member nothing stops spinning about its own axis is held**
  (`_hold_spinning_members()`): rotation about its axis is restrained at one
  of its supports, with a warning. Ball supports at both ends of a beam are
  the usual cause. Members along a skew axis, or with no support of their own,
  are only reported. A straight run of members joined rigidly end to end is
  not seen at all: each counts as held by the next.
- **A plane truss or frame that can leave its plane is held in it**
  (`_hold_plane_structure()`, `94g.3`). `analysis/plane_structure.py`:
  `plane_normal()` recognises one (curve members only, in a plane parallel to
  two global axes, loads and gravity in it, section axes in and across it; a
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
- **A connection is a support only if it has an `AppliedCondition`**
  (`stiffness_properties` in the domain model). Without one it restrains
  nothing, however many members it joins and whatever its type.
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
no combinations (a warning says so). A load case without loads has no step
and adds nothing (`cases_without_loads`). `TestLoadCombinations` checks a
combination against hand values and against one case holding the factored
loads.

**Reference results**: `examples/analysis-models/models/<name>/<name>.rmed` are
Code_Aster results for the same IFC files under self-weight (HDF5; read
`CHA/Bld_DISP` with h5py, six components per node stored component by
component). Use them to check any change to joints, supports or shells.
Compare the displacement field at several points and the reactions, not only
the largest displacement: `structure_01` once matched its reference maximum to
11% with a slab that was too stiff and a wall that was leaning over.


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
