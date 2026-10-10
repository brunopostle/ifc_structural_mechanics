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
| Cantilever, strong axis | 200 × 400 I, U1 | 0.1419 mm | 0.1419 mm | < 0.1% |
| Cantilever, weak axis | 200 × 400 I, U1 | 1.6144 mm | 1.6143 mm | < 0.1% |
| Fixed-fixed beam, midspan | 0.3 m square, B32R | 0.3506 mm | 0.3489 mm | 0.5% |
| Fixed-fixed beam, reaction | 0.3 m square, B32R | 20.00 kN | 20.00 kN | 0.0% |

**Tolerance**: 3% on deflection, 2% on the self-weight reaction. **Status**: PASS

The reaction under self-weight is low by the load on the restrained node itself (a sixth
of an element's weight for a quadratic element): CalculiX does not report the share of a
distributed load that lands there.

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
| `structure_01` | 0.4273 mm | 0.4288 / 0.4340 / 0.4359 mm | 1.0 / 0.5 / 0.25 m | +0.4% / +1.6% / +2.0% | yes, 5% at 0.5 m, and convergence |
| `slab_01`, supports as in the reference run | 0.3761 mm | 0.3686 / 0.3773 / 0.3796 mm | 1.0 / 0.5 / 0.25 m | −2.0% / +0.3% / +0.9% | yes, 3% at 0.5 m |
| `grid_of_beams` | 0.3963 mm | 0.519 / 0.653 / 0.577 mm | 1.0 / 0.5 / 0.25 m | does not converge | no |

`portal_01` also has a reference file, but it was run in inch and pound units with
metric gravity, so it is not comparable.

What the comparison shows:

- `structure_01` agrees over the whole field, not only at the maximum. At the point of
  largest deflection the reference has (0.066, −0.017, −0.422) mm and this library
  (0.066, −0.020, −0.430) mm at a 0.25 m mesh. The remaining 2% is shear deflection, which
  DKT shells and Euler beams do not have.
- `slab_01`'s reference was computed from an earlier version of the IFC file, with the
  slab clamped about its edge at x = 0 and hinged at x = 5. The file shipped today fixes
  both supports and releases the slab only about the two axes that do not matter, so both
  ends are clamped and the deflection is half as much. The test restores the reference's
  supports in memory. As authored the file gives 0.1810 mm at a 0.5 m mesh against
  0.1812 mm by hand (w L⁴ / 384 E I plus shear), which is tested too.
- `grid_of_beams` has single-axis end releases between members, which are analysed as
  full pins.

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
| `grid_of_beams` | `--gravity` | 0.52 mm | 263 N | Known not to converge |
| `portal_01` | — | 3.8 mm | 85.4 kN | Unchecked. All-U1 model; 4.1 mm at 0.25 m |
| `building_02` | — | 455 mm (Live), 434 mm (Extra_dead) | 29.4 MN | Unchecked, at a 2 m mesh. 118 mm under self-weight. At 4 m: 385 / 319 / 101 mm |
| `building_01` | — | — | — | Fails: singular stiffness matrix |

`building_02` is given at 2 m because a 1 m mesh of quadratic shells needs more than 5 GB
of memory. With linear shells at 1 m it gave 99 mm (Live) and 252 mm (Extra_dead): the
plate benchmark above shows why those were several times too small. Of the 434 mm under
Extra_dead, 317 mm is horizontal, which has not been explained.

---

## What is not yet validated

- **Distributed loads** (`IfcStructuralCurveAction`): exercised by `portal_01` but not
  compared with a reference.
- **Pinned and roller supports of beams** through the pipeline (Tier 1 covers them in
  CalculiX only).
- **Shell members in membrane action**: walls are only checked through `structure_01`.
- **T, L and C sections**: section properties are unit-tested against hand calculations,
  but no pipeline benchmark exists. L sections ignore the product of inertia.
- **Frames and buildings**: only `structure_01` has been compared with a reference.
  `building_02` has none.
- **Single-axis end releases between members, and skew supports**: not modelled.
- **Mixed U1 and native beams**: known to be wrong (joints act as pins).
- **Buckling** beyond the single Euler column.
