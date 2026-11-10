# Beam Section Orientation

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

**The open profiles' A, Iy and Iz come from their outline** (`94g.26`,
`converters/profile_geometry.py`): IfcOpenShell's corners for I, asymmetric I,
T, L and U, fillets and edge radii as tangent arcs in 256 pieces, integrated
by Green's theorem. HEB 160 and IPE 300 are their tables' to 1e-4; the plates
alone were 3.6% short in area and 3.2% in Iy. IfcOpenShell's own
triangulation draws a fillet as one chord (0.6% too much area), so do not use
it for this. An asymmetric I is about its own centroid (its flanges were once
averaged); its `dimensions` stay averaged. A sloped flange or leg follows
IfcOpenShell (an I's thickness at the flange edge, the others' nearer the
web; IFC's text does not say), with `W-SEC-004` unless Pset_ProfileMechanical
gives A, Iy and Iz. The torsion constant and shear areas are still those of
the plates. A dimension IFC requires that is missing raises `E-SEC-004`; T,
L, U and asymmetric I once took 0.1 or 0.01 m in its place.

**A member whose centroid is off its reference curve is eccentric** (`94g.35`).
IFC puts the origin of the profile, after its `Position`, on the curve, x along
local y and y along local z; a parameterised profile has the middle of its
bounding box there. `Section.centroid_offset` (local y, z, in m) is the
outline's centroid moved by `Position` (`MembersExtractor._place_section()`);
a `Position` turned other than 180 degrees raises `E-SEC-007`, as the
inertias would turn too. `Section.fibre_distances` are the outline's, from the
centroid, for `max_normal_stress_Pa`. Everything is built on the curve's nodes
as for any member; last, `_offset_eccentric_members()` gives the member's
elements copies of its nodes at the centroid, each joined to its node by a
stiff link (in `_rigid_links`), and `_offset_references` maps a copy back.
Lookups by member nodes at write time (`_support_member_nodes()`,
`_find_connection_nodes_at_location()`) map them, and loads along the member
are shared out on the curve (`_elements_on_reference_curves()`), its weight on
the elements as they are (`weighed_elements`). **CalculiX's `OFFSET1` and
`OFFSET2` are no use**: they move the expanded section and nothing else, and
a pull on an offset cantilever's node bent it not at all (measured on 2.23).
**The links are sized by stiffness** (`_offset_link_side()`): one adds about
`e E I / (E' I' L)` to a member's deflection, made 1e-5; a link much thicker
than its length is a badly shaped solid and put a cantilever's reactions out
by 2e-4, and one much thinner bent 8%. A centroid across the plane of a plane
frame makes it no plane structure. U1 members cannot be eccentric
(`E-SEC-008`). `TestEccentricMembers` pulls a bar moved by its Position and a
T along their curves against P e L² / 2 E I (1e-5).

**A surface member's openings are the other bounds of its face** (`2uq`,
`SurfaceMember.holes`, `entity_identifier.face_loops()`). Only `Bounds[0]` was once
read, so an opening was solid, and the hole's outline became the member if it came
first. They are meshed as holes, so weight and area loads leave them out of
themselves, and `_point_on_surface()` keeps a column passing through one from being
pinned to the slab. One that is not clear inside the outline and the others raises
`E-IFC-002` (`_check_holes()`); a surface connection's face with one raises
`E-SUP-004`. No example model has one.

**A plain `IfcFace` is read on the plane through its corners** (`94g.30`,
`entity_identifier.implied_face_axes()`). IFC wants an `IfcFaceSurface` for a
surface member or connection; Bonsai's face template (`ShapeBuilder.face()`)
writes an `IfcFace` of an `IfcPolyLoop`, and every surface member made in Bonsai
was refused. Its normal is the right-hand winding of its outer bound, its x the
default of `IfcAxis2Placement3D`; one `W-IFC-004` lists them. One that is not
plane raises `E-IFC-002` (`E-SUP-004` for a connection). A surface connection
only needs the axes when its condition differs by direction.

**Area loads follow the member's outline.** Where one surface member lies
inside another (a landing on a floor slab), fragmenting gives each element to
one of them. `_load_element_sets()` applies an area load to every shell
element within the loaded member's outline, whoever owns it, and a load on a
curve member to the elements in its geometry (`_geometry_element_sets`): a
beam lying inside another once had its loads left out with a warning.
