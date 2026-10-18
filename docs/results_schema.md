# results.json

`analyze_ifc()` (and `ifc-analysis analyze`) writes `results.json` beside the
solver's files: the results of the analysis keyed to the IFC GlobalIds of the
members, supports and load groups they belong to. It is the contract with
other tools, such as a viewer that draws results over the model or a
calculation report. This page describes schema **1.11**.

`results.json` is written by `ResultsExporter`
(`src/ifc_structural_mechanics/export/results_exporter.py`) and
`analyze_ifc()`, which adds `run` and `warnings`. An example, `beam_01.ifc`
with its load case and two combinations, is in
[`examples/beam_01_results.json`](examples/beam_01_results.json). It is made
with

```sh
ifc-analysis analyze examples/analysis-models/ifcFiles/beam_01.ifc \
    --output /tmp/beam_01 --mesh-size 0.5
cp /tmp/beam_01/results.json docs/examples/beam_01_results.json
```

## Versions

`schema_version` is `"<major>.<minor>"`, compared as two numbers (1.10 comes
after 1.9).

- A **minor** version adds keys, or values to a list of choices (`moments`
  gained `springs` in 1.9). A reader written for 1.x reads any later 1.y if it
  ignores keys it does not know and treats an unknown choice as it would a
  missing value.
- A **major** version removes or renames a key, or changes what a value
  means or its unit. None so far: 1.7 is the nearest, see below.

Keys are often absent rather than zero or `null` where a value cannot be
had (the moments of a support whose `moments` is `not_computed`, for
instance). Absent means unknown; never read it as zero.

### Changelog

| Version | Date | Change |
| --- | --- | --- |
| 1.0 | 2026-04-12 | Members with their largest displacement and von Mises stress per load case and their envelope, `global_displacements`, `global_reactions`. Added later under 1.0 without a bump (2026-10-10/11): `section_forces`, `section_force_diagrams`, `section_axes`, `max_normal_stress_Pa`, `utilisation_ratio`, `section_model`, `max_relative_displacement_m`. |
| 1.1 | 2026-10-11 | `supports[]` with the reaction at each support; `applied_load_N` and `imbalance_N` in `global_reactions`. |
| 1.2 | 2026-10-12 | `load_combinations` and the `by_load_combination` results beside each `by_load_case`. |
| 1.3 | 2026-10-12 | Skew supports: `axes`, `restrained_in_axes`, `by_load_case_in_axes`. |
| 1.4 | 2026-10-12 | `analysis_type`, and `buckling` with the buckling factors. |
| 1.5 | 2026-10-13 | `tied_to_surface_members`. |
| 1.6 | 2026-10-13 | Support moments from the solver's forces on the expanded nodes (`moments: "solver"`). |
| 1.7 | 2026-10-14 | The moments of `global_reactions` are those of the supports about the origin; before 1.7 they were always zero. `applied_moment_Nm`, `moment_imbalance_Nm`. |
| 1.8 | 2026-10-14 | `forces` on `global_reactions` entries (`solver` or `supports`). |
| 1.9 | 2026-10-18 | Elastic supports (`springs`, `moments: "springs"`) and surface supports (`type: "surface"`). |
| 1.10 | 2026-10-18 | `run` (how the results were made), `warnings`, `limits`. |
| 1.11 | 2026-10-18 | `prescribed_displacements` on supports the file moves. |

## Outline

```json
{
  "schema_version": "1.11",
  "units": {"length": "m", "force": "N", "moment": "N*m",
            "stress": "Pa", "displacement": "m"},
  "model": {"id": "...", "name": "..."},
  "run": {
    "created": "2026-10-18T10:28:58+00:00",
    "library": {"name": "ifc_structural_mechanics", "version": "0.1.0"},
    "solver": {"name": "CalculiX", "version": "2.23"},
    "input_file": {"name": "portal_01.ifc", "sha256": "8e9b..."},
    "settings": {"analysis_type": "linear_static", "mesh_size_m": 0.5,
                 "element_order": 2, "strict_connections": false,
                 "open_sections": "equivalent", "gravity": false}
  },
  "analysis_type": "linear_static" | "linear_buckling",
  "limits": {},
  "load_cases": ["Dead", "Live"],
  "load_combinations": [
    {"name": "ULS", "ifc_guid": "...", "factors": {"Dead": 1.35, "Live": 1.5}}
  ],
  "members": [
    {
      "ifc_guid": "...",
      "id": "...",
      "type": "curve" | "surface",
      "status": "ok" | "warning" | "fail",
      "section_model": "equivalent_rectangle",
      "tied_to_surface_members": ["..."],
      "envelope": {
        "max_displacement_m": 0.001,
        "max_relative_displacement_m": 0.0008,
        "max_von_mises_Pa": 1.5e6,
        "max_normal_stress_Pa": 1.4e6,
        "utilisation_ratio": 0.006,
        "section_forces": {"max_N_N": 0.0, "max_T_Nm": 0.0,
                           "max_Mf1_Nm": 1.0e4, "max_Mf2_Nm": 0.0,
                           "max_Vf1_N": 1.0e4, "max_Vf2_N": 0.0}
      },
      "by_load_case": {
        "Dead": {"max_displacement_m": 0.001, "max_von_mises_Pa": 1.5e6,
                 "max_normal_stress_Pa": 1.4e6, "section_forces": {...}}
      }
    }
  ],
  "global_displacements": {
    "envelope": {"max_displacement_m": 0.001, "max_tx_m": 0.0, ...},
    "by_load_case": {"Dead": {...}}
  },
  "global_reactions": {
    "by_load_case": {"Dead": {"fx_N": 0.0, "fy_N": 0.0, "fz_N": 5000.0,
                              "mx_Nm": 0.0, "my_Nm": -1.25e4, "mz_Nm": 0.0,
                              "resultant_N": 5000.0,
                              "forces": "solver" | "supports",
                              "applied_load_N": [0.0, 0.0, -5000.0],
                              "imbalance_N": 0.0,
                              "applied_moment_Nm": [0.0, 1.25e4, 0.0],
                              "moment_imbalance_Nm": 0.0}},
    "total": {...}
  },
  "supports": [
    {
      "ifc_guid": "...",
      "id": "...",
      "type": "point" | "line" | "surface",
      "position_m": [0.0, 0.0, 0.0],
      "restrained": ["tx", "ty", "tz", "ry"],
      "springs": [{"kind": "translation" | "rotation",
                   "direction": [0.0, 0.0, 1.0], "stiffness": 1.0e7,
                   "unit": "N/m/m2"}],
      "forces": "solver" | "member_end_forces" | "unreliable",
      "moments": "solver" | "member_end_forces" | "none_restrained"
                 | "springs" | "not_computed",
      "by_load_case": {
        "Dead": {"fx_N": 0.0, "fy_N": 0.0, "fz_N": 5000.0,
                 "mx_Nm": 0.0, "my_Nm": -1.0e4, "mz_Nm": 0.0,
                 "resultant_N": 5000.0}
      },
      "axes": {"x": [...], "y": [...], "z": [...]},
      "by_load_case_in_axes": {"Dead": {"fx_N": ..., ..., "mz_Nm": ...}},
      "prescribed_displacements": {
        "by_load_case": {"Settlement": {"translation_m": [0.0, 0.0, -0.01],
                                        "rotation_rad": [0.0, 0.0, 0.0]}},
        "by_load_combination": {...}
      }
    }
  ],
  "warnings": [
    {"code": "W-SEC-002", "title": "Sections analysed as equivalent rectangles",
     "message": "3 member(s) whose section is not a solid rectangle ...",
     "severity": "warning", "entity_type": null, "ccx_id": null,
     "domain_id": null, "ifc_guids": ["..."]}
  ]
}
```

Units are SI throughout, as `units` says. Directions are global unless a key
says otherwise (`_in_axes`, the section force diagrams).

## How the results were made: `run`

(schema 1.10)

- `created`: when the file was written, UTC, ISO 8601.
- `library`: this library's name and version.
- `solver`: CalculiX and its version as it printed it, or `null` if it did
  not. Version 2.21 and earlier get some reactions wrong (see `forces`).
- `input_file`: the name of the IFC file analysed and the SHA-256 of its
  bytes. A viewer can compare it with the file it has open to know whether
  the results are stale.
- `settings`: the options of the analysis that change its results:
  `analysis_type`, `mesh_size_m` (the default element size),
  `element_order` (2: B32R beams and S6 shells; 1: B31 and S3),
  `strict_connections` (true: only the connections of the file, no beams
  tied to the slabs they lie in), `open_sections` (`equivalent` or
  `user_element`) and `gravity` (a `Gravity` load case of self-weight was
  added).

## Warnings: `warnings`

(schema 1.10)

Every warning of the analysis, the same list as `analyze_ifc()` returns in
`result["warnings"]`: each approximation the analysis made that the user did
not ask for, and each result it has reason to doubt. A report has to state
them. Each has a `code` (`W-<stage>-<nnn>`, explained in
[messages.md](messages.md)), a `title`, a `message` about this model and
`ifc_guids`, the GlobalIds of the entities it is about, by which a viewer can
mark them; a warning about the model as a whole has none. `severity` is
always `warning`; `entity_type`, `domain_id` and `ccx_id` are mostly `null`.

An analysis that fails writes no `results.json`; its errors are in
`result["errors"]`.

## Pass or fail: `status` and `limits`

(`limits` schema 1.10)

A member's `status` is `fail` when a value in its `envelope` or
`combination_envelope` is over the limit of the same key in `limits`, and
`ok` otherwise. `limits` is what was given to `ResultsExporter`, for example
`{"max_von_mises_Pa": 250e6, "max_displacement_m": 0.02}`. `analyze_ifc()`
gives none, so `limits` is `{}` and every member is `ok`: `status` says
nothing about the member's design then. `warning` is a value the schema
allows and the library does not give at present.

## Analysis type and buckling

`analysis_type` (schema 1.4) says what was run. A buckling analysis has one
set of results, named in `load_cases`: the model under all of its loads
together, every load case and its self-weight. It has no reactions or
stresses. `buckling` is then present:

```json
"buckling": {"reference_load_case": "Reference loads",
             "modes": [{"mode": 1, "factor": 12.3}, ...]}
```

Each `factor` is what those loads have to be multiplied by for the model to
buckle in that mode, lowest first. The mode shapes are in the solver's result
file and not here: they are scaled to a largest value of one, so they are not
displacements.

## Load cases and combinations

`load_combinations` (schema 1.2) lists the load combinations of the file,
each with the factor of every load case in it. A combination's results are
those of its load cases, each multiplied by its factor and added: the solver
runs the load cases only, and the analysis has to be linear static. What is
added is what is linear in the load (displacement vectors, stress components,
section forces at each cross-section, forces at support nodes); magnitudes,
von Mises stress, the largest values along a member and its section force
diagram are then worked out from the sums, exactly as for a load case. They
are found beside each `by_load_case`, under the combination's name:

- `members[]`: `by_load_combination`, `combination_envelope` (the
  largest of each value over the combinations; `envelope` remains that of
  the load cases) and `section_force_diagrams_by_combination`. `status`
  fails if either envelope is over a limit.
- `global_displacements` and `global_reactions`: `by_load_combination`.
- `supports[]`: `by_load_combination` and, where the support has axes of
  its own, `by_load_combination_in_axes`.

A load case that has no loads was not solved and adds nothing; a combination
that includes one names it in `cases_without_loads`, and one made only of
such cases is listed without results. Two combinations of one name have the
GlobalId added to the name of the second. Combinations that cannot be formed
(no load case, or something in them that is not a load case) are not listed;
the analysis warns about them. A load case includes the weight of the members
when the file says so (`SelfWeightCoefficients`). Self-weight asked for with
`--gravity` is a load case of its own, `Gravity`, which no combination of
the file includes.

## Total reactions: `global_reactions`

Each entry of `global_reactions` has the solver's total reaction and (schema 1.1) `applied_load_N`, the
whole load of the case as written to the solver `[fx, fy, fz]`, and
`imbalance_N`, the size of what is left when it is added to the reaction.
It should be nothing. CalculiX 2.21 and earlier misreport the force along a
member at a support that holds the member's rotation, and the analysis warns
when that happens. `forces` (schema 1.8) says where the entry's forces come
from: `solver`, its own total, or `supports`, those of `supports` added
up, when the solver's total does not balance the loads, some supports' forces
had to be taken from member ends and none is `unreliable`. If one is, the
total is the solver's and does not balance.

The moments of a `global_reactions` entry (schema 1.7) are those of the
reactions about the origin of the global axes: for each support of
`supports`, its moments and the moment of its force at `position_m`,
added up. The solver has no such figure, and until 1.7 these keys were
always zero. They are absent when a support has no moments (`moments` is
`not_computed`) or the model's supports are not known. Note that they are
made of the forces `supports` gives, which are not the solver's where it
got them wrong (`forces`). `applied_moment_Nm` is the moment about the same point of
the loads as written to the solver, forces where they act and moments
applied, `[mx, my, mz]`, and `moment_imbalance_Nm` the size of what is
left when it is added to the reactions' moment. It should be nothing next to
either: a restraint the analysis added to hold the model (see the warnings)
is in neither `supports` nor here, and what it takes shows up as this.

`global_reactions.total` is only present when there is a single load case;
each case is analysed on its own, so several cases have no common total.

## Supports: `supports[]`

`supports` (schema 1.1) has the reaction at each support: what the support
exerts on the structure, at `position_m`, in global axes. `restrained`
lists the global directions the support holds (t for translation, r for
rotation). A skew support holds directions that are not global ones, which
are not in that list: `restrained_in_axes` (schema 1.3) has what it holds
along its own `axes`. The forces are the solver's, summed over the
support's nodes. For a line support `position_m` is the middle of its edge,
for a surface support (schema 1.9) the mean of the corners of its face.

`springs` (schema 1.9) is present for an elastic support: one that holds a
direction with a stiffness that is neither zero nor rigid. Each spring is a
translation along `direction` or a rotation about it, in global axes, with
its `stiffness` as the file gives it: `unit` is N/m or N*m/rad, per metre
along a line support (`/m`) and per square metre over a surface support
(`/m2`, a modulus of subgrade reaction). `restrained` lists only what is
held rigidly. The springs' part of the reaction is their stiffness times
their displacement, which is exact; it is in `by_load_case` with the rest.

`prescribed_displacements` (schema 1.11) is present for a support the file
moves (an `IfcStructuralLoadSingleDisplacement`: a settlement, or a support
turned): what it is moved by in each load case and combination that moves
it, in global axes, metres and radians. A load case that only moves
supports has an `applied_load_N` of zero, and reactions that balance each
other.

### Where the moments come from: `moments`

The solver gives a beam or shell node no moment, so the moments come from
elsewhere, and `moments` says where:

- `none_restrained`: the support holds no rotation; the moments are those
  of its nodal forces about `position_m` (zero for a point support).
- `springs` (schema 1.9): the support holds no rotation rigidly and has a
  rotational spring; the moments are those of the springs and of its nodal
  forces about `position_m`.
- `solver` (schema 1.6): the support holds a rotation. The solver expands
  beams and shells into solids and gives the force on each of their nodes;
  the moments are those of the forces on the nodes the support's own were
  expanded into, about `position_m`, less the moments applied at the
  support itself. They are in equilibrium with the loads as the forces are,
  for a member end, a clamped slab edge and a support a member runs on past
  alike. For a line support they include what its forces do about the middle
  of its edge. At a node of U1 user elements, which are not expanded and whose
  nodal forces CalculiX gets wrong, force and moment are the elements'
  stiffness times the solver's displacements (`aiz.19`), good to about
  1 in 10 000 (the result file has six figures).
- `member_end_forces`: the solver's forces at the support are wrong (see
  `forces`) or cannot be attributed to its nodes, and
  every member it connects is a curve member ending there. The moments are
  the section forces at those member ends, moved to `position_m`, about the
  restrained axes. They are integrated from stresses and are good to about
  1 %.
- `not_computed`: neither can be had: the solver's forces are wrong or not
  attributable, and the support joins a surface member, a member that runs on
  past it, one tied to a surface member along its length, or one without
  section forces. The moment keys are absent, not
  zero.

### Where the forces come from: `forces`

`forces` says where the forces come from. `solver` is the normal case.
CalculiX 2.21 and earlier misreport the force at a support that holds a
rotation. Where the solver's force at such a support is more than 3 % from
the force at the ends of its members, or the reactions of the load case do
not balance its loads, the support has `member_end_forces` (good to about
1 %), and its moments come from there as well, less any point load applied
at the support itself, which the member has none of. The solver is wrong at
member ends only, so if the supports then balance the loads to 1 % the others
are as the solver has them. If they do not, a support that holds a rotation
and has no member ends to go by (see `moments`) has `unreliable`: the
solver's figures are given, may be wrong, and it has no moments. The analysis
warns in both cases.

`axes`, `restrained_in_axes` and `by_load_case_in_axes` are present when
the support has axes of its own (a `ConditionCoordinateSystem`, or the edge
of a line support); the last gives the same reactions along them.

## Members: `members[]`

`max_relative_displacement_m` is how much a member distorts: the largest
difference in displacement between two of its points in any one global
direction, so without what the member moves as a whole.

### Section forces

Curve members carry `section_forces`: the largest magnitudes over the member
of the axial force N, the torque T, the bending moments Mf1 (stress varying
over the section's depth; strong-axis bending of a section deeper than wide)
and Mf2, and the shear forces Vf1 (along the depth) and Vf2, plus
`max_tension_N` and `max_compression_N`. They are integrated from the
solver's stresses over each cross-section. U1 user elements have no
stresses: theirs are worked out from each element's stiffness and the
displacements of its two nodes, less its share of the loads along it, and
have no middle cross-section.

`section_force_diagrams` holds the same forces along the member, signed, per
load case: parallel lists `distance_m` (from the member's start), `N_N`,
`Vf1_N`, `Vf2_N`, `T_Nm`, `Mf1_Nm`, `Mf2_Nm`. A distance listed twice
is a jump, before and after. `section_axes` gives the directions they refer
to: `x` from the first point of the member's IFC edge to the last, `1`
the section's first direction (the profile's depth) and `2 = x cross 1`.
Each force is what the part of the member beyond the cross-section exerts on
the part before it: N is positive in tension, Mf1 is positive when the +1 side
is in tension, Mf2 when the +2 side is, T is right-handed about x.
`max_normal_stress_Pa` is the largest of |N|/A + |Mf1| y/Iy + |Mf2| z/Iz over
those cross-sections, with the properties of the member's real section;
`utilisation_ratio` divides it by the material's yield strength when one is
known. `max_von_mises_Pa` is the solver's own value and is absent for members
analysed as equivalent rectangles.

`section_model` is only present on members whose section CalculiX has no
shape for (I, T, L, C) when they were analysed as a rectangle of the same
stiffness. Those members have no `max_von_mises_Pa`: the stresses in the
result file are the rectangle's.

`tied_to_surface_members` is only present on curve members that were tied
along their length to the surface members they lie in (a beam under a slab, a
column in a wall), and lists those. Force passes between the two at every
node, so the member's section forces are its share only. Where that happens
at a point (the end of a wall) they change abruptly from one cross-section to
the next and their largest values, the envelope with them, depend on the mesh
size.

### How results are attributed to members

Per-member displacement and stress are attributed element by element. CalculiX
expands beam and shell elements into solids and reports on the solids' nodes,
which it numbers itself; each solid keeps the number of the element it came
from. So a member's result nodes are the nodes of its elements in the result
file's own connectivity (`element_nodes`). Elements the result file does not
list (U1 user elements) fall back to the member's mesh nodes.
