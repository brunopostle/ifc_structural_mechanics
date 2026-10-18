"""An item's coordinates and directions are in the axes of its ObjectPlacement.

No example model places its items anywhere but at the origin, so none of this
was exercised: members added the offset of their placement without converting
it to metres, point connections and loads ignored placements altogether, and a
placement under a moved parent was read without the parent (``aiz.57``).

Each example is extracted as shipped and with every item given a placement
that moves and turns it: a local placement, and a grid placement on a grid
whose own placement makes up the same movement (``aiz.99``). The placed
models must be the first one moved and turned.
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


def _nested_placement(model, scale):
    parent = model.create_entity(
        "IfcLocalPlacement",
        RelativePlacement=_axes(model, PARENT_OFFSET / scale, PARENT_X, PARENT_Z),
    )
    return model.create_entity(
        "IfcLocalPlacement",
        PlacementRelTo=parent,
        RelativePlacement=_axes(model, CHILD_OFFSET / scale, CHILD_X, CHILD_Z),
    )


def _point2(model, x, y):
    return model.create_entity("IfcCartesianPoint", [float(x), float(y)])


def _line(model, point, direction):
    return model.create_entity(
        "IfcLine",
        Pnt=_point2(model, *point),
        Dir=model.create_entity(
            "IfcVector",
            Orientation=model.create_entity(
                "IfcDirection", [float(c) for c in direction]
            ),
            Magnitude=1.0,
        ),
    )


def _grid_axis(model, tag, curve, same_sense=True):
    return model.create_entity(
        "IfcGridAxis", AxisTag=tag, AxisCurve=curve, SameSense=same_sense
    )


def _grid(model, u_axes, v_axes, placement=None):
    return model.create_entity(
        "IfcGrid",
        GlobalId=ifcopenshell.guid.new(),
        ObjectPlacement=placement,
        UAxes=u_axes,
        VAxes=v_axes,
    )


def _intersection(model, axes, offsets=None):
    return model.create_entity(
        "IfcVirtualGridIntersection",
        IntersectingAxes=axes,
        OffsetDistances=[float(o) for o in offsets] if offsets else None,
    )


# The grid placement of the placed models, in metres in the grid's own axes
GRID_POINT = np.array([2.0, 1.0, 0.5])
GRID_X = np.array([0.0, 1.0, 0.0])


def _grid_placement(model, scale, grid_placement=None):
    """A placement at GRID_POINT with its x along GRID_X, given by grid axes.

    A polyline run backwards and offset to its left, an offset curve offset
    again, and a second intersection for the direction.
    """
    a = 1.0 / scale
    u1 = _grid_axis(
        model,
        "A",
        model.create_entity(
            "IfcPolyline",
            Points=[_point2(model, -5 * a, 3 * a), _point2(model, 5 * a, 3 * a)],
        ),
        same_sense=False,
    )
    u2 = _grid_axis(model, "B", _line(model, (0.0, 5 * a), (1.0, 0.0)))
    v1 = _grid_axis(
        model,
        "1",
        model.create_entity(
            "IfcOffsetCurve2D",
            BasisCurve=_line(model, (0.0, 0.0), (0.0, 1.0)),
            Distance=-1.0 * a,
            SelfIntersect=False,
        ),
    )
    _grid(model, [u1, u2], [v1], grid_placement)
    # Left of A as it runs (towards -x) is -y: 3 - 2 = 1. Left of 1 is -x
    return model.create_entity(
        "IfcGridPlacement",
        PlacementLocation=_intersection(model, [u1, v1], [2 * a, -1 * a, 0.5 * a]),
        PlacementRefDirection=_intersection(model, [u2, v1], [0.0, -1 * a, 0.5 * a]),
    )


def _place_everything(model, scale, kind):
    """Give every item and action one placement, in the file's unit."""
    placement = _nested_placement(model, scale)
    if kind == "grid":
        # The grid is placed so that the grid placement on it undoes itself
        turn = np.array([GRID_X, np.cross([0.0, 0.0, 1.0], GRID_X), [0, 0, 1.0]]).T
        undo = model.create_entity(
            "IfcLocalPlacement",
            PlacementRelTo=placement,
            RelativePlacement=_axes(
                model,
                -turn.T @ GRID_POINT / scale,
                [float(c) for c in turn.T @ [1.0, 0.0, 0.0]],
                (0.0, 0.0, 1.0),
            ),
        )
        placement = _grid_placement(model, scale, undo)
    for kind in ("IfcStructuralItem", "IfcStructuralActivity"):
        for entity in model.by_type(kind):
            entity.ObjectPlacement = placement


def _moved(points):
    return np.asarray(points, dtype=float) @ ROTATION.T + OFFSET


def _turned(vectors):
    return np.asarray(vectors, dtype=float) @ ROTATION.T


def _extract(name, place=None):
    model = ifcopenshell.open(os.path.join(IFC_DIR, f"{name}.ifc"))
    extractor = Extractor(model)
    if place:
        _place_everything(model, extractor.unit_scales["LENGTHUNIT"], place)
    extracted = extractor.extract_model()
    # Entities are only valid while their file is alive
    extracted._ifc_file = model
    return extracted


@pytest.fixture(
    scope="module",
    params=[
        (name, kind)
        for name in (
            "beam_01",
            "portal_01",
            "building_01",
            "structure_01",
            "grid_of_beams",
        )
        for kind in ("local", "grid")
    ],
    ids=lambda param: "-".join(param),
)
def models(request):
    """An example as shipped (m, mm or inches) and the same one placed."""
    name, kind = request.param
    return _extract(name), _extract(name, kind)


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

    def test_linear_placement_is_an_error(self):
        model = ifcopenshell.file(schema="IFC4X3")
        placement = model.create_entity("IfcLinearPlacement")
        with pytest.raises(ModelExtractionError, match="only IfcLocalPlacement"):
            get_transformation(placement)


class TestGridPlacement:
    """The intersection of two grid axes, with offsets, in the grid's axes."""

    def _rectangular(self, model, grid_placement=None):
        u = _grid_axis(model, "A", _line(model, (0.0, 0.0), (1.0, 0.0)))
        v = _grid_axis(model, "1", _line(model, (4.0, 0.0), (0.0, 1.0)))
        _grid(model, [u], [v], grid_placement)
        return u, v

    def _place(self, model, axes, offsets=None, reference=None, **attributes):
        return model.create_entity(
            "IfcGridPlacement",
            PlacementLocation=_intersection(model, axes, offsets),
            PlacementRefDirection=reference,
            **attributes,
        )

    def test_offsets_are_to_the_left_of_each_axis(self):
        model = ifcopenshell.file(schema="IFC4")
        u, v = self._rectangular(model)
        transformation = get_transformation(
            self._place(model, [u, v], [1.0, 2.0, 0.5]), 0.001
        )
        # Left of A (+x) is +y, left of 1 (+y) is -x; the third is along z
        np.testing.assert_allclose(transformation["location"], [0.002, 0.001, 0.0005])
        # With no direction, x is along the first axis
        np.testing.assert_allclose(transformation["rotationMatrix"], np.eye(3))

    def test_same_sense_turns_the_axis_and_its_offset_over(self):
        model = ifcopenshell.file(schema="IFC4")
        u, v = self._rectangular(model)
        u.SameSense = False
        transformation = get_transformation(self._place(model, [u, v], [1.0, 2.0]))
        np.testing.assert_allclose(transformation["location"], [2.0, -1.0, 0.0])
        np.testing.assert_allclose(
            transformation["rotationMatrix"], np.diag([-1.0, -1.0, 1.0]), atol=1e-12
        )

    def test_trimmed_curve_against_its_basis_turns_over(self):
        model = ifcopenshell.file(schema="IFC4")
        u, v = self._rectangular(model)
        u.AxisCurve = model.create_entity(
            "IfcTrimmedCurve",
            BasisCurve=u.AxisCurve,
            Trim1=[model.create_entity("IfcParameterValue", 0.0)],
            Trim2=[model.create_entity("IfcParameterValue", 10.0)],
            SenseAgreement=False,
            MasterRepresentation="PARAMETER",
        )
        transformation = get_transformation(self._place(model, [u, v], [1.0, 0.0]))
        np.testing.assert_allclose(transformation["location"], [4.0, -1.0, 0.0])

    def test_direction_is_taken_in_the_plane_of_the_grid(self):
        model = ifcopenshell.file(schema="IFC4")
        u, v = self._rectangular(model)
        reference = model.create_entity("IfcDirection", [1.0, 1.0, 5.0])
        transformation = get_transformation(
            self._place(model, [v, u], reference=reference)
        )
        np.testing.assert_allclose(transformation["location"], [4.0, 0.0, 0.0])
        r = np.sqrt(0.5)
        np.testing.assert_allclose(
            transformation["rotationMatrix"],
            [[r, -r, 0.0], [r, r, 0.0], [0.0, 0.0, 1.0]],
        )

    def test_grid_placement_is_applied(self):
        model = ifcopenshell.file(schema="IFC4")
        grid_placement = model.create_entity(
            "IfcLocalPlacement",
            RelativePlacement=_axes(model, (0.0, 0.0, 10.0), PARENT_X, PARENT_Z),
        )
        u, v = self._rectangular(model, grid_placement)
        transformation = get_transformation(self._place(model, [u, v]))
        # The grid's x is global y
        np.testing.assert_allclose(transformation["location"], [0.0, 4.0, 10.0])
        np.testing.assert_allclose(
            transformation["rotationMatrix"] @ [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]
        )

    def test_local_placement_relative_to_a_grid_placement(self):
        model = ifcopenshell.file(schema="IFC4")
        u, v = self._rectangular(model)
        placement = model.create_entity(
            "IfcLocalPlacement",
            PlacementRelTo=self._place(
                model, [u, v], reference=model.create_entity("IfcDirection", [0.0, 1.0])
            ),
            RelativePlacement=_axes(model, (1.0, 0.0, 0.0), (1.0, 0.0, 0.0), PARENT_Z),
        )
        transformation = get_transformation(placement)
        np.testing.assert_allclose(transformation["location"], [4.0, 1.0, 0.0])

    def test_placement_relative_to_its_grid(self):
        """IFC4.3 adds PlacementRelTo, which must be the grid's placement."""
        model = ifcopenshell.file(schema="IFC4X3")
        grid_placement = model.create_entity(
            "IfcLocalPlacement",
            RelativePlacement=_axes(model, (0.0, 0.0, 10.0), (1.0, 0.0, 0.0), PARENT_Z),
        )
        u, v = self._rectangular(model, grid_placement)
        placement = self._place(model, [u, v], PlacementRelTo=grid_placement)
        np.testing.assert_allclose(
            get_transformation(placement)["location"], [4.0, 0.0, 10.0]
        )
        placement.PlacementRelTo = model.create_entity(
            "IfcLocalPlacement",
            RelativePlacement=_axes(model, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), PARENT_Z),
        )
        with pytest.raises(ModelExtractionError, match="other than the placement"):
            get_transformation(placement)

    def test_parallel_axes_are_an_error(self):
        model = ifcopenshell.file(schema="IFC4")
        u = _grid_axis(model, "A", _line(model, (0.0, 0.0), (1.0, 0.0)))
        v = _grid_axis(model, "B", _line(model, (0.0, 3.0), (-1.0, 0.0)))
        _grid(model, [u], [v])
        with pytest.raises(ModelExtractionError, match="parallel") as error:
            get_transformation(self._place(model, [u, v]))
        assert error.value.code == "E-IFC-003"

    def test_circular_axis_is_an_error(self):
        model = ifcopenshell.file(schema="IFC4")
        u, v = self._rectangular(model)
        v.AxisCurve = model.create_entity(
            "IfcCircle",
            Position=model.create_entity(
                "IfcAxis2Placement2D", Location=_point2(model, 0.0, 0.0)
            ),
            Radius=5.0,
        )
        with pytest.raises(ModelExtractionError, match="only straight") as error:
            get_transformation(self._place(model, [u, v]))
        assert error.value.code == "E-IFC-003"

    def test_bent_polyline_is_an_error(self):
        model = ifcopenshell.file(schema="IFC4")
        u, v = self._rectangular(model)
        u.AxisCurve = model.create_entity(
            "IfcPolyline",
            Points=[
                _point2(model, 0.0, 0.0),
                _point2(model, 5.0, 1.0),
                _point2(model, 10.0, 0.0),
            ],
        )
        with pytest.raises(ModelExtractionError, match="not straight"):
            get_transformation(self._place(model, [u, v]))

    def test_axes_of_two_grids_are_an_error(self):
        model = ifcopenshell.file(schema="IFC4")
        u = _grid_axis(model, "A", _line(model, (0.0, 0.0), (1.0, 0.0)))
        v = _grid_axis(model, "1", _line(model, (4.0, 0.0), (0.0, 1.0)))
        _grid(model, [u], [])
        _grid(model, [], [v])
        with pytest.raises(ModelExtractionError, match="two grids"):
            get_transformation(self._place(model, [u, v]))
