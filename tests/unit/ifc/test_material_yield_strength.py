"""The yield stress of a steel is read from the IFC material, in project units."""

from unittest.mock import MagicMock

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.ifc.members_extractor import (  # noqa: E402
    MembersExtractor,
)

# An entity is only valid while its file is alive
_FILES = []


def _material(properties):
    """An IfcMaterial with one property set per ``{pset: {name: (type, value)}}``."""
    model = ifcopenshell.file(schema="IFC4")
    _FILES.append(model)
    material = model.create_entity("IfcMaterial", "S355")
    for pset_name, values in properties.items():
        model.create_entity(
            "IfcMaterialProperties",
            pset_name,
            None,
            [
                model.create_entity(
                    "IfcPropertySingleValue",
                    name,
                    None,
                    model.create_entity(measure, value),
                    None,
                )
                for name, (measure, value) in values.items()
            ],
            material,
        )
    return material


def _extract(material):
    extractor = MagicMock(spec=MembersExtractor)
    extractor.length_scale = 0.001
    extractor.mass_scale = 1000.0
    extractor.pressure_scale = 1.0e6  # the file is in MPa
    return MembersExtractor._create_material(extractor, material)


MECHANICAL = {
    "YoungModulus": ("IfcModulusOfElasticityMeasure", 2.1e5),
    "PoissonRatio": ("IfcPositiveRatioMeasure", 0.3),
}


def test_yield_stress_is_converted_to_pascals():
    material = _material(
        {
            "Pset_MaterialMechanical": MECHANICAL,
            "Pset_MaterialSteel": {"YieldStress": ("IfcPressureMeasure", 355.0)},
        }
    )

    assert _extract(material).yield_strength == pytest.approx(355e6)


def test_no_yield_stress_leaves_it_unknown():
    assert (
        _extract(_material({"Pset_MaterialMechanical": MECHANICAL})).yield_strength
        is None
    )


def test_compressive_strength_of_concrete_is_not_a_yield_stress():
    material = _material(
        {
            "Pset_MaterialMechanical": MECHANICAL,
            "Pset_MaterialConcrete": {
                "CompressiveStrength": ("IfcPressureMeasure", 30.0)
            },
        }
    )

    assert _extract(material).yield_strength is None
