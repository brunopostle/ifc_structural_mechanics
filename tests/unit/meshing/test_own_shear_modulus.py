"""Materials with a shear modulus of their own, as wood has (v0u).

A material whose shear modulus is not E / 2 (1 + nu) gets it in its beams,
along the member, and in its shells, in their plane and across it, with the
material's axis 1 along the shell's local x.
"""

import os
import re

import ifcopenshell
import numpy as np
import pytest

from ifc_structural_mechanics.api.structural_analysis import create_meshing_config
from ifc_structural_mechanics.config.analysis_config import AnalysisConfig
from ifc_structural_mechanics.config.system_config import SystemConfig
from ifc_structural_mechanics.ifc.extractor import Extractor
from ifc_structural_mechanics.meshing.unified_calculix_writer import (
    run_complete_analysis_workflow,
)
from ifc_structural_mechanics.utils.error_handling import MeshingError

IFC_DIR = os.path.join("examples", "analysis-models", "ifcFiles")

pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(IFC_DIR, "slab_01.ifc")),
    reason="example models submodule missing",
)


def _with_shear_modulus(name: str, ratio):
    """An example model whose material has a shear modulus of E / ratio."""
    model = ifcopenshell.open(os.path.join(IFC_DIR, f"{name}.ifc"))
    if ratio is None:
        return model
    for pset in model.by_type("IfcMaterialProperties"):
        if pset.Name != "Pset_MaterialMechanical":
            continue
        values = {p.Name: p for p in pset.Properties}
        modulus = values["YoungModulus"].NominalValue.wrappedValue
        properties = [p for p in pset.Properties if p.Name != "ShearModulus"]
        properties.append(
            model.create_entity(
                "IfcPropertySingleValue",
                Name="ShearModulus",
                NominalValue=model.create_entity(
                    "IfcModulusOfElasticityMeasure", modulus / ratio
                ),
            )
        )
        pset.Properties = properties
    return model


def _deck(model, tmp_path, domain=None) -> str:
    domain = domain or Extractor(model).extract_model()
    path = str(tmp_path / "analysis.inp")
    run_complete_analysis_workflow(
        domain_model=domain,
        output_inp_file=path,
        analysis_config=AnalysisConfig(),
        meshing_config=create_meshing_config(1.0),
        system_config=SystemConfig(),
        intermediate_files_dir=str(tmp_path / "intermediate"),
    )
    with open(path) as fh:
        return fh.read()


def _engineering_constants(deck: str) -> dict:
    """The nine constants of each orthotropic material, by name."""
    found = {}
    pattern = re.compile(
        r"\*MATERIAL, NAME=(\S+)\n\*ELASTIC, TYPE=ENGINEERING CONSTANTS\n"
        r"([^\n]*)\n([^\n]*)\n"
    )
    for name, first, second in pattern.findall(deck):
        values = [float(v) for v in (first + second).split(",") if v.strip()]
        found[name] = values
    return found


class TestShells:
    def test_material_and_axes(self, tmp_path):
        model = _with_shear_modulus("slab_01", 16.0)
        angle = np.radians(30.0)
        (plane,) = model.by_type("IfcPlane")
        plane.Position.RefDirection = model.create_entity(
            "IfcDirection", (float(np.cos(angle)), float(np.sin(angle)), 0.0)
        )
        domain = Extractor(model).extract_model()
        (slab,) = domain.members
        assert slab.local_x == pytest.approx([np.cos(angle), np.sin(angle), 0.0])
        material = slab.material
        deck = _deck(model, tmp_path, domain)

        name = f"MAT_{material.id}_SH"
        constants = _engineering_constants(deck)[name]
        modulus, nu = material.elastic_modulus, material.poisson_ratio
        assert constants == pytest.approx(
            [modulus] * 3 + [nu] * 3 + [modulus / 16.0] * 3, rel=1e-6
        )
        (section,) = re.findall(r"\*SHELL SECTION, [^\n]*", deck)
        assert f"MATERIAL={name}," in section
        orientation = re.search(r"ORIENTATION=(\S+)", section).group(1)
        axes = re.search(
            rf"\*ORIENTATION, NAME={orientation}, SYSTEM=RECTANGULAR\n([^\n]*)", deck
        ).group(1)
        a_and_b = [float(v) for v in axes.split(",")]
        assert a_and_b == pytest.approx(
            [np.cos(angle), np.sin(angle), 0.0, -np.sin(angle), np.cos(angle), 0.0],
            abs=1e-6,
        )

    def test_isotropic_material_is_as_before(self, tmp_path):
        deck = _deck(_with_shear_modulus("slab_01", None), tmp_path)
        assert "_SH" not in deck
        assert "*ORIENTATION" not in deck

    def test_face_without_axes_is_an_error(self, tmp_path):
        model = _with_shear_modulus("slab_01", 16.0)
        domain = Extractor(model).extract_model()
        (slab,) = domain.members
        slab.local_x = None
        with pytest.raises(MeshingError) as error:
            _deck(model, tmp_path, domain)
        assert error.value.code == "E-MAT-006"
        assert slab.ifc_guid in error.value.ifc_guids


class TestBeams:
    def test_shear_moduli_follow_the_one_given(self, tmp_path):
        """Every shear modulus of a beam's material is in proportion to G."""
        (tmp_path / "iso").mkdir()
        (tmp_path / "soft").mkdir()
        isotropic = _engineering_constants(
            _deck(_with_shear_modulus("cantilever_01", None), tmp_path / "iso")
        )
        soft = _engineering_constants(
            _deck(_with_shear_modulus("cantilever_01", 16.0), tmp_path / "soft")
        )
        assert isotropic and soft.keys() == isotropic.keys()
        nu = 0.2  # cantilever_01's
        ratio = (2 * (1 + nu)) / 16.0
        for name, constants in soft.items():
            before = isotropic[name]
            assert constants[:6] == pytest.approx(before[:6])
            # G12 and G13 hold the member's axis
            assert constants[6:8] == pytest.approx(
                [ratio * g for g in before[6:8]], rel=1e-5
            )
