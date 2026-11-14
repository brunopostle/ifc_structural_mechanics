"""A structural model as RFEM 6 exports it reads as the model it is.

``examples/rfem/structure_01_rfem.ifc`` is ``structure_01`` exported by RFEM
6.16, unchanged. RFEM writes its coordinates with Z down and turns them up
with the analysis model's SharedPlacement, which it gives to curve members and
connections but not to surface members; it leaves the identifier and type of
every topology representation unset; it names material properties 'Young
modulus' and the like; and it puts a surface connection with no condition on
each surface member. Each stopped the analysis or put the slab upside down,
3 m below the columns it rests on.
"""

import os

import numpy as np
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.ifc.entity_identifier import (  # noqa: E402
    get_item_transformation,
    get_representation,
)
from ifc_structural_mechanics.ifc.extractor import Extractor  # noqa: E402
from ifc_structural_mechanics.utils.error_handling import (  # noqa: E402
    ModelExtractionError,
)

RFEM = os.path.join("examples", "rfem", "structure_01_rfem.ifc")
SLAB = "0MBetTBij3CBOT8x93dlIS"
WALL = "30Nu9FEuzBzefjy_PVyI1C"
COLUMN = "3YkvmL4l5C5hq2iKoNYoDq"

# An entity is only valid while its file is alive
_FILES = []


def _open():
    model = ifcopenshell.open(RFEM)
    _FILES.append(model)
    return model


def _codes(model):
    return [w["code"] for w in model.analysis_warnings]


def _points(geometry):
    """Every point of a member's geometry, as an n x 3 array."""
    found = []

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple, np.ndarray)):
            if len(value) == 3 and all(
                isinstance(v, (int, float, np.floating)) for v in value
            ):
                found.append([float(v) for v in value])
            else:
                for item in value:
                    walk(item)

    walk(geometry)
    return np.array(found)


class TestRepresentation:
    def test_untyped_representations_are_found_by_their_items(self):
        model = _open()
        node = model.by_guid("1V8GzyZDb5G836zi8GXuvR")
        column = model.by_guid(COLUMN)
        slab = model.by_guid(SLAB)
        assert get_representation(node, "Vertex").Items[0].is_a("IfcVertexPoint")
        assert get_representation(column, "Edge").Items[0].is_a("IfcEdge")
        assert get_representation(slab, "Face").Items[0].is_a("IfcFace")

    def test_untyped_representation_of_other_items_is_not_taken(self):
        model = _open()
        assert get_representation(model.by_guid(COLUMN), "Face") is None
        assert get_representation(model.by_guid(SLAB), "Edge") is None


class TestPlacement:
    def test_unplaced_item_takes_the_shared_placement(self):
        model = _open()
        slab = model.by_guid(SLAB)
        assert slab.ObjectPlacement is None
        transformation = get_item_transformation(slab)
        # RFEM's SharedPlacement turns Z down to Z up, about x
        np.testing.assert_allclose(
            transformation["rotationMatrix"], np.diag([1.0, -1.0, -1.0]), atol=1e-12
        )

    def test_whole_model_is_upright_and_in_one_piece(self):
        extracted = Extractor(_open()).extract_model()
        slab = _points(extracted.get_member(SLAB).geometry)
        wall = _points(extracted.get_member(WALL).geometry)
        column = _points(extracted.get_member(COLUMN).geometry)
        np.testing.assert_allclose(slab[:, 2], 3.0, atol=1e-9)
        assert sorted({round(z, 9) for z in wall[:, 2]}) == [0.0, 3.0]
        # Cut back to its eccentric top, 0.15 m below the joint (d36)
        assert sorted({round(z, 9) for z in column[:, 2]}) == [0.0, 2.85]
        assert set(slab[:, 1].round(9)) == {0.0, 4.0}
        assert "W-IFC-007" in _codes(extracted)

    def test_no_warning_when_the_shared_placement_is_the_identity(self):
        model = _open()
        axes = model.by_type("IfcStructuralAnalysisModel")[0].SharedPlacement
        axes.RelativePlacement.Axis.DirectionRatios = (0.0, 0.0, 1.0)
        assert "W-IFC-007" not in _codes(Extractor(model).extract_model())

    def test_unplaced_item_in_models_placed_differently_is_an_error(self):
        model = _open()
        first = model.by_type("IfcStructuralAnalysisModel")[0]
        other = model.create_entity(
            "IfcStructuralAnalysisModel",
            GlobalId=ifcopenshell.guid.new(),
            PredefinedType="NOTDEFINED",
            SharedPlacement=model.create_entity(
                "IfcLocalPlacement",
                RelativePlacement=model.create_entity(
                    "IfcAxis2Placement3D",
                    Location=model.create_entity("IfcCartesianPoint", (0.0, 0.0, 0.0)),
                ),
            ),
        )
        model.create_entity(
            "IfcRelAssignsToGroup",
            GlobalId=ifcopenshell.guid.new(),
            RelatedObjects=[model.by_guid(SLAB)],
            RelatingGroup=other,
        )
        assert first.SharedPlacement != other.SharedPlacement
        with pytest.raises(ModelExtractionError) as error:
            get_item_transformation(model.by_guid(SLAB))
        assert error.value.code == "E-IFC-006"


class TestMaterial:
    def test_property_names_with_spaces_are_read(self):
        extracted = Extractor(_open()).extract_model()
        material = extracted.get_member(COLUMN).material
        assert material.elastic_modulus == pytest.approx(210e9)
        assert material.density == pytest.approx(7800.0)
        assert material.poisson_ratio == pytest.approx(0.2)
        assert material.thermal_expansion_coefficient == pytest.approx(1.2e-5)


class TestConnectionThatDoesNothing:
    def test_surface_connection_of_one_member_without_condition_is_left_out(self):
        extracted = Extractor(_open()).extract_model()
        ids = {c.id for c in extracted.connections}
        assert "2D6OnPe6n6oxO$t2E9PfHe" not in ids
        assert "2kNijBxrXBGQe8kDZ_HHES" not in ids
        (found,) = [w for w in extracted.analysis_warnings if w["code"] == "W-SUP-009"]
        assert set(found["ifc_guids"]) == {
            "2D6OnPe6n6oxO$t2E9PfHe",
            "2kNijBxrXBGQe8kDZ_HHES",
        }

    def test_surface_connection_of_two_members_without_condition_is_an_error(self):
        model = _open()
        connection = model.by_guid("2D6OnPe6n6oxO$t2E9PfHe")
        model.create_entity(
            "IfcRelConnectsStructuralMember",
            GlobalId=ifcopenshell.guid.new(),
            RelatingStructuralMember=model.by_guid(WALL),
            RelatedStructuralConnection=connection,
        )
        with pytest.raises(ModelExtractionError) as error:
            Extractor(model).extract_model()
        assert error.value.code == "E-SUP-004"
