# Validation Report

This report documents numerical accuracy tests for the `ifc_structural_mechanics` analysis
pipeline. Tests are grouped into two tiers:

- **Tier 1** — hand-crafted CalculiX input files run directly against the solver. These
  isolate the solver and result parser from IFC extraction, meshing and input writing.
- **Tier 2** — the full IFC → Gmsh → CalculiX → `results.json` pipeline, compared with
  closed-form beam and plate theory and with independent Code_Aster results. These are
  the tests that catch errors in section orientation, section properties, supports,
  joints and loads.

All of them live in `tests/validation/`, run under `pytest`, and are skipped when `ccx`
is not on the PATH. Figures below were measured on 2026-10-10 with CalculiX 2.23.

---

## Tier 1: Cantilever Beam with Tip Load

**Source**: `tests/validation/test_cantilever_benchmark.py`

### Problem definition

```
Fixed ▓▓▓══════════════════════════════▶ P = 1000 N (−y)
      0                                 x = L = 1.0 m
```

| Parameter | Value |
|-----------|-------|
| Length L | 1.0 m |
| Cross-section | 0.1 × 0.1 m square |
| Elastic modulus E | 210 GPa |
| Poisson ratio ν | 0.3 |
| Applied load P | 1000 N (−y direction) |
| Mesh | 10 B31 beam elements, uniform spacing |
| Boundary condition | All 6 DOFs fixed at x = 0 |

### Analytical solution

Second moment of area:

    I = bh³/12 = 0.1 × 0.1³ / 12 = 8.333 × 10⁻⁶ m⁴

Tip deflection (Euler–Bernoulli beam theory):

    δ = PL³ / (3EI) = 1000 × 1.0³ / (3 × 210×10⁹ × 8.333×10⁻⁶)
      = 1.9048 × 10⁻⁴ m

Reaction at fixed end:

    Fy = P = 1000 N

### Results

| Quantity | Analytical | FEA | Error |
|----------|-----------|-----|-------|
| Tip deflection δ | 1.9048 × 10⁻⁴ m | 1.9116 × 10⁻⁴ m | 0.36% |
| Reaction Fy | 1000.0 N | 1000.0 N | 0.00% |
| Fixed-end displacement | 0 | < 10⁻⁶ m | — |

**Tolerance**: 5% (test fails if deflection error exceeds 5%)

**Status**: PASS

### Notes

CalculiX internally expands B31 beam elements into C3D8I hexahedral brick elements for
the FEA computation. The original beam nodes do not appear in the FRD output; instead,
each beam node is expanded into 4 cross-section corner nodes. Node positions are used to
identify the tip and root cross-sections in the result file.

The 0.36% error is consistent with the discretisation error of a 10-element cubic beam
formulation for this load case.

---

## Tier 1: Simply Supported Beam with Midspan Load

**Source**: `tests/validation/test_simply_supported_benchmark.py`

### Problem definition

```
Pin ▲══════════════════════╦══════════════════════▲ Roller
    0         x = L/2      ↓ P = 10000 N          x = L = 2.0 m
```

| Parameter | Value |
|-----------|-------|
| Length L | 2.0 m |
| Cross-section | 0.1 × 0.1 m square |
| Elastic modulus E | 210 GPa |
| Poisson ratio ν | 0.3 |
| Applied load P | 10000 N (−y direction, at midspan) |
| Mesh | 20 B31 beam elements, uniform spacing |
| Boundary condition A | DOF 1–3 fixed at x = 0 (pin) |
| Boundary condition B | DOF 2–3 fixed at x = 2 (roller, free to slide in x) |

### Analytical solution

    I = bh³/12 = 0.1 × 0.1³ / 12 = 8.333 × 10⁻⁶ m⁴

Midspan deflection:

    δ = PL³ / (48EI) = 10000 × 2.0³ / (48 × 210×10⁹ × 8.333×10⁻⁶)
      = 9.5238 × 10⁻⁴ m

Total vertical reaction (sum of both supports):

    ΣFy = P = 10000 N

### Results

| Quantity | Analytical | FEA | Error |
|----------|-----------|-----|-------|
| Midspan deflection δ | 9.5238 × 10⁻⁴ m | 9.5578 × 10⁻⁴ m | 0.36% |
| Total reaction ΣFy | 10000.0 N | 10000.0 N | 0.00% |

**Tolerance**: 5%

**Status**: PASS

### Notes

A square cross-section is used so that this test does not depend on section
orientation. Orientation is covered by the Tier 2 tests below.

At pin supports, the cross-section is free to rotate. The expanded corner nodes at x = 0
and x = 2 therefore have non-zero transverse displacement due to end rotation. The test
verifies that the *average* displacement across corner nodes is near zero (as expected:
rotation makes upper and lower corners displace in opposite directions).

---

## Tier 1: Euler Column Buckling

**Source**: `tests/validation/test_buckling_benchmark.py`

Pinned-pinned column, L = 1.0 m, 0.1 × 0.1 m square, E = 210 GPa, 10 B31 elements, unit
axial load defined inside the `*BUCKLE` step. Twist about the column axis is restrained
at one end; without that the model is singular.

| Quantity | Analytical | FEA | Error |
|----------|-----------|-----|-------|
| Critical load P_cr | 1.727 × 10⁷ N (Euler) | 1.693 × 10⁷ N | 2.0% |

B31 is shear-flexible, so for this stocky column (L/h = 10) the shear-corrected value is
1.684 × 10⁷ N and the FEA result sits between the two.

**Tolerance**: 5%. **Status**: PASS

CalculiX scales only the loads defined inside the `*BUCKLE` step. Loads in a preceding
`*STATIC` step act as a fixed preload, and a buckle step with no loads of its own returns
meaningless factors.

---

## Tier 2: Full Pipeline Against Beam Theory

**Source**: `tests/validation/test_pipeline_benchmarks.py`

Each case starts from an IFC file, runs `analyze_ifc()` with a 0.05 m mesh, and reads the
answer from `results.json`. Variants of `cantilever_01.ifc` are made in memory by rotating
the member's `Axis` or replacing its profile. Reference values are Timoshenko beam theory
(bending plus shear deflection). Native sections are meshed with three-node B32R beams;
U1 is a two-node element, so each B32R is replaced by two of them.

`cantilever_01`: L = 3 m, fully fixed at one end, E = 210 MPa, ν = 0.2, ρ = 7.8 kg/m³,
loaded by self-weight. `beam_01`: L = 4 m, both ends fully fixed, 20 kN at midspan,
0.3 m square, E = 30 GPa.

| Case | Section and element | Reference | Pipeline | Error |
|------|---------------------|-----------|----------|-------|
| Cantilever, strong axis (as authored) | 0.2 × 0.4 rectangle, B32R | 0.2814 mm | 0.2800 mm | 0.5% |
| Cantilever, weak axis (`Axis` rotated 90°) | 0.2 × 0.4 rectangle, B32R | 1.1115 mm | 1.1059 mm | 0.5% |
| Cantilever reaction | 0.2 × 0.4 rectangle, B32R | 18.36 N | 18.31 N | 0.3% |
| Cantilever, strong axis | 200 × 400 I, equivalent rectangle | 0.1419 mm | 0.1417 mm | 0.2% |
| Cantilever, weak axis | 200 × 400 I, equivalent rectangle | 1.6087 mm | 1.5972 mm | 0.7% |
| Cantilever reaction | 200 × 400 I, equivalent rectangle | 2.663 N | 2.655 N | 0.3% |
| Cantilever, strong axis | 200 × 400 I, U1 (`--open-sections user-element`) | 0.1419 mm | 0.1419 mm | < 0.1% |
| Cantilever, weak axis | 200 × 400 I, U1 | 1.6144 mm | 1.6143 mm | < 0.1% |
| Cantilever | 150 mm round bar, equivalent rectangle | 0.6602 mm | 0.6589 mm | 0.2% |
| Cantilever | 300 × 10 mm tube, equivalent rectangle | 0.3579 mm | 0.3572 mm | 0.2% |
| Cantilever | 200 × 400 × 10 mm box, equivalent rectangle | 0.1814 mm | 0.1810 mm | 0.2% |
| Fixed-fixed beam, midspan | 0.3 m square, B32R | 0.3506 mm | 0.3489 mm | 0.5% |
| Fixed-fixed beam, reaction | 0.3 m square, B32R | 20.00 kN | 20.00 kN | 0.0% |
| Fixed-fixed beam, 5 kN/m along global −Z | 0.3 m square, B32R | 0.1753 mm | 0.1733 mm | 1.1% |
| Fixed-fixed beam, 5 kN/m along global +Y | 0.3 m square, B32R | 0.1753 mm | 0.1733 mm | 1.1% |
| Fixed-fixed beam, line-load reaction | 0.3 m square, B32R | 20.00 kN | 19.92 kN | 0.4% |
| Fixed-fixed beam, midspan, 20 kN | 200 × 400 I, equivalent rectangle | 1.0776 mm | 1.1002 mm | 2.1% |
| Fixed-fixed beam, 5 kN/m along global −Z | 200 × 400 I, equivalent rectangle | 0.5388 mm | 0.5389 mm | < 0.1% |
| Slab on two cantilever beams under its edges | 0.2 × 0.4 beams, 0.1 m slab, B32R + S6 | 3.360 mm | 3.376 mm | 0.5% |
| Slab on two cantilever beams inside it | 0.2 × 0.4 beams, 0.1 m slab, B32R + S6 | 3.360 mm | 3.358 mm | 0.1% |
| Slab on two cantilever beams, reaction | 0.2 × 0.4 beams, 0.1 m slab, B32R + S6 | 99.47 N | 98.96 N | 0.5% |
| Same, each beam's own entry in `results.json` | 0.2 × 0.4 beams, 0.1 m slab, B32R + S6 | 3.360 mm | 3.362 mm | 0.1% |
| Slab on two cantilever beams inside it | 200 × 400 I beams (equivalent rectangle), 0.1 m slab | 4.913 mm | 4.951 mm | 0.8% |

**Tolerance**: 3% on deflection, 2% on the self-weight reaction. **Status**: PASS

Section forces and member stress from `results.json`, same models (tolerance 1%):

| Case | Quantity | Statics | Pipeline | Error |
|------|----------|---------|----------|-------|
| Cantilever, 0.2 × 0.4 rectangle | Shear at the root | 18.364 N | 18.364 N | < 0.1% |
| Cantilever, 0.2 × 0.4 rectangle | Moment at the root | 27.546 N·m | 27.545 N·m | < 0.1% |
| Cantilever, 0.2 × 0.4 rectangle | Largest normal stress | 5165.0 Pa | 5164.7 Pa | < 0.1% |
| Cantilever, weak axis | Moment (reported as `Mf2`) | 27.546 N·m | 27.545 N·m | < 0.1% |
| Cantilever, 200 × 400 I, equivalent rectangle | Moment at the root | 3.9942 N·m | 3.994 N·m | < 0.1% |
| Cantilever, 200 × 400 I, equivalent rectangle | Normal stress, strong axis | 2435.9 Pa | 2435.8 Pa | < 0.1% |
| Cantilever, 200 × 400 I, equivalent rectangle | Normal stress, weak axis | 14961.6 Pa | 14960.8 Pa | < 0.1% |
| Fixed-fixed beam, 20 kN at midspan | Shear | 10.000 kN | 9.9996 kN | < 0.1% |
| Fixed-fixed beam, 20 kN at midspan | Moment at the ends | 10.000 kN·m | 10.042 kN·m | 0.4% |

CalculiX can write beam section forces, but only in its two-dimensional output mode,
where shell stresses are averaged through the thickness and their bending part is lost.
So they are integrated here from the ordinary three-dimensional results: at each
cross-section of an expanded beam element that has nodes (both ends, and the middle of a
quadratic element) the nodal stresses are interpolated over the rectangle and integrated
into an axial force, two shear forces, two bending moments and a torque. The fixed-fixed
row is from a 0.5 m mesh, eight elements; at the same mesh the cantilever's root moment is
0.5% low.

For a member analysed as an equivalent rectangle the solver's stresses are those of the
stand-in, but their resultants are the member's real forces, and the stress reported is
`|N|/A + |Mf1| y/Iy + |Mf2| z/Iz` with the properties of the real section. That is why the
I-section rows agree with hand values although no I-shaped stress field was ever computed.

The forces are also exported along each member with their signs
(`section_force_diagrams`). Two cases are tested point by point at 1% of the largest
value: the cantilever, where V = −w (L − x) and M = w (L − x)² / 2 at all 121
cross-sections, and the fixed-fixed beam, where the shear is −P/2 up to midspan and +P/2
after it, with both values listed at midspan, and the moment runs from +P L/8 at the
supports to −P L/8 under the load. The solver's own stress at the loaded cross-section is
the average of the two sides, which would give zero shear there; the step is rebuilt
from the cross-sections at the middle of each element, which belong to one element only.

Two checks without a hand value: in `portal_01` each column carries 42.70 kN, half the
85.41 kN reaction, and the beam's end shear is the same 42.70 kN, while the column shear
and the beam's axial force are both 12.41 kN. In `structure_01` the pin-ended column has
an axial force and no moment.

The reaction under self-weight is low by the load on the restrained node itself (a sixth
of an element's weight for a quadratic element): CalculiX does not report the share of a
distributed load that lands there.

**Sections other than solid rectangles.** CalculiX expands every beam into solid
elements, and only its rectangular section came out right. Its PIPE section gave a
cantilever 83% too flexible with the weight of a solid bar, and B31 elements reject PIPE
and BOX outright. Separately, the extraction was reading hollow IFC profiles as solid
ones (they are subtypes, so the test for the solid type matched first) and a solid circle
as a default 0.1 × 0.2 m rectangle. The three round and hollow cantilevers in the table
were 68%, 83% and 54% out before 2026-10-10.

Every such profile, and every I, T, L and C profile, is now analysed as a rectangle
`a × b` with a material of its own, where `a = √(12 Iy / A)`, `b = √(12 Iz / A)` and the
modulus and density are scaled by `A / (a b)`. That reproduces EA, both EI and the
weight exactly. The material is orthotropic, with the two shear moduli along the member
set so that the rectangle has the profile's shear stiffness in each direction; without
that the stocky I cantilever was 5.5% too stiff. The I-section fixed-fixed beam is a hard
case, with 37% of its deflection coming from shear in the web.

One thing this showed: CalculiX's expanded rectangle shears over its whole area, not the
5/6 of beam theory, because one quadratic solid across the section cannot hold a
parabolic shear distribution. Using 5/6 left the shear deflection of the I benchmarks 12
to 18% short. The solid-rectangle rows above are quoted against 5/6 and are a little
stiff for that reason, by less than 1%.

What the equivalent rectangle does not have is the profile's torsional stiffness (too
high for open sections, about half for thin closed ones) or its stresses, so
`results.json` reports no stress for these members. U1 elements with a general section
remain available with `--open-sections user-element` for models made of such members
only. On `portal_01` the two agree: 4.111 mm with equivalent rectangles and 4.120 mm with
U1 at a 0.25 m mesh.

The slab-on-beams model is written from scratch by the test, with a 0.25 m mesh: a
5 m × 1 m slab, 0.1 m thick, and two beams lying in it, fully fixed at one end. The IFC
connects the slab to the beams at the two beam tips only. Read literally the slab would
hang from those two points, which is a mechanism; the pipeline ties each beam to the slab
along its length (see `building_02` below), and the three then deflect as one cantilever
whose stiffness is the sum of the parts. In the second case the beams are 0.25 m in from
the edges, so their nodes fall inside shell elements.

The cantilever's strong-axis orientation was confirmed independently against
IfcOpenShell's Code_Aster reference for the same file
(`examples/analysis-models/models/cantilever_01/cantilever_01.comm`), which places the
0.4 m dimension along the member's local z.

These tests exist because of what they found when first written: beam sections rotated
90° (strong and weak axes swapped), point supports restraining neighbouring mesh nodes,
and wrong inertia formulas for I, L and C sections.

---

## Tier 2: Plate Bending

**Source**: `tests/validation/test_pipeline_benchmarks.py`
(`TestSimplySupportedPlateSelfWeight`)

`slab_01.ifc` (5 m × 3 m, 0.2 m thick, E = 210 MPa, ν = 0.2) with line supports added in
memory along all four edges, each restraining translation only, under self-weight. The
reference is Navier's double sine series for the centre deflection plus the Mindlin shear
term (moment sum over κGt): 0.0747 mm.

| Mesh | S6 (default) | Error | S3 (`--element-order 1`) | Error |
|------|--------------|-------|--------------------------|-------|
| 1.0 m | 0.0749 mm | +0.4% | 0.0337 mm | −55% |
| 0.5 m | 0.0766 mm | +2.6% | 0.0434 mm | −42% |
| 0.25 m | 0.0771 mm | +3.3% | 0.0604 mm | −19% |

**Tolerance**: 5% at 0.5 m; the 0.25 m result must be within 2% of the 0.5 m one and each
refinement must change the answer less than the one before. **Status**: PASS

CalculiX expands a shell into solid elements. S3 becomes a six-node wedge, which is far
too stiff in bending; S6 becomes a fifteen-node wedge. The S6 result settles about 3%
above thin-plate theory, as expected of a solid model whose supported edges are held at
mid-surface only.

---

## Tier 2: Against Code_Aster

**Source**: `tests/validation/test_pipeline_benchmarks.py` (`TestCodeAsterReferences`)

The example-models submodule ships IfcOpenShell's IFC2CA results for the same IFC files:
Code_Aster with Euler beams and DKT shells under self-weight (g = 9.806 m/s²). The
reference value is the largest nodal translation in
`examples/analysis-models/models/<name>/<name>.rmed`.

| Model | Code_Aster | This library | Mesh | Error | Tested |
|-------|-----------|--------------|------|-------|--------|
| `cantilever_01` | 0.2766 mm | 0.2800 mm | 0.05 m | +1.2% (shear deflection) | yes, 3% |
| `structure_01` | 0.4273 mm | 0.4285 / 0.4333 / 0.4343 mm | 1.0 / 0.5 / 0.25 m | +0.3% / +1.4% / +1.6% | yes, 5% at 0.5 m, and convergence |
| `slab_01`, supports as in the reference run | 0.3761 mm | 0.3686 / 0.3773 / 0.3796 mm | 1.0 / 0.5 / 0.25 m | −2.0% / +0.3% / +0.9% | yes, 3% at 0.5 m |
| `grid_of_beams` | 0.3963 mm; 0.367 mm without the weight of its rigid arms | 0.3719 / 0.3727 / 0.3727 mm | 1.0 / 0.5 / 0.25 m | +1.5% against 0.367 | yes, 3% at 0.5 m, and 1% between meshes |

`structure_01` is also compared member by member, on the largest displacement of each
member in `results.json` at a 0.5 m mesh (tested to 10%):

| Member | Code_Aster | This library, on the element faces | At the member axis |
|--------|-----------|--------------|------|
| Slab_01 | 0.4273 mm | 0.4333 mm | — |
| Wall_01 | 0.0764 mm | 0.0810 mm | — |
| Column_01 (pin-ended) | 0.0770 mm | 0.0832 mm | 0.0790 mm |
| Column_02 | 0.0898 mm | 0.0919 mm | 0.0917 mm |

`results.json` takes its values from the nodes of the solid elements CalculiX expands
beams and shells into, which lie on the faces of the member. Where a member rotates they
move a little more than its axis does.

`portal_01` also has a reference file, but it was run in inch and pound units with
metric gravity, so it is not comparable.

What the comparison shows:

- `structure_01` agrees over the whole field, not only at the maximum. At the point of
  largest deflection the reference has (0.066, −0.017, −0.422) mm and this library
  (0.066, −0.020, −0.429) mm at a 0.25 m mesh. The remaining 2% is shear deflection, which
  DKT shells and Euler beams do not have.
- `slab_01`'s reference was computed from an earlier version of the IFC file, with the
  slab clamped about its edge at x = 0 and hinged at x = 5. The file shipped today fixes
  both supports and releases the slab only about the two axes that do not matter, so both
  ends are clamped and the deflection is half as much. The test restores the reference's
  supports in memory. As authored the file gives 0.1810 mm at a 0.5 m mesh against
  0.1812 mm by hand (w L⁴ / 384 E I plus shear), which is tested too.
- `grid_of_beams` has five secondary beams, each ending 0.15 m to the side of and above
  a main beam's axis and released there in bending only. Until 2026-10-10 it gave 0.49,
  0.33 and 1.38 mm at the three mesh sizes, for two reasons. The release was a ball
  joint, so every secondary beam was free to spin about its own axis; and a joint along
  a main beam's span was attached to that beam's nearest end, by the support. Both are
  fixed: a release about one or two axes is now built from translation ties on a pair of
  stiff arms, and joints are attached where they are.
- The `grid_of_beams` reference is itself 0.029 mm too high. IFC2CA gives its rigid
  eccentricity arms a 1 m square section and the model's density, so each of the ten
  weighs 16 N, more than the 11 N a secondary beam delivers. The main beams deflect
  0.084 mm at midspan in the reference and 0.055 mm by hand without that load. The
  secondary beams themselves agree: midspan relative to the ends is 0.3084 mm in the
  reference and 0.3102 mm here. The test takes the spurious load off by hand.

`structure_01` has now been wrong in three different ways. Before 2026-10-10 it gave
between 1.7 and 17 mm (rigid joints that were really pins, joints written as fixed
supports, a line support reduced to one node, slabs given a default steel material, load
cases that accumulated from step to step). After those fixes it gave 0.38 to 0.56 mm
depending on the mesh, and the 0.47 mm at 0.5 m looked like agreement. It was not: the
slab was too stiff and the wall was leaning over by 0.3 mm, and the two errors happened to
offset each other in the largest displacement. Five more causes had to be removed:

1. Linear S3 shells, too stiff in bending.
2. Three-node beam elements written with their nodes in Gmsh's order rather than
   CalculiX's.
3. The wall's line support held about global X instead of about its own edge. IFC gives a
   support condition in the connection's axes.
4. The slab rigidly joined to the wall, where the IFC file releases it along that edge.
5. A column that stops at the slab soffit tied to the slab in translation as well as by
   its rigid link, which stopped the joint rotating.

The lesson for this project is to compare displacement fields and reactions, never a
single maximum.

---

## Example Model Baselines

Full pipeline, default 1.0 m mesh (2 m for `building_02`), quadratic elements. These are
**regression baselines, not validated results**, except where a Tier 2 test covers the
model.

| Model | Load flag | Max displacement | Vertical reaction | Standing |
|-------|-----------|------------------|-------------------|----------|
| `beam_01` | — | 0.34 mm | 20.0 kN | Covered by Tier 2 at a finer mesh; the 1.0 m mesh is 3% stiff |
| `cantilever_01` | `--gravity` | 0.28 mm | 17.3 N | Covered by Tier 2 |
| `structure_01` | `--gravity` | 0.429 mm | 651 N | Covered by Tier 2 (Code_Aster) |
| `slab_01` | `--gravity` | 0.173 mm | 220 N | Covered by Tier 2 (beam theory) at 0.5 m; 5% stiff at 1.0 m |
| `grid_of_beams` | `--gravity` | 0.372 mm | 266 N | Covered by Tier 2 (Code_Aster, corrected) |
| `portal_01` | — | 4.04 mm | 85.4 kN | No reference. 4.11 mm at 0.25 m; 3.84 and 4.12 mm with U1 elements |
| `building_02` | — | 25.8 mm (Live), 15.3 mm (Extra_dead) | 30.0 MN (Live), 60.3 MN (Extra_dead) | At a 2 m mesh. 16.8 mm and 66.9 MN under self-weight. At 4 m: 24.0 / 14.4 / 15.7 mm. Reactions match the applied loads; deflections plausible but not compared with a reference |
| `building_01` | — | 0.286 mm (Live), 0.101 mm (floor finishing) | 282.0 kN (Live), 13.5 kN (floor finishing) | 6.66 mm and 48.54 MN under self-weight. At 0.5 and 0.25 m: 0.337 and 0.352 mm (Live), 7.76 and 8.51 mm (self-weight). Reactions match the applied loads; deflections unchecked |

`building_02` is given at 2 m because a 1 m mesh of quadratic shells needs more than 5 GB
of memory. With linear shells at 1 m it gave 99 mm (Live) and 252 mm (Extra_dead): the
plate benchmark above shows why those were several times too small.

Until 2026-10-10 a distributed load was written by its magnitude alone, as a CalculiX
pressure along the element's own axes: `P2` on a beam, `P` normal to a shell. Its
direction and sign were lost. The 480 line loads of the Extra_dead case, all vertical,
pushed the floor beams sideways (333 mm of horizontal movement), and the total reaction
came out with the wrong sign. Distributed loads are now turned into work-equivalent nodal
forces in their global direction. Summing load × area and load × length over the IFC
file gives 30.017 MN for Live and 60.286 MN for Extra_dead; the reactions in the two
steps are 30.017 and 60.283 MN.

With the loads right, the Live case still gave 462 mm, on the 8.5 m × 21.4 m ground-floor
slab that carries 16 kPa. The IFC file connects every slab at its four corners and
nowhere else: 576 beams and columns lie along slab edges or in walls with no connection
between the corners, and this slab also passes two columns on each long side that it is
not connected to. Beam and shell meshes have separate nodes, so the slab spanned 21 m
from corner to corner and the beams under its edges carried nothing (0.1 mm of
deflection in the edge beam, 408 mm in the slab edge beside it).

A curve member lying in a surface member is now tied to it in translation along its
length, and the analysis says so in a warning. The Live maximum is 25.8 mm, and this
slab moves 25.3 mm at the middle of its 8.5 m bay; a simply supported plate of that size
would give 29 mm and a clamped one 9 mm. The reactions are unchanged, and the difference between a 4 m and a
2 m mesh fell from 17% to 7%. The tie is a hinge line: it carries no moment about the
beam, and beam and slab axes are at the level the IFC gives them, so there is no
composite action.

With `--strict-connections` the ties are left out and the analysis is of the connections
in the file alone: 462, 42 and 120 mm for the three cases, as before. That run now ends
with a warning: "Load case Live: member 2v2zbtMavCUv4$UquJwvIb distorts by 462 mm over its
23.1 m (1/50), more than 1/100. It is probably not connected or supported as intended."
The default run, where the same slab distorts by 25.8 mm (about 1/900), raises none, and
neither does any other example model.

Per-member values in `results.json` were wrong on this model until 2026-10-10: the nodes
of the solids CalculiX expands each element into were guessed from the mesh node numbers.
They are now taken from the element connectivity in the result file, where each solid
keeps the number of the element it came from. All 1304 members have a displacement and a
stress for each of the three load cases; the largest member value equals the global
maximum in each case, and for all 664 slabs and walls it equals the largest displacement
found in the result file within the member's outline.

---

## What is not yet validated

- **Distributed loads on shells** (`IfcStructuralPlanarAction`): the totals are checked
  on `building_02`, but no deflection is compared with a reference. Loads on beams are
  covered by Tier 2.
- **Pinned and roller supports of beams** through the pipeline (Tier 1 covers them in
  CalculiX only).
- **Torque and axial force in section forces**: checked on synthetic stress fields in
  unit tests and by joint equilibrium in `portal_01`, not against a pipeline benchmark
  of their own.
- **Member stress** is the normal stress from axial force and bending only. Shear,
  torsion, buckling and anything specific to concrete are not checked.
- **Shell members in membrane action**: walls are only checked through `structure_01`.
- **T, L and C sections**: section properties are unit-tested against hand calculations,
  and they go through the same equivalent rectangle as the I section, but none has a
  pipeline benchmark of its own. L sections ignore the product of inertia.
- **Frames and buildings**: only `structure_01` has been compared with a reference.
  `building_02` has none.
- **Beams tied to the slab or wall they lie in**: covered by Tier 2 for a slab on two
  beams. Beams in walls and columns in walls use the same code but have no benchmark.
- **Per-member stress in `results.json`**: attributed to the right member, but no value
  is compared with a reference.
- **Skew supports**: not modelled. Releases in skew axes between members are, but
  have only a unit test.
- **Mixed U1 and native beams**: known to be wrong (joints act as pins). U1 is no
  longer used unless asked for.
- **Torsion of non-rectangular sections**: approximate by construction, and not
  measured.
- **`building_01`**: reactions only. Its self-weight deflection is still moving 10%
  between a 0.5 m and a 0.25 m mesh.
- **Buckling** beyond the single Euler column.
