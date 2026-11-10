# Connections

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
  `_write_rigid_links()`. Links are not in `self.elements` or `EALL`. Where no
  member reaches the connection (`building_02` has two, with 115 links for
  its 117 eccentric ends) the nearest member end is the joint and the others
  are linked to it: the connection itself has no node (`aiz.88`).
- **A point force on a beam node is put on a knot** (`aiz.76`, `aiz.91`,
  `_knot_point_loaded_nodes()`). On a beam node that is not a knot CalculiX
  puts a force on the four corners of the expanded cross-section, a quarter
  each (`gen3dforc.f`), and dents them more the finer the mesh: a column
  under a load on its top shortened 6.6% more than PL/EA at a 0.1 m mesh,
  and an I section (its equivalent rectangle) under a load at midspan sagged
  1.2% more than Timoshenko's beam at 0.25 m and 3.1% at 0.05 m. A short
  thin link at right angles, its tip free, makes the node a knot: the column
  is right to 0.03% and the I section to 3e-6 at any mesh. The knot links
  are in `_knot_links`, not `_rigid_links`, and their element sets are named
  `KNOT_LINK_<id>`.
- **Beams have no Poisson's ratio** (`aiz.91`, `_BEAM_POISSON`): their
  materials (`MAT_RT_`, `MAT_EQ_`) are written with nu = 0, their shear
  moduli as before. Beam theory has no use for it, and in an expanded beam
  it makes the section contract as it bends, which a knot (clamped end,
  joint at an angle, link, arm, point load) stops: a cantilever was 1.2,
  0.75 and 0.5% stiff at a 0.5, 0.25 and 0.1 m mesh with nu = 0.2 and is
  exact at all three without (once its shear modulus was put right,
  `aiz.101`); a beam with a knot at every node was 24% stiff
  with nu = 0.3. Knots cost a beam nothing now. Shells keep theirs: a shell
  node that is a knot has its thickness held, which stiffens the slab there
  (a cantilevered slab clamped through knots along a line: 3% of its own
  deflection at a 0.25 m mesh, nu = 0.3).
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
  a line is a hinge about it. Both nodes of each pair are knots (see Skew supports in `supports.md`).
  Where a support holds the copy and not the original, the original is the
  dependent side of the tie (`aiz.106`); it was once left out, and the members
  came apart at that node with the reactions balancing.
- **A joint's tie leans on whichever node is free** (`aiz.107`,
  `_write_tie()`, used by release hinges, ball joints and hinged edges): a
  support holding a released member's end and not the joint once left the
  tie out, and the other beam came loose. Where every node of a tie is decided
  already and supports do not hold them all, `E-JNT-005` stops the analysis;
  no example model reaches it. A support that holds a rotation is checked
  against the ends of every member with an element at its nodes, tied ones
  too (`_member_ends_at()`): with the support's own members alone a correct
  solver force was taken for a mistake and halved.
- **A curve member lying in a surface member bears on it along its length**,
  connected in the IFC or not (`_build_line_bearings()`). Example models
  connect a slab at its corners only; without this the edge beams carry
  nothing and the slab spans corner to corner (`building_02` gave 462 mm).
  Each beam node the shell mesh does not share is tied in DOF 1-3 to the
  triangle it falls in, with that element's shape functions. It is a hinge
  line, and one warning reports how many members were tied. The shell nodes of
  a tie are knots, the beam's already (see Skew supports in `supports.md`). Not tied: nodes
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
- **A line connection of the file joining a beam and a slab joins them all
  along it** (`aiz.51`, `_line_joints()`), under strict connections too.
  It was once taken for a point at its midpoint: a knot there, or one rigid
  link from a downstand beam, and the slab hung from it. The geometry stage
  meshes the line into the slab and the beam with the same nodes along it
  (`_seed_line_joints()`, `_conform_line_joints()`: the beam is split at the
  line's ends and at the image of every point on either, and each pair of
  pieces is transfinite with one count; the pieces are found after
  `fragment()` by distance, since it moves vertices it merges, across the
  rounding of `_coord_key()` too, `9ot`). Rigid (neither member released
  about the line): the nodes are merged, or joined by a rigid link where the
  beam is eccentric (a downstand beam; `IfcRelConnectsWithEccentricity` is
  taken from the geometry, as at points), in `_merge_rigid_connection_nodes()`.
  Released: each beam node is tied in DOF 1-3 to the slab node at its foot,
  through a link where eccentric (`_build_line_joints()`). **Not with arms
  or equations**: tying a slab's middle surface reaches neither its normals
  nor its rotation, and a slab clamped that way to a beam held against
  twisting came out 40% too flexible in its own share. A line connection
  joining two curve members raises `AnalysisError`. `TestSlabJoinedToBeamsAlongALine`
  has a strip between stiff beams against q B^4 / 384 D and 5 q B^4 / 384 D
  (0.5% and 0.14% at a 0.25 m mesh). A surface member hinged about such a
  line is a hinge with the beam only: `_release_hinged_edges()` takes the
  surface members of a connection alone.
- **A member nothing stops spinning about its own axis is held**
  (`_hold_spinning_members()`): rotation about its axis is restrained at one
  of its supports, with a warning. Ball supports at both ends of a beam are
  the usual cause. A member is held by a support that restrains that
  rotation or by a member across it that it joins without a torsional
  release. Members in line turn together and hold nothing for each other:
  they are one run, held once (`aiz.72`), at a support at an end of the run
  if it has one, else at a joint inside it (measured to 0.1%: only the
  torsion of members in line is restrained there). The support is given
  the rotation to hold (`connection.torsion_hold_axes`, `aiz.74`):
  `support_restraint()` returns it with what the file says, so it is
  written in the support's set, its moment is in the reactions, and along
  a skew axis (a rafter, a brace) the arm and equations are those of a
  skew support; `_build_support_arms()` runs after this step for that
  reason. Only on a line support along a global axis is it a `*BOUNDARY`
  at one node (`_torsion_holds`). Only reported: runs with no support of
  their own, and skew ones on line supports or in a model with U1 members.
  **A member across holds a run only if it cannot swing with it**
  (`aiz.79`, `analysis/spinning.py`): `free_runs()` counts what is free
  with every member and joint a rigid body, rigidly joined ones merged,
  and holds each run whose turning is still free (a beam on two balls with
  an arm hanging from one end; a mechanism under load, once 7480 km of
  deflection). It can only add holds, and it takes a member the mesh ties
  to a surface (`_curve_members_on_surfaces()`) or one joined to a member
  it does not count as held, so it misses mechanisms through slabs rather
  than invent ones there.
- **A movement of the whole structure that nothing resists is reported**
  (`zb7`, `W-SUP-008`, `analysis/rigid_body.py`, `_report_free_movements()`
  after the writer's own holds). The structure is one rigid body there, so it
  finds only real mechanisms and misses those inside it (spinning and the
  plane hold look for those). `Two_Span_Beam.ifc` had three supports free
  along the beam: CalculiX solved it without a word, the whole beam 5.8 mm
  along its length. Not held for the user: which support should hold it is
  theirs to say.
- **A plane truss or frame that can leave its plane is held in it**
  (`_hold_plane_structure()`, `94g.3`). `analysis/plane_structure.py`:
  `plane_normal()` recognises one (curve and surface members in one plane
  of any direction, loads, the self-weight of load cases and gravity in it,
  section axes and supports in and across it; a straight run takes the
  plane of its loads) and returns its unit normal, exactly a global axis
  when it is one (`global_axis()`). `out_of_plane_freedoms()` counts what
  nothing restrains, with members and joints as rigid bodies tied by the
  file's connections and supports (a surface member in translation only,
  which can only overcount). If any, every node gets the translation
  across the plane restrained (a `*BOUNDARY` of its own, not in
  `ALL_BC_NODES`, so not in the reactions; in a skew plane an `*EQUATION`
  per node, `_plane_hold_equations()`, with what its support holds put in
  and arm and hinge tips left out), `spinning_members()` says where to hold
  what can still spin (in a skew plane with a stiff arm along the normal,
  `_build_spin_arms()`), and one warning reports it (`94g.9`).
  An `*EQUATION` on a shell node ties the mean of its top and bottom
  layers only (see Skew supports in `supports.md`); the plane hold's is across the shell,
  where that does not matter. Linear static
  only: buckling out of the plane must stay possible. A plane model that
  stands up (`beam_01`, `portal_01`) is untouched. **Never restrain a
  rotation at a node inside a member in bending**: CalculiX's rotational
  restraint of a beam node is approximate, and doing so moved a portal's
  moments by 3% and made them unequal. Hold rotations only at a pinned end
  or at a support, as `_hold_spinning_members()` does.
- **Curve members that touch share a node, connection or not** (`aiz.80`).
  `fragment()` gives a beam ending on the span of another, or two that
  cross, one node there, and a shared node is a rigid joint. Where no
  connection of the file joins the two
  (`_curve_members_joined_by_the_mesh()`), one warning counts the places
  (`building_02` has 334: its secondary beams and some columns end on girders
  and have connections of their own that join nothing else), and
  `_hold_spinning_members()` counts the joint as one: those beams were once
  reported as free to spin. Rigid is the decision (2026-10-12): analysis
  programs join members that meet, and the IFC specification, which joins
  members through connection objects alone, says nothing of members that
  only touch. Do not make these joints pins, and do not take them apart
  under `--strict-connections`. `plane_structure.py` counts them as rigid
  joints too (`mesh_joints`, `aiz.81`): a plane frame joined that way was
  once held in its plane when it stood up on its own.
- **A connection is a support only if it has an `AppliedCondition`**
  (`stiffness_properties` in the domain model). Without one it restrains
  nothing, however many members it joins and whatever its type.
- **What a connection holds says nothing about how members are joined to
  it** (`aiz.78`). Members meeting at a pinned support with no release of
  their own (`IfcRelConnectsStructuralMember.AppliedCondition`) are joined
  rigidly: a beam runs on over the support. `analyze_connection_type()` once
  called a support with a free rotation a "hinge", and the writer released
  every member there. The writer's "hinge" type is now only for a
  `HingeConnection` built by hand.
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

**A line load may vary along its member or act on part of it** (`aiz.58`). An
`IfcStructuralCurveAction` of type LINEAR or POLYGONAL has an
`IfcStructuralLoadConfiguration`: values with their `Locations` along the member, the
first and last being where the load starts and ends. They become `LineLoad.samples`
(distance from the member's start in metres, force per length);
`_varying_line_load_to_nodal_forces()` integrates them over each element, and
`_seed_load_points()` puts a mesh node at every sample. `portal_01` is loaded on half
of its beam this way and was once analysed with twice its load, because the locations
were not read. `ProjectedOrTrue` is applied in the extractor (`_per_true_length()`).
The other distributions (`aiz.58`):

- **SINUS and PARABOLA** have one value, the largest, at the middle of the member, and
  none at its ends. They are `LineLoad.half_wave` (a key of `HALF_WAVES` in
  `domain/load.py`) and `LineLoad.peak`; `magnitude` is the mean value, as it is for a
  load with samples. `_half_wave_load_to_nodal_forces()` integrates them with a
  five-point Gauss rule.
- **DISCRETE** is a configuration of `IfcStructuralLoadSingleForce` with a location
  each. `_create_domain_loads()` returns a list for that reason: one `PointLoad` per
  force, with id `<GlobalId>#<n>` and `action_id` the GlobalId (the check for loads in
  no load case goes by it). In LOCAL_COORDS they keep `coordinate_system = "local"`
  and `member_reference`, and `_point_load_lines()` turns them with the member's axes.
- **A point load on the span of a curve member gets a mesh node**
  (`_seed_load_points()`), whatever it came from. It once went to the nearest node,
  silently if that was within 0.1 m.
- EQUIDISTANT and USERDEFINED actions, the varying actions of IFC2X3 and a warping
  moment raise `ModelExtractionError`; never read one as a constant load.
- **A point action in LOCAL_COORDS is in the axes of the item it is assigned to**
  (`aiz.85`): a member's, or a connection's `local_axes` (the
  `ConditionCoordinateSystem` of a point connection, the global axes when it has
  none). `_point_load()` sets `coordinate_system` and puts the item's GlobalId in
  `member_reference`, a connection's as well; `_to_global_axes()` turns force and
  moment. Assigned to no item, or to a surface connection, it raises.

**Applied moments** (`aiz.58`) are `Load.moment`: N·m on a `PointLoad`, N·m per
metre on a `LineLoad` with one value (a moment that varies along its member raises).
They are written as `*CLOAD` on rotations 4 to 6. CalculiX makes a beam node loaded
that way a knot, and the moment arrives in the member (measured on hand-written input
at a member's end, between elements and at a middle node, on 2.21 and 2.23). This is
not the `*EQUATION` on DOF 4-6 that does nothing (see `connections.md`). Things to keep:

- A moment per length is shared out to the nodes as a force is. A couple along a beam
  then leaves a saw tooth in the moment diagram of half of what one element carries.
- A moment on a rotation that a support holds by `*BOUNDARY` goes straight into the
  support. `_StepLoadRecorder` notes it and does not pass it on to the file: the
  solver would warn for each one ("zero coefficient on the dependent side", "no MPC is
  generated for the mean rotation").
- `support_node_loads` has six values per node. A support's moment is its member
  ends' less the point moments applied at its own nodes
  (`_moments_on_support_nodes()`), not the nodal shares of a moment per length, which
  the section forces at the end of the member include already (measured: taking them
  off gave 2020.8 N·m for 2000).
- A moment at a node of no curve member raises `AnalysisError`: shells alone have no
  rotation about their normal.
- `plane_normal()` takes a moment about the normal as a load in the plane.
- A load case of moments alone has no force for the reactions to be compared with;
  `BALANCE_NOISE_N` (1 mN) stops rounding from being reported as an imbalance.

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
no combinations (a warning says so). A load case with neither loads nor
self-weight has no step and adds nothing (`cases_without_loads`). `TestLoadCombinations` checks a
combination against hand values and against one case holding the factored
loads.

**Reference results**: `examples/analysis-models/models/<name>/<name>.rmed` are
Code_Aster results for the same IFC files under self-weight (HDF5; read
`CHA/Bld_DISP` with h5py, six components per node stored component by
component). Use them to check any change to joints, supports or shells.
Compare the displacement field at several points and the reactions, not only
the largest displacement: `structure_01` once matched its reference maximum to
11% with a slab that was too stiff and a wall that was leaning over.

`portal_01.ifc` holds results of its own (`IfcStructuralPointReaction` and
`IfcStructuralCurveReaction` in an `IfcStructuralResultGroup`, in lbf and inches):
reactions, and member end forces. `_portal_reactions_in_the_file()` reads them. They
were computed with a shear area of about 0.79 of the section, where this library
takes the web of an I section, so thrust and moments differ by 2 to 6%; the vertical
reactions agree to 0.02%. Its displacements are in some other unit and are not used.
