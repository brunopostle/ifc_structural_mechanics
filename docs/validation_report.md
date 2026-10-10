# Validation Report

This report documents numerical accuracy tests for the `ifc_structural_mechanics` analysis
pipeline. Tests are grouped into two tiers:

- **Tier 1** — hand-crafted CalculiX input files run directly against the solver. These
  isolate the solver and result parser from IFC extraction, meshing and input writing.
- **Tier 2** — the full IFC → Gmsh → CalculiX → `results.json` pipeline, compared with
  closed-form beam theory. These are the tests that catch errors in section orientation,
  section properties, supports and loads.

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
(bending plus shear deflection).

`cantilever_01`: L = 3 m, fully fixed at one end, E = 210 MPa, ν = 0.2, ρ = 7.8 kg/m³,
loaded by self-weight. `beam_01`: L = 4 m, both ends fully fixed, 20 kN at midspan,
0.3 m square, E = 30 GPa.

| Case | Section and element | Reference | Pipeline | Error |
|------|---------------------|-----------|----------|-------|
| Cantilever, strong axis (as authored) | 0.2 × 0.4 rectangle, B31 | 0.2814 mm | 0.2806 mm | 0.3% |
| Cantilever, weak axis (`Axis` rotated 90°) | 0.2 × 0.4 rectangle, B31 | 1.1115 mm | 1.1106 mm | 0.1% |
| Cantilever reaction | 0.2 × 0.4 rectangle, B31 | 18.36 N | 18.21 N | 0.8% |
| Cantilever, strong axis | 200 × 400 I, U1 | 0.1419 mm | 0.1419 mm | < 0.1% |
| Cantilever, weak axis | 200 × 400 I, U1 | 1.6144 mm | 1.6140 mm | < 0.1% |
| Fixed-fixed beam, midspan | 0.3 m square, B31 | 0.3505 mm | 0.3467 mm | 1.1% |
| Fixed-fixed beam, reaction | 0.3 m square, B31 | 20.00 kN | 20.00 kN | 0.0% |

**Tolerance**: 3% on deflection, 2% on the self-weight reaction. **Status**: PASS

The reaction under self-weight is low by half an element's weight: CalculiX does not
report the share of a distributed load that lands on the restrained node.

The cantilever's strong-axis orientation was confirmed independently against
IfcOpenShell's Code_Aster reference for the same file
(`examples/analysis-models/models/cantilever_01/cantilever_01.comm`), which places the
0.4 m dimension along the member's local z.

These tests exist because of what they found when first written: beam sections rotated
90° (strong and weak axes swapped), point supports restraining neighbouring mesh nodes,
and wrong inertia formulas for I, L and C sections.

---

## Tier 2: Against Code_Aster

**Source**: `tests/validation/test_pipeline_benchmarks.py` (`TestCodeAsterReferences`)

The example-models submodule ships IfcOpenShell's IFC2CA results for the same IFC files:
Code_Aster with Euler beams and DKT shells under self-weight (g = 9.806 m/s²). The
reference value is the largest nodal translation in
`examples/analysis-models/models/<name>/<name>.rmed`.

| Model | Code_Aster | This library | Mesh | Error | Tested |
|-------|-----------|--------------|------|-------|--------|
| `cantilever_01` | 0.2766 mm | 0.2806 mm | 0.05 m | +1.4% (shear deflection) | yes, 3% |
| `structure_01` | 0.4273 mm | 0.3752 / 0.4724 / 0.5609 mm | 1.0 / 0.5 / 0.25 m | −12% / +11% / +31% | yes, 25% at 0.5 m |
| `slab_01` | 0.3761 mm | 0.056 / 0.108 / 0.143 mm | 1.0 / 0.5 / 0.25 m | −62% at best | no |
| `grid_of_beams` | 0.3963 mm | 0.489 / 0.326 / 1.380 mm | 1.0 / 0.5 / 0.25 m | does not converge | no |

`portal_01` also has a reference file, but it was run in inch and pound units with
metric gravity, so it is not comparable.

What the comparison shows:

- `structure_01` is in the right range but not converged. Linear S3 shells converge
  slowly, and the slab-to-wall edge hinge is not modelled.
- `slab_01` is too stiff because the rotational release along its supported edges is
  ignored. By hand the clamped value is 0.171 mm and the simply supported value 0.854 mm.
- `grid_of_beams` has single-axis end releases, which are analysed as full pins.

Before 2026-10-10 `structure_01` gave between 1.7 and 17 mm. Getting it to 0.4 mm took
five fixes: rigid joints that were really pins, joints written as fixed supports, a line
support reduced to one node, slabs given a default steel material, and load cases that
accumulated from step to step.

---

## Example Model Baselines

Full pipeline, default 1.0 m mesh. These are **regression baselines, not validated
results**, except where a Tier 2 test covers the model.

| Model | Load flag | Max displacement | Vertical reaction | Standing |
|-------|-----------|------------------|-------------------|----------|
| `beam_01` | — | 0.26 mm | 20.0 kN | Covered by Tier 2 at a finer mesh; the 1.0 m mesh is 25% stiff |
| `cantilever_01` | `--gravity` | 0.28 mm | 15 N | Covered by Tier 2 |
| `structure_01` | `--gravity` | 0.38 mm | 632 N | Covered by Tier 2 (Code_Aster) |
| `slab_01` | `--gravity` | 0.06 mm | 198 N | Known too stiff |
| `grid_of_beams` | `--gravity` | 0.49 mm | 244 N | Known not to converge |
| `portal_01` | — | 3.1 mm | 85.4 kN | Unchecked. All-U1 model |
| `building_02` | — | 99 mm (Live), 252 mm (Extra_dead) | 29.4 MN | Unchecked. 25.5 mm under self-weight; about half these values at a 2 m mesh |
| `building_01` | — | — | — | Fails: singular stiffness matrix |

---

## What is not yet validated

- **Distributed loads** (`IfcStructuralCurveAction`): exercised by `portal_01` but not
  compared with a reference.
- **Pinned and roller supports** through the pipeline (Tier 1 covers them in CalculiX only).
- **Shell members**: no plate-theory benchmark for `IfcStructuralSurfaceMember`.
- **T, L and C sections**: section properties are unit-tested against hand calculations,
  but no pipeline benchmark exists. L sections ignore the product of inertia.
- **Frames and buildings**: only `structure_01` has been compared with a reference.
  `building_02` has none.
- **Edge releases and single-axis end releases**: not modelled (see above).
- **Mixed U1 and B31 beams**: known to be wrong (joints act as pins).
- **Buckling** beyond the single Euler column.
