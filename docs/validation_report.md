# Validation Report

This report documents numerical accuracy tests for the `ifc_structural_mechanics` analysis
pipeline. Tests are grouped into two tiers:

- **Tier 1** — hand-crafted CalculiX input files run directly against the solver. These
  tests isolate the solver and result parser from the IFC extraction and meshing stages,
  and compare against known analytical solutions.
- **Tier 2** — full IFC → Gmsh → CalculiX pipeline run against real IFC files. These
  check that the end-to-end workflow produces physically plausible results, but do not
  have analytical reference solutions to compare against.

The Tier 1 tests are in `tests/validation/` and are run automatically by `pytest`. They
require CalculiX to be installed (`ccx` on PATH) and are skipped otherwise.

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

A symmetric (square) cross-section is used deliberately to avoid sensitivity to beam
normal vector orientation. For asymmetric sections (I-sections, T-sections, etc.) the
orientation of the cross-section relative to the bending plane significantly affects
results. This is a known limitation; see `VISION.md` Phase 1 for the planned
`SECTION=GENERAL` work.

At pin supports, the cross-section is free to rotate. The expanded corner nodes at x = 0
and x = 2 therefore have non-zero transverse displacement due to end rotation. The test
verifies that the *average* displacement across corner nodes is near zero (as expected:
rotation makes upper and lower corners displace in opposite directions).

---

## Tier 2: Full Pipeline — Example Model Regression Baselines

These results were obtained by running the full IFC → Gmsh → CalculiX pipeline on the
example models in `examples/analysis-models/`. They are regression baselines, not
comparisons against independent analytical solutions. Significant changes from these
values indicate a regression in the pipeline.

| Model | Load flag | Max displacement | Reaction | Notes |
|-------|-----------|-----------------|----------|-------|
| `beam_01` | — | 0.26 mm | 20 kN | Simply supported beam, point load |
| `portal_01` | — | 0.55 mm | 1265 / 5007 N | Portal frame |
| `cantilever_01` | `--gravity` | 1.1 mm | 69 / 15 N | Cantilever, self-weight |
| `slab_01` | `--gravity` | 0.39 mm | 198 kN | Flat slab |
| `structure_01` | `--gravity` | 2.8 mm | 634 kN | Mixed beam/shell structure |
| `building_01a` | `--gravity` | 14 mm | 275 kN | Multi-storey building, gravity |
| `building_02` | — | 80 mm | 29 MN | Larger building, lateral load |

Models not in the table are known to have unresolved issues:

| Model | Issue |
|-------|-------|
| `grid_of_beams` | Near-mechanism: corner supports at intermediate beam positions are not located by the node search (known limitation). No material density in IFC, so gravity load produces near-zero self-weight. |
| `building_01` | Near-mechanism under lateral load: pinned column bases with no moment-resisting connections. This is a modelling issue, not a solver issue — `building_01a` (gravity load only) is stable. |

---

## What is not yet validated

The following are not covered by current Tier 1 tests. They represent areas where
numerical accuracy is less certain:

- **Non-square beam sections**: I-sections, T-sections, L-sections. Currently
  approximated as equivalent rectangles in CalculiX. The approximation cannot match
  both strong-axis and weak-axis moments of inertia simultaneously. A `SECTION=GENERAL`
  implementation (see `VISION.md`) would remove this limitation.
- **Shell/plate elements**: `IfcStructuralSurfaceMember` (slabs, walls). No Tier 1
  benchmark with analytical reference solution exists yet.
- **Linear buckling**: The two-step buckling INP is implemented but eigenvalue results
  have not been compared against an analytical Euler column solution.
- **Distributed loads on beams**: `IfcStructuralCurveAction` handling is exercised by
  integration tests but not compared against analytical results (e.g. `wL⁴/(8EI)` for
  uniformly distributed load on a cantilever).
