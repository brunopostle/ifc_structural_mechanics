"""Derived units and a property's own unit are read as the file declares them.

They need not be made of the file's length and force units (``94g.25``): every
value here is what the file gives in the unit it declares, and each test would
be wrong by the factor shown if the unit were made of the base units instead.
"""

import os

import ifcopenshell
import pytest

from ifc_structural_mechanics.ifc.entity_identifier import get_connection_input
from ifc_structural_mechanics.ifc.extractor import Extractor

IFC_DIR = os.path.join("examples", "analysis-models", "ifcFiles")

pytestmark = pytest.mark.skipif(
    not os.path.isdir(IFC_DIR), reason="example models submodule missing"
)

# An open file has to outlive its entities
_FILES = []


def _open(name):
    model = ifcopenshell.open(os.path.join(IFC_DIR, f"{name}.ifc"))
    _FILES.append(model)
    return model


def _si(model, name, unit_type, prefix=None):
    return model.create_entity(
        "IfcSIUnit", UnitType=unit_type, Prefix=prefix, Name=name
    )


def _derived(model, unit_type, *elements):
    """A derived unit of (named unit, exponent) pairs."""
    return model.create_entity(
        "IfcDerivedUnit",
        Elements=[
            model.create_entity("IfcDerivedUnitElement", Unit=unit, Exponent=exponent)
            for unit, exponent in elements
        ],
        UnitType=unit_type,
    )


def _assign(model, unit):
    """Make a unit the project's, in place of any of its type."""
    (assignment,) = model.by_type("IfcUnitAssignment")
    assignment.Units = [
        other
        for other in assignment.Units
        if getattr(other, "UnitType", None) != unit.UnitType
    ] + [unit]
    return unit


def _kilonewton(model):
    return _si(model, "NEWTON", "FORCEUNIT", "KILO")


def _metre(model):
    return _si(model, "METRE", "LENGTHUNIT")


def _gigapascal(model, unit_type):
    return _derived(model, unit_type, (_si(model, "PASCAL", "PRESSUREUNIT", "GIGA"), 1))


def _loads(model):
    return [load for group in model.load_groups for load in group.loads]


def _material_of_first_member(model):
    return model.members[0].material


class TestLoads:
    def test_line_force(self):
        """kN/m in a file in pounds and inches: 100 of them, not 100 lbf/in."""
        model = _open("portal_01")
        _assign(
            model,
            _derived(
                model,
                "LINEARFORCEUNIT",
                (_kilonewton(model), 1),
                (_metre(model), -1),
            ),
        )
        (load,) = _loads(Extractor(model).extract_model())
        assert load.samples[0][1][2] == pytest.approx(-100e3)

    def test_line_load_with_no_unit_declared_is_made_of_force_and_length(self):
        model = _open("portal_01")
        (assignment,) = model.by_type("IfcUnitAssignment")
        assignment.Units = [
            unit
            for unit in assignment.Units
            if getattr(unit, "UnitType", None) != "LINEARFORCEUNIT"
        ]
        (load,) = _loads(Extractor(model).extract_model())
        assert load.samples[0][1][2] == pytest.approx(-100 * 4.44822162 / 0.0254)

    def test_line_moment(self):
        """kN.m/m where force and length make it lbf."""
        model = _open("portal_01")
        _assign(
            model,
            _derived(
                model,
                "LINEARMOMENTUNIT",
                (_kilonewton(model), 1),
                (_metre(model), 1),
                (_metre(model), -1),
            ),
        )
        # A moment along a member can only be constant: one value
        action = model.by_type("IfcStructuralCurveAction")[0]
        action.PredefinedType = "CONST"
        action.AppliedLoad = model.create_entity(
            "IfcStructuralLoadLinearForce", LinearMomentY=2.0
        )
        (load,) = _loads(Extractor(model).extract_model())
        assert load.moment[1] == pytest.approx(2000.0)

    def test_planar_force(self):
        """kN/m² in a file in millimetres: 1000 N/m² per unit, not 1e9."""
        model = _open("building_01")
        _assign(
            model,
            _derived(
                model,
                "PLANARFORCEUNIT",
                (_kilonewton(model), 1),
                (_metre(model), -2),
            ),
        )
        action = model.by_type("IfcStructuralPlanarAction")[0]
        value = action.AppliedLoad.PlanarForceZ
        # A load is listed once per load case it is in
        load = next(
            load
            for load in _loads(Extractor(model).extract_model())
            if load.id == action.GlobalId
        )
        assert abs(load.magnitude[2]) == pytest.approx(abs(value) * 1000.0)

    def test_torque(self):
        """kN.m in a file in millimetres and newtons: 1000 N.m, not 0.001."""
        model = _open("beam_01")
        _assign(
            model,
            _derived(model, "TORQUEUNIT", (_kilonewton(model), 1), (_metre(model), 1)),
        )
        (action,) = model.by_type("IfcStructuralPointAction")
        action.AppliedLoad.MomentY = 3.0
        # A load is listed once per load case it is in
        load = next(
            load
            for load in _loads(Extractor(model).extract_model())
            if load.id == action.GlobalId
        )
        assert load.moment[1] == pytest.approx(3000.0)


class TestMaterials:
    """portal_01's material gives no units of its own, so the project's apply."""

    def _values(self, model, name):
        (prop,) = [
            prop
            for prop in model.by_type("IfcPropertySingleValue")
            if prop.Name == name
        ]
        return prop

    def test_modulus_of_elasticity(self):
        model = _open("portal_01")
        _assign(model, _gigapascal(model, "MODULUSOFELASTICITYUNIT"))
        self._values(model, "YoungModulus").NominalValue.wrappedValue = 200.0
        # Its Poisson's ratio comes from E and G, so G has to agree
        _assign(model, _gigapascal(model, "SHEARMODULUSUNIT"))
        self._values(model, "ShearModulus").NominalValue.wrappedValue = 80.0
        material = _material_of_first_member(Extractor(model).extract_model())
        assert material.elastic_modulus == pytest.approx(200e9)
        assert material.poisson_ratio == pytest.approx(0.25)

    def test_poisson_ratio_comes_from_moduli_in_different_units(self):
        """E in psi and G in GPa: their raw ratio would be nonsense."""
        model = _open("portal_01")
        _assign(model, _gigapascal(model, "SHEARMODULUSUNIT"))
        psi = 6894.7572932
        self._values(model, "ShearModulus").NominalValue.wrappedValue = (
            2.9e7 * psi / (2.5 * 1e9)
        )
        material = _material_of_first_member(Extractor(model).extract_model())
        assert material.poisson_ratio == pytest.approx(0.25, rel=1e-6)

    def test_thermal_expansion(self):
        """Per megakelvin, a unit no base unit of the file makes."""
        model = _open("portal_01")
        _assign(
            model,
            _derived(
                model,
                "THERMALEXPANSIONCOEFFICIENTUNIT",
                (_si(model, "KELVIN", "THERMODYNAMICTEMPERATUREUNIT", "MEGA"), -1),
            ),
        )
        (pset,) = [
            pset
            for pset in model.by_type("IfcMaterialProperties")
            if pset.Name == "Pset_MaterialMechanical"
        ]
        pset.Properties = list(pset.Properties) + [
            model.create_entity(
                "IfcPropertySingleValue",
                Name="ThermalExpansionCoefficient",
                NominalValue=model.create_entity(
                    "IfcThermalExpansionCoefficientMeasure", 12.0
                ),
            )
        ]
        material = _material_of_first_member(Extractor(model).extract_model())
        assert material.thermal_expansion_coefficient == pytest.approx(12e-6)


class TestPropertysOwnUnit:
    """IfcPropertySingleValue.Unit goes before what the project assigns."""

    def _with_unit(self, model, name, value, unit):
        (prop,) = [
            prop
            for prop in model.by_type("IfcPropertySingleValue")
            if prop.Name == name
        ]
        prop.NominalValue.wrappedValue = value
        prop.Unit = unit
        return prop

    def test_young_modulus(self):
        model = _open("portal_01")
        self._with_unit(
            model,
            "YoungModulus",
            200.0,
            _gigapascal(model, "MODULUSOFELASTICITYUNIT"),
        )
        self._with_unit(
            model, "ShearModulus", 80.0, _gigapascal(model, "SHEARMODULUSUNIT")
        )
        material = _material_of_first_member(Extractor(model).extract_model())
        assert material.elastic_modulus == pytest.approx(200e9)
        assert material.poisson_ratio == pytest.approx(0.25)

    def test_density_needs_no_project_unit(self):
        """Its own unit says what it is, so the range for no unit does not apply."""
        model = _open("portal_01")
        (assignment,) = model.by_type("IfcUnitAssignment")
        assignment.Units = [
            unit
            for unit in assignment.Units
            if getattr(unit, "UnitType", None) != "MASSDENSITYUNIT"
        ]
        self._with_unit(
            model,
            "MassDensity",
            7.85,
            _derived(
                model,
                "MASSDENSITYUNIT",
                (_si(model, "GRAM", "MASSUNIT", "MEGA"), 1),
                (_metre(model), -3),
            ),
        )
        material = _material_of_first_member(Extractor(model).extract_model())
        assert material.density == pytest.approx(7850.0)

    def test_yield_stress(self):
        model = _open("portal_01")
        (pset,) = [
            pset
            for pset in model.by_type("IfcMaterialProperties")
            if pset.Name == "Pset_MaterialMechanical"
        ]
        pset.Properties = list(pset.Properties) + [
            model.create_entity(
                "IfcPropertySingleValue",
                Name="YieldStress",
                NominalValue=model.create_entity("IfcPressureMeasure", 355.0),
                Unit=_si(model, "PASCAL", "PRESSUREUNIT", "MEGA"),
            )
        ]
        material = _material_of_first_member(Extractor(model).extract_model())
        assert material.yield_strength == pytest.approx(355e6)

    def test_profile_property(self):
        """cm⁴ on a profile's property, in a file with a declared mm⁴ or none."""
        model = _open("beam_01")
        profile = model.create_entity(
            "IfcIShapeProfileDef",
            ProfileType="AREA",
            OverallWidth=160.0,
            OverallDepth=160.0,
            WebThickness=8.0,
            FlangeThickness=13.0,
        )
        centimetre = _si(model, "METRE", "LENGTHUNIT", "CENTI")
        model.create_entity(
            "IfcProfileProperties",
            Name="Pset_ProfileMechanical",
            Properties=[
                model.create_entity(
                    "IfcPropertySingleValue",
                    Name="MomentOfInertiaY",
                    NominalValue=model.create_entity(
                        "IfcMomentOfInertiaMeasure", 2492.0
                    ),
                    Unit=_derived(model, "MOMENTOFINERTIAUNIT", (centimetre, 4)),
                )
            ],
            ProfileDefinition=profile,
        )
        extractor = Extractor(model)
        section = extractor.members_extractor._create_section(profile)
        assert section.moment_of_inertia_y == pytest.approx(2492e-8)


class TestStiffness:
    """Each of the five kinds of stiffness has a unit of its own."""

    def _scales(self, model):
        return Extractor(model).unit_scales

    def _kn(self, model):
        return _kilonewton(model)

    def test_point(self):
        model = _open("cantilever_01")
        kn, m = self._kn(model), _metre(model)
        _assign(model, _derived(model, "LINEARSTIFFNESSUNIT", (kn, 1), (m, -1)))
        degree = model.create_entity(
            "IfcConversionBasedUnit",
            Dimensions=model.create_entity(
                "IfcDimensionalExponents", 0, 0, 0, 0, 0, 0, 0
            ),
            UnitType="PLANEANGLEUNIT",
            Name="degree",
            ConversionFactor=model.create_entity(
                "IfcMeasureWithUnit",
                model.create_entity("IfcPlaneAngleMeasure", 0.0174532925199433),
                _si(model, "RADIAN", "PLANEANGLEUNIT"),
            ),
        )
        _assign(
            model,
            _derived(model, "ROTATIONALSTIFFNESSUNIT", (kn, 1), (m, 1), (degree, -1)),
        )
        connection = model.by_type("IfcStructuralPointConnection")[0]
        connection.AppliedCondition = model.create_entity(
            "IfcBoundaryNodeCondition",
            None,
            model.create_entity("IfcLinearStiffnessMeasure", 2.0),
            model.create_entity("IfcBoolean", True),
            model.create_entity("IfcBoolean", False),
            model.create_entity("IfcRotationalStiffnessMeasure", 3.0),
            model.create_entity("IfcBoolean", False),
            model.create_entity("IfcBoolean", False),
        )
        values = get_connection_input(
            connection, "point", unit_scales=self._scales(model)
        )
        assert values["dx"] == pytest.approx(2000.0)
        assert values["dy"] == 1e20
        # A kilonewton metre per degree, as portal_01 declares in lbf.in/deg
        assert values["drx"] == pytest.approx(3000.0 / 0.0174532925199433)

    def test_edge(self):
        model = _open("slab_01")
        kn, m = self._kn(model), _metre(model)
        _assign(
            model,
            _derived(model, "MODULUSOFLINEARSUBGRADEREACTIONUNIT", (kn, 1), (m, -2)),
        )
        _assign(
            model,
            _derived(
                model,
                "MODULUSOFROTATIONALSUBGRADEREACTIONUNIT",
                (kn, 1),
                (m, 1),
                (m, -1),
            ),
        )
        connection = model.by_type("IfcStructuralCurveConnection")[0]
        connection.AppliedCondition = model.create_entity(
            "IfcBoundaryEdgeCondition",
            None,
            model.create_entity("IfcModulusOfLinearSubgradeReactionMeasure", 2.0),
            model.create_entity("IfcBoolean", True),
            model.create_entity("IfcBoolean", False),
            model.create_entity("IfcModulusOfRotationalSubgradeReactionMeasure", 3.0),
            model.create_entity("IfcBoolean", False),
            model.create_entity("IfcBoolean", False),
        )
        values = get_connection_input(
            connection, "line", unit_scales=self._scales(model)
        )
        assert values["dx"] == pytest.approx(2000.0)
        assert values["drx"] == pytest.approx(3000.0)

    def test_face(self):
        model = _open("slab_01")
        kn, m = self._kn(model), _metre(model)
        _assign(
            model, _derived(model, "MODULUSOFSUBGRADEREACTIONUNIT", (kn, 1), (m, -3))
        )
        connection = model.by_type("IfcStructuralCurveConnection")[0]
        connection.AppliedCondition = model.create_entity(
            "IfcBoundaryFaceCondition",
            None,
            model.create_entity("IfcModulusOfSubgradeReactionMeasure", 4.0),
            model.create_entity("IfcBoolean", True),
            model.create_entity("IfcBoolean", True),
        )
        values = get_connection_input(
            connection, "surface", unit_scales=self._scales(model)
        )
        assert values["dx"] == pytest.approx(4000.0)

    def test_the_extractor_passes_them_on(self):
        """A numeric spring on a point support, read through the extractor."""
        model = _open("cantilever_01")
        kn, m = self._kn(model), _metre(model)
        _assign(model, _derived(model, "LINEARSTIFFNESSUNIT", (kn, 1), (m, -1)))
        support = model.by_type("IfcStructuralPointConnection")[0]
        support.AppliedCondition = model.create_entity(
            "IfcBoundaryNodeCondition",
            None,
            model.create_entity("IfcLinearStiffnessMeasure", 2.0),
            model.create_entity("IfcBoolean", True),
            model.create_entity("IfcBoolean", True),
            model.create_entity("IfcBoolean", True),
            model.create_entity("IfcBoolean", True),
            model.create_entity("IfcBoolean", True),
        )
        (connection,) = [
            found
            for found in Extractor(model).extract_model().connections
            if found.id == support.GlobalId
        ]
        assert connection.stiffness_properties["dx"] == pytest.approx(2000.0)
