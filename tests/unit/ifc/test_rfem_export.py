"""A structural model as RFEM 6 exports it reads as the model it is.

``examples/rfem/structure_01_rfem.ifc`` is ``structure_01`` exported by RFEM
6.16, unchanged. RFEM writes its coordinates with Z down and turns them up
with the analysis model's SharedPlacement, which it gives to curve members and
connections but not to surface members; it leaves the identifier and type of
every topology representation unset; it names material properties 'Young
modulus' and the like; and it puts a surface connection with no condition on
each surface member. Each stopped the analysis or put the slab upside down,
3 m below the columns it rests on.

``examples/rfem/bonsai_frame_3d_rfem.ifc`` is the Bonsai example frame built
again in RFEM 6.15 and exported, unchanged (reported 2026-11-18). Its load
cases are load groups of type LOAD_CASE, each term of a combination is a load
group with a Coefficient holding one load case, its point loads are on
connections with untyped representations, and the edges of its faces' loops
are out of order. Each stopped the analysis or lost its load cases.
"""

import os

import numpy as np
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.ifc.entity_identifier import (  # noqa: E402
    face_loops,
    get_item_transformation,
    get_representation,
)
from ifc_structural_mechanics.ifc.extractor import Extractor  # noqa: E402
from ifc_structural_mechanics.utils.error_handling import (  # noqa: E402
    ModelExtractionError,
)

RFEM = os.path.join("examples", "rfem", "structure_01_rfem.ifc")
FRAME = os.path.join("examples", "rfem", "bonsai_frame_3d_rfem.ifc")
SLAB = "0MBetTBij3CBOT8x93dlIS"
WALL = "30Nu9FEuzBzefjy_PVyI1C"
COLUMN = "3YkvmL4l5C5hq2iKoNYoDq"

# An entity is only valid while its file is alive
_FILES = []


def _open(path=RFEM):
    model = ifcopenshell.open(path)
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


class TestFrameLoadCases:
    """Load groups of type LOAD_CASE are load cases, as IFC4 allows."""

    def test_load_cases_are_read(self):
        extracted = Extractor(_open(FRAME)).extract_model()
        cases = {g.name: g for g in extracted.load_groups if g.is_load_case}
        assert set(cases) == {"Q", "Wx", "Wy"}
        assert [len(cases[n].actions) for n in ("Q", "Wx", "Wy")] == [1, 2, 3]

    def test_combinations_through_factor_groups(self):
        """Combination -> load group (Coefficient) -> load case."""
        extracted = Extractor(_open(FRAME)).extract_model()
        names = {g.id: g.name for g in extracted.load_groups}
        combinations = {
            c.name: {names[i]: f for i, f in c.load_groups.items()}
            for c in extracted.load_combinations
        }
        assert combinations == {
            "Load Combination 1": {"Q": 1.5, "Wx": pytest.approx(0.9)},
            "Load Combination 2": {"Q": pytest.approx(1.05), "Wy": 1.5},
            "Load Combination 3": {"Q": 1.0},
        }
        assert "W-LOD-005" not in _codes(extracted)

    def test_point_loads_are_at_their_untyped_nodes(self):
        extracted = Extractor(_open(FRAME)).extract_model()
        (wy,) = [g for g in extracted.load_groups if g.name == "Wy"]
        positions = sorted(tuple(np.round(load.position, 6)) for load in wy.actions)
        # RFEM's Z down, turned up by the SharedPlacement
        assert positions == [(0.0, 0.0, 3.5), (6.0, 0.0, 3.5), (12.0, 0.0, 3.5)]


class TestUnchainedEdgeLoop:
    """RFEM gives a face's edges in the sense of each edge, out of order."""

    def test_outline_is_read_end_to_end(self):
        model = _open(FRAME)
        face = get_representation(
            model.by_guid("30OGJYwY1Bax8sEPxwObEn"), "Face"
        ).Items[0]
        outline, holes = face_loops(face)
        assert holes == []
        assert np.round(outline, 6).tolist() == [
            [6.0, 0.0, -3.5],
            [12.0, 0.0, -3.5],
            [12.0, -5.0, -3.5],
            [6.0, -5.0, -3.5],
        ]

    def test_both_surfaces_are_reported(self):
        extracted = Extractor(_open(FRAME)).extract_model()
        (found,) = [w for w in extracted.analysis_warnings if w["code"] == "W-IFC-008"]
        assert set(found["ifc_guids"]) == {
            "30OGJYwY1Bax8sEPxwObEn",
            "1JxZ01lwX6HODpvlB5C06b",
        }

    def test_edges_that_make_no_outline_are_an_error(self):
        model = _open(FRAME)
        member = model.by_guid("30OGJYwY1Bax8sEPxwObEn")
        loop = get_representation(member, "Face").Items[0].Bounds[0].Bound
        # Leave out one side: the rest do not close
        loop.EdgeList = loop.EdgeList[:3]
        with pytest.raises(ModelExtractionError) as error:
            Extractor(model).extract_model()
        assert error.value.code == "E-IFC-002"
        assert "do not join up into one closed outline" in str(error.value)

    def test_chained_loop_is_not_reported(self):
        extracted = Extractor(_open()).extract_model()
        assert "W-IFC-008" not in _codes(extracted)
