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
loaded by self-weight. `beam_01`: L = 4 m, both ends fully fixed, 0.3 m square,
E = 30 GPa, 2500 kg/m³. As shipped its one load case has 20 kN at midspan and the
beam's own weight (2207 N/m); the rows that name a single load are variants with the
weight taken out of the case.

| Case | Section and element | Reference | Pipeline | Error |
|------|---------------------|-----------|----------|-------|
| Cantilever, strong axis (as authored) | 0.2 × 0.4 rectangle, B32R | 0.2814 mm | 0.2800 mm | 0.5% |
| Cantilever, weak axis (`Axis` rotated 90°) | 0.2 × 0.4 rectangle, B32R | 1.1115 mm | 1.1059 mm | 0.5% |
| Cantilever reaction | 0.2 × 0.4 rectangle, B32R | 18.36 N | 18.36 N | 0.0% |
| Cantilever, strong axis | 200 × 400 I, equivalent rectangle | 0.1419 mm | 0.1417 mm | 0.2% |
| Cantilever, weak axis | 200 × 400 I, equivalent rectangle | 1.6087 mm | 1.5972 mm | 0.7% |
| Cantilever reaction | 200 × 400 I, equivalent rectangle | 2.663 N | 2.663 N | 0.0% |
| Cantilever, strong axis | 200 × 400 I, U1 (`--open-sections user-element`) | 0.1419 mm | 0.1419 mm | < 0.1% |
| Cantilever, weak axis | 200 × 400 I, U1 | 1.6144 mm | 1.6143 mm | < 0.1% |
| Cantilever | 150 mm round bar, equivalent rectangle | 0.6602 mm | 0.6584 mm | 0.3% |
| Cantilever | 300 × 10 mm tube, equivalent rectangle | 0.3579 mm | 0.3535 mm | 1.2% |
| Cantilever | 200 × 400 × 10 mm box, equivalent rectangle | 0.1814 mm | 0.1793 mm | 1.2% |
| Fixed-fixed beam as shipped (20 kN and its weight), midspan | 0.3 m square, B32R | 0.4280 mm | 0.4252 mm | 0.6% |
| Fixed-fixed beam as shipped, reaction | 0.3 m square, B32R | 28.829 kN | 28.829 kN | 0.0% |
| Fixed-fixed beam, its weight alone, midspan | 0.3 m square, B32R | 0.0774 mm | 0.0765 mm | 1.2% |
| Fixed-fixed beam, 5 kN/m along global −Z | 0.3 m square, B32R | 0.1753 mm | 0.1733 mm | 1.1% |
| Fixed-fixed beam, 5 kN/m along global +Y | 0.3 m square, B32R | 0.1753 mm | 0.1733 mm | 1.1% |
| Fixed-fixed beam, line-load reaction | 0.3 m square, B32R | 20.00 kN | 20.00 kN | 0.0% |
| Fixed-fixed beam, midspan, 20 kN | 200 × 400 I, equivalent rectangle | 1.0776 mm | 1.1002 mm | 2.1% |
| Fixed-fixed beam, 5 kN/m along global −Z | 200 × 400 I, equivalent rectangle | 0.5388 mm | 0.5389 mm | < 0.1% |
| Slab on two cantilever beams under its edges | 0.2 × 0.4 beams, 0.1 m slab, B32R + S6 | 3.360 mm | 3.376 mm | 0.5% |
| Slab on two cantilever beams inside it | 0.2 × 0.4 beams, 0.1 m slab, B32R + S6 | 3.360 mm | 3.358 mm | 0.1% |
| Slab on two cantilever beams, reaction | 0.2 × 0.4 beams, 0.1 m slab, B32R + S6 | 99.47 N | 99.47 N | 0.0% |
| Same, each beam's own entry in `results.json` | 0.2 × 0.4 beams, 0.1 m slab, B32R + S6 | 3.360 mm | 3.362 mm | 0.1% |
| Slab on two cantilever beams inside it | 200 × 400 I beams (equivalent rectangle), 0.1 m slab | 4.913 mm | 4.951 mm | 0.8% |

**Tolerance**: 3% on deflection, 0.01% on the self-weight reaction. **Status**: PASS

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
| Fixed-fixed beam as shipped (20 kN and its weight) | Shear at the ends, (P + w L) / 2 | 14.4145 kN | 14.4140 kN | < 0.1% |
| Fixed-fixed beam as shipped | Moment at the ends, P L / 8 + w L² / 12 | 12.943 kN·m | 12.951 kN·m | 0.1% |

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
cross-sections, and the fixed-fixed beam as shipped, where the shear steps by P at
midspan, from −P/2 to +P/2 with both values listed there, and grows by the beam's
weight towards each end, and the moment runs from P L/8 + w L²/12 at the supports to
−(P L/8 + w L²/24) under the load. The solver's own stress at the loaded cross-section is
the average of the two sides, which would give zero shear there; the step is rebuilt
from the cross-sections at the middle of each element, which belong to one element only.

Two checks without a hand value: in `portal_01`, loaded on the right half of its beam,
the columns carry 10.14 and 32.56 kN, which add up to the 42.70 kN reaction, and the
beam's largest end shear is the same 32.56 kN, while the column shear and the beam's
axial force are both 6.21 kN. In `structure_01` the pin-ended column has an axial force
and no moment.

Until 2026-10-11 the reaction under self-weight came out low by the load on the
restrained node itself (a sixth of an element's weight for a quadratic element), because
CalculiX does not report the share of a load that lands there. The results now add it
back; see Support reactions below.

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
set so that the rectangle has the profile's shear stiffness in each direction (open
profiles) or its torsional stiffness (tubes, boxes and round bars; see Torsion below);
without that the stocky I cantilever was 5.5% too stiff. The I-section fixed-fixed beam is a hard
case, with 37% of its deflection coming from shear in the web.

The shear moduli are set against the rectangle's whole area, not the 5/6 of it that beam
theory gives a rectangle. That is a calibration: with 5/6 the shear deflection of the I
benchmarks came out 12 to 18% short, and with the whole area the simply supported I beam
below has it within 5%. An ordinary isotropic rectangle does follow 5/6 (the simply
supported 0.3 m square below matches to 0.01%), so the difference belongs to these
strongly orthotropic materials.

What the equivalent rectangle does not have is the profile's stresses, so
`results.json` takes them from the section forces. Nor can it have the profile's shear
and torsional stiffness at once; see Torsion below. U1 elements with a general section remain available with
`--open-sections user-element` for models made of such members only. On `portal_01` the
two agree: 2.172 mm with equivalent rectangles and 2.181 mm with U1 at a 0.25 m mesh.

**T, angle and channel**, all 200 × 400 mm, as cantilevers under self-weight about both
axes (0.05 m mesh, tolerance 3%). The reference uses the second moments about the
centroidal axes parallel to the legs, computed in the test from the section's rectangles.

| Section | Strong axis: theory / pipeline | Weak axis: theory / pipeline |
|---------|-------------------------------|------------------------------|
| T | 0.2405 / 0.2401 mm (0.2%) | 2.1608 / 2.1501 mm (0.5%) |
| Angle | 0.2264 / 0.2261 mm (0.2%) | 1.2464 / 1.2423 mm (0.3%) |
| Channel | 0.1419 / 0.1417 mm (0.2%) | 0.8772 / 0.8721 mm (0.6%) |

For the angle this is the library's assumption rather than the whole truth: its principal
axes are rotated, and a real angle also moves sideways. A channel is an
`IfcUShapeProfileDef`. Until 2026-10-11 the extractor looked for an entity name that does
not exist in IFC, so every real channel became a default 0.1 × 0.2 m rectangle without a
word (682% out on this case). A profile the library cannot read, a Z section for
instance, now stops the analysis with an error naming the member and the profile.

**Simply supported beam**: `beam_01` on a pin and a roller, 0.25 m mesh.

| Case | Quantity | Theory | Pipeline | Error |
|------|----------|--------|----------|-------|
| 20 kN at midspan, 0.3 m square | Deflection | 1.3382 mm | 1.3383 mm | < 0.1% |
| 20 kN at midspan, 0.3 m square | Moment / shear | 20.000 kN·m / 10.000 kN | 20.000 / 9.9996 | < 0.1% |
| 5 kN/m, 0.3 m square | Deflection | 0.8337 mm | 0.8337 mm | < 0.1% |
| 5 kN/m, 0.3 m square | Moment at midspan | 10.000 kN·m | 10.026 kN·m | 0.3% |
| 5 kN/m, 200 × 400 I | Deflection | 1.8940 mm | 1.8983 mm | 0.2% |

A pin here holds the three translations and rotation about the beam's axis. Supports that
hold the translations alone, at both ends, leave the beam free to turn about its own
axis. The solver does not object; it returns an arbitrary rotation, and the deflection
read on the faces of the 0.3 m section came out as 2.92 mm instead of 1.34. Such a member
is now held in torsion at one support and the analysis says so; the same case then gives
1.3383 mm.

**Torsion**: a 3 m cantilever with a 1 m arm at right angles on its tip and 1 kN on the
end of the arm (0.125 m mesh). Statics fixes the forces whatever the stiffness: the
pipeline gives a torque of 999.99 N·m in the cantilever and moments of 2999.98 and
999.99 N·m at the two roots.

The torsional stiffness each section is analysed with is read from the solver's own
nodes: the rotation of two cross-sections of the cantilever, a metre apart, under the
known torque.

| Section | Model | J used / J true |
|---------|-------|-----------------|
| 0.3 m square | CalculiX's rectangle as it comes | 1.185 |
| 0.2 × 0.4 m rectangle | CalculiX's rectangle as it comes | 1.164 |
| 0.3 m square | rectangle, width modulus lowered | 1.002 |
| 0.2 × 0.4 m rectangle, deep or flat | rectangle, width modulus lowered | 1.000 |
| 0.1 × 0.4 m rectangle | rectangle, width modulus lowered | 1.000 |
| 300 × 10 tube | equivalent rectangle, torsion matched | 1.000 |
| 300 × 40 tube | equivalent rectangle, torsion matched | 1.000 |
| 200 × 400 × 10 box | equivalent rectangle, torsion matched | 1.000 |
| 300 × 300 × 20 box | equivalent rectangle, torsion matched | 1.000 |
| 200 mm round bar | equivalent rectangle, torsion matched | 1.000 |
| 200 × 400 I | equivalent rectangle, shear matched | 29.9 |

Four things are going on here.

*CalculiX's rectangle is too stiff in torsion.* It puts one solid element across the
section, and the only warping that element can take is x₂x₃. That gives
J = a³b³ / 3(a² + b²) in place of Saint-Venant's value: a⁴/6 against 0.1406 a⁴ for a
square. The measured 1.185 and 1.164 are this formula to three figures, and were what
the pipeline gave until 2026-10-11.

*Solid rectangles now have one shear modulus lowered.* The formula has two shear moduli
in it. The one for the plane of the member's axis and the section's depth is kept; the
one across the width is lowered until the formula gives Saint-Venant's value. The rows
"width modulus lowered" are the result, the same with linear and quadratic elements (the
square's 1.002 is the rounding of 0.1406). What it costs was measured on hand-written
cantilevers, 3 m and 1.5 m long, comparing the centre line with the same beam left
isotropic:

| Section (depth × width) | Width modulus | Deflection along the depth | Deflection along the width, 3 m | 1.5 m |
|---|---|---|---|---|
| 0.3 × 0.3 m | 0.73 G | 1.0000 | 1.0028 | 1.0107 |
| 0.4 × 0.2 m | 0.55 G | 1.0000 | 1.0032 | 1.0116 |
| 0.2 × 0.4 m | 0.83 G | 1.0000 | 1.0027 | 1.0102 |

Loaded along the width, each follows Timoshenko's beam with 5/6 of the lowered modulus as
closely as the isotropic one follows it with the real one (0.5% at 3 m, 1.2% at 1.5 m,
both from the clamped end). So the shear stiffness across the width is down by 27%, 45%
and 17%, nothing else has moved, and the analysis says so in a warning with the number of
members and the largest reduction. Of the example models, five give the same four figures
as before; `grid_of_beams` rose from 0.3727 to 0.3732 mm, `building_01` from 0.2857 to
0.2864 mm under Live and from 6.66 to 6.78 mm under self-weight, and `building_02` from
25.6 to 25.7 mm under Live. Reactions are unchanged.

The same check found the torsion constant the domain model computed for a rectangle
sixteen times too large (the formula is in half sides and was given whole ones, the wrong
way round). Nothing used it before this.

*Tubes, boxes and round bars are given their own torsion constant.* The equivalent
rectangle's two shear moduli are scaled by one number until the formula above gives G J
for the section. The cost is shear stiffness, too high by the same number: 1.11 for the
round bar, 1.40 for the 200 × 400 × 10 box, 1.88 for the 300 × 10 tube. That is why the
tube and box cantilevers in the table above are 1.2% stiff where they used to be 0.2%.
Before this change the same sections had the right shear stiffness and 0.53, 0.71 and
0.90 of their torsional stiffness.

*Open sections cannot be treated the same way.* The I section would need its shear
moduli cut thirtyfold. It keeps its shear stiffness and is 30 times too stiff in
torsion. U1 elements (`--open-sections user-element`) are no better: 267 times for the
same I section and 1.6 for the box, measured from the tip deflection. Where open sections
carry torsion, neither model can be trusted.

An earlier version of this section said that a solid square matched theory to 0.9% and
gave 0.47, 0.67, 0.83 and 31 for the other sections. Those came from the tip deflection
with the bending taken out. Deflections are read on the faces of the expanded elements,
where the arm's rotation adds to them, and for the square that addition happened to
cancel an 18% error in the twist.

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

The same plate under an `IfcStructuralPlanarAction` of 2.5 kPa along global −Z, in a load
case of its own, gives 0.01250 mm at a 0.5 m mesh against 0.01220 mm (+2.4%, tolerance
5%), and a reaction of 37.50 kN, the whole load. Given along global X instead, the
same load does not bend the plate.

**Columns meeting a slab with no connection.** The plate with its supports removed and
four 0.3 m square columns, fixed at their bases, standing under its quarter points. The
file has no connection between slab and columns. Read literally the slab is in the air:
with `--strict-connections` the run reports a displacement of 5 × 10⁵ km and a probable
mechanism. By default each column is pinned to the slab where it meets it, and carries a
quarter of the slab plus its own weight: 78.05 N at the base against 78.05 N by statics.
With the columns continued 1 m above the slab, 84.93 N against 84.93 N.

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
| `grid_of_beams` | 0.3963 mm; 0.367 mm without the weight of its rigid arms | 0.3723 / 0.3731 / 0.3732 mm | 1.0 / 0.5 / 0.25 m | +1.7% against 0.367 | yes, 3% at 0.5 m, and 1% between meshes |

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

`portal_01` also has a Code_Aster file, but it was run in inch and pound units with
metric gravity, so it is not comparable. Its IFC file holds the results of the program
that wrote it, for its own load case, and those are compared below (A load on part of
a member).

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
| `beam_01` | — | 0.41 mm | 28.8 kN | 20 kN and its own weight. Covered by Tier 2 at a finer mesh; the 1.0 m mesh is 3% stiff |
| `cantilever_01` | `--gravity` | 0.28 mm | 18.4 N | Covered by Tier 2 |
| `structure_01` | `--gravity` | 0.429 mm | 660 N | Covered by Tier 2 (Code_Aster) |
| `slab_01` | `--gravity` | 0.173 mm | 230 N | Covered by Tier 2 (beam theory) at 0.5 m; 5% stiff at 1.0 m |
| `grid_of_beams` | `--gravity` | 0.372 mm | 273 N | Covered by Tier 2 (Code_Aster, corrected) |
| `portal_01` | — | 2.15 mm | 42.7 kN | Reactions against the results in the file (Tier 2). 2.17 mm at 0.25 m; 2.06 and 2.18 mm with U1 elements. Until 2026-10-12 it was loaded on the whole beam, twice what the file says: 4.04 mm and 85.4 kN |
| `building_02` | — | 16.8 mm (Dead), 25.7 mm (Live), 15.3 mm (Extra_dead) | 67.0 MN (Dead), 30.0 MN (Live), 60.3 MN (Extra_dead) | At a 2 m mesh. `Dead` is the self-weight. At 4 m (measured before `Dead` was a case, with `--gravity`): 15.7 / 24.1 / 14.4 mm. Reactions match the applied loads; deflections plausible but not compared with a reference |
| `building_01` | — | 6.78 mm (Dead), 0.286 mm (Live), 0.10 mm (floor finishing) | 48.55 MN (Dead), 282.0 kN (Live), 13.5 kN (floor finishing) | `Dead` is the self-weight, nearly all of it a `Masonry` of 202 t/m³. At 0.5 and 0.25 m: 7.90 and 8.63 mm (Dead), 0.338 and 0.352 mm (Live). Reactions match the applied loads; deflections unchecked |

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
steps are 30.017 and 60.286 MN.

With the loads right, the Live case still gave 462 mm, on the 8.5 m × 21.4 m ground-floor
slab that carries 16 kPa. The IFC file connects every slab at its four corners and
nowhere else: 576 beams and columns lie along slab edges or in walls with no connection
between the corners, and this slab also passes two columns on each long side that it is
not connected to. Beam and shell meshes have separate nodes, so the slab spanned 21 m
from corner to corner and the beams under its edges carried nothing (0.1 mm of
deflection in the edge beam, 408 mm in the slab edge beside it).

A curve member lying in a surface member is now tied to it in translation along its
length, and the analysis says so in a warning. The Live maximum is 25.7 mm, and this
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

## Input that is refused or reported

An audit of the error handling (2026-10-11) found about 215 handlers that caught every
exception, most of which logged a line and carried on with a default or without the
entity. A member that could not be read was left out of the structure; a material with
no stiffness was analysed as steel; a slab with no thickness was 0.1 m thick; a support
or a load with no position went to the origin, or the load to node 2; a distributed load
that named no member went on the first member of the model; a force that could not be
read became 1 kN. None of this reached the results.

Seventy-one such handlers remain. Fifty-six turn the exception into an error of the
stage it happened in, naming the entity; the other fifteen are cleanup (closing Gmsh,
temporary files) or already put a warning in the results. About 4,000 lines that the
pipeline never ran went with them, including a second section-and-material extractor
whose only effect was to hang a default 0.1 × 0.2 m section on every slab.

The example models are unaffected: none of the removed fallbacks fired on them, and
their deflections and reactions are those of the tables above. Two things they did hide
are now in their results:

- `portal_01`: its steel has no Poisson's ratio in the file; 0.3 was assumed. The file
  gives a shear modulus, and since `aiz.83` Poisson's ratio is taken from it
  (E / 2G − 1 = 0.2946), with no warning; the reactions moved by under 0.01%.
- `building_01`: seven members overlap others and one is left with no elements of its
  own (a landing lying in a floor slab); where two overlap, the stiffness is that of the
  member that comes first in the file.

`tests/unit/ifc/test_extraction_fails_loudly.py` takes things out of the example files
one at a time (a material, a thickness, a position, a load group) and checks that each
is an error or a warning that names what is missing.
`tests/unit/analysis/test_loads_are_never_made_up.py` does the same for the load writer.

## Legacy code removed

A second pass (2026-10-11), over code rather than exception handlers: every function of
the library was traced through the validation suite and four command-line runs, and what
no run reached was read. About 3,300 lines of source went, and 1,400 of tests. Most were dead; these were not, and each
could have changed an answer without saying so:

| What it did | Now |
|---|---|
| A model with no supports had every node at y = 0 fully fixed | Error: the model has no supports |
| A support with no mesh node within 0.1 m was left out | Error naming the support |
| A line support with no node on its edge became a point support at its midpoint | Error |
| A connection of type "rigid" holding one member was a fixed support, condition or not | Restrains nothing without a support condition |
| The solver ran `model.inp` instead of the input it was given, if one five times larger lay beside it | Runs the input it is given |
| An input file left by an earlier run in the output directory was solved instead of the new one | The new one always replaces it |
| The solver's input was edited (a `*HEADING` inserted) and, after some errors, edited again and rerun | Run as written, once |
| Result files of any name in the directory were collected if the run's own were missing | Only the run's own |
| Results that could not be read or exported gave `"success"` with a warning | `"failed"`, with the error |
| A result file with no displacements read as a structure that does not move | Error |
| An unknown meshing algorithm became Delaunay | Error |
| The mesh writer created an empty file in place of a mesh when it ran under pytest | Removed |

None of these fired on the example models, whose deflections and reactions are unchanged
(checked on seven of them before and after, and on `building_02` by the slow tests). They
did fire in the test suite: about 25 tests built models with no supports and passed because the
writer invented them, and two tests of the Python API passed with `"success"` although
the results had failed to parse. Those tests now build supported models and stand-in
results.

Also found: `ifc-analysis --json-output` had not worked for some time. It tried to
serialise the domain model and exited with code 99. It now prints one JSON document.

`tests/unit/analysis/test_supports_are_never_made_up.py` and
`tests/unit/analysis/test_correct_inp.py` hold the new rules.

## Placements

An item's points and directions are in the axes of its `ObjectPlacement`. Every example
model leaves that placement at the origin, so the code that reads it had never run on
anything but the identity, and it was wrong in three ways (2026-10-11):

- a member's offset was added to coordinates already in metres without being converted
  itself, so in a file in millimetres a member placed 2 m away landed 2 km away;
- point connections and loads did not apply their placement at all, so the supports
  and loads of such a model stayed where the member had been;
- a placement relative to another one was read without its parent (and, since the
  error-handling audit, refused).

The whole chain of placements is now applied, in metres, to member geometry and `Axis`,
connection positions, edges and condition axes, release axes, load positions and the
forces of loads given in "global" coordinates (which IFC defines as the axes of the
action's placement).

`TestPlacedModel` gives every item of an example one nested placement, 13.5 m away and
a quarter turn about Z, and runs it beside the file as shipped. Measured at the mesh
sizes of the test:

| Model | Unit | Largest displacement, shipped | placed | Vertical reaction, shipped | placed |
|---|---|---|---|---|---|
| `beam_01` | mm | 0.4228 mm | 0.4228 mm | 28 829 N | 28 829 N |
| `portal_01`, gravity | inch | 105.12 mm | 105.12 mm | 4 826 215 N | 4 826 215 N |
| `structure_01`, gravity | m | 0.4333 mm | 0.4335 mm | 660.20 N | 660.20 N |
| `building_01`, Live (1 m, not in the suite) | mm | 0.2857 mm | 0.2857 mm | 282 000 N | 282 000 N |

The X and Y displacement components change places, as they should. `structure_01`
differs in the fourth figure because its slab is meshed afresh in the new position.
`tests/unit/ifc/test_object_placement.py` checks the extraction alone, with a placement
that also tilts: every member, connection, axis and load of five examples must be the
original moved and turned.

Not covered: items of one model under different placements (the code treats each item
by its own placement, but the tests give them all the same one). A model turned so
that its supports are skew to the global axes is under Skew supports, below.

## Support reactions

`results.json` gives the reaction at every support (`supports`, schema 1.1), and three
things about CalculiX's own figures were found on the way (2026-10-11).

**A load applied at a support node is not in the reaction CalculiX reports.** `RF` is the
force inside the structure at the node. On a 2 m beam fixed at one end and held
vertically at the other, 100 N down on the held node reads as no force there, and 70 N
along its free direction reads as 70 N. Distributed loads and self-weight put a share on
every node, so every total was short by the share on the support nodes, more on a coarse
mesh. The loads written at support nodes are now recorded and taken off:

| Model, self-weight | Weight | Reaction before, at 1.0 / 0.5 / 0.25 m | Now, at any of them |
|---|---|---|---|
| `cantilever_01` | 18.36 N | 17.34 / 17.85 / 18.11 N | 18.36 N |
| `structure_01` | 660.2 N | 651.2 / 655.9 / 657.9 N | 660.2 N |
| `slab_01` | 229.6 N | 219.7 / 224.4 / 226.6 N | 229.6 N |
| `grid_of_beams` | 273.2 N | 265.6 / 267.8 / 270.0 N | 273.2 N |

The 2.5 kPa plate went from 34.8 to 37.50 kN, and a pin-ended beam under 5 kN/m from
19.58 to 20.00 kN at a 0.25 m mesh. `global_reactions` now also gives the load applied in
each case and what is left when the two are added: under 3 parts in ten million on every
example, `building_02` included (30.017, 60.286 and 66.968 MN).

**CalculiX gives a node no reaction moment.** With `RF` under `*NODE FILE` it does write
the force on every node of the solids it expands beams and shells into. The forces on the
nodes a support's own were expanded into, taken about the support, are its moment
(`94g.8`): at the end of a member, along a clamped slab edge and where a member runs on
past its support. Like the forces they balance the loads, so where statics decides the
moment it is met at any mesh size:

| Case | Statics | Pipeline | Error |
|---|---|---|---|
| `cantilever_01`, root moment | 27.546 N·m | 27.546 N·m | none in five figures |
| Cantilever with an arm, root: bending and torque | 3000 and 1000 N·m | 3000.0 and 1000.0 N·m | none in six figures |
| `slab_01` clamped along one edge only, 2 kN/m², moment about the edge, 2 / 1 / 0.5 m mesh | 75 000 N·m | 75 000.0 / 75 000.0 / 75 000.0 N·m | under 1 in a million |
| Bar clamped 1 m from one end and 2 m from the other, loads at both ends | −5000 N·m | −5000.0 N·m | none in six figures |
| `beam_01`, fixed-end moments, P L / 8 + w L² / 12, 0.5 / 0.25 / 0.1 / 0.05 m mesh | ∓12 943 N·m | ∓12 997 / 12 971 / 12 958 / 12 954 N·m | 0.4 / 0.2 / 0.1 / 0.1% |
| `portal_01`, feet, against a plane frame with the same shear area, 0.25 m mesh | 7175.0 and −4549.6 N·m | 7236.2 and −4611.4 N·m | 0.9 and 1.4% |

Where statics does not decide it (`beam_01`, the portal) the moment is the mesh's own: it
converges as the displacements do. The section forces at the same member end, which is
where these moments came from before, are integrated from stresses taken to the end of an
element, and differed from the support's moment by w h² / 12 under a load of w along an
element of length h (measured on `beam_01`: 46.1, 11.5 and 1.9 N·m at 0.5, 0.25 and
0.1 m; they gave the cantilever's root 0.1% low at 0.25 m).

**The moment along an element** (`aiz.89`). That difference is the expanded element's:
its stress is the straight line through its two integration points, and where the
moment is a parabola the line is above it by w h² / 12 at the ends and below it by
w h² / 24 at the middle, all along the member. Statics between two cross-sections was
met all the same (root and midspan of `beam_01` were both shifted), so the diagrams
were within the 1% they are checked to. The shear under such a load is a straight line,
which the element has right, and w h is its change along the element, so the diagram
is put right with that and nothing assumed of the load:

| Case | Before | After |
|---|---|---|
| `beam_01`, diagram's end moment less the support's, 0.5 / 0.25 / 0.1 m mesh | 46.1 / 11.5 / 1.9 N·m | 0.12 / 0.06 / 0.11 N·m |
| `cantilever_01`, 0.5 m mesh, largest difference from w (L − x)² / 2 | 0.128 N·m | 0.0002 N·m |
| `cantilever_01`, root moment from the member end, 0.5 m mesh (statics 27.546) | 27.42 N·m | 27.55 N·m |
| `beam_01`, midspan plus end moment, 0.5 m mesh (P L / 4 + w L² / 8 = 24 414.5) | 24 414.3 N·m | 24 414.3 N·m |

The support moments, which come from the solver's nodal forces, do not change; on
CalculiX 2.21, where they come from the member ends, they now have the same accuracy.

Supports that had no moment before have one now: the clamped edges of `slab_01`
(∓96.1 N·m under its weight, w L² / 12 being 95.6), the wall foot of `structure_01`, the
four supports of `grid_of_beams`, whose main beams overhang by 0.1 m (58.1 N·m each), and
all 49 supports of `building_02` that hold a rotation, 23 of which had none. The moment is
still left out, not given as zero, where the solver's forces are wrong (below) and no
member ends there, or where a node has a user element.

**CalculiX 2.21 misreports the force at a support that holds a rotation.** CI installs
2.21 (Ubuntu 24.04); development was on 2.23. The same input file gives the same
displacements in both and different reactions:

| Case | True | 2.23 | 2.21 |
|---|---|---|---|
| Bar pulled with 1000 N and bent, clamped end, force along it | 1000 N | 1000.0 N | 1076.6 N |
| `portal_01`, vertical force at the two feet | 10 135 and 32 568 N | 10 137 and 32 565 N | 6246 and 31 784 N |
| `beam_01` with its point load only, resultant force at one end | 10 000 N | 10 000 N | 11 390 N |
| Cantilever with an arm, vertical force at the root | 1000 N | 1000 N | 444 N |
| `structure_01`, total | 660.2 N | 660.2 N | 667.9 N |

In `beam_01` the errors of the two ends cancel in the total, so checking the total
against the load is not enough. Each support that holds a rotation is compared with the
forces at the ends of its members: more than 3% apart, or a total that does not balance,
and the member ends' forces are used (good to about 1%; `"forces": "member_end_forces"`).
The moments go the same way: on 2.21 the forces on the expanded nodes are wrong where the
printed force is (`cantilever_01`: 25.28 N·m for 27.55 at the root, with 11.3 N along the
member that is not there) and the same as 2.23's elsewhere (the edges of `slab_01`, the
wall foot of `structure_01`, the supports of `grid_of_beams`), so a support whose forces
come from its member ends has its moments from there too.
Since the errors are at member ends alone, the supports are added up once those are
replaced: if they balance the loads to 1%, the supports with no member end keep the
solver's forces and moments and, where the solver's total does not balance,
`global_reactions` gives the supports' total (`"forces": "supports"`); if not, those supports are marked `"unreliable"`. The analysis
warns in either case. Measured on 2.21 (`94g.7`):

| Model | Solver's total | Supports' total | Applied |
|---|---|---|---|
| `portal_01` | 38 029 N | 42 701.0 N | 42 702.9 N |
| `beam_01` | 28 829.0 N (the errors of its two supports cancel; kept) | 28 827.9 N | 28 829.0 N |
| `structure_01`, gravity | 667.9 N, and 6.9 N sideways | 660.19 N | 660.20 N |

`structure_01`'s wall foot, once unreliable, has the solver's forces and moments, and the
moments of its three supports about the origin balance those of the weight to 2 in
100 000.

**A point load on a clamped support node** made the solver look wrong on any version: the
member's end has none of a force the support takes, the two differed by the load, and
the member end's figure was given (a cantilever with 1000 N at its tip and 700 N on its
root: 1000 N for 1700, and a warning). The load writer now marks point loads, and they
are taken off the member end before the comparison: 1700.0 N and no warning.

**A beam tied to a slab along its length** did the same: its end has its share of the
force only, the slab brings the rest to the support, and the two cantilevers under a slab
of `TestSlabBearingOnBeams` were given 58.45 N each for 49.74 on 2.23, with the warning
that the solver was wrong. Such a member is no longer used as a check: 49.73 and 49.74 N,
moments -124.34 N·m each for the -124.34 of statics. On 2.21, where the solver is wrong at
these roots (50.6 N along the beams that is not there), they are marked `"unreliable"`. The whole fast suite was run against 2.21 in a container: it passes, with
the nine tests of the solver's own reactions at clamped supports skipped. Against
conda-forge's unpatched 2.23, also in a container, none is skipped and all pass; CI now
runs the suite on both versions.

## Load combinations

A combination is not solved: its results are the sum of its load cases' results, each
times its factor (`analysis/superposition.py`). Only what is linear in the load is
added (displacement vectors, stress components, section forces at each cross-section,
forces at support nodes); the exporter then works out magnitudes, von Mises stress,
maxima, diagrams and reactions from the sum as it does for a load case.

Benchmark (`TestLoadCombinations`): `beam_01`, 4 m, fixed at both ends, 0.3 m square,
0.25 m mesh, with the self-weight taken out of `Dead`. `Dead` is 20 kN down at midspan;
`Live` is a line load of 5 kN/m down and 3 kN/m sideways. Combination `1.35 Dead + 1.5 Live`:

| Quantity | By hand | Combination | One case with the factored loads |
|---|---|---|---|
| Vertical reaction | 57 000 N | 56 999.995 N | |
| Sideways reaction | 18 000 N | 18 000.000 N | |
| End moment, vertical bending (P L/8 + w L²/12) | 23 500 N·m | 23 512.22 N·m | 23 512.23 N·m |
| End shear, vertical | 28 500 N | 28 498.95 N | 28 498.85 N |
| End moment, sideways bending | 6 000 N·m | 5 989.38 N·m | 5 989.37 N·m |
| End shear, sideways | 9 000 N | 8 999.65 N | 8 999.65 N |
| Moment at each support (from member ends) | 23 500 N·m | 23 512.22 N·m | 23 512.23 N·m |
| Largest displacement | | 0.744 365 8 mm | 0.744 366 6 mm |
| Largest von Mises stress | | 5.720 798 MPa | 5.720 792 MPa |
| Largest normal stress in the section | | 6.555 910 MPa | 6.555 910 MPa |

The combination and the single case differ by one part in a million, which is the
precision of the solver's result file. Adding the largest values of the two cases
instead would give 0.772 mm and 6.09 MPa: 3.7% and 6.5% too much, because the two
cases deflect in different directions. With a negative factor the error is larger:
`Dead - Live` has its largest moment at midspan, 6 633 N·m (by hand
P L/8 − w L²/24 = 6 667), where the difference of the two cases' largest moments,
which are both at the supports, is 3 367.

`building_02` (2 m mesh) has 17 combinations of `Dead`, `Live`, `Extra_dead`, `WIND`,
`EQX` and `EQY`. `Live` and `Extra_dead` have loads, `Dead` is the self-weight alone,
and the other three have nothing. Reactions: `Dead` 66.9681 MN, `Live` 30.0166 MN,
`Extra_dead` 60.2858 MN, `1.4D+1.6L` 226.1821 MN = 1.4 × (66.9681 + 60.2858) +
1.6 × 30.0166; largest displacement 16.8, 25.7, 15.3 and 54.4 mm. Until 2026-10-12
`Dead` was left out, and `1.4D+1.6L` came to 132.4 MN and 44.5 mm. The combinations took the run from 178 s to 277 s (5.8 s each) and `results.json`
from 5.4 to 43.7 MB when `Dead` was not a case, and left peak memory at 2.2 GB (one
is held at a time). With `Dead` the file is 45.9 MB and the peak 2.2 to 2.3 GB; the
run was timed at 184 s and, on a busy machine, 346 s.

What the extraction does with combinations (`tests/unit/ifc/test_load_combinations.py`,
on the example files): a relation without a factor counts once; the combination's
`Coefficient` multiplies its factors; a case assigned twice has its factors added. A
combination that names no load case, or includes something that is not a load case, is
left out with a warning. The old code read these silently as empty or partial, and
kept only the last factor of a case assigned twice.

## Self-weight of a load case

`IfcStructuralLoadCase.SelfWeightCoefficients` gives the shares of the members' weight
a load case includes along global x, y and z. Until 2026-10-12 it was read and not
applied: `Dead` of `beam_01`, `building_01` and `building_02` has `(0, 0, -1)`, and
self-weight was only analysed when asked for on the command line, as a case no
combination included. Now the step of a case has the members' weight, scaled and
turned by its coefficients, with the case's other loads. Standard gravity is taken
as 9.81 m/s²; IFC does not give it.

Benchmark (`TestSelfWeightOfALoadCase`): `beam_01` with its point load removed, so
that `Dead` is its weight alone, w = 2500 × 0.09 × 9.81 = 2207.25 N/m over 4 m,
0.05 m mesh.

| Coefficients | Quantity | By hand | Pipeline | Error |
|---|---|---|---|---|
| (0, 0, −1) | Vertical reaction, w L | 8 829.0 N | 8 829.0 N | 0.0% |
| (0, 0, −1) | End shear, w L / 2 | 4 414.5 N | 4 414.3 N | < 0.1% |
| (0, 0, −1) | End moment, w L² / 12 | 2 943.0 N·m | 2 945.1 N·m | 0.1% |
| (0, 0, −1) | Midspan deflection, bending and shear | 0.0774 mm | 0.0765 mm | 1.2% |
| (0, 0, −0.4) | Vertical reaction | 3 531.6 N | 3 531.6 N | 0.0% |
| (0, 0, −0.4) | Midspan deflection, 0.4 of the pipeline's 0.07649 mm | 0.03059 mm | 0.03059 mm | 0.0% |
| (0, −1, 0) | Reaction along Y, none along Z | 8 829.0 N | 8 829.0 N | 0.0% |
| (0, −1, 0) | End moment, sideways bending | 2 943.0 N·m | 2 944.8 N·m | 0.1% |

Run with `--gravity` as well, the same file gives `Dead` and `Gravity` with the same
reaction and deflection to nine figures, and a warning that the weight is there
twice. `beam_01` as shipped (20 kN and its weight) gives 28 829.0 N and, for its
combination `DCon1` = 1.5 `Dead`, 43 243.5 N = 1.5 × 28 829.0. A material with no
density in a case that includes self-weight is refused, as with `--gravity`.

Not checked against a reference: self-weight in a buckling step, where the weight of
every case is written with every load (the input file is checked, the factor is not).

## Plane trusses and frames

A structure drawn in one plane and loaded in it is usually supported as its textbook
picture is: in the plane, with pinned joints. In three dimensions nothing holds it
across the plane, and every pinned bar can spin about its own axis. CalculiX solves
such a model without complaint. Measured before this change (0.1 m square bars, 0.5 m
mesh): member forces were right to four figures in every case, and displacements were
not.

| Model | Largest displacement by hand | Before | Out of plane, before |
|---|---|---|---|
| Truss, supports holding X and Z only | 0.0375 mm | 0.706 mm | 0.66 mm |
| Truss, pin and roller that also hold Y | 0.0375 mm | 0.0546 mm | 0.030 mm |
| Portal, feet fixed in the plane only | 9.93 mm | 13.3 mm | 9.0 mm |
| Beam on supports holding X and Z only | 7.63 mm | 8.84 mm | 5.66 mm |

The only warning was that members were free to spin, and the last two had none.

`analysis/plane_structure.py` now recognises a plane structure (curve members only, in
a plane parallel to two global axes, every load and gravity acting in it, sections
with their axes in and across it) and counts the movements out of the plane that
nothing restrains, treating members and joints as rigid bodies tied by the
connections and supports of the file. If there are any, every node is held across the
plane, and each member or straight run of members that can still spin is held against
it at one end. One warning says so. A plane structure that stands up on its own
(`beam_01`, `portal_01`, a portal with fully fixed feet) is left as it is, and so is
any model in a buckling analysis.

Truss (`TestPlaneTruss`): two 4 m panels 3 m high, 10 kN at the middle of the bottom
chord, 0.05 m square bars, pinned at both ends. Identical results with supports in X
and Z only and with supports that also hold Y.

| Quantity | Method of joints / virtual work | Pipeline | Difference |
|---|---|---|---|
| Bottom chord | +3 333.3 N | +3 333.2 N | 0.004% |
| Diagonals at the supports | −6 009.3 N | −6 009.3 and −6 009.1 N | 0.003% |
| Diagonals at the load | +6 009.3 N | +6 009.1 N | 0.003% |
| Top chord | −6 666.7 N | −6 666.4 N | 0.004% |
| Bending moment in any bar | 0 | under 1 N·m | |
| Deflection under the load | 0.149 99 mm | 0.150 80 mm | 0.5% |
| Displacement across the plane | 0 | 0.000 15 mm | |
| Reaction at each support | 5 000 N | 5 000.0 N | under 0.0001% |

The 0.5% is the bars turning: displacements are read on their faces (1.7% with 0.1 m
bars).

Portal (`TestPlaneFrame`): 3 m high, 4 m wide, 0.1 m square, 10 kN sideways at the top
of one column, 0.25 m mesh.

| Case | Quantity | By hand | Pipeline | Difference |
|---|---|---|---|---|
| Feet pinned | Moment at each corner (P h/2) | 15 000 N·m | 15 000.8 and 14 999.0 N·m | 0.005% |
| Feet pinned | Sway | 42.86 mm | 42.63 mm | −0.5% |
| Feet fixed in the plane only | Moment at the feet | 8 863.6 N·m | 8 855.6 and 8 848.4 N·m | −0.1%, −0.2% |
| Feet fixed in the plane only | Moment at the corners | 6 136.4 N·m | 6 149.4 and 6 146.4 N·m | +0.2% |
| Feet fixed in the plane only | Sway | 9.935 mm | 9.904 mm | −0.3% |
| Feet fixed in the plane only | Reaction moment at each foot | 8 863.6 N·m | 8 855.6 and 8 848.4 N·m | −0.1%, −0.2% |

The portal held in its plane gives the figures of the same portal with feet fixed in
all six directions, which needs no holding and gets none, to five figures in sway and
four in every section force. That is the check that the restraints added do nothing in
the plane.

Two things found on the way:

- **Restraining the rotation of a node inside a member in bending disturbs it.** The
  first version held every member against rotation about the two in-plane axes at a
  node in its span: the portal's foot moments became 9 087 and 8 577 N·m (+2.5% and
  −3.2%, and no longer equal) and its sway 3.6% too small. Rotations are now held only
  where a member can spin, at an end where it is pinned if it has one, else at a
  support.
- **A straight run of members joined rigidly end to end spins as one.** The existing
  check took each to be held in torsion by its neighbour. In a plane structure they
  are now found by the kinematic count (`spinning_members()`); in a space structure
  they were not until `aiz.72` (next section).

## Members in line, and beams over a support

Two errors with one cause in common: taking what happens at a joint from the wrong
place. Both gave answers with no warning. The models are 0.1 m square bars built with
`tests.helpers.plane_model`, at a 0.25 m mesh.

**A straight run of members free to spin** (`aiz.72`, `TestStraightRunFreeToSpin`). A
4 m beam of two members on supports that hold translations only, with 10 kN down and
5 kN across at the joint, so that it is not a plane structure. Each member counted as
held in torsion by the other. Members in line are now one run, held when any of them
is, and otherwise at one support:

| Case | Quantity | Beam theory | Before | Now |
|---|---|---|---|---|
| Supports at the ends | deflection down | 7.634 mm | 12.97 mm | 7.638 mm |
| | deflection across | 3.817 mm | 9.15 mm | 3.820 mm |
| Supports at joints inside the run, 1 m overhanging each | deflection down | 7.634 mm | | 7.638 mm |
| | deflection across | 3.817 mm | | 3.820 mm |

In the second case the hold is on a node where two members meet. It restrains their
torsion only, and the result does not move.

**A member along a skew axis that is free to spin** (`aiz.74`,
`TestInclinedBeamFreeToSpin`). A 5 m rafter rising 3 in 4, two members on supports that
hold translations only, 10 kN down and 5 kN across its plane at the joint. No rotation
of a node is about its axis, so it used to be reported and left. The support at its
foot is now given that rotation to hold, with a stiff arm as for a skew support:

| Quantity | Beam theory | Before | Now |
|---|---|---|---|
| Deflection down | 9.536 mm | 9.789 mm | 9.542 mm |
| Deflection along X | 7.152 mm | 7.352 mm | 7.167 mm |
| Deflection across the plane | 7.450 mm | 7.761 mm | 7.453 mm |
| Moments about the two section axes | 10 000 and 6250 N·m | | 9999.9 and 6250.0 N·m |
| Torsion | 0 | | 0.0 N·m |

The reactions add up to the loads to six figures, with 5030 and 4970 N of the 10 kN on
the two supports. Passes on CalculiX 2.21 as well: no rotation is restrained by
`*BOUNDARY`.

**A load on part of a member, and one that varies along it** (`aiz.58`,
`TestPortalAgainstTheResultsInItsFile`, `TestLoadThatVariesAlongABeam`). An
`IfcStructuralCurveAction` gives its load as values with their locations along the
member; it is linear between them, and the first and last locations are where it
starts and ends. The locations were not read. A load that varied was applied at its
mean value over the whole member, with a warning; one with equal values was applied
over the whole member with none, which is what `portal_01` has: 100 lbf/in from 96 to
192 in along its 192 in beam. It was analysed with 19 200 lbf, shared equally by the
feet, for the 9600 lbf the file states.

Each element now takes the work-equivalent nodal forces of the part of the load on it,
integrated exactly, and the mesh has a node wherever a load starts, ends or changes
slope. `portal_01.ifc` also holds the results of the program that wrote it, which had
not been compared with ours (0.25 m mesh):

| `portal_01` | In the file | Plane frame, shear area of the web | Result |
|---|---|---|---|
| Vertical reaction, left and right | 10 135.4 and 32 567.5 N | 10 137.4 and 32 565.5 N | 10 137.5 and 32 565.4 N |
| Thrust | 6328.4 N | 6166.9 N | 6205.5 N |
| Moment at the left and right foot | 7535.5 and 4900.8 N·m | 7175.0 and 4549.6 N·m | 7236.2 and 4611.4 N·m |

The vertical reactions are the file's to 0.02%. The thrust is 1.9% below the file's and
the moments 4 and 6%. That is the shear area. A plane frame by the stiffness method
with shear deformation, worked out for this comparison, gives the file's thrust for a
shear area of 0.79 of the section (6330 N at 7.0 in² of 8.84) and 6472 N with no shear
deformation at all; with the area of the web, which is what this library takes for an I
section, it gives 6166.9 N, and the result is 0.6% above that, falling as the mesh is
refined (6240, 6206 and 6188 N at 0.5, 0.25 and 0.125 m).

| 4 m beam, 0.1 m square, simply supported, 0.25 m mesh | Beam theory | Result |
|---|---|---|
| Load rising from 0 to 3 kN/m: reactions, w L / 6 and w L / 3 | 2000 and 4000 N | to 0.01% |
| The same: largest moment, w L² / (9 √3) | 3079.2 N·m | within 1% |
| The same: deflection, 0.006522 w L⁴ / E I and shear | 2.867 mm | within 1% |
| 3 kN/m from 1.9 to 3.9 m: reactions | 1650 and 4350 N | to 0.01% |
| The same: largest moment and shear | 3588.75 N·m and 4350 N | within 1% |
| 3 kN/m of plan on a rafter rising 3 in 4 (`PROJECTED_LENGTH`): total | 12 000 N | to 0.001% |
| Sine half wave (`SINUS`), 3 kN/m at midspan: reactions, w L / π | 3819.7 N each | to 0.00001% |
| The same: moment at midspan, w L² / π² | 4863.4 N·m | 4878.9 N·m |
| The same: deflection, w L⁴ / π⁴ E I and shear | 4.513 mm | 4.515 mm |
| Parabolic half wave (`PARABOLA`), 3 kN/m at midspan: reactions, w L / 3 | 4000 N each | to 0.00002% |
| The same: moment at midspan, 5 w L² / 48 | 5000 N·m | 5015.5 N·m |
| The same: deflection, 61 w L⁴ / 5760 E I and shear | 4.655 mm | 4.657 mm |
| Point forces (`DISCRETE`), 3 kN at 1.3 m and 6 kN at 2.9 m: reactions | 3675 and 5325 N | 3675.0 and 5325.0 N |
| The same: largest moment, under the second force | 5857.5 N·m | 5857.5 N·m |
| 3 kN along a rafter rising 3 in 4, in the rafter's axes (`LOCAL_COORDS`): reactions | 2400 and 1800 N | to 0.001% |

`ProjectedOrTrue` was not read either: a load per projected length was applied per true
length, 25% too much on that rafter. And a curve action's `PredefinedType` was not: a
sine or parabolic half wave was applied as a constant load of its peak value, and point
forces along a member (`DISCRETE`) as that many newtons per metre. Those two were made
errors first and are now applied as given. A half wave is `LineLoad.half_wave` with its
peak, integrated over each element with a five-point Gauss rule (exact for the parabola;
a sine wave over a single element is right to seven figures). The forces of a `DISCRETE`
action become point loads at their locations along the member, each with a mesh node of
its own: neither 1.3 m nor 2.9 m is a node of a 0.25 m mesh, and a point load used to go
to the nearest one. A warping moment (`IfcStructuralLoadSingleForceWarping`), which was
ignored, is an error.

The shear diagram under a load that varied had steps at the element ends that were not
there (`aiz.84`): 5% of the shear either way under the sine wave at this mesh, 14% near
midspan, 8% under the triangular load, and as much wherever a load covered part of a
member. The steps a point load leaves were found by comparing the change of the force
from the middle of one element to the next with the median of those changes along the
member, which is the usual one only under a uniform load. They are now found from each
element by itself: the force at its middle is the mean of its own two ends, so a middle
that is not the mean of the solver's two end values gives the difference between the
jumps at its ends, and those are added up along the member. The same beam, with the
largest difference from the closed form anywhere along the diagram as a share of the
largest shear:

| Load | 0.25 m mesh | 0.5 m | 1 m |
|---|---|---|---|
| Uniform | 0.00% | 0.00% | 0.00% |
| On part of the beam, 1.9 to 3.9 m | 0.00% | 0.00% | 0.00% |
| Triangular | 0.10% | 0.39% | 1.57% |
| Sine half wave | 0.32% | 1.26% | 4.83% |
| Parabolic half wave | 0.37% | 1.40% | 5.00% |

None has a step in its shear at 0.25 or 0.5 m. What is left is in the solver's own
values at the element ends, where the load varies within an element: the largest
shear reported under the sine wave is 3831.8 N for 3819.7 at 0.25 m and 4004.0 N with
four elements. `TestLoadThatVariesAlongABeam` checks the four diagrams at 0.5% and that
no distance is listed twice. With elements of 1 m the sine wave leaves one step of
103 N at 3 m, and the moment under the load on part of the beam one of 250 N·m at
each end of the load, in 3135: the moment at the middle of an element under a load
given at its nodes is out by w l² / 24.

A cross-section with a jump is told from the others by being off the line that most
of the seven around it are on, and where no line has more than half of them the
solver's values are left as they are. `portal_01` loses the eight steps it had in the
shear along its beam, four on each half, and one in the moment where the load starts;
`grid_of_beams` loses four in an axial force of nothing, and keeps those where its
cross beams frame in; `beam_01` keeps its one. Their largest forces do not change. In
`building_01` a force of 12 of the 32 curve members changes by more than 2% of the
member's largest. 22 of them are tied to a wall or a slab along their length and
seven overlap another member; the forces in those that change go up and down from one
cross-section to the next, and there is no reference to say which reading is right
(`aiz.86`).

**Applied moments** (`aiz.58`, `TestAppliedMoments`). They stopped the analysis. A
moment is now written on the rotations of the node it acts at, which CalculiX turns
into a knot. A 4 m beam, 0.1 m square, 0.25 m mesh:

| Case | Beam theory | Result |
|---|---|---|
| 1000 N·m at the tip of a cantilever: moment along it, and at the support | 1000 N·m | 1000.0 and 999.99 N·m |
| The same: tip deflection, M L² / 2 E I | 4.571 mm | 4.549 mm |
| 1000 N·m of torque at the tip: torque along it, and at the support | 1000 N·m | 1000.0 and 999.99 N·m |
| 1000 N·m in the middle of a simply supported beam: reactions, M / L | ∓250 N | to 0.01% |
| The same: moment either side, M / 2 | ±500 N·m | ±500.0 N·m |
| The same: deflection, M L² / (72 √3 E I) | 0.07331 mm | 0.07322 mm |
| 1000 N·m 1.5 m along one member: moment before and after it | 375 and −625 N·m | to 0.1% |
| With 1 kN/m on the first half and 4 kN at midspan: reactions | 3250 and 2750 N | to 0.01% |
| The same: moment just before and just after midspan | 4500 and 5500 N·m | 4497.4 and 5500.0 N·m |
| 500 N·m/m of torque along a cantilever: at the root, and at the support | 2000 N·m | 2000.0 and 1999.99 N·m |
| 500 N·m/m about Y along a simply supported beam: reactions and shear | 500 N | to 0.01% and within 1% |
| 1 kN at the tip, 500 and 300 N·m at the clamped root: support moments | 4500 and 300 N·m | within 1%, and 300.0 N·m |

Three things in the results had to change for these to come out. The solver's stress
at a cross-section two elements share is the mean of the two, so the moment diagram
passed through nothing where the 1000 N·m is applied and the largest moment reported
was 468.75 N·m, the value at the middle of the element beside it. A bending moment
changes by its shear per metre, so a change the shear does not account for is now put
back as a jump, half on each side. The same averaging happens between two members in
line, which the member's own cross-sections cannot show; its end then gets the value
its last own cross-section leads to. And the envelope is taken from the diagrams,
since the mean can also be the larger: 5002.6 N·m was reported for the member that has
4500 before the moment and 5500 after it.

A load case of moments alone applies no force, and the check of the reactions against
the applied load reported rounding (1e-6 N of 0 N) as an imbalance; it now needs a
millinewton. A couple per length along a beam leaves a saw tooth in the moment diagram
of half of what one element carries (62.5 N·m here, where the beam has none): it is
applied as moments at the nodes.

**A beam ending on the span of another** (`aiz.80`,
`TestBeamEndingOnTheSpanOfAnother`). A 3 m beam between the middles of two 4 m girders
fixed at their ends, 10 kN at its middle, 0.25 m mesh. The file gives each end of the
beam a connection of its own that joins nothing else, which is how `building_02`
describes its secondary beams. Curves that touch are meshed with one node, so the beam
is joined to the girders rigidly all the same:

| Quantity | Joined by the mesh | Girders in two members, joints in the file |
|---|---|---|
| Deflection | 2.9607 mm | 2.9607 mm |
| Torsion in each half of a girder | 929.3 N·m | 929.3 N·m |
| Moment in the middle of the beam | 5641.4 N·m | 5641.4 N·m |

P L / 4 is 7500 N·m, and 7500 less twice 929.3 is 5641.4: the moment at each end of the
beam is the torsion of the two halves of the girder. Two things were wrong before. The
beam was reported as free to spin about its own axis and "not held", since the check
went by the file's connections alone; and the rigid joint, which the file does not
have, was not reported. Now the check counts a shared node as the joint it is, and one
warning gives the number of such places. `building_02` has 334 (263 of a beam on a
beam, 71 of a column ending on a beam; every one a member ending on the span of
another at right angles), and its 37 "free to spin" members were among them. Its
solver input is the same to the byte as before; only the warnings changed.
`building_01` has two such places.

**A beam continuous over a pinned support** (`aiz.78`,
`TestBeamContinuousOverASupport`). Two 4 m spans, four members, three supports that
hold no rotation, 10 kN in the middle of each span. A support with a free rotation was
classified as a hinge and every member meeting at it was released, so the beam was
analysed as two simply supported ones:

| Quantity | Statics | Before | Now |
|---|---|---|---|
| Moment over the middle support | 3 P L / 16 = 7500 N·m | 0 | 7496 N·m |
| Moment under the loads | 5 P L / 32 = 6250 N·m | 10 000 N·m | 6252 N·m |
| Reaction at an end | 5 P / 16 = 3125 N | | 3126 N |
| Largest deflection | | 8.00 mm | 3.42 mm |

No example model has a support with a free rotation that joins two members, so none
of their results changed. The first case with supports at inner joints could not be
run before the second fix: its overhangs came out detached.

## Skew supports

A support whose axes are not parallel to the global ones, and whose condition treats
its three translations or its three rotations differently, used to be analysed as if
its axes were global, with a warning (`aiz.35`). It is now analysed as given.

Three ways of doing it were measured first on a hand-written input (4 m beam, 0.1 m
square, eight B32R elements, 10 kN at midspan), on CalculiX 2.23 and 2.21:

| What | How | Result |
|---|---|---|
| Roller on a 30 degree incline | `*EQUATION` between the node's own translations | reaction (-2886.75, 0, 5000.00) N: exact |
| | `*TRANSFORM` and `*BOUNDARY` | the same |
| The same, with a load of (1000, 0, -2000) N on the roller node | `*EQUATION` | solver's force less the load = (-1154.7, 0, 2000.0) N: exact |
| Rotation held about an axis at 45 degrees between Y and Z | `*TRANSFORM` and `*BOUNDARY` on DOF 4-5 | midspan (-2.173, -5.458) mm |
| | stiff arm, tip tied | midspan (-2.176, -5.455) mm |
| | `*EQUATION` on DOF 5 and 6 | nothing: the beam stays pinned |

Equations and arms are used. `*TRANSFORM` gives the same answers but changes the
meaning of every load and equation on the node it is applied to.

Through the pipeline (`TestSkewSupports`; the same beam as two members, 0.25 m mesh):

| Case | Quantity | Statics | Measured |
|---|---|---|---|
| Roller on a 30 degree incline | reaction along its normal | P / (2 cos 30) = 5773.5 N | 5773.5 N |
| | reaction along the incline | 0 | 0.0 N |
| | horizontal reaction at the pin | 2886.8 N | 2886.8 N |
| | axial force in the beam | 2886.8 N, compression | 2887.0 N |
| | largest moment | P L / 4 = 10 000 N·m | 9999.9 N·m |
| Clamped about an axis at 45 degrees | reaction at the clamp, along that axis | P sin 45 / 2 = 3535.5 N | 3535.5 N |
| | across it | 11/16 P cos 45 = 4861.4 N | 4872.1 N |
| | moment about that axis | 3/16 P cos 45 L = 5303.3 N·m | 5346.2 N·m |
| | moment about the free axis | 0 | 0.0 N·m |
| | reaction at the pinned end, Y and Z | 937.5 and 4062.5 N | 945.1 and 4054.9 N |

The roller gives the same figures with supports that hold nothing across the plane, as
a textbook draws them, where the plane hold and the equation meet on one node. The
clamp is 0.2% off in its force and 0.8% in its moment, which comes from the stresses
at the member end. Clamped about a global axis, the hand-written beam above gives
6901.7 N at the clamp for 11/16 P = 6875 N, 0.4% off.

`TestPlacedModel.test_turned_off_the_global_axes` turns two examples 30 degrees about Z
by their placement and runs them beside the files as shipped, under self-weight:

| Model | What becomes skew | Largest displacement, shipped | turned | Reactions along the supports' axes |
|---|---|---|---|---|
| `slab_01`, 0.25 m | two line supports clamped about their edge | 0.18238 mm | 0.18239 mm | 114.8 N each, both |
| `structure_01`, 0.5 m | a line support clamped about its edge, a point support holding one rotation, a slab hinged on a wall | 0.4333 mm | 0.4332 mm | (2.3, 406.7, -4.2) N at the line support, both |

Before the rotation about the shell normal was held at shell nodes, the turned
`slab_01` gave the right deflection and in-plane displacements of 800 km: an arm fixed
to a node of shells alone swings freely about their normal.

## What is not yet validated

- **Plane structures in a plane not parallel to two global axes**, and plane
  structures with surface members (a shear wall), are not recognised and get no help.
  Nor were the benchmark models authored in Bonsai: they are built with IfcOpenShell.
- **Members that can spin in a space structure** are found one member or one straight
  run at a time. A member is taken to be held by any member across it that it joins
  without a torsional release; whether that one can itself give way is not checked.
- **Self-weight of a load case** is checked on one beam, with native elements. Not
  checked: U1 elements (their weight is written as nodal forces), surface members
  other than through the totals of `building_01` and `building_02`, and buckling.
- **Load combinations** are checked on one beam. Buckling has none. A case without
  loads adds nothing and is named in `cases_without_loads`.
- **Reactions on CalculiX 2.21 and earlier** at a clamped member end with no section
  forces to replace them (a U1 member, a member and a slab at one support): marked
  unreliable, with every other support that has no member end, and the total is the
  solver's.

- **Distributed loads on shells in their own axes** (`GlobalOrLocal` local): global
  ones are covered by the plate benchmark; local ones only by a unit test.
- **Supports released in bending only at one end** have no benchmark.
- **Members free to spin that are reported and left**: those with no support of their
  own (no example has one now), and those along a skew axis whose supports are line
  supports.
- **Curve members that touch with no connection between them are joined rigidly**, by
  the node the mesh gives them, under `--strict-connections` as well, and a warning
  counts them (decision 2026-10-12: it is what analysis programs do with members that
  meet). The IFC specification does not cover the case. It joins members through
  connection objects alone (`IfcRelConnectsStructuralMember`), expects "point
  connections at each end of the member" and topology that shares vertices, and says
  nothing of members that only touch.
- **Member stress** is the normal stress from axial force and bending only. Shear,
  torsion, buckling and anything specific to concrete are not checked.
- **Shell members in membrane action**: walls are only checked through `structure_01`.
- **Angles about their true principal axes**: the product of inertia is ignored.
  Z, lipped C and arbitrary profiles are not supported at all.
- **Frames and buildings**: only `structure_01` has been compared with a reference.
  `building_02` has none.
- **Beams tied to the slab or wall they lie in**: covered by Tier 2 for a slab on two
  beams and for columns under and through a slab. Beams in walls and columns in walls
  use the same code but have no benchmark. A rigid (moment-carrying) line connection
  between a beam and a slab is analysed as a hinge line.
- **Per-member stress in `results.json`**: attributed to the right member, but no value
  is compared with a reference.
- **Unsupported input**: surface connections, moments applied to surface members or
  varying along a member, and load kinds other than forces and moments stop the
  analysis with an error naming the entity. So do the varying actions of IFC2X3 and
  curve actions of type `EQUIDISTANT` or `USERDEFINED`.
- **Skew supports**: validated for a point support on a beam (translation and
  rotation) and, by turning two examples, for line supports and hinged edges of
  slabs and walls. Not covered: a support whose translations are partly free *and*
  whose rotations are skew (the arm's tip is then tied to the node, not to the
  ground: measured on a hand-written input, not through the pipeline), and a support
  tilted out of a horizontal plane on a shell. Releases in skew axes between members
  have only a unit test.
- **Mixed U1 and native beams**: known to be wrong (joints act as pins). U1 is no
  longer used unless asked for.
- **Torsion**: right for tubes, boxes and round bars, at the cost of their shear
  stiffness (1.1 to 1.9 times too high), and for solid rectangles at the cost of
  their shear stiffness across the width (17 to 45% too low). 30 times too stiff for
  the I section; see the torsion table above.
- **`building_01`**: reactions only. Its deflection under `Dead` (self-weight) is still moving 10%
  between a 0.5 m and a 0.25 m mesh.
- **Buckling** beyond the single Euler column.
