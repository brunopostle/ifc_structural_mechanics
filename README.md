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
- **Beam Sections**: Solid rectangles use CalculiX's own rectangular section. Every other supported profile (circular, hollow circular, hollow rectangular, I, asymmetric I, T, L, and U channel) is analysed as a rectangle with the same axial, bending and shear stiffness and the same weight, computed from the profile's `A`, `Iy`, `Iz` and shear areas, so any mix of sections runs on stock CalculiX. Sections are oriented by `IfcStructuralCurveMember.Axis`, with the profile depth along the member's local z
- **Supports and Releases**: Support conditions are read in the connection's own axes (a line support's `drx` is rotation about its edge), whether or not those are parallel to the global ones: a roller on an incline reacts along its normal, and a line support along a diagonal wall can hold rotation about its edge alone. Rotational releases from `IfcRelConnectsStructuralMember.AppliedCondition` become pinned member ends, hinged edges between a slab and a wall, a support that leaves the released rotations free, or a hinge about one or two axes; an eccentric member end is hinged where it ends, on a rigid lever arm
- **Result Visualization**: 3D visualization of deformed meshes and stress fields using PyVista; filter by load case with `--step`

### Known Limitations

Open bugs and planned work are tracked in the project's `bd` (beads) issue
database; `bd list --status=open` shows the current list. The points below are
the ones a user needs to know before trusting a result.

- **Large models are only partly verified.** `structure_01` (slab, wall and two
  columns) is within 2% of an independent Code_Aster result. `building_02`
  solves, its reactions match the applied loads and its deflections are
  plausible, but it has no reference. `building_01` solves and its reactions
  match the applied loads to the newton, with no reference either; its
  `Masonry` material is 202 t/m³ in the file, which makes its `Dead` case
  (self-weight) 48.5 MN beside 0.3 MN of live load.
- **Reactions need CalculiX 2.23 or later to be exact.** CalculiX 2.21 (the
  version in Ubuntu 24.04) misreports the force at a support that holds a
  rotation, by anything up to the size of the load; displacements and member
  forces are the same in both. The analysis detects this and warns. At such
  a support the forces are then taken from the ends of the members it holds,
  good to about 1%, and where the solver's total does not balance the loads
  the total given is that of the supports (`"forces": "supports"` in
  `global_reactions`). The other supports (a
  clamped slab edge, a beam running on past its support) keep the solver's
  figures, which are right there, as long as the whole then balances the
  loads; if it does not they are marked `"unreliable"` in `results.json`
  and the total is the solver's, and wrong.
- **Reaction moments** come from the forces the solver gives on the nodes of
  the solids it expands beams and shells into, taken about the support: a
  member end, a clamped slab edge and a support a member runs on past alike
  (`"moments": "solver"` in `results.json`). They balance the loads as the
  forces do. Where CalculiX 2.21 got those forces wrong they are the section
  forces at the ends of the members the support holds, good to about 1%, and
  where that is not possible either they are left out, not given as zero.
- **A beam lying in a slab or wall is tied to it along its length**, whether or
  not the IFC file connects them there, and the analysis warns that it did so.
  Models that connect a slab only at its corners would otherwise leave the
  beams under its edges carrying nothing. The tie passes forces, not moments.
  `--strict-connections` analyses only the connections in the file.
- **Large models are slow.** `building_02` takes 3 to 6 minutes (measured 184 s
  and 346 s on the same machine, the second while it was busy) and 2.3 GB at a
  2 m mesh, with three load cases and 17 combinations, and needs more than 5 GB at 1 m. Its deflections move about 7%
  between a 4 m and a 2 m mesh. `--element-order 1`
  switches to linear elements, which are faster but several times too stiff in
  slab bending at these mesh sizes.
- **Sections other than solid rectangles are analysed as equivalent
  rectangles**, with a warning that says how many of each kind. Axial and
  bending stiffness and weight are those of the real section. Shear and
  torsion cannot both be:
  - *Open sections* (I, T, angle, channel) have the right shear stiffness and
    far too much torsional stiffness: 30 times too much for a 200 × 400 I
    section. Do not rely on results where open sections carry torsion.
  - *Tubes, boxes and round bars* have the right torsional stiffness and too
    much shear stiffness: 1.1 times for a round bar, 1.4 for a
    200 × 400 × 10 box, 1.9 for a 300 × 10 tube. On a cantilever ten
    diameters long this takes about 1% off the deflection; on short, stocky
    members it takes more.
- **Solid rectangles are soft in shear across their width**, with a warning
  that says how many and by how much. CalculiX's own beam element is too
  stiff in torsion (18.5% for a square, 16% for a 1:2 rectangle), so the shear
  stiffness across the width is lowered until the torsional stiffness is
  right: by 27% for a square, 45% for a section twice as deep as wide, 17%
  for one twice as wide as deep. Bending, and shear along the depth, are not
  affected. Sideways shear is a small part of a member's deflection: 0.3% for
  a cantilever ten times as long as it is wide, 1% at five times.
- For equivalent rectangles the stresses CalculiX computes are the
  rectangle's, so these members have no `max_von_mises_Pa` (their entry in
  `results.json` carries `"section_model": "equivalent_rectangle"`); their
  stress is the normal stress from the section forces, below.
- **`--open-sections user-element`** analyses them with CalculiX U1 elements
  instead. Their torsion is no better: 267 times too stiff for the same I
  section and 1.6 times for the box. It only works
  when every member of the model is such a section: stock CalculiX crashes
  when a U1 element shares a model with any other beam or shell element.
  With U1, a release about one or two axes becomes a full pin (with a
  warning) and the reactions are reported with the wrong sign.
- **Unsupported profiles stop the analysis.** A Z section, a lipped C or an
  arbitrary profile raises an error that names the member and the profile.
- **Nothing the file leaves out is made up.** The analysis stops, with an
  error that names the entity, when
  - a member has no geometry, no material, no profile or (a slab or wall) no
    thickness, or its material has no Young's modulus;
  - a connection has no position, or is an `IfcStructuralSurfaceConnection`;
  - a load has no position or no member, applies a moment to a surface
    member or one that varies along its member, or is of a kind
    other than a point, line or area force (temperature, prescribed
    displacement);
  - an item's placement is not an `IfcLocalPlacement` (a grid placement);
  - self-weight is asked for and a material has no mass density;
  - the model has no support, or a support lies more than 0.1 m from every
    mesh node (a support that holds no member and lies on none is only
    reported);
  - the results cannot be read back from the solver or written to
    `results.json`.

  It carries on, with a warning in the results, when
  - a material has no mass density (its members weigh nothing) or no
    Poisson's ratio (0.3 is assumed);
  - loads of the file belong to no load group or load case (they are not
    applied);
  - a point load lands more than 0.1 m from the nearest mesh node;
  - members overlap (one layer of elements, with the properties of the member
    that comes first in the file), or a member is left with no elements;
  - the file has more than one structural analysis model (the first is
    analysed).

  Before this, each of these was a line in a log file and a default: steel, a
  0.1 × 0.2 m section, a 0.1 m slab, a support at the origin, a load on the
  first member of the model.
- **A beam with nothing restraining rotation about its own axis is held at
  one support**, with a warning. Two supports that each fix the three
  translations and no rotation, the usual description of a simply supported
  beam, leave it free to spin; the solver then returns an arbitrary rotation
  that used to more than double the reported deflection. A straight run of
  members joined end to end is held as one, and an inclined member is held
  about its own axis.
- **Curve members that touch with no connection between them are joined
  rigidly**, with a warning that counts the places: a beam ending on the
  span of another, or two that cross, are meshed with one node there.
  `--strict-connections` does not change this.
- **A column meeting a slab at a point with no connection is pinned to it
  there**, with a warning, like a beam lying in a slab. `--strict-connections`
  turns both off. A line connection in the file between a beam and a slab is
  always honoured, as a hinge along the line.
- **Section approximations.** No product of inertia and no offset between
  centroid and member axis. `IfcAsymmetricIShapeProfileDef` has its flanges averaged, and
  L (angle) sections are analysed about their leg-parallel axes rather than
  their rotated principal axes.
- **Beam results.** For every beam and column and every load case
  `results.json` gives the largest axial force (tension and compression
  separately), shear forces, bending moments and torque, and the largest
  normal stress they produce in the member's real section (`|N|/A + |M|/W`
  about both axes; no shear, torsion or buckling). A `utilisation_ratio` is
  that stress over the yield stress, for materials whose IFC definition has a
  `YieldStress`.
- **Plane trusses and frames.** A structure drawn and loaded in one plane
  (parallel to two global axes) and supported as its textbook picture is, in
  that plane only and with pinned joints, is a mechanism in three dimensions.
  It is recognised, held in its plane and against bars spinning, and a
  warning says so; nothing in the plane is affected. A pin-jointed truss
  gives the bar forces of the method of joints to four figures and the
  virtual-work deflection to 0.5%; a portal gives its hand moments to 0.2%
  and its sway to 0.5%. Before, the same truss came out with 19 times its
  deflection.
- **Self-weight where the file asks for it.** A load case includes the
  weight of the members when its `SelfWeightCoefficients` say so: `(0, 0, -1)`
  is the whole weight downwards, and other values scale and turn it. It is
  part of that case and of every combination that includes it. `beam_01`
  under its own weight gives w L in reaction to six figures and
  w L² / 12 at its fixed ends to 0.1%.
- **Load combinations.** Every `LOAD_COMBINATION` group of the file is
  reported with the factor of each load case in it
  (`IfcRelAssignsToGroupByFactor`), and has the results a load case has:
  displacements, stresses, section forces and their diagrams, reactions at
  each support (`by_load_combination` in `results.json`, schema 1.2). The
  solver runs the load cases only; a combination is their factored sum, with
  everything that is not linear in the load (magnitudes, von Mises stress,
  the largest values along a member) worked out again from the sum. Linear
  static analysis only. A beam under `1.35 Dead + 1.5 Live` matches one load
  case holding the factored loads to one part in a million. `building_02`'s 17
  combinations add about 100 s to its 180 s, and take its `results.json`
  from 5 MB to 44 MB.
- **Support reactions.** `supports` in `results.json` (schema 1.1) gives, for
  every support and load case, the force and moment it exerts on the
  structure, at its position, in global axes and in the support's own axes
  if it has any, keyed by the connection's GlobalId, with the directions it
  holds along each (`restrained`, and `restrained_in_axes` since schema 1.3). `global_reactions` gives
  their total, the applied load of each case and the difference between the
  two, which should be nothing. A load applied at a support node is counted
  (CalculiX leaves it out of what it reports there). Its moments (schema 1.7)
  are those of all the supports about the origin of the global axes, with
  the moment of the applied loads about the same point beside them
  (`applied_moment_Nm`, `moment_imbalance_Nm`).
- **Force diagrams** (`section_force_diagrams`) list the same six forces with
  their signs along each member, in the axes given by `section_axes`: `x` from
  the first point of the member's IFC edge to the last, `1` along the
  profile's depth, `2 = x × 1`. Each force is what the part of the member
  beyond a cross-section exerts on the part before it; a moment is positive
  when it puts the + side of its axis in tension. A distance listed twice is a
  step, before and after. The step under a point load is recovered only on
  members of four or more quadratic elements; on shorter ones, and with
  `--element-order 1`, the shear there is the average of the two sides.
- **Implausible results are flagged, not judged.** A model can solve with
  nothing wrong in the solver's eyes and displacements of metres. The
  analysis warns when a member distorts by more than 1/100 of its own size
  (it is probably not connected or supported as intended), naming the load
  case and the worst member, and when any displacement exceeds 5% of the size
  of the model (probably a mechanism). These limits are far above
  serviceability; passing them says nothing about a design.
- **Displacements are read on the faces of the solid elements** CalculiX
  expands beams and shells into, so a member that rotates reports a few
  percent more than its axis moves.
- **Distributed loads are uniform over the whole member.** A load given per
  projected length, or over part of a member, is applied as a uniform load per
  true length over all of it.
- **A file with no load case has no loads.** `cantilever_01`, `slab_01`,
  `structure_01` and `grid_of_beams` return zero displacement unless
  `--gravity` adds self-weight as a case of its own (`Gravity`). Standard
  gravity is taken as 9.81 m/s²; IFC gives self-weight as a share of the
  members' weight, not as an acceleration.
- **A beam or column tied to the slab or wall it lies in** has section forces
  that are its share only, and `results.json` marks it
  (`tied_to_surface_members`, schema 1.5). Where force passes between the two
  at a point (the end of a wall, a column in a wall) they change abruptly
  from one cross-section to the next and their largest values depend on the
  mesh size.
- **Linear buckling** is validated for one Euler column only. Its
  `results.json` (schema 1.4) has the buckling factors of all the loads of
  the model together (`buckling.modes`) and the displacements under those
  loads; mode shapes are in the solver's result file only, and there are no
  stresses, reactions or load combinations.
- **Members without an IFC `Axis`** are given a default section orientation,
  which for a non-square section may not be the one intended. A warning says
  how many and names the first.

## Installation

### Prerequisites

Install these separately before installing this library:

- **Python 3.9 or later** (CI tests 3.9, 3.10 and 3.11)
- **CalculiX** (`ccx` executable) — finite element solver. The unmodified distribution package is the supported target; 2.23 or later for exact support reactions (see Known Limitations)
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

# Add self-weight to a file that has no load case
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
| `--gravity` | Add self-weight as a load case of its own, `Gravity`. For files with no load case: a load case that includes self-weight in the file has it without this | off |
| `--strict-connections` | Analyse only the connections in the IFC file. Without it a beam or column lying in a slab or wall is also tied to it along its length | off |
| `--open-sections [equivalent\|user-element]` | How sections other than solid rectangles are analysed: as a rectangle of the same stiffness, or with CalculiX U1 elements (only for models made of nothing else) | `equivalent` |
| `--verbose` | Enable verbose logging | off |
| `--json-output` | Print the outcome (status, warnings, errors, output files) as one JSON document on standard output | off |
| `--map-entities/--no-map-entities` | Map errors back to IFC entities | on |

### Python API

```python
from ifc_structural_mechanics.api.structural_analysis import analyze_ifc

result = analyze_ifc(
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
| `beam_01` | 4 m beam fixed at both ends, 20 kN at midspan and its own weight | No | 0.41 mm (0.43 mm at a 0.05 m mesh) | 28.8 kN | 0.43 mm by hand | Verified |
| `cantilever_01` | 3 m cantilever, 0.2 × 0.4 m section, self-weight | **Yes** | 0.28 mm | 18.4 N | 0.277 mm Code_Aster, 0.281 mm by hand | Verified |
| `structure_01` | Slab hinged on a wall, two columns, self-weight | **Yes** | 0.429 mm (0.433 mm at 0.5 m) | 660 N | 0.427 mm Code_Aster | Verified, within 2% |
| `slab_01` | Slab clamped along two edges, self-weight | **Yes** | 0.173 mm (0.181 mm at 0.5 m) | 230 N | 0.181 mm by hand | Verified; the Code_Aster file is for other supports |
| `grid_of_beams` | Secondary beams hinged onto two main beams, self-weight | **Yes** | 0.372 mm (0.373 mm at 0.5 m) | 273 N | 0.396 mm Code_Aster, 0.367 mm without its spurious arm weight | Verified, within 2% |
| `portal_01` | Portal frame of I-sections, load on half of its beam | No | 2.15 mm (2.17 mm at 0.25 m) | 42.7 kN | Reactions stored in the file: vertical to 0.02%, thrust 1.9% lower (shear area) | Verified against a plane frame with the same shear area, within 1.5% |
| `building_02` | Multi-storey building, three load cases and 17 combinations | No | 16.8 mm (Dead, its self-weight), 25.7 mm (Live), 15.3 mm (Extra_dead), 54.4 mm (1.4D+1.6L) at a 2 m mesh | 67.0 MN (Dead), 30.0 MN (Live), 60.3 MN (Extra_dead) | applied loads by hand | Runs; loads and reactions verified, deflections plausible but unchecked |
| `building_01` | Small building with I-section beams and masonry walls, three load cases | No | 6.78 mm (Dead, its self-weight), 0.29 mm (Live), 0.10 mm (floor finishing); 7.90, 0.34 and 0.11 mm at 0.5 m | 48.55 MN (Dead), 282.0 kN (Live), 13.5 kN (floor finishing) | applied loads by hand | Runs; loads and reactions verified, deflections not |

Values are from the default 1.0 m mesh (2 m for `building_02`, which does not
fit in 5 GB of memory at 1 m) with CalculiX 2.23 and quadratic elements,
measured on 2026-10-11 (`beam_01` and the two buildings on 2026-10-12). The Code_Aster references are the IfcOpenShell IFC2CA
results shipped in `examples/analysis-models/models/`. Reactions equal the
applied loads to six figures at any mesh size; `results.json` gives both, and
the reaction at each support (see below).

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
