# Boundary Condition Handling

`IfcBoundaryNodeCondition` uses three value types for each stiffness component:
- `IfcBoolean(True)` — rigid/fixed (treated as 1e20 N/m or N·m/rad)
- `IfcBoolean(False)` — free/released (treated as 0.0)
- Numeric measure — spring stiffness in project units

The helper `_ifc_stiffness_to_float()` in `entity_identifier.py` handles this;
`get_connection_input()` scales a number by the unit the file declares for its kind, else by the powers of length it has
(N/m and N·m/rad at a point, per metre along an edge, N/m per m² over a face). A condition of another kind than its connection (a node condition on a line support) raises `E-SUP-007`; it once held nothing. IFC2X3 names translations `LinearStiffness*` and has numbers only, -1 for rigid, a convention IFC4 forbids (`aiz.105`); no IFC2X3 model gets that far yet, since its members stop extraction first (`E-SEC-001`, `E-MAT-002`: no `IfcMaterialProfileSet`, no `HasProperties`). After extraction, `get_constrained_dofs(connection)` in `boundary_condition_handling.py` translates per-DOF stiffness values to the list of CalculiX DOF numbers to fix (threshold 1e12). This correctly handles pinned supports (`T,T,T,F,F,F` → DOF 1-3) and fully fixed supports (`T,T,T,T,T,T` → DOF 1-6).

**The six values are in the connection's own axes, not the global ones.** A point
connection uses its `ConditionCoordinateSystem`; a curve connection has x along its
edge, with `Axis` giving local z. The extractor stores them as
`connection.local_axes` and `get_constrained_dofs()` permutes the flags into global
DOF numbers, so `drx` of a line support along global Y is DOF 5, rotation about the
edge.

**Skew supports** (`aiz.35`): axes that are not parallel to the global ones, with a
condition that treats its translations or its rotations differently (a roller on an
incline, a line support along a diagonal wall that holds rotation about its edge).
`support_restraint()` gives what any support holds as direction rows in global
coordinates; `get_constrained_dofs()` returns only those that are global DOFs, so ask
`support_restraint()` (or `share_in_span()`) when the question is what a support holds.
What is skew is written by `write_boundary_conditions()` from `support_equations()`:

- A translation is an `*EQUATION` between the node's own global translations. The
  reaction arrives as the solver's force at the node, as for a `*BOUNDARY` (measured,
  with and without a load on the node).
- A rotation is held with a stiff arm (`rotation_arm()`, built by
  `_build_support_arms()`): a B31 link from the node along an axis the support leaves
  free, its tip tied in the directions that stop the held rotations and no other. The
  tip is a support node (in `ALL_BC_NODES` and `support_nodes`), since part of the
  reaction arrives there; it is not in `BC_<id>`. When any rotation of a support is
  skew, all of them go through the arm and none is a `*BOUNDARY`.
- **Do not use `*TRANSFORM` for this.** It works, rotations of beam nodes included
  (measured), but it changes the meaning of every `*CLOAD` and `*EQUATION` term on the
  node, and distributed loads, joints, bearings and the load recorder all write those.
- **A node of shells alone has no rotation about their normal**, and an arm fixed to
  it swings about that axis freely: `slab_01` turned 30 degrees came out with the
  right deflection and in-plane displacements of 800 km. `_drilling_axis()` finds
  such nodes and `rotation_arm()` holds the tip against it too.
- Arm tips and hinge tips are in `self._helper_nodes`. Supports and loads look for
  their node in `_structure_nodes()`, which leaves them out; use it, not
  `dict(self.nodes)`, for anything placed by position.
- The first term of every such equation is in `_collect_boundary_condition_dofs()`
  with the restrained DOFs, so no joint equation makes it depend on something else
  as well; the plane hold skips it for the same reason.
- **An `*EQUATION` on a node of shells alone holds the mean of the top and
  bottom of its expanded section, not the middle** (`aiz.103`; `gen3dmpc.f`
  has the line for the middle commented out, `gen3dboun.f` holds both for a
  `*BOUNDARY`). `slab_01` pushed in its plane between pinned edges, the hold
  along them an equation, was 1.9, 3.0 and 4.8% too flexible at a 0.5, 0.25
  and 0.125 m mesh. It grows with refinement, and did so wherever an equation
  acts in the shells' plane (`aiz.104`): sheared along it, a hinge between two
  slabs was 4.4, 7.8 and 8.9% too flexible at 0.25, 0.125 and 0.0625 m, a slab
  tied or hinged to beams along its edges 9, 15 and 19%; line springs in its
  plane, at 0.5, 0.25 and 0.125 m, 3.6, 6.4 and 9.1%.
  `_knot_shell_nodes_on_equations()` hangs a knot link on every such node of
  skew support equations, edge hinges, line bearings and translational springs
  not along the normal: each is then within 1e-3 of its reference at every mesh
  (`TestEquationsOnShellsInTheirPlane`), and in bending the knots change nothing
  to six figures. A spring along the normal gets none: the mean is what matters
  across the shell.
- **A knot on a node of shells in one plane has no stiffness against turning
  about their normal**, as all its section's points are in line along it. The
  solver's value for that rotation is noise, and it breaks equilibrium once the
  knot turns about anything else: with the link along the normal the hinge above
  was out of balance by 20 kN of its 20 kN load at 0.0625 m, and a slab on surface
  springs carried 78.0 kN of 75 kN. So the link lies in the plane and its tip is tied
  against turning about the normal (`_knot_drilling`), which leaves imbalances
  under 1 N and touches no point of the section. That tie is held against the
  ground, so it is only for shells with one normal (`_SHELL_SAME_NORMAL`, the
  cosine in `gen3dnor.f`): where a wall meets a slab the points are not in line,
  the knot needs no tie, and one is a real moment on the structure. `building_01`
  has 135 such nodes of its 250 knots, and its moments were out by 104 455 N·m (5e-4)
  with its forces balancing. Check `moment_imbalance_Nm` as well as `imbalance_N`.
- No arms in a model with U1 members (no link elements next to U1): a skew rotation
  there stops the analysis with an `AnalysisError`.

**Elastic supports** (`aiz.94`): a stiffness that is neither zero nor rigid is
a spring (`support_springs()`; it was once taken as free without a word). Measured
on 2.23, and what the design rests on:

- `SPRING1` on DOF 1-3 of a beam or shell node works; on DOF 4-6 it is accepted
  and does nothing.
- A spring at the tip of a stiff arm holds the node's translation as well. So
  `_build_support_springs()` puts each spring on a node of its own whose first
  translation an `*EQUATION` makes what it resists: the node's translation along
  the spring, or for a rotation the arm tip's movement across the arm over its
  length. The spring node is held in DOF 2-3 (the solver crashes without a word
  otherwise). Rotational springs on a node of shells alone: the arm lies in their
  plane and its tip is held against turning about the normal relative to the
  node; one about the normal holds nothing and is left out with a warning.
- `RF` is wrong at a node an equation leans on (a line bearing's tie gave
  -7994 N where the spring took +1006 N), and at a spring node it is the spring's
  force along global x whatever its direction. So the reaction of a spring is its
  stiffness times its node's displacement (`SPRING_NODES`, printed every step,
  `ResultsParser.parse_spring_displacements()`, combined by superposition).
  `ResultsExporter._elastic_correction()` takes the spring nodes' `RF` and the
  equations' push on support nodes (`_spring_push_on_node()`) off the solver's
  total and adds the springs.
- A line or surface spring is shared out by `spring_node_shares()`: HRZ-lumped
  (a six-node triangle's corners 3/57, middles 16/57 of its area; a quadratic
  edge 1/6, 2/3, 1/6), since the shape functions' integrals give a six-node
  triangle's corners nothing. The elements found must cover the edge or face to
  1%, else `AnalysisError`.

**Surface supports** (`aiz.96`, `IfcStructuralSurfaceConnection`) keep their
outline in `connection.face`; their axes are those of the `Position` of the
face's `IfcPlane` (z across it), and a condition that differs by direction on a
face with no plane raises. `GmshGeometry._surface_support_pieces()` intersects
the outline with each surface member and the pieces fragment the members, so
the mesh follows it. The support holds every node on the face
(`find_nodes_in_face()`). An `IfcBoundaryFaceCondition` has translations only:
inside a rigidly held area a slab's normals still turn, against transverse
shear alone, over about sqrt(D / kappa G t), which at the edge of the area adds
M l / D of rotation (measured: half of `slab_01` held, the free half 15% over
q L^4 / 8 D, as that predicts). `TestElasticSupports` and `TestSurfaceSupports`
check them against closed forms.

`results.json` lists what a support holds along global axes in `restrained` and along
its own in `restrained_in_axes`. `TestSkewSupports` has the incline, a clamp about a
skew axis, a clamp sliding on the incline (arm tip tied to a node with an
equation of its own) and `slab_01` tilted 30 degrees (skew edges, drilling)
against statics; `TestPlacedModel.test_turned_off_the_global_axes` runs
`slab_01` and `structure_01` turned 30 degrees about Z against the files as shipped.

**Support displacements** (`aiz.58`): a point action whose applied load is an
`IfcStructuralLoadSingleDisplacement`, assigned to a point connection with an
`AppliedCondition`, moves that support (settlement, a support turned). It is a
`SupportDisplacement` in `LoadGroup.support_displacements`, never among
`loads`, which everything else reads as forces; rotations follow the file's
`PLANEANGLEUNIT`. The steps give it as `*BOUNDARY` values on the support's set
(`_write_support_displacements()`). Measured on 2.21 and 2.23: a value
written in a step stays in force in the later ones, so every DOF any case
moves is written in every step, zero where the step moves none; `*BOUNDARY,
OP=NEW` breaks the model, do not use it. A nonzero rotation on a clamped
beam node works. Only a direction the support holds rigidly as a global DOF
can be moved (`support_displacement_values()`): one it leaves free would add
a restraint, and springs and skew directions (equations) are not done; each
raises `E-LOD-007`, as do one on a member and one in a buckling analysis.
Reactions balance each other (`applied_load_N` is zero), and
`supports[].prescribed_displacements` says what moved. `TestSupportDisplacements`
has a settled middle support and a turned end of a fixed beam against
Timoshenko's closed forms (0.1%), a second case, and a combination.

**Temperature loads** (`aiz.98`): a curve or planar action whose applied load
is an `IfcStructuralLoadTemperature` changes the temperature of the whole
member it is assigned to (CONST only; another distribution, or one on a point
action, raises `E-LOD-008`). It is a `TemperatureLoad` in
`LoadGroup.temperature_loads`, never among `loads`, in K
(`THERMODYNAMICTEMPERATUREUNIT`: a difference, so 5/9 per °F, and the
material's `ThermalExpansionCoefficient` per file unit is divided by the
same). `DeltaTY` and `DeltaTZ` are differences between the outer fibres on
either side of local y and z: across a curve member's real section
(`Section.get_depths()`: width along y, depth along z), across a surface
member's thickness (z only; its normal is that of its face's plane,
`SurfaceMember.normal`). No coefficient, no axes or depth for a difference,
a U1 member or a buckling analysis raises `E-LOD-008`. Measured on 2.21 and
2.23, and what the writer rests on:

- `*TEMPERATURE` takes the change, then gradients in K/m: on a beam node
  along the element's tangent times its section's 1 axis, then along the 1
  axis; on a shell node along the element's normal. The curvature is alpha
  times the gradient whatever the rectangle, so an equivalent one is
  exact. Both turn over with the element's node order, so
  `_prepare_temperature_loads()` turns the elements of a member with a
  difference to run with its x or normal, and `_temperature_fields()` gives
  each node its values from the section axes recorded per element.
- Beam materials (`MAT_RT_`, `MAT_EQ_`, 1 axis along the member) expand
  along the member only (`TYPE=ORTHO`): isotropic expansion is held by any
  knot that holds the section, and a free cantilever under a gradient had
  E alpha dT of stress at its root. Shells expand isotropically.
- A node has one temperature. Where members with different changes meet
  (one heated, one not but with a coefficient), the node takes the mean
  (`W-LOD-010`): two elements see part of the other's change, and a
  restrained run keeps its whole expansion (exact for B32R).
- Every node of a member that expands is written in every step, zero where
  the step heats nothing (temperatures stay in force), after
  `*INITIAL CONDITIONS, TYPE=TEMPERATURE` of zero. A free cantilevered slab
  is no closed form (its clamped edge holds the curvature across); the
  benchmark is a slab on three corners, a sphere.

`plane_structure.py` takes a difference as bending along its gradient.
`TestTemperatureLoads` has a free and a clamped bar, cantilevers, a fixed
beam, a beam bowing out of its plane, the slab, a second case and a node
shared with a cold member against closed forms.

**Member-side releases** (`IfcRelConnectsStructuralMember.AppliedCondition`) are in
the axes of that relation (`connection.release_axes_by_member`; the member's own axes
when the relation has no `ConditionCoordinateSystem`). `released_rotation_axes()`
returns them as directions, and `get_released_rotations()` as global DOFs (None for a
partial release in skew axes: use the directions). A support holding a single member
leaves the released rotations free, whatever their axes: a fully fixed support under a
column released in both bending rotations is written as DOF 1-3 plus torsion. A
surface member is hinged along an edge when it is released about the direction of
the edge, whichever way the edge runs.

Support nodes: `find_support_nodes()` returns the single mesh node nearest the
connection position (within 0.1 m) plus any node coincident with it (beam and
shell meshes keep separate nodes at one point). It never returns a neighbouring
node; doing so fixed two adjacent nodes on fine meshes. Of coincident nodes a
support keeps those of the members it holds (`aiz.97`,
`UnifiedCalculixWriter._support_member_nodes()`, edges and faces too): a
support of a beam at the corner of a slab hinged to it once clamped the
slab's corner, and the slab came out 15% stiff. With none of its members'
nodes there (one stopping short of it) it keeps them all. Point loads go to the
single nearest node.
