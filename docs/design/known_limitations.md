# Known Limitations

Open bugs and proposed work are tracked in beads (`bd list --status=open`), not
here. This section only records the constraints that shape day-to-day work.

- **Stock CalculiX is the target** (decision 2026-10-09). The local `ccx` may be
  a patched Copr build; CI runs Ubuntu's package (2.21) on three Python
  versions and conda-forge's 2.23 in a job of its own
  (`test-calculix-2-23`). Do not rely on the gen3delem patch in `patches/`.
- **Reactions are the solver's nodal forces less the loads applied at the
  support nodes** (`94g.1`). CalculiX's `RF` is the force inside the
  structure at a node: a load applied there in a restrained direction is
  missing from it and one in a free direction appears in it (measured).
  `write_analysis_steps()` records what each step puts on support nodes
  (`_StepLoadRecorder` reads the `*CLOAD` lines as they are written;
  `_weight_on_nodes()` gives the share of `*DLOAD GRAV`), and
  `ResultsExporter` takes it off. Reactions then equal the applied loads to
  six figures at any mesh size; `global_reactions` carries `applied_load_N`
  and `imbalance_N`.
- **The solver's force at a node is what the elements there put on it; an
  equation's share is not in it** (`uda`). So a member tied to a support node
  gives its force at its own node, and a support that does not hold that member
  never saw it: a wall hinged to two floors, whose foot ends at corners other
  walls' supports hold, was 15.7 of 539 kN short (and the horizontal reactions
  not zero), 2.8 kN of it sideways, with every displacement right. Every
  translation tie between nodes at one point is noted
  (`_translation_ties`), and `_add_nodes_tied_to_supports()` counts the nodes
  tied to a support node as that support's: in `ALL_BC_NODES` and its record
  and not in `BC_<id>`, as arm tips are. Nothing about the solve changes. A
  node a support holds itself stays that support's. Measured: the imbalance goes
  from 3% to 3e-8 at any mesh, on 2.21 and 2.23.
- **The moments in `global_reactions` are added up from `supports`**
  (`94g.10`): each support's moments and its force at its position, about
  the origin of the global axes. The solver has no total moment, and the
  keys were zero in every model until schema 1.7. They are absent when a
  support has no moments. `write_analysis_steps()` records the moment of
  each step's loads about the origin (`StructuralModel.applied_load_moments`:
  every nodal force where it acts, and every moment applied), which is
  beside them as `applied_moment_Nm` with `moment_imbalance_Nm`. Measured:
  the two cancel to six figures or better in all eight example models
  (`building_01` `Dead`: 194 162 872 against 194 162 905 N·m), and on
  CalculiX 2.21 to 5 in 100 000 in `beam_01` and `portal_01`, where the
  forces come from the member ends.
- **CalculiX gives a node no reaction moment; its forces on the expanded
  nodes have it** (`94g.8`). `*NODE FILE` asks for `RF`, which puts the
  force on every node of the expanded solids in the FRD. The writer records
  every element at each support node, links and arms included
  (`_record_support_node_elements()`: the forces between the elements at a
  node only cancel when all are added); `parse_support_node_moments()` takes
  an expanded node for the node of its element it is nearest to and gives
  the moment of those forces about each support node; `_support_entry()`
  adds the lever arms of the nodal forces and takes off every moment
  applied at the node, shares of a moment per length too
  (`support_node_loads` has values 7 to 9 per node for that). Measured: a
  cantilever root, a slab clamped along one edge and a bar clamped along
  its span give statics to five figures at any mesh size, where member ends
  gave 0.1%. In a statically indeterminate model they are the mesh's own
  answer: `beam_01`'s fixing moment is 0.4% above beam theory at 0.5 m and
  0.1% at 0.1 m, and the moment at that end of the member's diagram agrees
  with it to 1 in 100 000 (`aiz.89`, below). CalculiX 2.21 has these forces wrong at a clamped member end
  only (the same as 2.23 on the slab edges, the wall foot and the grid),
  with the printed force wrong by as much, so the check on the forces
  covers the moments.
  `supports[].moments` is `"solver"` then. The section forces at the ends
  of the members (`_member_ends_at()`) remain the check on the solver's
  forces and the source (`"member_end_forces"`) where it got them wrong, or
  a node has a user element; `"not_computed"`, with the keys absent, only
  where neither can be had. A node whose expanded forces do not add up to
  the force printed for it gets no moment (the tolerance allows for six
  figures of a couple through a slab's thickness, which at a coarse mesh
  is far larger than the node's force).
- **CalculiX 2.21, Ubuntu 24.04's, misreports `RF` at a support that holds
  a rotation** (2.23 is right, stock as well as the Copr build;
  displacements are identical). The errors of two
  supports can cancel, so `ResultsExporter` checks each such support against
  its member ends (3%) and the whole against the applied load, replaces what
  it can (`forces: "member_end_forces"`), and
  `plausibility.balance_warnings()` says so. 2.21 is wrong at clamped member
  ends only (measured: slab edges, a wall foot and supports a member runs on
  past are as 2.23 has them), so when the supports balance the loads to 1%
  with those replaced, the others keep the solver's forces and moments and
  the total in `global_reactions` is that of the supports where the solver's
  own does not balance (`forces: "supports"`; `_supports()` builds them
  twice for that). A solver's total that balances is kept: in `beam_01` the
  errors of the two supports cancel and it is exact. Only if
  they still do not balance are the others `"unreliable"` and the total the
  solver's (`94g.7`). Measured on 2.21: `portal_01`'s own total is 11%
  short and the supports' is off by 5 in 100 000; `structure_01`'s wall
  foot was unreliable and is not. `building_02`'s own total is 4% over, 26
  of its 51 supports are replaced, each within 4e-5 of what 2.23 gives (the
  other 25 are identical), and the total balances to 2e-5 (`1y6`). **A point force on a support node is not
  in the member's end**: `support_node_loads` has it a second time (values
  10 to 12, from the `** Point loads` line the load writer puts before
  them) and `_support_entry()` takes it off the member end's force before
  comparing. Without that a load on a clamped node made the solver look
  wrong on any version and the reaction came out short by the load. **A
  member tied to a surface along its length is no check on its support**
  (`_member_ends_at()` returns None for it): its end has its share of the
  force only. Two cantilevers under a slab had 58.5 N each for 49.7, as
  `member_end_forces` with a warning, on 2.23; on 2.21 such a root is now
  `"unreliable"`, which it is. Tests of the solver's own
  reactions at clamped supports call `_needs_solver_reactions()` and are
  skipped on 2.21; the 2.23 job in CI fails if any of them is skipped. To run the suite against 2.21 locally: a container from
  `ubuntu:24.04` with `calculix-ccx`, and a `ccx` script first in `PATH`
  that runs `podman run --rm -v "$PWD":/w:Z -w /w <image> ccx "$@"`.
- **Only the solid rectangle is written as a CalculiX section**, with one
  shear modulus lowered to correct its torsion. Every other
  profile is an equivalent rectangle (see `sections.md`). Do not
  go back to CalculiX's CIRC, PIPE or BOX: a PIPE cantilever measured 83% too
  flexible with the weight of a solid bar, and B31 rejects PIPE and BOX.
- **U1 beams are opt-in** (`--open-sections user-element`) and only correct in
  all-U1 models. On stock CalculiX a U1 element next to any other 1D/2D
  element crashes in gen3delem
  (`CalculixRunner._raise_if_known_gen3delem_user_element_bug()` reports it);
  on a patched build a U1 beam and a native beam sharing a node transfer no
  moment (`aiz.14`), and a U1 member at a connection is tied in translation
  only. So the writer refuses a U1 member joined to native beams or shells,
  by a shared node or a connection, unless the file releases every rotation
  of one of the two (`_check_user_elements_join_their_own_kind()`, an
  `AnalysisError`). CalculiX gets the nodal forces of U1 wrong
  (`resultsmech_u1.f` adds both end forces with one sign and recovers them
  with `1/(1 - phi)`: a root printed -1500 N, or 728 N, for +1500), and its
  printed section forces with them. At support nodes where only U1 elements
  meet, `ResultsParser._correct_user_element_forces()` replaces force and
  moment with the elements' stiffness times the displacements
  (`analysis/user_element_forces.py`, the matrix of `e_c3d_u1.f` as it is,
  which is not the textbook Timoshenko beam) and corrects the printed total
  (`aiz.19`). Good to about 1e-4: the FRD has six figures, and the shear of a
  short element is a small difference of its displacements. Measured the
  same on 2.21 and 2.23. Statics decides at run time: if ours do not balance
  the loads and the solver's do, CalculiX has changed U1 and its forces are
  kept, with a warning to update the matrix; if both balance, a warning says
  the solver has put it right; if neither, a U1 warning says so.
  **Section forces of U1 members** (`bgz`) come from the same matrix:
  `ResultsParser.compute_user_element_section_forces()` takes each
  element's stiffness times its displacements, less its share of the loads
  along it (`StructuralModel.user_element_loads`, recorded per step by the
  load writer: `_note_user_element_loads()` works out each element's share
  on a set of that element alone, and the self-weight is half of each
  element's at either end), and gives records at both ends and no middle,
  which `_restore_jumps()` leaves as they are. A U1 element carries no load
  of its own, so these are the forces of statics at every node of a
  determinate member, at any mesh. The six figures of the FRD limit them
  towards a free end, where the forces are small differences of large
  displacements: measured on the I cantilever about its weak axis, shear
  out by 0.7% of the root's at a 0.25 m mesh and 5% at 0.05 m, moments by
  3e-4 to 1e-3; about the strong axis 0.1% and 0.5%.
- **Equivalent-rectangle members have no `max_von_mises_Pa`** (the solver's
  stresses are the rectangle's); `results.json` marks them with
  `section_model`. Their stress is `max_normal_stress_Pa`, from the section
  forces and the real section.
- **Beam section forces are integrated by us** (`analysis/section_forces.py`),
  never requested from CalculiX: it only writes them in 2D output mode
  (`OUTPUT=2D` + `SECTION FORCES`), which averages shell stress through the
  thickness. At each cross-section of an expanded element that has nodes, the
  nodal stresses are interpolated and integrated in the axes the writer
  recorded for the element (`StructuralModel.beam_section_frames`), turned
  to point the way the member does (first point of its geometry to the last)
  so signs are the same along a member. `results.json` has the envelope and
  the signed diagram.
- **`analysis/plausibility.py` warns about results too large to believe**:
  a member distorting by more than 1/100 of its size
  (`max_relative_displacement_m`, which leaves out rigid movement), or any
  displacement over 5% of the model's size. `building_02` with
  `--strict-connections` is the case it was written for. A warning here
  means look at connections and supports before anything else.
- **Nodal stresses are averaged between elements that share nodes**, so a
  force that jumps at a cross-section (shear under a point load, bending
  moment under an applied moment) comes out as the mean of the two sides.
  `ResultsExporter._restore_jumps()` puts the step back from the elements'
  own middle cross-sections. A force at the middle of a quadratic element is
  the mean of the element's own two ends, less what the load does by varying
  along it, so a middle that is not the mean of the solver's two end values
  says the jumps at the ends differ, by four times as much. `_jumps_between()`
  adds those up along the member; a cross-section with a jump is off the line
  that most of the seven around it are on (`_lines_most_are_on()`), and where
  no line has more than half of them no jump is given (a member tied to a
  slab at every node). Two elements are enough. **Nothing is assumed of the
  load**: the slopes between middles were once compared with their median,
  which put a step of 5 to 14% at every element end under a load that varied
  or covered part of the member (`aiz.84`). Do not go back to slopes between
  middles. Tried and dropped on the way: solving for the jumps from pairs of
  neighbours (one element with senseless values, and `building_01` has them,
  grew into steps of ten times the force along the whole member) and a
  repeated-median fit (it missed the steps where cross beams frame into
  `grid_of_beams`, three jumps in seven cross-sections). A bending moment
  changes by its shear per metre, so what the shear on each side does not
  account for is its jump. At a knot (members at an angle) the nodes are
  separate and the values are already one-sided. Members in line that are
  joined rigidly share nodes as two elements of one member do
  (`_ends_shared()`), and their end cross-section is one more with a jump to
  find, of which the member has its half; its moment always gets the value
  the member's own last middle leads to (a 2% threshold once left 24 700 and
  24 830 N·m over a support for 24 765, `lo7`). **Change a section force with
  `_shift()`**, which moves the record's `force` and `moment` vectors with it:
  the supports are checked against those vectors, and a shear restored in
  `Vf1` alone left both members' ends at a support between them with the
  mean, which cancelled, and the support came out as zero (`lo7`,
  `Two_Span_Beam.ifc`). The envelope in `results.json` is
  taken from these diagrams, never from the raw cross-sections: beside a
  jump the mean can be larger than either side's own value.
- **A moment curved along an element is put right** (`aiz.89`,
  `_correct_curvature()`). An expanded B32R has two integration points
  along it and its nodal stress is the straight line through them, so
  where a load along the element makes the moment a parabola the ends read
  `M'' h²/12` too large and the middle `M'' h²/24` too small (46 N·m at
  `beam_01`'s fixed ends at a 0.5 m mesh). The shear is a straight line and
  right, and `M''` is its change along the element: nothing is assumed of
  the load. It is done after the shear jumps are restored (a point load
  would otherwise count as half a load along the element), with one value
  at a shared cross-section so that a jump in the moment is still found.
  The diagrams, the envelope, `max_normal_stress_Pa` and the member ends a
  support is checked against all read the corrected records
  (`_member_records()`). Measured: `cantilever_01`'s diagram is
  w (L - x)²/2 to 1 in 100 000 at a 0.5 m mesh, where it was 0.5% out.
- **Section forces of a member tied to a surface along its length are its share
  only** (`aiz.86`), and `results.json` marks it with
  `tied_to_surface_members`. A tie brings force in at every node, middle nodes
  included. Under a load spread along the member the diagram is smooth
  (`TestSlabBearingOnBeams`, measured). Where force passes at a point it is
  not: a column of `building_01` standing in a masonry wall has -3457, -871,
  +1717 kN in its first element at a 0.5 m mesh and -4145, -834, +2574 kN at
  0.25 m. The size is real (its `Dead` case is 48.5 MN), the values at the
  ends of that element grow as the mesh is refined, and `_restore_jumps()`
  has nothing to go by there. The tie warning says so; nothing is smoothed.
- **`building_01` solves**; its reactions match the applied loads (282.0 and
  13.5 kN) and its self-weight is dominated by a 202 t/m³ `Masonry` material
  in the file. `building_02` solves, its reactions match the applied loads and its
  deflections are plausible (26 mm under Live at a 2 m mesh), but it has no
  reference, and a 1 m mesh needs more than 5 GB of memory (`aiz.37`).
  Never run it finer than 2 m on the development machine. The knots of `aiz.104`
  took a whole run at 2 m from 13 min and 2.34 GB to 15 min and 3.10 GB, and moved its
  largest displacements by 0.34% and its supports by 0.35% at most; the figures for
  `ccx` that follow are from before them. Measured
  2026-10-17: at 2 m `ccx` alone needs 60 s and 2.08 GB (SPOOLES, the only
  direct solver of stock builds); `SOLVER=ITERATIVE CHOLESKY` does not
  converge on expanded shells, and S8R quads instead of S6 save 17% of
  memory on a plate. Measured 2026-10-18 on a machine with 6.7 GB and as
  much zram: at 1 m the whole run takes 24 min, `ccx` about 5 to 5.5 GB,
  reactions balance to 1e-7, and the largest displacements are 2 to 6%
  above those at 2 m (Dead 17.81 against 16.81 mm, Live 26.64 against
  26.06). A 2 m mesh is good enough for development.
- **Member results are read on the faces of expanded elements.** A member's
  largest displacement in `results.json` includes what its rotation adds at
  the faces: a few percent on a slender member, more on a deep one. Its
  `deflected_shapes` (`94g.13.2`, `ResultsExporter._member_deflections()`)
  are the axis: at each cross-section the nodes' movement is fitted with a
  rigid body's (translation of the centre, rotation of the section), which
  matches Timoshenko's cantilever to 1.5e-4 (`TestDeflectedShape`). The
  movement of each point connection (`connections`, `94g.13.3`, for an IFC
  result export) is taken from them, carried out to the connection as a
  rigid body; no rotation where every member there is released.
  Surface members have `surface_mesh` and `surface_fields`
  (`export/surface_fields.py`, `94g.13.5`): membrane forces and plate
  moments from a straight-line fit through the thickness of the expanded
  solid's stresses, shears from the moments by equilibrium (the solver's
  own transverse shear was 12% high at a clamped edge), for load cases only
  (linear: a combination is its cases times their factors), as are the
  deflected shapes: in `building_02` the two for its 16 combinations were
  26 MB of 62. The exporter of a combination (`_for_a_combination`) builds
  only what is copied back from it. The writer
  records the shell mesh for it (`StructuralModel.shell_elements`).
  `ResultsExporter.write()` puts lists of numbers on one line.
  `global_displacements` leaves out the nodes of links and arms, elements of
  no member (`ResultsExporter._link_nodes()`, `aiz.92`): their faces are up
  to 0.25 m from their axis, and one set `structure_01`'s largest Y
  displacement 57% above the structure's own and `building_01`'s `Dead`
  0.6% above it.
- **`slab_01.rmed` is not a reference for `slab_01.ifc`** (`aiz.36`): it was
  computed with one edge hinged; the IFC file as shipped clamps both. The
  Code_Aster runs also give their rigid eccentricity arms weight (16 N each in
  `grid_of_beams`, whose reference maximum is 0.029 mm too high for it).
- **Self-weight is what the file says it is** (`aiz.71`, decision
  2026-10-12). `IfcStructuralLoadCase.SelfWeightCoefficients` are the shares
  of the members' weight a case includes along global x, y and z
  (`LoadGroup.self_weight_coefficients`, `includes_self_weight`); the case's
  step gets `*DLOAD GRAV` scaled and turned by them
  (`_write_self_weight()`, with `STANDARD_GRAVITY` = 9.81 m/s², which IFC
  does not give). A case with nothing else is still a case: select load
  cases with `LoadGroup.has_actions`, never with `.loads`. `Dead` has
  `(0, 0, -1)` in `beam_01`, `building_01` and `building_02`. A buckling
  step has the weight of every case, as it has every load.
- **`--gravity` is for files with no load case** (`cantilever_01`,
  `slab_01`, `structure_01`, `grid_of_beams`, which have no loads otherwise,
  and whose Code_Aster references are self-weight runs). It adds a case of
  its own, `Gravity`, that no combination includes, and warns when a case of
  the file already has self-weight. Do not make it change the file's cases.
- **Benchmarks on `beam_01` variants take the weight out** (`_beam_01()` in
  `test_pipeline_benchmarks.py`) so that one load is checked against its
  closed form; those that run the file as shipped include it.
- **Buckling factors** come from a single `*BUCKLE` step that contains the
  loads. CalculiX scales only loads defined inside that step; a preceding
  `*STATIC` step is a fixed preload. Validated for one Euler column only.
  The result file has the displacements under those loads first (the same
  as a static run, measured) and then a shape per mode, on a scale of the
  solver's own (the largest translation 5.6e-4 for a column's first mode,
  2.3e-5 for its tenth; it was once documented as one, which it is not).
  `ResultsParser._set_mode_shapes_apart()` moves the shapes to
  `parsed_results["mode_shapes"]`; they are not displacements and must never
  be listed as load cases (`aiz.73`). `results.json` has the one case
  `Reference loads`, `buckling.modes` with the factors, and each curve
  member's `mode_shapes` (`94g.13.4`), each mode scaled by
  `ResultsExporter._scale_buckling_shapes()` to a largest translation of
  one along any member. A modal analysis's `mode_shapes` keep the solver's
  scale, a generalised mass of one.
- **Modal analysis** (`lon`, `--analysis-type modal`, `--modes`, default 10)
  is one `*FREQUENCY` step and no load. Its mass is the materials' density
  alone (a material without one stops it, `E-MAT-003`): IFC cannot say
  which loads are mass, so none is, and `W-LOD-011` says so when the file
  has load cases. Links, arms and springs have no mass; knots for point
  loads are not made and the plane hold is not applied (modes out of the
  plane are real). U1 members are refused (`E-SEC-006`): CalculiX gives
  them no mass. `ResultsParser.parse_frequencies()` reads the frequencies,
  participation factors and effective masses (rotations about the global
  origin) from the .dat, the same on 2.21 and 2.23; every displacement set
  in the .frd is a shape, mass-normalised, and goes to `mode_shapes` as
  `Mode <n>` (buckling shapes are named so too). A mode below 0.01 Hz or
  with a negative eigenvalue is `mechanism` (`W-CHK-003`): CalculiX solves
  a mechanism and gives such modes rather than stopping. Measured
  (`TestModalAnalysis`): an equivalent rectangle has the real section's mass
  and rotary inertia, rho (Iy + Iz), and its bending modes are Timoshenko's
  with kappa 1 on the real shear areas to 1e-3; axial modes are exact;
  torsion of a solid rectangle is 0.8% low, of an open section 5.4 times too
  high (30 times too stiff). `cantilever_01`'s first four vertical modes
  are Timoshenko's with 5/6 to 1e-6 (they were 0.16 to 2.8% above before
  its shear modulus was put right, `aiz.101`); sideways they follow the
  width modulus written, 17% above 5/6 G, to 1e-3. `slab_01` held in translation on four
  edges is 1.4 to 1.7% below Mindlin's hard simply supported plate, as its
  static deflection is 2.6 to 3.3% above Navier's.
- **FRD/DAT parsing is duplicated on purpose** between `results_parser.py` and
  `ccxquery/parsers/`; `ccxquery` is a standalone debugging tool.
