# Models exported by RFEM

`structure_01_rfem.ifc` is `structure_01` (`../analysis-models/ifcFiles`) rebuilt in
RFEM 6.16 and exported by it as structural IFC4, unchanged (2026-11-14). It is not valid
IFC (`ifcopenshell.validate` finds unset representation types and connections joined to
nothing), which is why it is here and not in `tests/test_data`. What RFEM does that other
tools do not:

- coordinates with Z down, turned up by the analysis model's `SharedPlacement`, which
  curve members and connections have as their `ObjectPlacement` and surface members do
  not have at all (read in the SharedPlacement, `W-IFC-007`);
- `IfcTopologyRepresentation` with no identifier or type (read from its items);
- material properties named `Young modulus`, `Poisson's ratio`, `Density`;
- an `IfcStructuralSurfaceConnection` with no condition on each surface member (left
  out, `W-SUP-009`);
- the columns drawn up to the slab, and the 0.15 m eccentricity of their tops only in
  `IfcRelConnectsWithEccentricity`, its `PointOnRelatingElement` measured from the joint
  and not from the start of the member as IFC says (read so, `W-JNT-011`;
  `ifc_structural_mechanics-d36`);
- no relation between the slab and the column tops (the slab is joined to them,
  `W-JNT-012`).

`tests/validation/test_pipeline_benchmarks.py::TestRfemExport` checks it against RFEM's
own 0.441 mm, and that its columns move as in the ifc2ca file.

`bonsai_frame_3d_rfem.ifc` is the frame of `../bonsai` built again in RFEM 6.15 and
exported, unchanged (a user's report, 2026-11-18). It has no self-weight case, so it has
Q, Wx and Wy of the Bonsai model's four load cases. What it adds to the list above:

- load cases that are `IfcStructuralLoadGroup`s of type `LOAD_CASE`, not
  `IfcStructuralLoadCase`s (both are IFC4; read as load cases);
- each term of a combination a load group of type `LOAD_GROUP` with the factor as its
  `Coefficient`, holding one load case (read through, the factors multiplied);
- the edges of each face's `IfcEdgeLoop` in the sense of each edge and out of order,
  against IFC's IsContinuous rule (read by following them end to end, `W-IFC-008`);
- the zero components of its point loads written as denormal numbers such as
  1.5e-309, uninitialised memory; they are read as the near-zeros they are.
