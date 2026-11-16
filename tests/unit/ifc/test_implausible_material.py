"""W-MAT-005: a Young's modulus or density no real material has (ozy).

ETABS 17.0.1 wrote building_01's Masonry in kPa under a declared MPa.
"""

import os

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.ifc.extractor import Extractor  # noqa: E402
from ifc_structural_mechanics.ifc.members_extractor import (  # noqa: E402
    MembersExtractor,
)

_FILES = []


def _material(young, density):
    model = ifcopenshell.file(schema="IFC4")
    _FILES.append(model)
    material = model.create_entity("IfcMaterial", "Masonry")
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
                ("YoungModulus", "IfcModulusOfElasticityMeasure", young),
                ("PoissonRatio", "IfcPositiveRatioMeasure", 0.2),
                ("MassDensity", "IfcMassDensityMeasure", density),
            )
        ],
        material,
    )
    return material


def _warnings(young, density):
    material = _material(young, density)
    # The units declared: a density with none must look like kg/m3 (E-MAT-005)
    extractor = MembersExtractor(
        material.file, {"PRESSUREUNIT": 1.0, "MASSDENSITYUNIT": 1.0}
    )
    extracted = extractor._create_material(material)
    assert extracted.elastic_modulus == pytest.approx(young)
    return [w for w in extractor.warnings if w["code"] == "W-MAT-005"]


def test_real_material_raises_no_warning():
    assert _warnings(2.1e11, 7850.0) == []


@pytest.mark.parametrize(
    "young, density, said",
    [
        (2.48e13, 1800.0, "Young's modulus of 2.48e+13 Pa"),
        (2.1e5, 7850.0, "Young's modulus of 2.1e+05 Pa"),
        (2.1e11, 202350.0, "mass density of 202350 kg/m3"),
        (2.1e11, 0.00785, "mass density of 0.00785 kg/m3"),
    ],
)
def test_constant_no_material_has_is_used_with_a_warning(young, density, said):
    found = _warnings(young, density)

    assert len(found) == 1
    assert said in found[0]["message"]
    assert "Masonry" in found[0]["message"]


def test_building_01_masonry_is_named_once():
    model = ifcopenshell.open(
        os.path.join("examples", "analysis-models", "ifcFiles", "building_01.ifc")
    )
    _FILES.append(model)
    found = [
        w
        for w in Extractor(model).extract_model().analysis_warnings
        if w["code"] == "W-MAT-005"
    ]

    assert len(found) == 1
    assert "'Masonry'" in found[0]["message"]
    assert "Young's modulus" in found[0]["message"]
    assert "mass density" in found[0]["message"]
