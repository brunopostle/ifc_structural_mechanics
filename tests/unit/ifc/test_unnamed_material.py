"""A material with no name is read and called by its entity id (9zt).

RFEM writes ``IfcMaterial('', '', $)``; a name is only a label.
"""

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.ifc.members_extractor import (  # noqa: E402
    MembersExtractor,
)

_FILES = []


def _material(name):
    model = ifcopenshell.file(schema="IFC4")
    _FILES.append(model)
    material = model.create_entity("IfcMaterial", name, "", None)
    model.create_entity(
        "IfcMaterialProperties",
        "Pset_MaterialMechanical",
        None,
        [
            model.create_entity(
                "IfcPropertySingleValue",
                prop,
                None,
                model.create_entity(measure, value),
                None,
            )
            for prop, measure, value in (
                ("YoungModulus", "IfcModulusOfElasticityMeasure", 2.1e11),
                ("PoissonRatio", "IfcPositiveRatioMeasure", 0.3),
                ("MassDensity", "IfcMassDensityMeasure", 7850.0),
            )
        ],
        material,
    )
    return material


@pytest.mark.parametrize("name", ["", None])
def test_unnamed_material_is_named_by_its_id(name):
    material = _material(name)

    extracted = MembersExtractor(material.file)._create_material(material)

    assert extracted.name == f"IfcMaterial #{material.id()}"
    assert extracted.elastic_modulus == pytest.approx(2.1e11)


def test_named_material_keeps_its_name():
    material = _material("S355")

    assert MembersExtractor(material.file)._create_material(material).name == "S355"
