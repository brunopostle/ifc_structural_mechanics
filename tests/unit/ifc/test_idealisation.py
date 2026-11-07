"""The check of structural members against the building elements they idealise.

A model built here in metres: a 6 m beam along global x, 0.2 wide and 0.3
deep, and a 4 x 5 m slab 0.2 thick at z = 3, each with the member that stands
for it, linked by IfcRelAssignsToProduct (94g.33).
"""

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.material
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.unit
import ifcopenshell.guid
import numpy as np
import pytest
from click.testing import CliRunner

from ifc_structural_mechanics.cli.commands import cli
from ifc_structural_mechanics.ifc.idealisation import (
    check_idealisation,
    element_member_pairs,
    elements_of_member,
    members_of_element,
    reference_points,
)


class _Model:
    """A beam and a slab with their members, which tests then change."""

    def __init__(self, member_relating: bool = True):
        f = self.f = ifcopenshell.file(schema="IFC4")
        ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject")
        ifcopenshell.api.unit.assign_unit(
            f, length={"is_metric": True, "raw": "METERS"}
        )
        model = ifcopenshell.api.context.add_context(f, context_type="Model")
        self.body = ifcopenshell.api.context.add_context(
            f,
            context_type="Model",
            context_identifier="Body",
            target_view="MODEL_VIEW",
            parent=model,
        )
        self.reference = ifcopenshell.api.context.add_context(
            f,
            context_type="Model",
            context_identifier="Reference",
            target_view="GRAPH_VIEW",
            parent=model,
        )
        self.member_relating = member_relating
        self.concrete = ifcopenshell.api.material.add_material(f, name="Concrete")
        self.steel = ifcopenshell.api.material.add_material(f, name="Steel")
        self.plaster = ifcopenshell.api.material.add_material(f, name="Plaster")
        self._beam()
        self._slab()

    # The beam along global x, its body extruded along its placement's z
    def _beam(self):
        f = self.f
        self.beam = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBeam")
        matrix = np.eye(4)
        matrix[:3, :3] = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], dtype=float)
        ifcopenshell.api.geometry.edit_object_placement(
            f, product=self.beam, matrix=matrix
        )
        self.beam_profile = self._rectangle(0.2, 0.3)
        representation = ifcopenshell.api.geometry.add_profile_representation(
            f, context=self.body, profile=self.beam_profile, depth=6.0
        )
        ifcopenshell.api.geometry.assign_representation(
            f, product=self.beam, representation=representation
        )
        profiles = ifcopenshell.api.material.add_material_set(
            f, name="beam", set_type="IfcMaterialProfileSet"
        )
        ifcopenshell.api.material.add_profile(
            f, profile_set=profiles, material=self.concrete, profile=self.beam_profile
        )
        ifcopenshell.api.material.assign_material(
            f,
            products=[self.beam],
            type="IfcMaterialProfileSetUsage",
            material=profiles,
        )
        self.curve = self.curve_member((0, 0, 0), (6, 0, 0))
        self.member_profile(self.curve, self._rectangle(0.2, 0.3), self.concrete)
        self.link(self.curve, self.beam)

    def _slab(self):
        f = self.f
        self.slab = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlab")
        matrix = np.eye(4)
        matrix[2, 3] = 3.0
        ifcopenshell.api.geometry.edit_object_placement(
            f, product=self.slab, matrix=matrix
        )
        representation = ifcopenshell.api.geometry.add_slab_representation(
            f,
            context=self.body,
            depth=0.2,
            polyline=[(0, 0), (4, 0), (4, 5), (0, 5), (0, 0)],
        )
        ifcopenshell.api.geometry.assign_representation(
            f, product=self.slab, representation=representation
        )
        self.layers = ifcopenshell.api.material.add_material_set(
            f, name="slab", set_type="IfcMaterialLayerSet"
        )
        layer = ifcopenshell.api.material.add_layer(
            f, layer_set=self.layers, material=self.concrete
        )
        layer.LayerThickness = 0.2
        ifcopenshell.api.material.assign_material(
            f, products=[self.slab], type="IfcMaterialLayerSet", material=self.layers
        )
        self.surface = self.surface_member(
            [(0, 0, 3.1), (4, 0, 3.1), (4, 5, 3.1), (0, 5, 3.1)], 0.2
        )
        ifcopenshell.api.material.assign_material(
            f, products=[self.surface], material=self.concrete
        )
        self.link(self.surface, self.slab)

    def _rectangle(self, width, depth, name=None):
        return self.f.create_entity(
            "IfcRectangleProfileDef",
            ProfileType="AREA",
            ProfileName=name,
            XDim=width,
            YDim=depth,
        )

    def _point(self, xyz):
        return self.f.create_entity(
            "IfcVertexPoint",
            self.f.create_entity("IfcCartesianPoint", [float(c) for c in xyz]),
        )

    def _topology(self, item, kind):
        """A 'Reference' representation of one topological item.

        Built by hand: api.geometry.add_topology_representation is not in
        ifcopenshell 0.8.4, the last release for Python 3.9.
        """
        return self.f.create_entity(
            "IfcTopologyRepresentation",
            ContextOfItems=self.reference,
            RepresentationIdentifier="Reference",
            RepresentationType=kind,
            Items=[item],
        )

    def _place(self, item):
        ifcopenshell.api.geometry.edit_object_placement(
            self.f, product=item, matrix=np.eye(4)
        )

    def curve_member(self, start, end):
        item = ifcopenshell.api.root.create_entity(
            self.f,
            ifc_class="IfcStructuralCurveMember",
            predefined_type="RIGID_JOINED_MEMBER",
        )
        self._place(item)
        edge = self.f.create_entity("IfcEdge", self._point(start), self._point(end))
        item.Representation = self.f.create_entity(
            "IfcProductDefinitionShape",
            Representations=[self._topology(edge, "Edge")],
        )
        return item

    def surface_member(self, corners, thickness):
        item = ifcopenshell.api.root.create_entity(
            self.f, ifc_class="IfcStructuralSurfaceMember", predefined_type="SHELL"
        )
        item.Thickness = thickness
        self._place(item)
        loop = self.f.create_entity(
            "IfcPolyLoop",
            [
                self.f.create_entity("IfcCartesianPoint", [float(v) for v in c])
                for c in corners
            ],
        )
        face = self.f.create_entity(
            "IfcFace", [self.f.create_entity("IfcFaceOuterBound", loop, True)]
        )
        item.Representation = self.f.create_entity(
            "IfcProductDefinitionShape",
            Representations=[self._topology(face, "Face")],
        )
        return item

    def member_profile(self, member, profile, material):
        profiles = ifcopenshell.api.material.add_material_set(
            self.f, name="member", set_type="IfcMaterialProfileSet"
        )
        ifcopenshell.api.material.add_profile(
            self.f, profile_set=profiles, material=material, profile=profile
        )
        ifcopenshell.api.material.assign_material(
            self.f, products=[member], type="IfcMaterialProfileSet", material=profiles
        )

    def link(self, member, element):
        if self.member_relating:
            relating, related = member, element
        else:
            relating, related = element, member
        # By hand: api.structural.assign_product is not in ifcopenshell 0.8.4,
        # the last release for Python 3.9
        self.f.create_entity(
            "IfcRelAssignsToProduct",
            GlobalId=ifcopenshell.guid.new(),
            RelatedObjects=[related],
            RelatingProduct=relating,
        )

    def move_edge(self, member, start, end):
        edge = member.Representation.Representations[0].Items[0]
        edge.EdgeStart.VertexGeometry.Coordinates = [float(c) for c in start]
        edge.EdgeEnd.VertexGeometry.Coordinates = [float(c) for c in end]

    def findings(self, **kwargs):
        return check_idealisation(self.f, **kwargs)

    def codes(self, **kwargs):
        return [found["code"] for found in self.findings(**kwargs)]


@pytest.fixture
def model():
    return _Model()


class TestQueries:
    def test_pairs_either_way_round(self):
        for member_relating in (True, False):
            built = _Model(member_relating=member_relating)
            pairs = element_member_pairs(built.f)
            assert {(m.GlobalId, e.GlobalId) for m, e in pairs} == {
                (built.curve.GlobalId, built.beam.GlobalId),
                (built.surface.GlobalId, built.slab.GlobalId),
            }
            assert members_of_element(built.beam) == [built.curve]
            assert elements_of_member(built.surface) == [built.slab]

    def test_reference_points_go_through_the_placement(self, model):
        matrix = np.eye(4)
        matrix[:3, 3] = [1.0, 2.0, 0.5]
        ifcopenshell.api.geometry.edit_object_placement(
            model.f, product=model.curve, matrix=matrix
        )
        found = reference_points(model.curve)
        assert found["kind"] == "edge"
        assert np.allclose(found["points"], [[1, 2, 0.5], [7, 2, 0.5]])


class TestAgreement:
    def test_a_model_that_agrees_has_no_findings(self, model):
        assert model.findings() == []

    def test_either_way_round(self):
        assert _Model(member_relating=False).findings() == []

    def test_a_member_from_axis_to_axis_runs_on_past_its_element(self, model):
        """Ends are not compared: a beam framing into columns stops at them."""
        model.move_edge(model.curve, (-0.2, 0, 0), (6.2, 0, 0))
        assert model.findings() == []

    def test_a_profile_of_the_same_dimensions_and_another_name(self, model):
        model.f.remove(model.curve.HasAssociations[0])
        model.member_profile(
            model.curve, model._rectangle(0.2, 0.3, "R200x300"), model.concrete
        )
        assert model.findings() == []

    def test_the_command_says_so_and_exits_with_zero(self, model, tmp_path):
        path = tmp_path / "agrees.ifc"
        model.f.write(str(path))
        run = CliRunner().invoke(cli, ["check", str(path)])
        assert run.exit_code == 0, run.output
        assert "agree" in run.output


class TestFindings:
    def test_a_member_beside_its_element(self, model):
        model.move_edge(model.curve, (0, 0.5, 0), (6, 0.5, 0))
        (found,) = model.findings()
        assert found["code"] == "W-BLD-007"
        # 0.5 m from the axis, the body 0.1 m to one side of it
        assert "0.400 m" in found["message"]
        assert found["ifc_guids"] == [model.curve.GlobalId, model.beam.GlobalId]

    def test_a_slab_member_on_another_level(self, model):
        for point in (
            model.surface.Representation.Representations[0]
            .Items[0]
            .Bounds[0]
            .Bound.Polygon
        ):
            point.Coordinates = (point.Coordinates[0], point.Coordinates[1], 6.1)
        assert model.codes() == ["W-BLD-007"]

    def test_a_window_the_member_does_not_have_is_an_area_not_a_position(self, model):
        """An opening through the slab makes its area smaller, not the member
        outside it."""
        opening = ifcopenshell.api.root.create_entity(
            model.f, ifc_class="IfcOpeningElement"
        )
        matrix = np.eye(4)
        matrix[:3, 3] = [0.5, 0.5, 2.9]
        ifcopenshell.api.geometry.edit_object_placement(
            model.f, product=opening, matrix=matrix
        )
        ifcopenshell.api.geometry.assign_representation(
            model.f,
            product=opening,
            representation=ifcopenshell.api.geometry.add_slab_representation(
                model.f,
                context=model.body,
                depth=0.4,
                polyline=[(0, 0), (3, 0), (3, 4), (0, 4), (0, 0)],
            ),
        )
        ifcopenshell.api.feature.add_feature(
            model.f, feature=opening, element=model.slab
        )
        (found,) = model.findings()
        assert found["code"] == "W-BLD-008"
        assert "20 against 8" in found["message"]

    def test_a_member_half_the_length_of_its_element(self, model):
        model.move_edge(model.curve, (0, 0, 0), (3, 0, 0))
        (found,) = model.findings()
        assert found["code"] == "W-BLD-008"
        assert "3 against 6 m" in found["message"]

    def test_a_member_of_no_length(self, model):
        model.move_edge(model.curve, (1, 0, 0), (1, 0, 0))
        assert model.codes() == ["W-BLD-010"]

    def test_another_material(self, model):
        model.f.remove(model.curve.HasAssociations[0])
        model.member_profile(model.curve, model._rectangle(0.2, 0.3), model.steel)
        (found,) = model.findings()
        assert found["code"] == "W-BLD-002"
        assert "'Steel' in elements of 'Concrete'" in found["message"]

    def test_another_section(self, model):
        model.f.remove(model.curve.HasAssociations[0])
        model.member_profile(model.curve, model._rectangle(0.2, 0.4), model.concrete)
        (found,) = model.findings()
        assert found["code"] == "W-BLD-004"
        assert "YDim 0.4 m" in found["message"]
        assert "YDim 0.3 m" in found["message"]

    def test_another_thickness(self, model):
        model.surface.Thickness = 0.25
        (found,) = model.findings()
        assert found["code"] == "W-BLD-003"
        assert "0.250 m" in found["message"]
        assert "0.200 m" in found["message"]


class TestLoadBearingLayers:
    """Plaster and insulation carry nothing: which layers count is a rule."""

    def _add_plaster(self, model, category=None):
        layer = ifcopenshell.api.material.add_layer(
            model.f, layer_set=model.layers, material=model.plaster
        )
        layer.LayerThickness = 0.03
        layer.Category = category
        return layer

    def test_layers_of_the_members_material(self, model):
        self._add_plaster(model)
        assert model.findings() == []

    def test_layers_marked_load_bearing(self, model):
        """Marked layers count, whatever the member's material."""
        self._add_plaster(model)
        model.layers.MaterialLayers[0].Category = "LoadBearing"
        ifcopenshell.api.material.unassign_material(model.f, products=[model.surface])
        ifcopenshell.api.material.assign_material(
            model.f, products=[model.surface], material=model.steel
        )
        assert model.codes() == ["W-BLD-002"]

    def test_none_that_can_be_told(self, model):
        self._add_plaster(model)
        ifcopenshell.api.material.unassign_material(model.f, products=[model.surface])
        ifcopenshell.api.material.assign_material(
            model.f, products=[model.surface], material=model.steel
        )
        assert model.codes() == ["W-BLD-002", "W-BLD-009"]

    def test_no_layer_set_compares_with_the_body(self, model):
        ifcopenshell.api.material.unassign_material(model.f, products=[model.slab])
        assert model.findings() == []
        model.surface.Thickness = 0.3
        (found,) = model.findings()
        assert found["code"] == "W-BLD-003"
        assert "its body across the member" in found["message"]


class TestWhatIsMissing:
    def test_a_member_with_no_element(self, model):
        model.curve_member((0, 0, 0), (0, 0, 3))
        assert model.codes() == ["W-BLD-006"]

    def test_a_wall_with_no_member(self, model):
        wall = ifcopenshell.api.root.create_entity(model.f, ifc_class="IfcWall")
        (found,) = model.findings()
        assert found["code"] == "W-BLD-005"
        assert found["ifc_guids"] == [wall.GlobalId]

    def test_a_wall_that_carries_nothing(self, model):
        wall = ifcopenshell.api.root.create_entity(model.f, ifc_class="IfcWall")
        pset = ifcopenshell.api.pset.add_pset(
            model.f, product=wall, name="Pset_WallCommon"
        )
        ifcopenshell.api.pset.edit_pset(
            model.f, pset=pset, properties={"LoadBearing": False}
        )
        assert model.findings() == []

    def test_a_whole_whose_part_has_a_member(self, model):
        """A roof made of the slab: the slab is its member's element."""
        roof = ifcopenshell.api.root.create_entity(model.f, ifc_class="IfcRoof")
        ifcopenshell.api.aggregate.assign_object(
            model.f, products=[model.slab], relating_object=roof
        )
        assert model.findings() == []

    def test_a_file_with_no_links(self, model):
        for relation in model.f.by_type("IfcRelAssignsToProduct"):
            model.f.remove(relation)
        (found,) = model.findings()
        assert found["code"] == "W-BLD-001"
        assert set(found["ifc_guids"]) == {model.curve.GlobalId, model.surface.GlobalId}

    def test_the_command_lists_them_and_exits_with_one(self, model, tmp_path):
        ifcopenshell.api.root.create_entity(model.f, ifc_class="IfcColumn")
        path = tmp_path / "column.ifc"
        model.f.write(str(path))
        run = CliRunner().invoke(cli, ["check", str(path), "--json-output"])
        assert run.exit_code == 1, run.output
        assert '"W-BLD-005"' in run.output
