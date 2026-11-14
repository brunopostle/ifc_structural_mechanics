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
- the eccentricity of the column tops only in `IfcRelConnectsWithEccentricity`, which is
  not read yet (`ifc_structural_mechanics-d36`);
- no relation between the slab and the column tops (tied by `W-JNT-003`).

`tests/validation/test_pipeline_benchmarks.py::TestRfemExport` checks it against RFEM's
own 0.441 mm.
