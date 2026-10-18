# Warnings and errors

<!-- Written by python -m ifc_structural_mechanics.utils.messages; do not edit. -->

Every warning and error the analysis gives has a code, which the command line prints and `analyze_ifc()` gives as `code` in `result["warnings"]` and `result["errors"]`: W for a warning, E for an error that stops the analysis, the stage of the analysis it comes from, and a number. Within a stage the ones most likely to be met come first. The message itself says what was found in the model; what follows says what it means and what to do.

## Reading the IFC file

### E-IFC-001: No structural members

The file has no IfcStructuralCurveMember or IfcStructuralSurfaceMember. The analysis reads the structural analysis model (the analytical view), not the building elements: create one first, in Bonsai with the structural tools.

### E-IFC-002: Member geometry cannot be read

A curve member needs an IfcEdge representation and a surface member an IfcFaceSurface or IfcFace, with vertices that have coordinates. The message names the member and what is missing.

### E-IFC-003: Placement cannot be used

IfcLocalPlacement is supported, with axes that are not parallel, and IfcGridPlacement on straight grid axes (lines, straight polylines, their trims and offsets) that are not parallel. Circular grid axes and IfcLinearPlacement are not. Place the item with a local placement.

### E-IFC-004: Units cannot be worked out

The project's units (IfcUnitAssignment) do not say what a value of this kind is measured in, so it cannot be converted. Give the project its units.

### E-IFC-005: Entity cannot be read

Reading an entity of the file failed unexpectedly; the message gives the entity and the error. The file may not be valid against its schema: check it with a validator. Report it with the file if it is valid.

### W-IFC-001: More than one structural analysis model

The file has several IfcStructuralAnalysisModel and only the first is analysed. Split the file, or put the model to analyse first.

### W-IFC-002: Members without a material (retired)

No longer given: such members stop the analysis (E-MAT-001).

### W-IFC-003: Curve members without a section (retired)

No longer given: such members stop the analysis (E-SEC-001).

## Materials

### E-MAT-001: Member without a material

A surface member needs an IfcMaterial (directly, or through a layer or constituent set), and a curve member gets its material with its profile (E-SEC-001). Assign one.

### E-MAT-002: Material without a Young's modulus

The material has no Pset_MaterialMechanical.YoungModulus, and nothing can be analysed without it. Add it.

### E-MAT-003: Self-weight of a material without a density

A load case includes self-weight, --gravity was given, or the analysis is modal, and a material has no Pset_MaterialCommon.MassDensity, so the weight or the mass cannot be worked out. Give the material its density.

### E-MAT-004: Elastic constants that do not fit together

The material has a shear modulus and no Poisson's ratio, and the two moduli give a ratio no isotropic material has (or the shear modulus is not positive). Check the constants.

### W-MAT-001: Material without a mass density

The material has no Pset_MaterialCommon.MassDensity, so its members weigh nothing. That is only right if no load case includes self-weight; when one does, or --gravity is given, the analysis stops instead. Give the material its density.

### W-MAT-002: Material without a Poisson's ratio

The material has neither Pset_MaterialMechanical.PoissonRatio nor a shear modulus, and 0.3 is used. That suits steel and is near enough for most concrete (0.2) in bending; shear and torsion stiffness depend on it. Give the material its ratio.

### W-MAT-003: Shear modulus does not agree with the other constants

The material gives Young's modulus, Poisson's ratio and a shear modulus that an isotropic material cannot have together. The analysis uses Young's modulus and Poisson's ratio. Check which of the three is right.

## Sections

### E-SEC-001: Curve member without a profile

A curve member needs an IfcMaterialProfileSet (usually through an IfcMaterialProfileSetUsage) with a material and a profile. Assign one.

### E-SEC-002: Profile not supported

Supported profiles are the rectangle, circle, hollow rectangle, hollow circle, I, asymmetric I, T, L and U (channel) parameterised profiles. An arbitrary or composite profile has no section properties the analysis can use. Use one of those, or ask for the profile.

### E-SEC-003: Surface member without a thickness

IfcStructuralSurfaceMember.Thickness is empty. Give it.

### E-SEC-004: Section cannot be analysed

The section's properties cannot be turned into a CalculiX section (a dimension or stiffness of zero, or one missing for user elements). The message says what.

### E-SEC-005: Section direction cannot be found

A curve member of no length, or with ends that cannot be read, has no direction to place its section by. Check its geometry.

### E-SEC-006: User elements in a modal analysis

CalculiX gives its U1 elements no mass, so a modal analysis cannot be made of members analysed with them (--open-sections user-element). Analyse the model with equivalent sections.

### W-SEC-001: Torsion of solid rectangles corrected

CalculiX makes a solid rectangular beam too stiff in torsion (18.5 % for a square) and in shear (it shears with its whole area, not 5/6 of it). The shear stiffness along the member's depth is set to Timoshenko's and the one across its width is changed until its torsion is right; it is then off by the percentage given, a few percent for a section up to twice as deep as wide. A deeper section would need a modulus across its width above the material's, so that one is held at the material's and the one along the depth raised instead: its shear stiffness along the depth is then too high by the second percentage given (4 % at 3:1, 14 % at 10:1). Bending is not affected. Nothing needs doing unless a result depends on that shear.

### W-SEC-002: Sections analysed as equivalent rectangles

CalculiX has no I, T, L or channel shape, so these members are rectangles with the same area, bending stiffness and weight. Their deflections and section forces are right; their stress is worked out from the section forces and the real section (max_normal_stress_Pa), and the solver's own stresses are not given. An open section is far too stiff in torsion: do not rely on results where such members carry torsion, nor on modes in which they twist. Closed and round sections have their torsion right and are up to twice too stiff in shear.

### W-SEC-003: Section orientation guessed

The members have no usable Axis (IFC2X3 has none; an axis along the member says nothing), so which way the section faces is a guess: its depth as near vertical as the member allows, along global X for a vertical member. Strong and weak axes may be the wrong way round. Give each curve member an Axis.

### W-SEC-004: Section approximated

Something of the member's section could not be represented exactly; the message says what.

## Meshing

### E-MSH-001: Gmsh failed

Gmsh could not build or mesh the geometry; the message gives its error. Members that cross at very small angles, or tiny edges where members nearly meet, are the usual cause. Try another --mesh-size, and check the geometry where the message points.

### E-MSH-002: Members with no elements

These members have no elements in the mesh, so the model cannot be analysed as given. A member wholly inside another loses its elements to it; that is a warning (W-MSH-002) unless nothing is left.

### E-MSH-003: Elements cannot be attributed to members

The mesh has no physical groups, so with more than one member of a kind it cannot say which element belongs to which. This is an internal error: report it.

### E-MSH-004: Support or joint cannot be laid onto a surface

A surface support's outline, or a line joining a beam to a slab, could not be put into the slab's geometry. Check that it lies in the surface.

### E-MSH-005: Unknown meshing option

A meshing option has a value Gmsh does not know; the message lists the ones it does.

### W-MSH-001: Members overlap

Two members occupy the same place (a short beam inside a longer one, a landing in a floor slab). The mesh has one set of elements there, analysed with the material and section or thickness of the member that comes first in the file, not both. Remove the overlap if both were meant to carry load.

### W-MSH-002: Members with no elements

These members lie wholly inside others (see W-MSH-001) and have no elements of their own. They take no part in the analysis and have no results; the member they overlap carries their share.

## Joints between members

### E-JNT-001: Member does not reach its connection

The mesh has no node for a member at a connection it is joined to, so it cannot be joined there. The connection probably lies off the member: check both.

### E-JNT-002: Line connection cannot be made

An IfcStructuralCurveConnection joins a beam and a slab all along it. Here it joins two curve members, or a member that does not run along the line or lies too far from it, or the slab's mesh has no node where the beam's does. The message says which.

### E-JNT-003: User elements joined to other elements

With --open-sections user-element, U1 beams pass no moment to native beams or shells, and stock CalculiX crashes on the mix. Release every rotation of one of the members at such joints, or analyse without user elements.

### E-JNT-004: Joint of a kind that cannot be modelled

The connection between members is of a type the writer does not model: a spring joint between members, or a type it does not know. A model read from an IFC file has neither (members are joined rigidly unless their relation releases them, and springs act against the ground); one built by hand can. Report it.

### W-JNT-001: Curve members tied to the surface members they lie in

A beam along the edge of a slab, or a column in a wall, with no connection in the file along their length, is tied to the surface in translation along it, as a slab bears on its beams. Without this a slab connected at its corners spans corner to corner. The member's section forces are its share only; where force passes between the two at a point they change abruptly and depend on the mesh size. Use --strict-connections to analyse only the connections in the file.

### W-JNT-002: Curve members touching without a connection

A beam ending on the span of another, or two members crossing, share one mesh node there, which joins them rigidly, whether or not the file connects them and with --strict-connections too. Most analysis programs do the same. Add a connection with a release if the joint is meant to be a pin.

### W-JNT-003: Curve members tied to a surface member at a point

A column ending on a slab or passing through it, with no connection in the file, is tied to it in translation there. Use --strict-connections to analyse only the connections in the file.

### W-JNT-004: Curve members left unconnected to the surface they lie in

--strict-connections was given, so beams along a slab with no connection in the file are not tied to it, and a slab connected only at its corners spans between them. Expect large deflections if that is not what the file means.

### W-JNT-005: Curve members left unconnected to a surface at a point

--strict-connections was given, so columns meeting a slab where the file has no connection are not joined to it.

### W-JNT-006: Member end too far from its connection

The member ends further from the connection than a rigid link can bridge, so it is tied to the joint in translation only and carries no moment there. Check the geometry of the member and the position of the connection.

### W-JNT-007: Partial rotational release analysed as a pin

The member is released about some rotations at the connection, which cannot be represented where it is, and it is released about all three. The joint is more flexible than the file says.

### W-JNT-008: Connection with no nodes (retired)

No longer given: a connection whose members have no node at it stops the analysis (E-JNT-001).

### W-JNT-009: Spring connection between members not implemented (retired)

No longer given: such a connection stops the analysis (E-JNT-004).

### W-JNT-010: Connection of an unknown type (retired)

No longer given: such a connection stops the analysis (E-JNT-004).

## Supports

### E-SUP-001: No supports

No connection has an AppliedCondition that restrains anything, so nothing holds the structure. Give the supports their IfcBoundaryNodeCondition (or edge or face condition).

### E-SUP-002: Support with no node

The mesh has no node within 0.1 m of the support (or none on its edge or face). It probably does not lie on its member: move it there.

### E-SUP-003: Connection position cannot be found

A point connection needs an IfcVertexPoint representation or a placement away from the origin. Give it one.

### E-SUP-004: Surface connection cannot be used

A surface connection needs a plane face with one outer bound of points and a condition; a condition that differs by direction needs the face to be on an IfcPlane whose axes give the directions. The message says what is missing.

### E-SUP-005: Curve connection without an edge

A curve connection needs an IfcEdge representation whose ends can be read.

### E-SUP-006: Connection of an unsupported type

Only point, curve and surface connections are supported.

### E-SUP-007: Condition cannot be read

The boundary condition lacks a value the analysis needs, or does not pass validation. The message says which.

### E-SUP-008: Elastic support cannot be applied

A spring stiffness is negative, or a rotational spring lies about an axis the analysis cannot represent there (partly released, at an angle to the shells, in a model with user elements), or the elements found do not cover the support's edge or face. The message says which.

### E-SUP-009: Skew rotation in a model with user elements

Holding a rotation about an axis that is not a global one takes a stiff arm, and arms cannot be used beside U1 elements. Analyse without --open-sections user-element.

### W-SUP-001: Members held against spinning about their own axis

Nothing restrains these members' rotation about their own axis: ball supports at both ends of a beam are the usual cause, and so is a member across that has no support of its own and would swing with them. Each, or the straight run of members it is part of, is held in torsion at one of its supports so that the results are defined; that support is reported as holding the rotation. Where nothing loads the movement the hold carries nothing; where a load does (on the member that would swing) the support's moment is the torsion it carries, which the model as given cannot resist. Restrain that rotation at a support to be explicit.

### W-SUP-002: Plane structure held in its plane

Every member and load lies in one plane and nothing holds the structure there, so it is analysed as a plane frame: every node is held across the plane. Forces and displacements in the plane are not affected. Add supports across the plane to analyse it in three dimensions.

### W-SUP-003: Possible mechanism

No support restrains a rotation and no joint between members carries moment, so under sideways load the structure may be a mechanism. CalculiX may report a zero pivot or very large displacements. Check the rotations of the supports' IfcBoundaryNodeCondition and the releases at the joints.

### W-SUP-004: Members free to spin that could not be held

As W-SUP-001, but there was no support to hold them at, so their displacements include an arbitrary rotation about their axis. Restrain that rotation at a support or joint.

### W-SUP-005: Supports that support nothing

These supports are connected to no member and lie on none, so they are left out. Connect them to the members they hold.

### W-SUP-006: Rotational spring about a shell's normal left out

Shell nodes have no rotation about the shell's normal, so a spring about it holds nothing and is left out.

### W-SUP-007: No connections

The model has no structural connections, so nothing supports it and the analysis will fail. Add supports (connections with an AppliedCondition).

## Loads, load cases and load combinations

### E-LOD-001: Load of an unsupported kind

Supported are point, linear, curve and planar actions with single forces, linear forces or planar forces (and their configurations), point actions with single displacements on supports, and curve and planar actions with temperature changes of a constant distribution. Displacements with a distortion and the varying actions of IFC2X3 are not.

### E-LOD-002: Load distribution cannot be used

A load that varies along its member needs an IfcStructuralLoadConfiguration with a value at each of its Locations, in ascending order and on the member. EQUIDISTANT and USERDEFINED distributions are not supported. The message says what is wrong.

### E-LOD-003: Load with nothing to act on

The load is not assigned to a member (IfcRelConnectsStructuralActivity), or has no position of its own or of the item it is assigned to. Assign it.

### E-LOD-004: Load in axes that cannot be used

The load is given in local coordinates of an item that has no axes (none assigned, a surface connection, a curve member with no usable Axis), or per projected length in local coordinates. Give it in global coordinates.

### E-LOD-005: Moment that cannot be applied

Shells have no rotation about their normal and are not given moments; warping moments, moments per projected length and moments that vary along the member are not supported either.

### E-LOD-006: Load without a value

The action has no AppliedLoad, or its force cannot be read. Give it one.

### E-LOD-007: Support displacement that cannot be applied

A prescribed displacement (IfcStructuralLoadSingleDisplacement) moves a support along what it holds. It has to be a point action assigned to a point connection with an AppliedCondition, and every component that is not zero has to be along a direction the support holds rigidly in global axes: not one it leaves free, which would add a restraint the file does not have, not a spring, and not a skew direction, which is held by equations. A buckling analysis takes no support displacements. The message says which applies.

### E-LOD-008: Temperature load that cannot be applied

A temperature change (IfcStructuralLoadTemperature) is applied to the whole of the member its action is assigned to: a curve action to one curve member, a planar action to one surface member, with a constant distribution. The member's material needs a thermal expansion coefficient (Pset_MaterialMechanical.ThermalExpansionCoefficient), which is never assumed. A difference across a curve member needs its local axes (Axis) and a section whose depth is known; a surface member takes a difference across its thickness (DeltaTZ) only, and needs a plane for its normal. A buckling analysis takes no temperature loads, nor does a member of CalculiX user elements (--open-sections user-element). The message says which applies.

### W-LOD-001: No loads

No load case has loads or self-weight and --gravity was not given, so the analysis has nothing to analyse. Give --gravity if self-weight is the load meant.

### W-LOD-002: Loads in no load case

These loads belong to no load group or load case, so no step applies them. Assign them to a load case.

### W-LOD-003: Self-weight asked for twice

--gravity was given and load cases of the file already include self-weight. The weight is analysed again as a load case of its own, Gravity, which no combination includes. Leave out --gravity to use the file's load cases alone.

### W-LOD-004: Load combinations with no load case

These load combinations include no load case and have no results.

### W-LOD-005: Load combinations including something other than a load case

A combination may only include load cases. These include another group (a load group or another combination) and have no results.

### W-LOD-006: Load combinations outside a linear static analysis

Combinations are only formed in a linear static analysis, by adding up the results of their load cases. A buckling or modal analysis has none.

### W-LOD-007: Point load moved to the nearest node

The point load is further than 0.1 m from any mesh node and is applied at the nearest one. Check that it lies on a member.

### W-LOD-008: Load in the local axes of an item that has none (retired)

No longer given: such a load stops the analysis (E-LOD-004), since its direction is not known.

### W-LOD-009: Load on a member with no elements (retired)

No longer given: the loads of a member that another one overlaps are applied to the elements lying in its own geometry, whoever they belong to.

### W-LOD-010: Temperature shared at nodes between members

CalculiX gives each node one temperature, and members meeting at a node share it. Where a heated member meets one with another temperature change (or none) and a thermal expansion coefficient, the node takes the mean of their values, so the elements next to it on both sides see part of the other's change. The effect is local and shrinks as the mesh is refined; a gradient at a joint between members at an angle is the least accurate. The message counts the nodes and names the members.

### W-LOD-011: Loads are not mass in a modal analysis

A modal analysis takes its mass from the density of the members' materials and applies no load. A load that stands for mass (finishes, partitions, a share of the imposed load) is not counted, since nothing in IFC says which loads are mass, and the frequencies are those of the bare structure. Where that mass matters, the frequencies are too high by about the square root of the ratio of the masses.

## The solver

### E-SLV-001: The structure is a mechanism

CalculiX found the stiffness matrix singular: some part of the model can move without resistance. Look for missing supports, members joined by pins on all sides, and members that meet nothing. The warnings W-SUP-003 and W-JNT-008 may point to it.

### E-SLV-002: CalculiX failed

CalculiX stopped with an error; the message gives its output. The input file is kept in the output directory: report it.

### E-SLV-003: CalculiX not found

The ccx executable is not on the PATH or cannot be run. Install CalculiX (2.21 or later; 2.23 recommended) or set its path in the system configuration.

### E-SLV-004: CalculiX did not converge

The solver did not reach a solution; the message gives its reason.

### E-SLV-005: CalculiX crashed on user elements

Stock CalculiX crashes in gen3delem when U1 beams sit beside other beam or shell elements. Analyse without --open-sections user-element.

### E-SLV-006: Input file cannot be written or found

The CalculiX input file could not be written to, copied to or found in the output directory. Check the directory and the space left.

### W-SLV-001: Warning from CalculiX

CalculiX printed this warning, given once for each kind with a count. The analysis removes the causes it knows of, so one that appears is worth reporting with the input file.

### W-SLV-002: More warnings from CalculiX

CalculiX printed more kinds of warning than are listed; the rest are in its output.

## Reading the results

### E-RES-001: Results cannot be read

CalculiX ran but its result files could not be read or turned into results.json; the message gives the error. Report it with the output directory.

### E-RES-002: No results

CalculiX wrote no result file, or one with no displacements. Its output in the output directory says why.

### E-RES-003: Load combination cannot be formed

The results of the load cases of a combination cannot be added up (one lacks results the others have). Report it.

### E-RES-004: Results of user elements cannot be worked out

The forces of U1 elements are worked out from their displacements and the loads along them, and one of those is missing from the results. Report it.

### E-RES-005: No buckling factors

The buckling analysis ran and CalculiX reported no buckling factor.

### E-RES-006: No displacement of a spring

The reaction of an elastic support is its stiffness times the displacement CalculiX prints for it, and it printed none. Report it.

### E-RES-007: No modes

The modal analysis ran and CalculiX reported no frequency. Its output in the output directory says why.

### W-RES-001: Reactions corrected

CalculiX 2.21 and earlier misreport the force at a support that holds a rotation. Such supports have their forces taken from the ends of their members (good to about 1 %), and the message says which totals still do not balance the loads. Displacements and member forces are not affected. CalculiX 2.23 does not need this.

### W-RES-002: Results left out

The solver wrote values that are not numbers or are out of range, and they are left out. Report it with the input file.

### W-RES-003: Forces at supports of U1 elements do not balance

CalculiX gets the forces of its U1 elements wrong, and the analysis works them out from the elements' stiffness instead. Here neither set balances the loads: this version of CalculiX may have a different U1 element. Do not rely on the reactions.

### W-RES-004: CalculiX has changed its U1 element

The solver's own forces at the supports of U1 elements balance the loads and those worked out from the U1 stiffness do not, so the solver's are given, with no moments. Report it: the U1 matrix in analysis/user_element_forces.py needs bringing up to date.

### W-RES-005: CalculiX's U1 forces are right

The solver's own forces at the supports of U1 elements balance the loads, which CalculiX 2.23 does not. The reactions given are worked out from the U1 stiffness and agree with them.

## Plausibility of the results

### W-CHK-001: Member distorts too much

The member bends or stretches by more than 1/100 of its size, leaving out how it moves as a whole. It is probably not connected or supported as intended: look at its connections and supports first.

### W-CHK-002: Displacement too large

A displacement is more than 5 % of the size of the model, so the model is probably a mechanism. Check the supports and the connections between members.

### W-CHK-003: Modes that are mechanisms

A modal analysis found modes with no frequency (below 0.01 Hz, or a negative eigenvalue): some part of the model can move without straining, which a static analysis would stop at. Their frequencies, participation factors and shapes mean nothing. Check the supports and the connections between members.

## Anything else

### E-GEN-001: Internal error

Something the analysis does not expect happened; the message gives the error. Report it with the IFC file and the command.
