"""Extraction either gives the model the file describes or says why not.

Each case here used to be swallowed: a member dropped, a load sent to the
origin or left out, steel assumed for a material with no stiffness. The
analysis then ran on another structure and nothing in the results said so.
"""

import os

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.ifc.extractor import Extractor  # noqa: E402
from ifc_structural_mechanics.utils.error_handling import (  # noqa: E402
    ModelExtractionError,
)

IFC_DIR = os.path.join("examples", "analysis-models", "ifcFiles")

# An entity is only valid while its file is alive
_FILES = []


def _open(name):
    model = ifcopenshell.open(os.path.join(IFC_DIR, f"{name}.ifc"))
    _FILES.append(model)
    return model


def _warnings(model):
    return [w["message"] for w in Extractor(model).extract_model().analysis_warnings]


class TestMembers:
    def test_example_models_raise_no_warning(self):
        assert _warnings(_open("cantilever_01")) == []
        assert _warnings(_open("slab_01")) == []

    def test_member_without_material_profile_is_an_error(self):
        model = _open("cantilever_01")
        member = model.by_type("IfcStructuralCurveMember")[0]
        for association in model.by_type("IfcRelAssociatesMaterial"):
            model.remove(association)
        with pytest.raises(ModelExtractionError) as error:
            Extractor(model).extract_model()
        assert member.GlobalId in str(error.value)
        assert "no material profile" in str(error.value)

    def test_member_without_geometry_is_an_error(self):
        model = _open("cantilever_01")
        member = model.by_type("IfcStructuralCurveMember")[0]
        member.Representation = None
        with pytest.raises(ModelExtractionError) as error:
            Extractor(model).extract_model()
        assert member.GlobalId in str(error.value)
        assert "no edge representation" in str(error.value)

    def test_material_without_stiffness_is_an_error(self):
        """It used to be analysed as steel."""
        model = _open("cantilever_01")
        for pset in model.by_type("IfcMaterialProperties"):
            if pset.Name == "Pset_MaterialMechanical":
                model.remove(pset)
        with pytest.raises(ModelExtractionError, match="no Young's modulus"):
            Extractor(model).extract_model()

    def test_material_without_density_is_weightless_and_says_so(self):
        """It used to weigh as much as steel."""
        model = _open("cantilever_01")
        for pset in model.by_type("IfcMaterialProperties"):
            if pset.Name == "Pset_MaterialCommon":
                model.remove(pset)
        extracted = Extractor(model).extract_model()
        assert extracted.members[0].material.density is None
        (message,) = [w["message"] for w in extracted.analysis_warnings]
        assert "no mass density" in message and "weightless" in message

    def test_material_without_poisson_ratio_gets_a_warning(self):
        model = _open("cantilever_01")
        for pset in model.by_type("IfcMaterialProperties"):
            if pset.Name == "Pset_MaterialMechanical":
                pset.Properties = [
                    p for p in pset.Properties if p.Name != "PoissonRatio"
                ]
        extracted = Extractor(model).extract_model()
        assert extracted.members[0].material.poisson_ratio == 0.3
        (message,) = [w["message"] for w in extracted.analysis_warnings]
        assert "no Poisson's ratio" in message and "0.3 is assumed" in message

    def test_poisson_ratio_comes_from_the_shear_modulus(self):
        """portal_01 gives E and G; 0.3 used to be assumed (aiz.83)."""
        extracted = Extractor(_open("portal_01")).extract_model()
        material = extracted.members[0].material
        assert material.poisson_ratio == pytest.approx(29e6 / (2 * 11.2e6) - 1)
        assert not any(
            "Poisson" in w["message"] or "shear modulus" in w["message"]
            for w in extracted.analysis_warnings
        )

    @staticmethod
    def _set_shear_modulus(model, value):
        for pset in model.by_type("IfcMaterialProperties"):
            for prop in pset.Properties:
                if prop.Name == "ShearModulus":
                    measure = prop.NominalValue.is_a()
                    prop.NominalValue = model.create_entity(measure, value)

    def test_impossible_shear_modulus_is_an_error(self):
        model = _open("portal_01")
        self._set_shear_modulus(model, 5e6)  # E 29e6 gives nu = 1.9
        with pytest.raises(ModelExtractionError, match="no isotropic material"):
            Extractor(model).extract_model()

    def test_shear_modulus_at_odds_with_poisson_ratio_gets_a_warning(self):
        model = _open("beam_01")
        self._set_shear_modulus(model, 10000.0)  # E 30000, nu 0.2 give 12500
        messages = _warnings(model)
        assert any(
            "shear modulus" in m and "Poisson's ratio 0.2" in m for m in messages
        )

    def test_consistent_shear_modulus_raises_no_warning(self):
        assert not any("shear modulus" in m for m in _warnings(_open("beam_01")))

    def test_slab_without_thickness_is_an_error(self):
        """It used to be 0.1 m thick."""
        model = _open("slab_01")
        slab = model.by_type("IfcStructuralSurfaceMember")[0]
        slab.Thickness = None
        with pytest.raises(ModelExtractionError) as error:
            Extractor(model).extract_model()
        assert slab.GlobalId in str(error.value)
        assert "no thickness" in str(error.value)

    def test_slab_gets_no_section(self):
        """A second extractor used to hang a default 0.1 x 0.2 section on it."""
        slab = Extractor(_open("slab_01")).extract_model().members[0]
        assert getattr(slab, "section", None) is None


class TestConnections:
    def test_connection_without_position_is_an_error(self):
        """It used to be put at the origin."""
        model = _open("cantilever_01")
        connection = model.by_type("IfcStructuralPointConnection")[0]
        connection.Representation = None
        connection.ObjectPlacement = None
        with pytest.raises(ModelExtractionError) as error:
            Extractor(model).extract_model()
        assert connection.GlobalId in str(error.value)
        assert "position cannot be found" in str(error.value)


class TestLoads:
    def test_load_in_no_group_is_reported(self):
        model = _open("beam_01")
        for relation in model.by_type("IfcRelAssignsToGroup"):
            if any(
                item.is_a("IfcStructuralAction") for item in relation.RelatedObjects
            ):
                model.remove(relation)
        messages = _warnings(model)
        assert any("belong to no load group" in m for m in messages)

    def test_applied_moment_is_read(self):
        """It used to be left out, and the force applied alone.

        beam_01 is in newtons and millimetres: 500 N·mm is 0.5 N·m.
        """
        model = _open("beam_01")
        action = model.by_type("IfcStructuralPointAction")[0]
        action.AppliedLoad.MomentY = 500.0
        loads = [
            load
            for group in Extractor(model).extract_model().load_groups
            for load in group.loads
        ]
        found = [load for load in loads if load.id == action.GlobalId]
        assert found
        for load in found:
            assert load.moment.tolist() == pytest.approx([0.0, 0.5, 0.0])

    def test_local_point_action_names_the_item_whose_axes_it_is_in(self):
        """It used to be applied in global axes (`aiz.85`)."""
        model = _open("beam_01")
        action = model.by_type("IfcStructuralPointAction")[0]
        action.GlobalOrLocal = "LOCAL_COORDS"
        member = action.AssignedToStructuralItem[0].RelatingElement
        loads = [
            load
            for group in Extractor(model).extract_model().load_groups
            for load in group.loads
            if load.id == action.GlobalId
        ]
        assert loads
        for load in loads:
            assert load.coordinate_system == "local"
            assert load.member_reference == member.GlobalId

    def test_local_point_action_on_no_item_is_an_error(self):
        model = _open("beam_01")
        action = model.by_type("IfcStructuralPointAction")[0]
        action.GlobalOrLocal = "LOCAL_COORDS"
        model.remove(action.AssignedToStructuralItem[0])
        with pytest.raises(ModelExtractionError) as error:
            Extractor(model).extract_model()
        assert action.GlobalId in str(error.value)
        assert "assigned to no item" in str(error.value)

    def test_moment_that_varies_along_a_member_is_an_error(self):
        model = _open("portal_01")
        action = model.by_type("IfcStructuralCurveAction")[0]
        action.AppliedLoad.Values[1].LinearMomentX = 5.0
        with pytest.raises(ModelExtractionError) as error:
            Extractor(model).extract_model()
        assert action.GlobalId in str(error.value)
        assert "a moment (LinearMomentX) that varies along its member" in str(
            error.value
        )

    def test_load_of_an_unsupported_kind_is_an_error(self):
        """It used to be applied as a force of zero."""
        model = _open("beam_01")
        action = model.by_type("IfcStructuralPointAction")[0]
        action.AppliedLoad = model.create_entity(
            "IfcStructuralLoadTemperature", DeltaTConstant=20.0
        )
        with pytest.raises(ModelExtractionError, match="IfcStructuralLoadTemperature"):
            Extractor(model).extract_model()
