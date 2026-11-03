"""Surface items written as a plain IfcFace, as Bonsai's face template does (94g.30).

IFC wants an IfcFaceSurface, whose plane gives the item its axes.
``ShapeBuilder.face()`` writes an IfcFace of an IfcPolyLoop, and every surface
member made in Bonsai was refused. Such a face is read on the plane through its
corners, with W-IFC-004; one that is not plane is refused.
"""

import json
import os
import shutil

import numpy as np
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
shape_builder = pytest.importorskip("ifcopenshell.util.shape_builder")

from ifc_structural_mechanics.ifc.entity_identifier import (  # noqa: E402
    implied_face_axes,
)
from ifc_structural_mechanics.ifc.extractor import Extractor  # noqa: E402
from ifc_structural_mechanics.utils.error_handling import (  # noqa: E402
    ModelExtractionError,
)

IFC_DIR = os.path.join("examples", "analysis-models", "ifcFiles")
SLAB_CORNERS = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (5.0, 3.0, 0.0), (0.0, 3.0, 0.0)]

# An entity is only valid while its file is alive
_FILES = []


def _slab_01():
    model = ifcopenshell.open(os.path.join(IFC_DIR, "slab_01.ifc"))
    _FILES.append(model)
    return model


def _give_plain_face(model, item, corners=SLAB_CORNERS):
    """Give an item the face ``ShapeBuilder.face()`` writes, in place of its own."""
    face = shape_builder.ShapeBuilder(model).face(corners)
    assert face.is_a() == "IfcFace"
    assert face.Bounds[0].Bound.is_a("IfcPolyLoop")
    item.Representation.Representations[0].Items = [face]
    return face


def _w_ifc_004(model):
    return [w for w in model.analysis_warnings if w["code"] == "W-IFC-004"]


class TestImpliedFaceAxes:
    def test_z_by_the_winding_and_x_by_the_ifc_default(self):
        x_axis, z_axis = implied_face_axes(SLAB_CORNERS)
        assert z_axis == pytest.approx([0.0, 0.0, 1.0])
        assert x_axis == pytest.approx([1.0, 0.0, 0.0])
        x_axis, z_axis = implied_face_axes(SLAB_CORNERS[::-1])
        assert z_axis == pytest.approx([0.0, 0.0, -1.0])
        assert x_axis == pytest.approx([1.0, 0.0, 0.0])

    def test_x_is_global_x_made_square_to_z(self):
        # A wall in the plane x = y: up, then along (1, 1, 0), turns about
        # (-1, 1, 0)
        wall = [(0, 0, 0), (0, 0, 3), (4, 4, 3), (4, 4, 0)]
        x_axis, z_axis = implied_face_axes(wall)
        root = 2**-0.5
        assert z_axis == pytest.approx([-root, root, 0.0])
        assert x_axis == pytest.approx([root, root, 0.0])

    def test_a_face_across_global_x_takes_global_y(self):
        x_axis, z_axis = implied_face_axes([(0, 0, 0), (0, 2, 0), (0, 2, 3), (0, 0, 3)])
        assert z_axis == pytest.approx([1.0, 0.0, 0.0])
        assert x_axis == pytest.approx([0.0, 1.0, 0.0])

    def test_a_face_that_is_not_plane_is_refused(self):
        with pytest.raises(ValueError, match="not plane"):
            implied_face_axes([(0, 0, 0), (5, 0, 0), (5, 3, 0.01), (0, 3, 0)])

    def test_a_face_with_no_area_is_refused(self):
        with pytest.raises(ValueError, match="no area"):
            implied_face_axes([(0, 0, 0), (1, 0, 0), (2, 0, 0)])


class TestSurfaceMember:
    def test_is_read_as_the_face_surface_it_replaces(self):
        shipped = Extractor(_slab_01()).extract_model().members[0]
        model = _slab_01()
        slab = model.by_type("IfcStructuralSurfaceMember")[0]
        _give_plain_face(model, slab)
        extracted = Extractor(model).extract_model()
        (member,) = extracted.members
        assert np.allclose(member.geometry, shipped.geometry)
        assert member.normal == pytest.approx(shipped.normal)
        assert member.thickness.value == shipped.thickness.value
        (found,) = _w_ifc_004(extracted)
        assert found["ifc_guids"] == [slab.GlobalId]
        assert "1 surface member(s)" in found["message"]

    def test_its_normal_follows_the_winding(self):
        model = _slab_01()
        _give_plain_face(
            model, model.by_type("IfcStructuralSurfaceMember")[0], SLAB_CORNERS[::-1]
        )
        (member,) = Extractor(model).extract_model().members
        assert member.normal == pytest.approx([0.0, 0.0, -1.0])

    def test_its_normal_is_turned_with_its_placement(self):
        model = _slab_01()
        slab = model.by_type("IfcStructuralSurfaceMember")[0]
        _give_plain_face(model, slab)
        # Stand the slab up: local z along global -y
        placement = model.create_entity(
            "IfcAxis2Placement3D",
            model.create_entity("IfcCartesianPoint", (0.0, 0.0, 0.0)),
            model.create_entity("IfcDirection", (0.0, -1.0, 0.0)),
            model.create_entity("IfcDirection", (1.0, 0.0, 0.0)),
        )
        slab.ObjectPlacement = model.create_entity("IfcLocalPlacement", None, placement)
        member = next(
            m
            for m in Extractor(model).members_extractor.extract_surface_members()
            if m.id == slab.GlobalId
        )
        assert member.normal == pytest.approx([0.0, -1.0, 0.0])
        assert np.allclose(
            sorted(map(tuple, np.round(member.geometry, 9) + 0.0)),
            sorted([(0, 0, 0), (5, 0, 0), (5, 0, 3), (0, 0, 3)]),
        )

    def test_one_that_is_not_plane_is_an_error_that_names_it(self):
        model = _slab_01()
        slab = model.by_type("IfcStructuralSurfaceMember")[0]
        _give_plain_face(model, slab, [(0, 0, 0), (5, 0, 0), (5, 3, 0.2), (0, 3, 0)])
        with pytest.raises(ModelExtractionError) as error:
            Extractor(model).extract_model()
        assert error.value.code == "E-IFC-002"
        assert slab.GlobalId in error.value.ifc_guids
        assert "not plane" in str(error.value)
        assert "IfcFaceSurface" in str(error.value)

    def test_a_face_surface_raises_no_warning(self):
        assert _w_ifc_004(Extractor(_slab_01()).extract_model()) == []


class TestSurfaceConnection:
    def _add(self, model, condition):
        slab = model.by_type("IfcStructuralSurfaceMember")[0]
        face = shape_builder.ShapeBuilder(model).face(SLAB_CORNERS)
        shape = model.create_entity(
            "IfcProductDefinitionShape",
            None,
            None,
            [
                model.create_entity(
                    "IfcTopologyRepresentation",
                    slab.Representation.Representations[0].ContextOfItems,
                    "Reference",
                    "Face",
                    [face],
                )
            ],
        )
        surface = model.create_entity(
            "IfcStructuralSurfaceConnection",
            "2Xq$8rX9P0Uw2P5bHS7Y0h",
            slab.OwnerHistory,
            None,
            None,
            None,
            slab.ObjectPlacement,
            shape,
            condition,
        )
        group = model.by_type("IfcRelAssignsToGroup")[0]
        group.RelatedObjects = list(group.RelatedObjects) + [surface]
        extracted = Extractor(model).extract_model()
        (connection,) = [c for c in extracted.connections if c.id == surface.GlobalId]
        return connection, extracted

    def test_a_condition_that_differs_by_direction_takes_the_implied_axes(self):
        """It was refused: the face had no plane to give the directions."""
        model = _slab_01()
        condition = model.create_entity(
            "IfcBoundaryFaceCondition",
            None,
            model.create_entity("IfcBoolean", True),
            model.create_entity("IfcBoolean", False),
            model.create_entity("IfcModulusOfSubgradeReactionMeasure", 1.0e7),
        )
        connection, extracted = self._add(model, condition)
        assert connection.local_axes[0] == pytest.approx([1.0, 0.0, 0.0])
        assert connection.local_axes[2] == pytest.approx([0.0, 0.0, 1.0])
        (found,) = _w_ifc_004(extracted)
        assert found["ifc_guids"] == [connection.id]

    def test_a_condition_alike_in_every_direction_needs_no_axes(self):
        model = _slab_01()
        stiff = model.create_entity("IfcModulusOfSubgradeReactionMeasure", 1.0e7)
        condition = model.create_entity(
            "IfcBoundaryFaceCondition", None, stiff, stiff, stiff
        )
        connection, extracted = self._add(model, condition)
        assert connection.local_axes is None
        assert _w_ifc_004(extracted) == []


@pytest.mark.skipif(shutil.which("ccx") is None, reason="CalculiX not installed")
def test_slab_01_with_a_plain_face_gives_the_results_of_the_file_as_shipped(
    tmp_path,
):
    from ifc_structural_mechanics.api.structural_analysis import analyze_ifc

    model = _slab_01()
    _give_plain_face(model, model.by_type("IfcStructuralSurfaceMember")[0])
    plain = str(tmp_path / "plain.ifc")
    model.write(plain)

    results = {}
    for name, path in (
        ("shipped", os.path.join(IFC_DIR, "slab_01.ifc")),
        ("plain", plain),
    ):
        output = str(tmp_path / name)
        result = analyze_ifc(path, output, mesh_size=0.5, gravity=True)
        assert result["status"] == "success", result.get("errors")
        with open(os.path.join(output, "results.json")) as fh:
            results[name] = json.load(fh)
        results[name + "_codes"] = [w["code"] for w in result["warnings"]]

    assert "W-IFC-004" in results["plain_codes"]
    assert "W-IFC-004" not in results["shipped_codes"]
    shipped = results["shipped"]["global_displacements"]["envelope"]
    plain = results["plain"]["global_displacements"]["envelope"]
    for key, value in shipped.items():
        if isinstance(value, float):
            assert plain[key] == pytest.approx(value, rel=1e-6, abs=1e-12), key
