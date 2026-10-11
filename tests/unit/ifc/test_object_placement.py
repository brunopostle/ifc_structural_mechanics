"""An item's coordinates and directions are in the axes of its ObjectPlacement.

No example model places its items anywhere but at the origin, so none of this
was exercised: members added the offset of their placement without converting
it to metres, point connections and loads ignored placements altogether, and a
placement under a moved parent was read without the parent (``aiz.57``).

Each example is extracted twice here, as shipped and with every item given a
placement that moves and turns it. The second model must be the first one
moved and turned.
"""

import os

import numpy as np
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from ifc_structural_mechanics.ifc.entity_identifier import (  # noqa: E402
    get_transformation,
)
from ifc_structural_mechanics.ifc.extractor import Extractor  # noqa: E402
from ifc_structural_mechanics.utils.error_handling import (  # noqa: E402
    ModelExtractionError,
)

IFC_DIR = os.path.join("examples", "analysis-models", "ifcFiles")

# Offsets in metres; written to the file in its own unit
PARENT_OFFSET = np.array([12.0, -7.0, 3.0])
CHILD_OFFSET = np.array([1.5, 2.5, -0.5])

# The parent turns a quarter about global Z, the child tilts about its own x
PARENT_X, PARENT_Z = (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
CHILD_X, CHILD_Z = (1.0, 0.0, 0.0), (0.0, -0.6, 0.8)


def _rotation(x_axis, z_axis):
    x_axis, z_axis = np.array(x_axis), np.array(z_axis)
    return np.array([x_axis, np.cross(z_axis, x_axis), z_axis]).T


PARENT_R = _rotation(PARENT_X, PARENT_Z)
ROTATION = PARENT_R @ _rotation(CHILD_X, CHILD_Z)
OFFSET = PARENT_OFFSET + PARENT_R @ CHILD_OFFSET


def _axes(model, offset, x_axis, z_axis):
    return model.create_entity(
        "IfcAxis2Placement3D",
        Location=model.create_entity("IfcCartesianPoint", [float(c) for c in offset]),
        Axis=model.create_entity("IfcDirection", z_axis),
        RefDirection=model.create_entity("IfcDirection", x_axis),
    )


def _place_everything(model, scale):
    """Give every item and action one nested placement, in the file's unit."""
    parent = model.create_entity(
        "IfcLocalPlacement",
        RelativePlacement=_axes(model, PARENT_OFFSET / scale, PARENT_X, PARENT_Z),
    )
    placement = model.create_entity(
        "IfcLocalPlacement",
        PlacementRelTo=parent,
        RelativePlacement=_axes(model, CHILD_OFFSET / scale, CHILD_X, CHILD_Z),
    )
    for kind in ("IfcStructuralItem", "IfcStructuralActivity"):
        for entity in model.by_type(kind):
            entity.ObjectPlacement = placement


def _moved(points):
    return np.asarray(points, dtype=float) @ ROTATION.T + OFFSET


def _turned(vectors):
    return np.asarray(vectors, dtype=float) @ ROTATION.T


def _extract(name, place):
    model = ifcopenshell.open(os.path.join(IFC_DIR, f"{name}.ifc"))
    extractor = Extractor(model)
    if place:
        _place_everything(model, extractor.unit_scales["LENGTHUNIT"])
    extracted = extractor.extract_model()
    # Entities are only valid while their file is alive
    extracted._ifc_file = model
    return extracted


@pytest.fixture(
    scope="module",
    params=["beam_01", "portal_01", "building_01", "structure_01", "grid_of_beams"],
)
def models(request):
    """An example as shipped (m, mm or inches) and the same one placed."""
    return _extract(request.param, False), _extract(request.param, True)


def _loads(model):
    return [load for group in model.load_groups for load in group.loads]


class TestPlacedModel:
    def test_members_are_moved_and_turned(self, models):
        original, placed = models
        assert len(original.members) == len(placed.members) > 0
        for before, after in zip(original.members, placed.members):
            np.testing.assert_allclose(
                after.geometry, _moved(before.geometry), atol=1e-9
            )

    def test_member_axes_are_turned(self, models):
        original, placed = models
        checked = 0
        for before, after in zip(original.members, placed.members):
            if getattr(before, "local_axis", None) is None:
                continue
            checked += 1
            np.testing.assert_allclose(
                after.local_axis, _turned(before.local_axis), atol=1e-9
            )
        if any(m.entity_type == "curve" for m in original.members):
            assert checked > 0

    def test_connections_are_moved(self, models):
        original, placed = models
        assert len(original.connections) == len(placed.connections) > 0
        for before, after in zip(original.connections, placed.connections):
            np.testing.assert_allclose(
                after.position, _moved([before.position])[0], atol=1e-9
            )
            if getattr(before, "edge", None):
                np.testing.assert_allclose(after.edge, _moved(before.edge), atol=1e-9)

    def test_connection_axes_are_turned(self, models):
        """A support's restraints are in the axes of its placement."""
        original, placed = models
        for before, after in zip(original.connections, placed.connections):
            axes = before.local_axes
            if axes is None and getattr(before, "edge", None):
                assert after.local_axes is None
                continue
            expected = _turned(np.eye(3) if axes is None else axes)
            np.testing.assert_allclose(after.local_axes, expected, atol=1e-9)

    def test_release_axes_are_turned(self, models):
        original, placed = models
        for before, after in zip(original.connections, placed.connections):
            axes_before = getattr(before, "release_axes_by_member", None) or {}
            axes_after = getattr(after, "release_axes_by_member", None) or {}
            assert set(axes_before) == set(axes_after)
            for member_id, axes in axes_before.items():
                if axes is None:
                    assert axes_after[member_id] is None
                    continue
                np.testing.assert_allclose(
                    axes_after[member_id], _turned(axes), atol=1e-9
                )

    def test_loads_are_moved_and_turned(self, models):
        original, placed = models
        assert len(_loads(original)) == len(_loads(placed))
        for before, after in zip(_loads(original), _loads(placed)):
            force = np.asarray(before.get_force_vector(), dtype=float)
            if getattr(before, "coordinate_system", "global") != "local":
                # "Global" forces are in the axes of the action's placement
                force = _turned([force])[0]
            np.testing.assert_allclose(
                after.get_force_vector(), force, atol=1e-9 * max(1.0, abs(force).max())
            )
            for attribute in ("position", "start_position", "end_position"):
                point = getattr(before, attribute, None)
                if point is not None:
                    np.testing.assert_allclose(
                        getattr(after, attribute), _moved([point])[0], atol=1e-9
                    )


class TestTransformation:
    def _file(self):
        return ifcopenshell.file(schema="IFC4")

    def test_offset_is_converted_to_metres(self):
        model = self._file()
        placement = model.create_entity(
            "IfcLocalPlacement",
            RelativePlacement=_axes(
                model, (1000.0, 0.0, 0.0), (1.0, 0.0, 0.0), PARENT_Z
            ),
        )
        transformation = get_transformation(placement, 0.001)
        np.testing.assert_allclose(transformation["location"], [1.0, 0.0, 0.0])

    def test_parent_placement_is_applied(self):
        model = self._file()
        parent = model.create_entity(
            "IfcLocalPlacement",
            RelativePlacement=_axes(model, (0.0, 5.0, 0.0), PARENT_X, PARENT_Z),
        )
        placement = model.create_entity(
            "IfcLocalPlacement",
            PlacementRelTo=parent,
            RelativePlacement=_axes(model, (1.0, 0.0, 0.0), (1.0, 0.0, 0.0), PARENT_Z),
        )
        transformation = get_transformation(placement)
        # The child's x offset lies along the parent's x, which is global y
        np.testing.assert_allclose(transformation["location"], [0.0, 6.0, 0.0])
        np.testing.assert_allclose(
            transformation["rotationMatrix"] @ [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]
        )

    def test_placement_with_parallel_axes_is_an_error(self):
        """Its rotation is not a number; it must not reach the coordinates."""
        model = self._file()
        placement = model.create_entity(
            "IfcLocalPlacement",
            RelativePlacement=_axes(model, (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), PARENT_Z),
        )
        with pytest.raises(ModelExtractionError, match="cannot be read"):
            get_transformation(placement)

    def test_identity_is_none(self):
        model = self._file()
        placement = model.create_entity(
            "IfcLocalPlacement",
            RelativePlacement=_axes(model, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), PARENT_Z),
        )
        assert get_transformation(placement) is None
        assert get_transformation(None) is None

    def test_grid_placement_is_an_error(self):
        model = self._file()
        placement = model.create_entity("IfcGridPlacement")
        with pytest.raises(ModelExtractionError, match="only IfcLocalPlacement"):
            get_transformation(placement)
