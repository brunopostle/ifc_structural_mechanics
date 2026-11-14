# IFC units and placements

**Units are not all made of the length unit** (`94g.22`, `94g.23`). Bonsai's default
project has lengths in mm, areas in m², and no density unit; the example models'
units are all made of their length unit, so none of them shows a mix.
`CrossSectionArea` is in `AREAUNIT`, a density and an inertia in `MASSDENSITYUNIT` and
`MOMENTOFINERTIAUNIT` (`utils/units.unit_to_si()` works through the unit's entities:
IfcOpenShell's scales are to grams, which makes a pound 453.6). IFC does not say what
an unassigned unit means. An unassigned area is in the length unit squared; an
unassigned density is in kg/m³, the spec's "usually", and one that cannot be stops the
analysis (`E-MAT-005`); an unassigned inertia is in m⁴. Pset_ProfileMechanical of a
profile is used where it agrees with the dimensions to a factor of 1.5, else the
dimensions are, with `W-SEC-005` (`94g.24`): Bonsai can write m⁴ under a declared mm⁴.
Where the value as written agrees with them, the message says it looks to be in m⁴ (or
m²) under the unit declared and what to change (`94g.27`); it is not read so (decision
2026-11-07): the file is read as it declares, and the outline's inertias are the
tables' to 1e-4.
The other derived units are read as declared too (`94g.25`, `Extractor._get_unit_scales()`):
line and planar forces, torques, moments per length, moduli, thermal expansion and the
five stiffnesses (`portal_01` has lbf·in per degree). Undeclared, each is made of the
length, force, pressure and temperature units, a rotational stiffness per radian;
Bonsai's templates declare none of them. Where that depends on a length unit other
than the metre (line and area loads, point moments, the stiffnesses but the
rotational one along an edge), `W-IFC-005` says how each kind was read (`94g.32`,
`Extractor._undeclared_unit_warnings()`, from the extractors' `undeclared_units`):
in Bonsai's millimetres 5000 meant as 5 kN/m² is 5000 N/mm². A property's own
`IfcPropertySingleValue.Unit` goes before the project's (`_own_scale()`), so a test that
restates a value of `beam_01` or `building_01`, whose materials give units, has to set
it too. Poisson's ratio from E and G is worked out in SI, as they may differ.
A derived unit of one unit to the power one (`portal_01`'s moduli in psi) breaks
`IfcDerivedUnit` WR1: it is read as that unit, with `W-IFC-006` (`xxa`). Write GPa as
kN·mm⁻² in tests; every file in `tests/test_data` must pass `ifcopenshell.validate`
with EXPRESS rules (`tests/unit/test_test_data_is_valid.py`). A value is in the
unit of its measure type: IFC4's `Pset_MaterialMechanical.ShearModulus` is an
`IfcModulusOfElasticityMeasure`, in the `MODULUSOFELASTICITYUNIT`; only an
`IfcShearModulusMeasure` is in the `SHEARMODULUSUNIT` (`lo7`: Bonsai declares the
first only, and 81000 N/mm² was read as 81000 Pa).

**Everything an item gives is in the axes of its `ObjectPlacement`**: the points of its
representation, a member's `Axis`, a connection's `ConditionCoordinateSystem`. The values
of a load in `GLOBAL_COORDS`, and a load case's `SelfWeightCoefficients`, are not: IFC
calls the analysis model's coordinate system global, so they are in the axes of the
model's `SharedPlacement`, which need not be the project's (RFEM writes Z down; `0io`).
`loads_extractor.global_axes_placement()` takes the SharedPlacement of the model of the
action's item, else of its load cases, else the action's own `ObjectPlacement`, the rule
of `ifcopenshell.util.structural.get_global_axes`; a load case that no model is loaded by
directly is in the models of its combinations (`beam_01`). Every example's
SharedPlacement is the identity. A structural item with no `ObjectPlacement` is read in its model's SharedPlacement,
which IFC says "shall be common to all items" of the model: RFEM 6 places curve members
and connections there (Z down turned up) and surface members nowhere, and read in the
project's axes its slab lay 3 m below the columns it rests on (`W-IFC-007` when the
SharedPlacement is not the identity; `E-IFC-006` if the item's models disagree;
`examples/rfem`, `tests/unit/ifc/test_rfem_export.py`). A rotated SharedPlacement is
normal and not warned about. `get_item_transformation(item, length_scale)`
returns the whole chain of placements with its offset in metres; apply it with
`transform_vectors()` to coordinates that are already in metres. No example model has a
placement away from the origin, so nothing but `tests/unit/ifc/test_object_placement.py`
and `TestPlacedModel` will tell you if a new extraction path forgets it (`aiz.57`: members
once added the offset in the file's unit, and supports and loads ignored it).
